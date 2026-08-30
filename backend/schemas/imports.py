from pydantic import BaseModel, Field


class ImportResultOut(BaseModel):
    """What an import actually did.

    Reported field by field rather than as a single count, because the useful
    question afterwards is "why did it not pick up book X?" and the answer is
    almost always one of: the book is not in the catalogue, the status was
    already correct, or the row could not be acted on at all.
    """

    rows_read: int = Field(ge=0, description="Rows with a title")
    matched: int = Field(ge=0, description="Rows matched to a book already here")
    created: int = Field(ge=0, description="Books added from the file")
    statuses_updated: int = Field(ge=0, description="Statuses actually changed")
    skipped: int = Field(
        ge=0,
        description=(
            "Rows this import could not act on: no title, or an ISBN held by a "
            "book the caller cannot see"
        ),
    )
    # Capped by the router: a large export with nothing matching would
    # otherwise return more than it was given.
    unmatched_titles: list[str] = []


class ImportPreviewRow(BaseModel):
    """One row as the parser read it, for the confirmation step."""

    title: str
    author: str | None = None
    isbn: str | None = None
    status: str | None = None


class ImportPreviewOut(BaseModel):
    """What the file turned out to be, before anything is written.

    Exists because a column guessed wrong is invisible until after the import,
    and after the import is too late: the fix is deleting a few hundred books.
    The reader sees which header filled which field, and the first few rows as
    the parser actually read them.
    """

    #: Every header in the file, so a wrong guess can be corrected against the
    #: real list rather than from memory.
    headers: list[str]
    #: Field name to the header it was taken from, or null where nothing
    #: matched. The keys are what `overrides` accepts.
    mapping: dict[str, str | None]
    #: What separated the columns. Worth showing: a tab-separated file read as
    #: CSV is the failure that looks like corrupt data.
    delimiter: str
    total_rows: int = Field(ge=0)
    skipped: int = Field(ge=0, description="Rows with no title")
    #: How many different tags this file carries. Shown next to the "bring the
    #: tags across" switch, because a count of this file beats a warning that
    #: says "often hundreds".
    distinct_tags: int = Field(default=0, ge=0)
    rows: list[ImportPreviewRow] = []


class MarcPreviewRow(BaseModel):
    """One MARC record as the reader read it, for the confirmation step.

    Wider than `ImportPreviewRow` by exactly the fields a MARC record carries
    and a CSV does not, because those are the ones a cataloguer is checking:
    a `245` split into the wrong subfields shows up here as a title with the
    subtitle inside it, and a `082` that did not parse shows up as no call
    number at all.
    """

    title: str
    author: str | None = None
    isbn: str | None = None
    #: The shelf notations and subject headings, as `scheme:number` pairs. The
    #: same spelling `GET /api/books?classification=` takes, so a reader can
    #: paste one straight into a filter to see what the library already holds
    #: under it.
    classifications: list[str] = []


class MarcPreviewOut(BaseModel):
    """What a MARC upload turned out to hold, before anything is written.

    **A different model from `ImportPreviewOut` rather than a superset**, and
    the difference is what the reader is being asked. A CSV preview exists to
    let somebody correct a **column guess**, so it carries the headers, the
    mapping and the delimiter. MARC has no columns to guess: `245 $a` is the
    title because the standard says so. What a cataloguer checks instead is
    whether the records came through, which of them this app could not read,
    and how many are already held.

    `already_held` is why the model exists at all. Importing the same file
    twice is the ordinary accident here, and the answer to "will this double my
    catalogue" has to be visible before the write rather than in the result
    afterwards.

    **`blocked` is what makes `readable - already_held` the truth rather than an
    overstatement.** The import has a second refusal: a record whose ISBN
    belongs to a Book the member cannot see is neither matched nor created,
    because the unique index is on the whole table while the shelf is not. A
    preview that modelled only `already_held` would promise records the import
    then refuses. It is a count and never a title, for `importing.py`'s reason:
    naming them would be an oracle for "does a private book with this ISBN exist
    in this house".

    **A count is still an oracle, and this one is cheaper than the import's.**
    The same fact has been readable off `ImportResultOut.skipped` since the CSV
    importer, and `importing.py` argues why: the alternative is letting the
    insert reach the unique index, which raises and writes nothing for the whole
    file. What is new is the **price**. The import pays for each probe by
    writing a Book for every ISBN that does not collide; a preview writes
    nothing. Measured: 20,000 records, 3,860,064 bytes, answered 200 in 1.08
    seconds with zero books written, against a rate limit of three a minute.

    Accepted rather than closed, and the reasoning is in `docs/decisions.md`
    rather than here, because no arithmetic hides it: `readable`,
    `already_held` and `blocked` are the three numbers the screen exists for,
    and publishing any two publishes the third.

    **It under-counts in one shape, which narrows the oracle rather than
    widening it.** A record whose ISBN belongs to an invisible Book but whose
    title and author match a visible one is matched, not blocked:
    `MarcIndex.find` resolves it on the identity key and `isbn_is_taken` is
    never consulted. So a hit here means the ISBN is held **and** nothing on
    this shelf matches the record, which is less than "this ISBN exists". The
    import agrees, and drops the incoming ISBN rather than writing it: see
    `importing._MARC_GAP_FIELDS` for why that is what stops a 500.
    """

    total_records: int = Field(ge=0, description="Records in the file")
    readable: int = Field(ge=0, description="Records with a title this app can store")
    skipped: int = Field(ge=0, description="Records with no title")
    already_held: int = Field(
        ge=0, description="Records matching a book this member can already see"
    )
    blocked: int = Field(
        default=0,
        ge=0,
        description=(
            "Records the import will refuse: their ISBN belongs to a book this "
            "member cannot see"
        ),
    )
    rows: list[MarcPreviewRow] = []
