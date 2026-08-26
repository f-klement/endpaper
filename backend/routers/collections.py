"""Named parts of the shelf: physical and ebook, kept and sold, yours and mine.

**A collection is shelving, never permission.** Filing a book into one changes
nothing about who may see it: `visible_to()` remains the only access control on
content, and every count served here applies it. The temptation this module
exists to resist is treating the collection as a second scoping axis beside
privacy, because the two look alike from a distance and only one of them is
enforced everywhere. See `docs/decisions.md`.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import require_admin
from dependencies import CurrentUser, DbSession, RowId
from models import Book, Collection, User
from schemas import CollectionCreate, CollectionOut, CollectionUpdate
from shelf import Shelf

logger = logging.getLogger("endpaper.collections")

router = APIRouter(prefix="/api/collections", tags=["collections"])


def _named(db: Session, name: str, *, other_than: int | None = None) -> Collection | None:
    """The collection already carrying this name, case insensitively.

    The database refuses the clash outright through `uq_collections_name_nocase`,
    so this exists to answer with a 409 rather than letting an IntegrityError
    surface as a 500. The index is still the rule: this check races, that one
    cannot.
    """
    query = db.query(Collection).filter(func.lower(Collection.name) == name.lower())
    if other_than is not None:
        query = query.filter(Collection.id != other_than)
    return query.first()


def _counts(db: Session, user_id: int) -> dict[int, int]:
    """How many books each collection holds, for this caller, in one statement.

    **Filtered by `visible_to`, and that is not decoration.** A raw count would
    publish, on a label every member can read, that somebody's private books
    exist and how many. It also excludes trashed rows, so deleting the last
    book on a shelf leaves the shelf reading 0 rather than claiming a book in
    the bin.

    One grouped query rather than a count per collection: this list is fetched
    by the library filter, the book detail picker and the collections page, so
    an N+1 here would be an N+1 nearly everywhere.
    """
    rows = (
        Shelf.seen_by(db, user_id)
        .select(Book.collection_id, func.count(Book.id))
        .filter(Book.collection_id.isnot(None))
        .group_by(Book.collection_id)
        .all()
    )
    return {collection_id: count for collection_id, count in rows if collection_id is not None}


@router.get("", response_model=list[CollectionOut])
def list_collections(db: DbSession, current_user: CurrentUser) -> list[CollectionOut]:
    """Every collection in the library, with the caller's own counts.

    Ordered case insensitively by name: "ebooks" sorting after "Zola" because
    of its first letter's byte value is the kind of ordering a reader reads as
    a bug.
    """
    counts = _counts(db, current_user.id)
    return [
        CollectionOut(id=row.id, name=row.name, book_count=counts.get(row.id, 0))
        for row in db.query(Collection).order_by(func.lower(Collection.name)).all()
    ]


@router.post("", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
def create_collection(
    payload: CollectionCreate, db: DbSession, current_user: CurrentUser
) -> CollectionOut:
    """Invent a collection.

    Any member, like `POST /api/books/tags` and for the same reason: a shelf
    only an admin can divide up is one nobody divides up.

    A name that already exists returns the existing collection rather than a
    409. Somebody typing a name that is already there means that collection,
    and an error would send them off to find it by hand. Renaming is the
    opposite case and does answer 409, because a rename onto an occupied name
    would silently merge two shelves.
    """
    existing = _named(db, payload.name)
    if existing is not None:
        return CollectionOut(
            id=existing.id,
            name=existing.name,
            book_count=_counts(db, current_user.id).get(existing.id, 0),
        )

    collection = Collection(name=payload.name, created_by_user_id=current_user.id)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    # New, so it holds nothing. Stated rather than counted, because a query
    # that can only answer zero is a query worth not making.
    return CollectionOut(id=collection.id, name=collection.name, book_count=0)


@router.patch("/{collection_id}", response_model=CollectionOut)
def rename_collection(
    collection_id: RowId,
    payload: CollectionUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> CollectionOut:
    """Rename one. Any member: a rename moves no book and is undone by another.

    Refuses a name another collection already holds. The alternative is a merge
    of two shelves, which is a different operation with different consequences
    for the books in both, and nobody asked for it by typing a name.
    """
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    clash = _named(db, payload.name, other_than=collection_id)
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A collection with that name already exists.",
        )

    collection.name = payload.name
    db.commit()
    db.refresh(collection)
    return CollectionOut(
        id=collection.id,
        name=collection.name,
        book_count=_counts(db, current_user.id).get(collection.id, 0),
    )


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(
    collection_id: RowId,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> None:
    """Remove a collection. Its books are unfiled, never deleted.

    **Admin only, and deliberately asymmetric with creating one**, exactly like
    `DELETE /api/books/tags/{id}`. Creating is additive and undone by deleting;
    deleting empties a shelf label off every book in the house at once, with no
    undo, and one member should not be able to unpick the library's filing on
    their own.

    Nothing here nulls the column by hand, and two things do it instead. The
    ORM nulls the loaded children, which is what this delete actually emits;
    `books.collection_id` is also `ON DELETE SET NULL`, which is what covers a
    restore or a statement run by hand, neither of which passes through here.
    The second is the one worth keeping: a row left pointing at a destroyed
    collection is a dangling foreign key, and it is also why
    `PRAGMA foreign_keys=ON` is load bearing here.
    """
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    db.delete(collection)
    db.commit()
