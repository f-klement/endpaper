"""Named parts of the shelf: physical and ebook, kept and sold, yours and mine.

**A collection is shelving, never permission.** Filing a book into one changes
nothing about who may see it: a book's visibility is decided by `visible_to()`
alone, and every count served here applies it. The temptation this module
exists to resist is treating the collection as a second scoping axis beside
privacy, because the two look alike from a distance and only one of them is
enforced everywhere. See `docs/decisions.md`.

**A name is a disclosure, and that half of the doctrine was wrong.** The
paragraph above is about books and stays true; what it never covered is the
label. A collection whose every book is hidden from the caller used to be
served to them by name on every page load, and filing a book into a guessed id
then succeeded and handed the name back. Who may be told a collection exists is
`shelving.Shelving`, asked here and at the book write doors and nowhere else.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import require_admin
from dependencies import CurrentUser, DbSession, RowId
from models import Collection, User, fold_collection_name
from schemas import CollectionCreate, CollectionOut, CollectionUpdate
from shelving import Shelving

logger = logging.getLogger("endpaper.collections")

router = APIRouter(prefix="/api/collections", tags=["collections"])


def _named(db: Session, name: str, *, other_than: int | None = None) -> Collection | None:
    """The collection already carrying this name, case insensitively.

    The database refuses the clash outright through `uq_collections_name_folded`,
    so this exists to answer with a 409 rather than letting an IntegrityError
    surface as a 500. The index is still the rule: this check races, that one
    cannot.

    **Both sides fold in Python, and that is the point of the stored column.**
    This used to compare `func.lower(Collection.name)`, which folds in SQLite,
    against `name.lower()`, which folds in Python. The two agreed on ASCII and
    on nothing else, so the check and the index it backs were wrong together
    and `Ästhetik` and `ästhetik` were two shelves. See the comment on
    `Collection.__table_args__` and `docs/decisions.md`, "SQLite folds case in
    ASCII and Python does not".
    """
    query = db.query(Collection).filter(
        Collection.name_folded == fold_collection_name(name)
    )
    if other_than is not None:
        query = query.filter(Collection.id != other_than)
    return query.first()


@router.get("", response_model=list[CollectionOut])
def list_collections(db: DbSession, current_user: CurrentUser) -> list[CollectionOut]:
    """Every collection the caller may be told about, with their own counts.

    **Not every collection in the library**, which is what this used to be. A
    collection whose every book is hidden from the caller is absent, because
    its name is the caller's first and only evidence that somebody's books are
    filed somewhere. `shelving.Shelving` is the rule and carries the three arms,
    what stays uncovered, and why a row that vanishes and returns is correct.

    One consequence worth knowing at this site: a listed row reading
    `book_count: 0` used to mean "empty, or holding books you cannot see", and
    now means empty, or holding only books you can see in the trash. The count
    stopped being readable as a hidden total because the rows it could be read
    against are gone.
    """
    shelving = Shelving.seen_by(db, current_user.id)
    return [
        CollectionOut(
            id=row.id, name=row.name, book_count=shelving.counts.get(row.id, 0)
        )
        for row in shelving.listable()
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

    **So a guessed name still confirms a collection exists, and that is left
    open deliberately.** `uq_collections_name_folded` is global, so the
    collision check cannot take a viewer without racing the index it exists to
    front, and answering a collision any other way is a new status code on a
    route that declares 201. What the guess no longer buys is the write: the
    caller gets the row and `shelving.Shelving` then refuses to file anything
    into it, which is the answer an unused id gets. `Shelving`'s docstring
    carries this under what is not closed.
    """
    existing = _named(db, payload.name)
    if existing is not None:
        return CollectionOut(
            id=existing.id,
            name=existing.name,
            book_count=Shelving.seen_by(db, current_user.id).counts.get(existing.id, 0),
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

    **One migration does merge, and it is not this rule being bent.** The
    revision that made the name fold outside ASCII found libraries already
    holding a pair like `Ästhetik` and `ästhetik`, which the new index cannot
    both keep, and there was nobody to ask: an upgrade has no caller to answer
    409 to. So it merges the pair once, into the lower id, and logs what it
    moved. Here there is a caller, and a caller who typed a name has asked for
    that name and not for two shelves to become one.

    **And the same 404 for a collection this caller may not be told about**,
    which is `shelving.Shelving.assignable`. This route is open to every member
    and answers over the whole id space, so before it the 404-or-200 was an
    existence oracle by id on a table of consecutive integers: closing the list
    and leaving this would have moved a broadcast to a poll. The two answers
    are now one.

    The 409 is the other half and is not closed: a taken name still answers
    differently from a free one, for the reason `create_collection` gives.
    """
    shelving = Shelving.seen_by(db, current_user.id)
    collection = db.get(Collection, collection_id)
    if collection is None or not shelving.assignable(collection.id):
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
        book_count=shelving.counts.get(collection.id, 0),
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

    **Deliberately not gated on `shelving.Shelving`, unlike the rename beside
    it, and the reason is what gating would cost.** An admin has no privilege
    over another member's private books, so a collection holding only those is
    one no admin may be told about; refusing the delete there would make it
    permanently undeletable while it still holds its name against
    `uq_collections_name_folded`, and the only symptom would be a 409 nobody
    can explain. What the ungated 404-or-204 discloses is an id, to an admin,
    with no name in the response. That is the smaller of the two, and it is a
    choice rather than an oversight.
    """
    collection = db.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    db.delete(collection)
    db.commit()
