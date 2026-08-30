"""Turning ORM rows into the payloads the API returns.

Its own module rather than private helpers inside `routers/books.py` for two
reasons. `routers/loans.py` needs `books_to_out` and used to reach for it with
a function-local `from routers.books import ...` to dodge the import cycle that
a top-level import would have created, which is a cycle announcing itself. And
`BookOut` is assembled rather than mapped: several of its fields are not
columns, so the assembly is a piece of behaviour with its own tests, not
plumbing.

**`BookOut` depends on who is asking.** `active_loan`, the four `my_*` reading
fields and the three `my_progress_*` ones are all per-request, so the same book
row serialises differently for two accounts. Never cache a `BookOut` across
users.
"""

import re
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

import ddc
from enums import ClassificationScheme
from models import Book, Collection, Loan, ReadingProgress, Tag, User
from reading import Reading, discussers
from schemas import (
    BookOut,
    ClassificationIn,
    ClassificationOut,
    LoanOut,
    PublicBookOut,
    UserOut,
)
from shelf import Shelf, rereading_filtered_rows

# The metadata sources themselves live in `metadata.py`. What is here is the
# part that is ours rather than theirs: mapping whatever subject headings a
# catalogue happens to use onto this library's own tag vocabulary.


def match_subjects_to_tags(subjects: list[str], tags: list[Tag]) -> list[int]:
    """Case-insensitive match of source subjects against our tag names, on word boundaries.

    **Boundaries rather than a bare substring, and the reason is a measurement
    rather than taste.** A substring match reads a tag name anywhere inside a
    subject, so `Software engineering` proposed **War**, `Outer Party` proposed
    **Art**, `thoughtcrime` proposed **Crime** and `Trous noirs` proposed
    **Noir**. Every one of those is pre-selected by the web client, so a wrong
    suggestion is written unless somebody unticks it, while a missing one costs
    a click to add. That asymmetry is what decides this.

    Measured live on 2026-08-24, running this function against the 105 seeded
    tag names:

    | population | substring | on word boundaries |
    |---|---|---|
    | 12 English books, Open Library subjects | 27 suggestions, 7 wrong | 20, **2 wrong** |
    | 10 German ISBNs, DNB subject headings | 5 suggestions, **5 wrong** | 0, none |

    The German row is the sharper one: on those records the substring route
    produced nothing but false positives (`Gegenw**art**sliteratur` and
    `Soft**war**eentwicklung`), which is the failure the DDC number projection
    in `suggested_tag_ids` exists to work around.

    **What boundaries cost, stated rather than hidden**, and it is two tags
    rather than one: `fiction classics` no longer proposes **Classic**, on 2 of
    the 12 English books, and **Travel** is lost on one. A second run over nine
    books during review found the same direction, 18 suggestions to 11, losing
    Crime, Art, Noir and War, all wrong, against Classic twice and Travel.

    Allowing an optional trailing `s` recovers those and was measured too, but
    it re-admits **Noir**, so it buys 2 correct suggestions for 2 wrong ones.
    Not taken, for the asymmetry above: a wrong suggestion is written unless
    somebody unticks it.

    Still not fixed by this, and not fixable here: `Medicine in Literature`
    proposes **Medicine** and `computer science` proposes **Science**. Both
    match on a boundary and are wrong for a different reason, which is that the
    subject is about the tag rather than an instance of it.
    """
    if not subjects:
        return []
    subjects_blob = " | ".join(subject.lower() for subject in subjects)
    matched: list[int] = []
    for tag in tags:
        # Strip parenthetical suffixes: "Young Adult (13-18)" becomes "young adult".
        tag_core = re.sub(r"\s*\([^)]+\)", "", tag.name).strip().lower()
        # Lookaround rather than `\b`, because a tag name can end in a
        # non-word character ("C++"), where `\b` asserts the opposite thing.
        if tag_core and re.search(
            rf"(?<!\w){re.escape(tag_core)}(?!\w)", subjects_blob
        ):
            matched.append(tag.id)
    return matched


def suggested_tag_ids(
    subjects: list[str],
    classifications: Sequence[ClassificationIn | ClassificationOut],
    tags: list[Tag],
) -> list[int]:
    """Tags a library might want on this book, from both kinds of evidence.

    Two routes to the same list, and they fail on opposite records. The
    name match reads the **caption** a catalogue supplied, which works for
    an English record and scores zero on a German one. The DDC projection reads
    the **number**, which is the same in both: `004` is Informatik in a German
    record and Computing in an English one, and both resolve to Computing here.

    Measured on 2026-08-23 against ten German ISBNs at the DNB: eight carried a
    DDC heading, and the caption route matched a seeded tag on none of them.

    **The server never writes a tag from this list**, and that is the whole
    claim: it is returned, and `Book.tags` is not touched anywhere near here.
    Do not add a caller that does.

    **The web client pre-selects every id in it**, so on the ordinary scan the
    suggested tags do land unless the member unchecks them
    (`frontend/src/pages/ScanPage/hooks.ts`, `setSelectedTagIds` then the
    `addTag` calls on confirm). That is a deliberate reading of "suggestion",
    argued in `docs/decisions.md`, and it is written here because four
    documents used to say "nothing applies it" and mean only this half.

    Tags are a small curated vocabulary the library chooses from, which is
    why the projection stops at proposing one.

    Only DDC is projected, of the four schemes stored. An LCC number needs the
    published division list this mapping is, and LCC has no equivalent short
    enough to ship. A GND number is an authority record identifier rather than a
    place in a schedule: there is no arithmetic that takes `4203576-4` to a
    division, and the library vocabulary it would map to is the caption, which
    `match_subjects_to_tags` above already reads (a GND heading reaches
    `subjects` too).
    """
    matched = list(match_subjects_to_tags(subjects, tags))
    numbers = [
        entry.number
        for entry in classifications
        if entry.scheme is ClassificationScheme.DDC
    ]
    wanted = {name.lower() for name in ddc.tag_names(numbers)}
    if wanted:
        seen = set(matched)
        matched.extend(
            tag.id for tag in tags if tag.name.lower() in wanted and tag.id not in seen
        )
    return matched


def loan_summary(loan: Loan) -> LoanOut:
    """A loan as it appears *inside* a book payload.

    `book` is left None deliberately: the caller is already holding the book
    this loan belongs to, and populating it would both bloat the response and
    trigger a lazy load per book.
    """
    return LoanOut(
        id=loan.id,
        book_id=loan.book_id,
        loaned_to_user_id=loan.loaned_to_user_id,
        # Set instead of loaned_to_user_id when the book went to somebody with
        # no account. Carried here too, or the badge on a book lent to a
        # neighbour says "Loaned to" and then nothing.
        loaned_to_name=loan.loaned_to_name,
        loaned_by_user_id=loan.loaned_by_user_id,
        loaned_at=loan.loaned_at,
        returned_at=loan.returned_at,
        book=None,
        loaned_to=UserOut.model_validate(loan.loaned_to) if loan.loaned_to else None,
        loaned_by=UserOut.model_validate(loan.loaned_by) if loan.loaned_by else None,
    )


def derived_percent(page: int | None, percent: int | None, page_count: int | None) -> int | None:
    """How far through a book a recorded position is, as a whole number.

    Derived on every read rather than stored beside the position, so there is
    one fact in the database and no second copy to fall out of step when a
    metadata refresh corrects the page count.

    The order is the whole rule: a page against a known page count, else
    whatever percent was recorded, else nothing. A page with no page count
    yields nothing rather than a guess, which is why an audiobook records a
    percent in the first place.

    Clamped at 100 because `page_count` comes from a metadata provider and is
    off by one often enough that the last page routinely computes to 101.
    """
    if page is not None and page_count:
        return max(0, min(100, round(page / page_count * 100)))
    if page is not None:
        return None
    return percent


def _latest_progress(
    book_ids: list[int], current_user: User, db: Session
) -> dict[int, ReadingProgress]:
    """The caller's newest recorded position per book, in one statement.

    A window function rather than a query per book: adding a per-request field
    inside the serialisation loop is the N+1 that took listing 25 books from 6
    statements to 53, and this is exactly that shape of field.

    Ranked on `(recorded_at DESC, id DESC)` rather than on `max(id)`. The two
    agree for every row this app inserts, since the table is append-only and
    `recorded_at` defaults to now, and they stop agreeing after a restore,
    which carries the source database's timestamps into freshly assigned ids.

    `user_id` is in the filter, not only `book_id`. Progress is personal, and a
    page of books the caller may see is not a licence to see what anybody else
    was reading in them.
    """
    ranked = (
        select(
            ReadingProgress,
            func.row_number()
            .over(
                partition_by=ReadingProgress.book_id,
                order_by=(ReadingProgress.recorded_at.desc(), ReadingProgress.id.desc()),
            )
            .label("rank"),
        )
        .where(
            ReadingProgress.user_id == current_user.id,
            ReadingProgress.book_id.in_(book_ids),
        )
        .subquery()
    )
    entity = aliased(ReadingProgress, ranked)
    return {
        row.book_id: row
        for row in db.query(entity).filter(ranked.c.rank == 1).all()
    }


def _discussers(book_ids: list[int], db: Session) -> dict[int, list[UserOut]]:
    """Who has offered to talk about each of these books, as the API says it.

    The query is `reading.discussers`, which owns why this one field is read
    across members instead of scoped to the caller. What is left here is the
    part that belongs to serialisation: turning the rows into `UserOut`.
    """
    return {
        book_id: [UserOut.model_validate(user) for user in users]
        for book_id, users in discussers(db, book_ids).items()
    }


def _copy_counts(books: list[Book], current_user: User, db: Session) -> dict[str, int]:
    """How many copies each of these books' groups holds, in one statement.

    Keyed on the group token rather than on the book id, because that is what
    the rows already share: every member of a group gets the same answer, so a
    page showing both copies of one title costs one row of this result, not
    two.

    **`visible_to` applies**, and it is not a formality here. A member who made
    their own copy private would otherwise be announced to everyone here
    by the number on everybody else's card. It also excludes trashed rows, so
    deleting one of two copies leaves the other reading "1" rather than
    claiming a copy that is in the bin.

    Books with no group are absent from the result and read 1 from the default
    on `BookOut`, which is the same answer without a row to carry it.
    """
    groups = {book.copy_group for book in books if book.copy_group is not None}
    if not groups:
        return {}
    rows = (
        Shelf.seen_by(db, current_user.id)
        .select(Book.copy_group, func.count(Book.id))
        .filter(Book.copy_group.in_(groups))
        .group_by(Book.copy_group)
        .all()
    )
    return {token: count for token, count in rows if token is not None}


def _collection_names(books: list[Book], db: Session) -> dict[int, str]:
    """The name of each collection this page's books are filed in.

    One statement for the page, and none at all when nothing on it is filed,
    which is every page in a library that has not made a collection.

    Read here rather than through `Book.collection`, which is a lazy
    relationship: serialising a page of 25 filed books would otherwise issue 25
    SELECTs, the same N+1 this module exists to avoid, arrived at through a
    relationship instead of through a loop. Batching it here also means no
    caller has to remember a `joinedload`, unlike `Book.added_by`, whose cost
    depends on who fetched the rows.

    **No `visible_to`.** It filters books, and there is not a book in this
    query: it reads the label a row already in the caller's hands points at.
    The collection list itself is library wide by design, so a name is not a
    disclosure; the **count** is, and that one is filtered where it is served
    (`routers/collections._counts`).
    """
    ids = {book.collection_id for book in books if book.collection_id is not None}
    if not ids:
        return {}
    rows = db.query(Collection.id, Collection.name).filter(Collection.id.in_(ids)).all()
    return {row.id: row.name for row in rows}


def books_to_out(books: list[Book], current_user: User, db: Session) -> list[BookOut]:
    """Serialise a page of books, adding the per-request fields.

    None of them is a column, and the obvious implementation queries for each
    of them per book, which is what made listing 25 books cost 53 SELECTs.

    **The cost, measured rather than counted off the source.** This function is
    the one place that states it; `docs/architecture.md` and
    `docs/data-model.md` point here rather than repeating a number, because
    both have been wrong before and were wrong in the same way twice.

    **7** statements, constant in the size of the page: the books re-read to
    populate their tags, the tag load itself, the classification load, the
    loans, the statuses, the progress, and the members offering to talk about
    each book. Measured at 1, 5 and 25 books, unchanged.

    It was 6 until classifications were stored: `selectinload` issues one
    statement per relationship, so loading a second one on the same re-read
    costs exactly one more for the whole page, not one per book.

    **8 when the page holds a copy.** `_copy_counts` issues its statement only
    when some book on the page carries a `copy_group`, which almost none do,
    and it is one statement for the whole page whatever it finds.

    **8 as well when the page holds a book filed in a collection.**
    `_collection_names` is the same shape: nothing at all until a library
    makes a collection and puts something in it, then one statement for the
    page however many collections it spans. Measured directly on this function
    over a page of five filed books against a page of plain ones: **8 against
    7**, a delta of exactly one.

    **Plus one per distinct `added_by` author the session has not already
    loaded**, and that one is not this function's: `BookOut.model_validate`
    reads `book.added_by`, which lazy loads unless the caller fetched it. So
    the number depends on who called, and on who wrote the books.

    The caller's own row is always already loaded, because the auth dependency
    put it in this session before the endpoint touched a book, so **books the
    caller added cost nothing here**. That is the one condition that moves the
    number, which is why it is stated rather than left in the measurement.

    **Which of these figures a test would catch.** The 7 is read back out of
    this docstring by
    `test_the_number_in_the_docstring_is_the_number_it_costs`, and the two 8s
    follow from it, since `TestCopyCount` and `TestCollectionName` each assert a
    delta of exactly one against the same base. The 11 below and the per-author
    table are measurements and nothing pins them, so treat them as true of the
    day they were taken.

    Measured on rows fetched without `joinedload`, identical at 5 and at 25
    books, for one, two and three distinct authors:

        authors                  1   2   3
        caller wrote none        8   9  10
        caller is one of them    7   8   9

    Every listing endpoint in `routers/books.py` passes
    `joinedload(Book.added_by)`, so none of them pays any of it: `GET
    /api/books` measures a flat **11 SELECTs** end to end at 25 books, and
    `books_to_out` on rows fetched with the option is a flat 7 at 1, 5 and 25
    books. Both figures are for a page holding neither a copy nor a filed book,
    and the two conditional statements above are what a page holding either
    costs on top. The 7 was one lower before the classification load, and the
    11 was 12 until `Loading.SERIALISED` stopped loading tags this function
    loads anyway (2026-08-30, measured at 5 and at 25 books).

    A new caller that fetches books without that option gets the per-author
    cost back. That is the trap this paragraph exists to name.
    """
    if not books:
        return []

    book_ids = [book.id for book in books]

    # `rereading_filtered_rows`, not a shelf: this is not a visibility
    # question. These ids came out of a query that applied the predicate, and
    # this re-reads the same rows to populate a relationship on the objects
    # already in hand. Filtering here would answer a question nobody asked.
    #
    # Tags in one query for the whole page. `BookOut.model_validate` reads
    # `book.tags`, which is a lazy relationship, so without this a page of 25
    # books issued 25 extra SELECTs: the identical N+1 this function exists to
    # avoid, arrived by a different door. Re-querying rows already in the
    # identity map looks redundant and is not: it is what populates the
    # collection, and the objects handed back are the same ones.
    #
    # `classifications` rides along for the same reason and costs one more
    # SELECT for the whole page, not one per book: `selectinload` issues a
    # statement per relationship, so this option is why the count above is 7
    # and not 6.
    #
    # **`Loading.SERIALISED` depends on this line and deliberately loads no
    # tags of its own**, so deleting it does not restore a shelf-side eager
    # load: it reinstates the N+1 at every caller at once. `shelf.py`'s
    # `Loading` docstring carries the measurement.
    rereading_filtered_rows(db, book_ids).options(
        selectinload(Book.tags), selectinload(Book.classifications)
    ).all()

    active_loans = {
        loan.book_id: loan
        for loan in db.query(Loan)
        .options(joinedload(Loan.loaned_to), joinedload(Loan.loaned_by))
        .filter(Loan.book_id.in_(book_ids), Loan.returned_at.is_(None))
        .all()
    }

    # One query for the whole page, not one per book. The row carries the
    # status, the rating and both dates, so adding those three fields cost no
    # extra statements: the fetch was already here.
    user_books = Reading.by(db, current_user.id).of(book_ids)

    latest_progress = _latest_progress(book_ids, current_user, db)
    # `discuss_with`, not `discussers`: the module function of that name is
    # imported at the top of this file, and a local binding would shadow it
    # for the whole of this function body.
    discuss_with = _discussers(book_ids, db)
    # Only when something on the page is a copy, so the ordinary page pays
    # nothing for a feature almost no book uses.
    copy_counts = _copy_counts(books, current_user, db)
    # Same conditional shape, same reason: a library with no collections pays
    # nothing for the feature.
    collection_names = _collection_names(books, db)

    results: list[BookOut] = []
    for book in books:
        out = BookOut.model_validate(book)
        if book.copy_group is not None:
            out.copy_count = copy_counts.get(book.copy_group, 1)
        if book.collection_id is not None:
            # `.get`, not indexing: the row can vanish between the two
            # statements, and a name nobody can look up is a null rather than a
            # 500 in the middle of a listing.
            out.collection_name = collection_names.get(book.collection_id)
        loan = active_loans.get(book.id)
        out.active_loan = loan_summary(loan) if loan else None

        user_book = user_books.get(book.id)
        # No row means unread, and `status_of` is the one place that says so.
        # It also coerces back to the enum, which matters because the column is
        # a plain VARCHAR and assigning a str onto an enum-typed Pydantic field
        # bypasses validation and serialises with a warning. (Assignment skips
        # validation; model_validate would coerce.)
        out.my_status = user_books.status_of(book.id)
        out.my_rating = user_book.rating if user_book else None
        out.my_started_at = user_book.started_at if user_book else None
        out.my_finished_at = user_book.finished_at if user_book else None
        out.my_wants_to_discuss = bool(user_book.wants_to_discuss) if user_book else False
        out.discuss_with = discuss_with.get(book.id, [])

        progress = latest_progress.get(book.id)
        if progress is not None:
            out.my_progress_page = progress.page
            out.my_progress_percent = derived_percent(
                progress.page, progress.percent, book.page_count
            )
            out.my_progress_recorded_at = progress.recorded_at
        results.append(out)
    return results


def book_to_out(book: Book, current_user: User, db: Session) -> BookOut:
    return books_to_out([book], current_user, db)[0]




def books_to_public_out(books: Sequence[Book]) -> list[PublicBookOut]:
    """Serialise Books for a reader with no account.

    **It takes no `Session` and no `User`, and that signature is the guarantee
    rather than a convenience.** `books_to_out` above needs both because half
    of `BookOut` depends on who is asking; `PublicBookOut` has no such field, so
    this one structurally cannot issue a per member query. There is no viewer to
    scope one by and no argument that would let a caller supply one.
    `tests/test_serialisation.py::TestThePublicSerialiserCannotAskWhoIsAsking`
    is what holds that, because it is a property of the signature and the
    signature is the only place it can be read off.

    **Zero statements**, provided the caller loaded the two collections
    (`Loading.PUBLISHED`). Without it `model_validate` reads `book.tags` and
    `book.classifications` lazily and the page costs two statements per Book,
    which is the N+1 `books_to_out` exists to avoid, arrived at through the
    door that has no batching helper to reach for.
    """
    return [PublicBookOut.model_validate(book) for book in books]
