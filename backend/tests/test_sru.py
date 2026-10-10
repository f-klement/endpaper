"""Tests for backend/sru.py: the catalogue served over a protocol.

**The seam is `sru.respond`, a function over a query string**, which is what the
ticket asked for and what makes the interesting half testable at all. Everything
below drives that function directly: no client, no session token, no route. The
router has its own file, and what it owns is the gate rather than the protocol.

The one that matters is `TestNoIndexReachesAPrivateBook`. It is asserted **per
index**, driven from `sru.INDEXES` rather than from a list written here, because
one unfiltered index is the whole leak and a fixed list of indexes to test is a
list that an index added later is not on.
"""

import ast
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import Text

import marc
import sru
from bibliographic import BIBLIOGRAPHIC_CODES
from catalogue import _TEXT_CEILINGS
from enums import ClassificationScheme, HeadingKind, TagCategory
from models import (
    AUTHOR_LINE_MAX,
    CLASSIFICATION_LABEL_MAX,
    CLASSIFICATION_NUMBER_MAX,
    DESCRIPTION_MAX,
    Book,
    Classification,
    Tag,
    copy_group_token,
)
from schemas.classification import MAX_CLASSIFICATIONS_PER_BOOK
from schemas.public import PublicBookOut, PublicClassificationOut
from tests.strategies import invisible_characters, text_around, witness

#: The namespaces a response is read back through.
SRW = "{http://www.loc.gov/zing/srw/}"
DIAG = "{info:srw/xmlns/1/diagnostic-v1.1}"
EXPLAIN = "{http://explain.z3950.org/dtd/2.0/}"
MARC21 = "{http://www.loc.gov/MARC21/slim}"

#: What `explain` is told to report about itself.
#:
#: A reserved name from RFC 2606, so nothing here resolves and nothing here
#: names a deployment.
SERVER = sru.Server(host="catalogue.example", port=443, database="sru")


def respond(db: Any, **parameters: str) -> ElementTree.Element:
    """One request, as a parsed response.

    The parameters are urlencoded rather than pasted together, so a test can put
    a space or an ampersand in a query and be testing the server rather than its
    own string building.
    """
    return ElementTree.fromstring(sru.respond(urlencode(parameters), db, SERVER))


def diagnostic_of(root: ElementTree.Element) -> int | None:
    """The diagnostic number in a response, or None if it carries none."""
    uri = root.find(f"{SRW}diagnostics/{DIAG}diagnostic/{DIAG}uri")
    if uri is None or uri.text is None:
        return None
    return int(uri.text.rsplit("/", 1)[1])


def details_of(root: ElementTree.Element) -> str | None:
    """The `<details>` of a response's diagnostic, or None.

    **The only place two refusals that share a number differ.** Asserting the
    number alone let a test pass whichever of two arms had fired, which is the
    asymmetry its own name existed to pin.
    """
    details = root.find(f"{SRW}diagnostics/{DIAG}diagnostic/{DIAG}details")
    return None if details is None else details.text


def record_ids(root: ElementTree.Element) -> list[int]:
    """The `001` of every record in a response, in the order they came back."""
    return [
        int(field.text or "0")
        for field in root.iter(f"{MARC21}controlfield")
        if field.get("tag") == "001"
    ]


def number_of_records(root: ElementTree.Element) -> int:
    element = root.find(f"{SRW}numberOfRecords")
    assert element is not None
    assert element.text is not None
    return int(element.text)


def book_columns_marc_reads() -> set[str]:
    """Every `Book` column name `marc.py` reads, taken off the parse.

    **Every attribute access whose name is a Book column, whatever it is read
    off.** The first version tested `node.value.id == "book"`, which is one
    receiver name out of four: a rebound local, a helper parameter and
    `getattr` all walked past it, and `marc.py` already has two helpers that
    take a Book. Measured, both versions read the identical twelve columns
    today, so widening it costs nothing and closes three shapes.

    **`getattr(book, name)` is invisible to this pass**, and the caller says
    what that costs at its own site.

    **Widening it to every attribute name is safe only for a consumer whose
    allowlist already holds every column name a method call can contribute**,
    and that condition is a property of the consumer rather than of this walk.
    `TestTheRecordCarriesNoColumnThePublicPayloadWithholds` meets it: a
    `str.format` in the writer contributes `format`, which is a `Book` column
    and is also a `PublicBookOut` field, so nothing is refused. A second
    consumer was added here with a ten name allowlist, did not meet it, and
    refused a page over a column nothing reads. It was removed and derives from
    the rendered record instead. **So this is one caller by design**: the
    sentence "widening it costs nothing" is true of that caller and is not a
    property anybody else may borrow.
    """
    read = {
        node.attr
        for node in ast.walk(ast.parse(Path(marc.__file__).read_text()))
        if isinstance(node, ast.Attribute)
    }
    return read & {column.key for column in Book.__table__.columns}


# ── The shelf every visibility test is asserted against ──────────────────────


#: The values all three books share, so that one query per index matches all of
#: them and only the row filter decides what comes back.
#:
#: **A private book with different data would make every test below pass
#: vacuously**, which is the shape this file exists to refuse: the query would
#: find nothing, and a shelf with the privacy predicate deleted would answer
#: exactly the same. So the three rows differ in one column each and agree
#: everywhere else.
SHARED: dict[str, Any] = {
    "title": "Chartreuse Windmill",
    "author": "Ada Example",
    "publisher": "Gemini Press",
    "language": "de",
    "description": "a study of chartreuse windmills and their keepers",
    "year": 1974,
    "subtitle": "a study",
}


@pytest.fixture
def shelf(db, admin, member):
    """One public book, one private one and one in the trash, otherwise identical.

    The private book belongs to a **different** member from the trashed one, so
    an ownership arm reintroduced by accident would have somebody to match.
    That is the same arrangement `tests/routers/test_public.py` uses and for the
    same reason.
    """
    from datetime import UTC, datetime

    tag = Tag(name="windmills", category=TagCategory.CUSTOM)
    db.add(tag)
    db.flush()

    public = Book(
        isbn="9780000000001", added_by_user_id=admin["user"]["id"], **SHARED
    )
    private = Book(
        isbn="9780000000002",
        added_by_user_id=member["user"]["id"],
        is_private=True,
        **SHARED,
    )
    trashed = Book(
        isbn="9780000000003",
        added_by_user_id=admin["user"]["id"],
        deleted_at=datetime.now(UTC).replace(tzinfo=None),
        **SHARED,
    )
    for book in (public, private, trashed):
        book.tags.append(tag)
    db.add_all([public, private, trashed])
    db.commit()
    for book in (public, private, trashed):
        db.refresh(book)
    return {"public": public.id, "private": private.id, "trashed": trashed.id}


def term_for(field: sru.Field, hidden_id: int) -> str:
    """A term that matches all three books through one index.

    `IDENTIFIER` is the one that cannot use a shared value, because the ISBN is
    unique per row. It uses the prefix all three share, which `=` matches as a
    substring.

    `RECORD_ID` is the opposite case and is the sharpest test here: the only
    term that can reach the hidden book through it is that book's own id, so
    this is the index where an unfiltered shelf is one request away from a
    private record.
    """
    terms: dict[sru.Field, str] = {
        sru.Field.ANYWHERE: SHARED["title"],
        sru.Field.TITLE: SHARED["title"],
        sru.Field.CREATOR: SHARED["author"],
        sru.Field.PUBLISHER: SHARED["publisher"],
        sru.Field.IDENTIFIER: "978000000000",
        sru.Field.LANGUAGE: SHARED["language"],
        sru.Field.DESCRIPTION: "windmills",
        sru.Field.SUBJECT: "windmills",
        sru.Field.DATE: str(SHARED["year"]),
        sru.Field.RECORD_ID: str(hidden_id),
    }
    return terms[field]


def miss_for(field: sru.Field) -> str:
    """A term that matches **none** of the three books, through one index.

    **`term_for`'s three arms prove the row filter and nothing about the term.**
    Measured by replacing `sru.criteria` wholesale with `true()`: 0 of 36
    assertions fail, because the shelf holds exactly one public book, so
    "returns the public book and not the private one" is satisfied by a
    predicate that returns everything. Privacy still holds under that mutant, so
    it was not a leak; what was unguarded is `dc.title=nonexistent` answering
    with the whole catalogue.

    `dc.date` and `rec.id` are the two that cannot take a nonsense string: a
    year nothing carries and an id nothing has.
    """
    misses: dict[sru.Field, str] = {
        sru.Field.ANYWHERE: "Vermilion Sawmill",
        sru.Field.TITLE: "Vermilion Sawmill",
        sru.Field.CREATOR: "Bertha Nobody",
        sru.Field.PUBLISHER: "Sawmill Press",
        sru.Field.IDENTIFIER: "111111111111",
        sru.Field.LANGUAGE: "xx",
        sru.Field.DESCRIPTION: "sawmills",
        sru.Field.SUBJECT: "sawmills",
        sru.Field.DATE: "1066",
        sru.Field.RECORD_ID: "987654",
    }
    return misses[field]


class TestNoIndexReachesAPrivateBook:
    """The rule the whole module exists under, asserted through the protocol.

    Through the protocol rather than through the query layer, deliberately: a
    test that called `Shelf.seen_by_the_public` and checked its rows would be
    testing the shelf, which `tests/test_shelf.py` already does. What is new
    here is that a query language sits between a stranger and that shelf.
    """

    @pytest.mark.parametrize("index", sru.INDEXES, ids=lambda i: i.qualified)
    def test_the_private_book_is_absent_from_every_index(self, db, shelf, index):
        response = respond(
            db,
            operation="searchRetrieve",
            query=f'{index.qualified}="{term_for(index.field, shelf["private"])}"',
            maximumRecords="50",
        )
        assert diagnostic_of(response) is None
        assert shelf["private"] not in record_ids(response)

    @pytest.mark.parametrize("index", sru.INDEXES, ids=lambda i: i.qualified)
    def test_the_trashed_book_is_absent_from_every_index(self, db, shelf, index):
        response = respond(
            db,
            operation="searchRetrieve",
            query=f'{index.qualified}="{term_for(index.field, shelf["trashed"])}"',
            maximumRecords="50",
        )
        assert diagnostic_of(response) is None
        assert shelf["trashed"] not in record_ids(response)

    @pytest.mark.parametrize("index", sru.INDEXES, ids=lambda i: i.qualified)
    def test_the_public_book_is_present_through_every_index(self, db, shelf, index):
        """**The control, and without it the two above are worthless.**

        A query that matches nothing passes both of them, and so does an index
        whose compiler is broken. This is what says the term really does reach
        all three rows and that exactly one of them comes back.
        """
        response = respond(
            db,
            operation="searchRetrieve",
            query=f'{index.qualified}="{term_for(index.field, shelf["public"])}"',
            maximumRecords="50",
        )
        assert diagnostic_of(response) is None
        assert record_ids(response) == [shelf["public"]]
        assert number_of_records(response) == 1

    @pytest.mark.parametrize("index", sru.INDEXES, ids=lambda i: i.qualified)
    def test_a_term_that_matches_nothing_returns_nothing(self, db, shelf, index):
        """**The arm the other three do not cover, and the decisive one.**

        With `sru.criteria` replaced by `true()` the three arms above pass 36 of
        36, because a shelf holding one public book cannot tell "the predicate
        matched it" from "the predicate matched everything". This is what fails
        under that mutant, and under a per index one: measured 12 of 12 and 10
        of 12 respectively, clean on the real tree.
        """
        response = respond(
            db,
            operation="searchRetrieve",
            query=f'{index.qualified}="{miss_for(index.field)}"',
            maximumRecords="50",
        )
        assert diagnostic_of(response) is None
        assert record_ids(response) == []
        assert number_of_records(response) == 0

    def test_every_field_has_both_terms_and_every_index_a_field(self):
        """A guard that inspects nothing reads as coverage.

        `term_for` and `miss_for` are dict literals, so a `Field` added without
        an entry raises a `KeyError` inside a parametrised test, which is a
        failure but an obscure one. This says the same thing where a reader will
        see it, and it covers **both** tables: adding the miss table and leaving
        it out of this check is how the next `Field` gets a hit and no miss.
        """
        assert {index.field for index in sru.INDEXES} == set(sru.Field)
        for field in sru.Field:
            assert term_for(field, 1)
            assert miss_for(field)
            assert term_for(field, 1) != miss_for(field)


class TestExplainReportsTheIndexesThatExist:
    """`operation=explain` is generated from the registry, not written out."""

    @staticmethod
    def _explain(db) -> ElementTree.Element:
        root = respond(db, operation="explain")
        explain = root.find(f"{SRW}record/{SRW}recordData/{EXPLAIN}explain")
        assert explain is not None
        return explain

    @staticmethod
    def _reported(explain: ElementTree.Element) -> dict[str, tuple[str, ...]]:
        found = {}
        for element in explain.iter(f"{EXPLAIN}index"):
            name = element.find(f"{EXPLAIN}map/{EXPLAIN}name")
            assert name is not None
            assert name.text is not None
            qualified = f"{name.get('set')}.{name.text}" if name.get("set") else name.text
            found[qualified] = tuple(
                supports.text or ""
                for supports in element.iter(f"{EXPLAIN}supports")
                if supports.get("type") == "relation"
            )
        return found

    def test_explain_names_exactly_the_indexes_the_compiler_holds(self, db):
        """**Both directions.** A subset test forgives a document that omits an
        index and one that invents one, and the second is the worse failure: a
        client builds a query against it and gets diagnostic 16."""
        reported = self._reported(self._explain(db))
        assert reported == {
            index.qualified: index.relations for index in sru.INDEXES
        }

    def test_every_index_explain_names_actually_answers(self, db, shelf):
        """The half a document comparison cannot make: the index compiles.

        A registry entry with no compiler support answers diagnostic 16 or 19
        while `explain` promises it, and nothing above would notice.
        """
        for index in sru.INDEXES:
            for relation in index.relations:
                term = term_for(index.field, shelf["public"])
                response = respond(
                    db,
                    operation="searchRetrieve",
                    query=f'{index.qualified} {relation} "{term}"',
                )
                assert diagnostic_of(response) is None, (
                    f"{index.qualified} {relation} is advertised and refused"
                )

    def test_the_context_sets_declared_are_the_ones_used(self, db):
        explain = self._explain(db)
        declared = {
            element.get("name") for element in explain.iter(f"{EXPLAIN}set")
        }
        assert declared == {index.context_set for index in sru.INDEXES}

    def test_the_record_cap_is_advertised(self, db):
        """A client cannot size its paging against a number it is not told."""
        explain = self._explain(db)
        settings = {
            element.get("type"): element.text
            for element in explain.iter(f"{EXPLAIN}setting")
        }
        assert settings["maximumRecords"] == str(sru.MAX_RECORDS)


class TestTheBoundsAreRefusedWithADiagnostic:
    """Four bounds, each refused as a diagnostic in a 200 and never as a crash."""

    def test_a_query_longer_than_the_bound_is_refused(self, db):
        response = respond(
            db, operation="searchRetrieve", query="a" * (sru.MAX_QUERY_CHARS + 1)
        )
        assert diagnostic_of(response) == sru.Diagnostic.TOO_MANY_CHARACTERS_IN_QUERY

    def test_a_query_at_the_bound_is_accepted(self, db):
        """The other half of a bound, and the half that catches an off by one
        that has quietly made the server useless."""
        response = respond(
            db,
            operation="searchRetrieve",
            query="dc.title=" + "a" * (sru.MAX_QUERY_CHARS - len("dc.title=")),
        )
        assert diagnostic_of(response) is None

    def test_nesting_past_the_bound_is_refused_and_does_not_recurse(self, db):
        """**The bound this parser would be broken without.**

        A recursive descent parser blows the interpreter's stack on a query of
        nothing but open parentheses, and a `RecursionError` is a 500 rather
        than a diagnostic. The query here is the longest one the length bound
        admits, so it is the worst case the parser can be handed.
        """
        response = respond(
            db, operation="searchRetrieve", query="(" * sru.MAX_QUERY_CHARS
        )
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_USE_OF_PARENTHESES

    def test_nesting_at_the_bound_is_accepted(self, db):
        depth = sru.MAX_NESTING_DEPTH
        response = respond(
            db, operation="searchRetrieve", query="(" * depth + "dog" + ")" * depth
        )
        assert diagnostic_of(response) is None

    def test_more_search_clauses_than_the_bound_is_refused(self, db):
        query = " and ".join(f"dc.title=t{n}" for n in range(sru.MAX_CLAUSES + 1))
        response = respond(db, operation="searchRetrieve", query=query)
        assert diagnostic_of(response) == sru.Diagnostic.TOO_MANY_BOOLEAN_OPERATORS

    def test_the_clause_bound_is_reachable(self, db):
        query = " and ".join(f"dc.title=t{n}" for n in range(sru.MAX_CLAUSES))
        response = respond(db, operation="searchRetrieve", query=query)
        assert diagnostic_of(response) is None

    def test_more_words_in_a_term_than_the_bound_is_refused(self, db):
        words = " ".join(f"w{n}" for n in range(sru.MAX_WORDS_IN_A_TERM + 1))
        response = respond(
            db, operation="searchRetrieve", query=f'dc.title all "{words}"'
        )
        assert diagnostic_of(response) == sru.Diagnostic.TOO_MANY_BOOLEAN_OPERATORS

    def test_more_masks_in_a_term_than_the_bound_is_refused(self, db):
        response = respond(
            db,
            operation="searchRetrieve",
            query="dc.title=" + "*" * (sru.MAX_MASKS_IN_A_TERM + 1),
        )
        assert diagnostic_of(response) == sru.Diagnostic.TOO_MANY_MASKING_CHARACTERS


class TestTheCostOfTheWorstLegalQueryIsBounded:
    """What the bounds cost to **run**, which is not what they used to count.

    **This class replaced one that counted the wrong unit.** It counted `LIKE`
    occurrences in the compiled SQL and `docs/security.md` published that count
    as the bound. Predicates is not the quantity the bound exists to control:
    `dc.title`, `author` and `isbn` are short columns and `dc.description` has
    no length limit, so the widest index, the one that version measured and
    called the ceiling, is the **cheap** shape. Measured against 3,000 books
    with 2,000 character descriptions, 384 comparisons through
    `cql.serverChoice` are 584 to 650 ms and 128 through `dc.description`, which
    the same parse bounds admit, are 2091 to 2284 ms.

    So the bound is now `MAX_COMPARISON_BUDGET`, charged per comparison and
    weighted by `Cost`, and what is asserted here is that no legal query can
    exceed it and that the shapes measured to be expensive are refused. The wall
    clock figures live beside the constant, against the catalogue size they were
    taken on, because a duration is not a property of the server.
    """

    @staticmethod
    def _comparisons(query: str) -> int:
        """The SQL comparisons one query compiles to, off the compiled SQL.

        Still counted in `LIKE` occurrences, and that is right **here**: this
        measures what was built, and the budget is what decides whether it may
        be. The mistake was publishing this number as the bound.
        """
        from sqlalchemy.dialects import sqlite

        compiled = sru.criteria(sru.parse(query)).compile(
            dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
        )
        return str(compiled).count("LIKE")

    @staticmethod
    def _widest(index: str, clauses: int, words: int) -> str:
        text = " ".join(f"w{n}" for n in range(words))
        return " or ".join(f'{index} all "{text}"' for _ in range(clauses))

    def test_every_index_declares_what_it_costs(self):
        """No default on the field, so this cannot fail; asserted anyway,
        because a default added later would make every new index free."""
        assert all(isinstance(index.cost, sru.Cost) for index in sru.INDEXES)
        assert {index.cost for index in sru.INDEXES} == set(sru.Cost), (
            "both cost classes should be in use, or the weighting is doing "
            "nothing and the budget is a plain count under another name"
        )

    def test_the_cheap_ceiling_is_the_budget(self):
        """64 cheap comparisons are spendable, 65 are not."""
        assert self._comparisons(self._widest("dc.title", 8, 8)) == 64
        with pytest.raises(sru.SruError) as refused:
            sru.criteria(sru.parse(self._widest("dc.title", 8, 8) + ' or dc.title=x'))
        assert refused.value.diagnostic == sru.Diagnostic.TOO_MANY_BOOLEAN_OPERATORS

    def test_the_expensive_ceiling_is_an_eighth_of_it(self):
        """`dc.description` is weighted 8, so 8 comparisons spend the budget."""
        assert self._comparisons(self._widest("dc.description", 1, 8)) == 8
        with pytest.raises(sru.SruError) as refused:
            sru.criteria(sru.parse(self._widest("dc.description", 2, 8)))
        assert refused.value.diagnostic == sru.Diagnostic.TOO_MANY_BOOLEAN_OPERATORS

    def test_the_shape_that_was_measured_at_two_seconds_is_refused(self):
        """The finding, as a test. 16 clauses of 8 words over the unbounded
        column: inside every parse bound, and 2091 to 2284 ms."""
        with pytest.raises(sru.SruError) as refused:
            sru.criteria(sru.parse(self._widest("dc.description", 16, 8)))
        assert refused.value.diagnostic == sru.Diagnostic.TOO_MANY_BOOLEAN_OPERATORS

    def test_the_shape_the_old_bound_called_the_ceiling_is_refused_too(self):
        """384 comparisons through the three column index, 584 to 650 ms. The
        old rule permitted it and named it the worst case; it was neither."""
        with pytest.raises(sru.SruError) as refused:
            sru.criteria(sru.parse(self._widest("cql.serverChoice", 16, 8)))
        assert refused.value.diagnostic == sru.Diagnostic.TOO_MANY_BOOLEAN_OPERATORS

    def test_the_subject_index_is_charged_as_expensive(self):
        """Its column is `String(100)`, so a weighting derived from the column
        type would call it cheap. It is a correlated EXISTS and measures 1067 to
        1143 ms at 64 comparisons, which is where its weight comes from."""
        with pytest.raises(sru.SruError):
            sru.criteria(sru.parse(self._widest("dc.subject", 2, 8)))
        assert self._comparisons(self._widest("dc.subject", 1, 8)) >= 0

    @pytest.mark.parametrize(
        "query",
        [
            'dc.title="harry potter"',
            'dc.title all "harry potter"',
            'cql.serverChoice all "one two three four five six seven eight"',
            'dc.description="a whole phrase"',
            'dc.description all "four separate words here"',
            'dc.title=a and dc.creator=b and dc.date>1990 and bath.isbn=978',
        ],
        ids=["phrase", "two words", "anywhere eight", "description phrase",
             "description four", "four indexes"],
    )
    def test_the_queries_a_client_actually_sends_are_well_inside_it(self, query):
        """**The half a ceiling test always needs.** A bound that refuses real
        queries is not a tighter bound, it is a broken server, and the previous
        bound admitted all of these."""
        assert sru.criteria(sru.parse(query)) is not None

    #: Every index that can actually exhaust the budget, and what one
    #: comparison through it costs.
    #:
    #: **The three column ones are the whole point of this table.** They carry
    #: `Cost.CHEAP`, so a message rendering the weight rather than the charge
    #: says 1 where the truth is 3, and a client believing it sends 64 terms and
    #: is refused at 22. `dc.date` and `rec.id` are absent because 16 clauses at
    #: 1 cannot reach 64, so their message is unreachable.
    EXHAUSTING = {
        "cql.serverChoice": 3,
        "bib.anywhere": 3,
        "dc.title": 1,
        "dc.description": 8,
        "dc.subject": 8,
    }

    @pytest.mark.parametrize("qualified", sorted(EXHAUSTING), ids=lambda n: n)
    def test_the_refusal_names_what_a_comparison_really_costs(self, qualified):
        """**Nothing asserted this string, so both the wrong message and the
        right one passed the whole file.**

        `details_of` existed and was used only by the integer pair. The charge
        is `comparisons * cost.value` and the message rendered `cost.value`,
        which differ exactly on the two indexes that compare three columns, and
        those are the ones a client is most likely to reach the bound with.
        """
        charge = self.EXHAUSTING[qualified]
        with pytest.raises(sru.SruError) as refused:
            sru.criteria(sru.parse(self._widest(qualified, 16, 8)))
        assert refused.value.details == (
            f"{qualified}: {charge} a comparison, "
            f"{sru.MAX_COMPARISON_BUDGET} a query"
        )

    #: How much of `_DETAILS_CHARS` the longest refusal must leave unused.
    #:
    #: **The headroom is pinned and the length is not**, because pinning the
    #: length is how the next edit lands back on the limit. The wording this
    #: replaced measured exactly 60 against a limit of 60: never truncated, and
    #: one reworded verb from losing its tail silently, since `_safe` cuts
    #: without saying so. 12 is a three digit budget, a longer index name and a
    #: changed verb together.
    DETAILS_HEADROOM = 12

    def test_no_refusal_is_ever_truncated_and_none_is_near_it(self):
        """Two assertions, and the first is the property while the second is
        the margin. A message that fits exactly satisfies the first forever and
        tells nobody it is one character from losing the half that matters."""
        longest = ""
        for index in sru.INDEXES:
            columns = 3 if index.field is sru.Field.ANYWHERE else 1
            details = (
                f"{index.qualified}: {columns * index.cost.value} a comparison, "
                f"{sru.MAX_COMPARISON_BUDGET} a query"
            )
            assert sru._safe(details) == details, (
                f"`{details}` is truncated by `_safe`, so a client is told what "
                "the index costs and not what the budget is."
            )
            longest = max(longest, details, key=len)
        assert len(longest) <= sru._DETAILS_CHARS - self.DETAILS_HEADROOM, (
            f"the longest refusal is {len(longest)} of {sru._DETAILS_CHARS} "
            f"characters, leaving under {self.DETAILS_HEADROOM} spare: "
            f"{longest!r}. Shorten it rather than raising the limit, which also "
            "bounds how much client text may be echoed."
        )

    def test_the_stated_charge_is_the_one_actually_spent(self):
        """The diagonal, derived a second way. The message is asserted above
        against a hand written table; this recomputes the same figure off
        `INDEXES` and the budget, so a table copied wrong fails rather than
        agreeing with itself."""
        for qualified, charge in self.EXHAUSTING.items():
            index = sru._BY_NAME[qualified.lower()]
            columns = 3 if index.field is sru.Field.ANYWHERE else 1
            assert charge == columns * index.cost.value
            # And the budget really is exhausted at the count that charge implies.
            affordable = sru.MAX_COMPARISON_BUDGET // charge
            assert sru.criteria(sru.parse(self._words(qualified, affordable))) is not None
            with pytest.raises(sru.SruError):
                sru.criteria(sru.parse(self._words(qualified, affordable + 1)))

    @staticmethod
    def _words(index: str, count: int) -> str:
        """A query comparing one index `count` times, in as few clauses as the
        parse bounds allow."""
        clauses, remainder = divmod(count, sru.MAX_WORDS_IN_A_TERM)
        parts = [
            f'{index} all "{" ".join(f"w{n}" for n in range(sru.MAX_WORDS_IN_A_TERM))}"'
            for _ in range(clauses)
        ]
        if remainder:
            parts.append(f'{index} all "{" ".join(f"v{n}" for n in range(remainder))}"')
        return " or ".join(parts)

    def test_the_budget_is_per_request_and_not_shared_between_them(self):
        """**Nothing pinned this and the only thing preventing it was a line.**

        `criteria()` builds the budget inline, so a module level one, which is a
        plausible later optimisation, would leave the second request of a pair
        refused. Under xdist that surfaces as whichever test happened to run
        second, in a file that need not be this one. The widest query this
        server accepts, twice in a row, is the whole guard.
        """
        widest = self._widest("dc.title", 8, 8)
        assert sru.criteria(sru.parse(widest)) is not None
        assert sru.criteria(sru.parse(widest)) is not None

    def test_the_budget_is_spent_across_the_whole_query_not_per_clause(self):
        """One budget threaded through the tree, so sixteen cheap clauses of
        four words each cannot each spend sixty four."""
        with pytest.raises(sru.SruError):
            sru.criteria(sru.parse(self._widest("dc.title", 16, 8)))


class TestTheCostOfTheWidestLegalResponseIsBounded:
    """The other half of the budget above, charged in the unit it is paid in.

    `MAX_COMPARISON_BUDGET` bounds what a stranger's query costs to **run**.
    This bounds what the answer costs to **emit**, and until this class it was
    the one bound in `sru.py` stated in a unit it is not paid in: `MAX_RECORDS`
    counts rows, a response costs bytes, and a narrow row makes the count look
    like a worst case. The module has already paid for that mistake once, which
    is the class above: a ceiling counted in `LIKE` occurrences, replaced by a
    measured budget. `_serialise` builds the whole document as one string
    before a response exists, so the figure here is what one request carrying
    no session can make this server hold at once.

    **The byte pin names nothing, and that is a property of its shape rather
    than a gap to close.** It is an equality on one integer, so every change it
    is meant to catch and every change it is not produce the same failure,
    distinguishable only by a difference a reader has to interpret. Measured by
    a review seat: deleting an unrelated language field, touching no bound, no
    count and no fill, reddened it at minus 4,200 bytes and read exactly like a
    widened column. **So the naming is done by the arms beside it**, which
    report the field by its MARC tag, the column by its name, the row
    identifiers by their digits and the published figure by its document, and
    the pin's own message says only what it knows.

    **What bounds `description` is a three way partition, and the sentence this
    class replaced collapsed it to one part.** The column is `Text` and bounds
    nothing. Every write through a schema is held to `models.DESCRIPTION_MAX`,
    which is where the fixture reads it from. `backup.py` inserts through Core,
    so `@validates` never fires and a restored row is bounded by nothing at
    all: `models.py` records a 3,000,256 byte description that reached the
    table that way. And a `max_length` counts characters where a response
    counts bytes, so neither half of the partition is a byte figure by itself.

    **The fixture's columns are derived by rendering, not by reading source.**
    A record is built with a distinct sentinel in every column a value could
    make long, and the columns whose sentinel comes back in the document are
    the ones a fill can widen. That answers three questions with one
    instrument: which columns to fill, whether each one's value really reaches
    the record, and whether a column arrives that no write path bounds.

    **It replaced an AST walk over `marc.py` and the reason is worth keeping.**
    That walk collects every attribute name, so `str.format` anywhere in the
    writer contributes `format`, which is a `Book` column: the fixture then
    refused a page over a column nothing reads, and prescribed a repair to a
    production file for a column that does not exist in that sense. The walk is
    right for the class it was written for, whose allowlist holds every column
    name a method call can contribute; it is wrong here. A rendered value is a
    property of the record. An attribute name is a spelling.

    **Three fills and two credit counts, because a page is not a length.**
    `ElementTree` writes `&` as five bytes, so the same declared maxima make a
    page several times over; and `700` repeats once per credited name inside
    `AUTHOR_LINE_MAX` with nothing bounding the count, so the same 500
    characters is one name or 250 of them. Both are asserted below rather than
    stated here, because a described reason rots and an asserted one reddens.

    **Widest means widest, and two things a client may legitimately post were
    missing from an earlier version of this fixture.** A heading carries a
    declared kind, which moves `$2` from `gnd` to `gnd-content`, eight bytes on
    each of eight headings. And `uq_books_isbn_single_copy` is **partial** on
    `copy_group IS NULL`, so a page of rows a member has declared to be copies
    of one title holds fifty identical ISBNs at the declared maximum and needs
    no serial there at all. Measured, the two are worth 3,600 bytes a page, and
    without them this class pinned a figure and `docs/security.md` published it
    as the widest a write can produce when it was not.

    **So exactly one column still forces a serial**, and the uniqueness that
    forces it is total rather than partial: `(book_id, scheme, number)` on a
    classification. Measured at the widest fill, 32 bytes a record, so the
    figure below **understates** the true widest by about 1,600 bytes a page.
    The serial width is derived from the count it separates rather than chosen.

    **What it does not hold**, stated rather than closed:

    * A restored row beats it, and no figure here could fail to be beaten by
      one. That is the third part of the partition above.
    * **The rendering derivation sees `Book` columns and nothing else**, and
      a field the writer sources from a relation is outside it. That is the
      unbounded shape rather than the mild one, since a relation's row count
      is not a column bound.
    * **Every arm here reads one record, so a field the fixture's own record
      does not render is outside all of them.** The tag arm covers a field fed
      by a relation for `classifications`, the one relation this fixture
      populates, and measured, a `590` fed from `book.tags` reddens nothing
      here and moves neither pin. So the tag arm names a field **the widest
      record renders**, and that is the whole of what it claims.
    * **The tag arm reads the set of tags**, so a field repeating an existing
      tag does not change it and neither does a widened bound. Measured, a
      second `520` moves this page by 129,050 bytes and reddens no arm at all:
      the pin sees it and cannot name it. Those two shapes have no arm.
    * **Two mechanisms make a column invisible to a sentinel and they are a
      false negative pair**, so neither reads as the instrument working on its
      own. `language` is looked up in `bibliographic.BIBLIOGRAPHIC_CODES` and
      an arbitrary string writes no `041`; that one is harmless, and measured
      rather than argued: all 20 codes are three characters, so `041 $a` is
      three bytes whatever `LANGUAGE_MAX` says, and the control arm asserts it.
      `cover_url` is the other half and is **not** harmless: a `@validates`
      hook rewrites it on `setattr`, so the sentinel never reaches the column
      at all and a field fed from it would be invisible here. `emitted_columns`
      checks the write separately and names any other column a hook touches;
      `WRITE_HOOK_DISCARDS` carries the one exemption and what it costs.
    * It is a tripwire on the record's shape and not a platform limit. Nothing
      enforces this figure at runtime and no deployment was measured against
      it.
    * **It refuses a page that is different, not a page that is large.** That
      is the price of zero headroom, taken deliberately: a bound with slack in
      it is a number nobody can re-derive.
    * `isbn` filled with 20 characters of `&` is past what ISBN validation
      accepts. Deliberate, and the same exception the export arm takes for the
      same reason: it is the cheapest demonstration that the column's bound and
      the write path's bound are two different rules.
    """

    #: The widths this fixture fills to, which is the catalogue import's
    #: ceiling table and **not** the API's write bound.
    #:
    #: `catalogue._TEXT_CEILINGS` is live configuration for the import path,
    #: where a value past its entry is **dropped** from an external record.
    #: The API's own bounds are `max_length` on the schemas in
    #: `schemas/book.py`, and the two are different sets: the schemas also
    #: bound `location`, `purchase_source`, `categories` and
    #: `purchase_currency`, which this table does not carry.
    #:
    #: **The seven columns this class fills coincide under both**, because
    #: each side reads the same `models.*_MAX` constants, so the widths here
    #: are the API's. This table is read rather than four schema models
    #: because it is one mapping, and the refusal below says plainly that
    #: adding a column to it is not the repair for a missing bound.
    CEILINGS = _TEXT_CEILINGS

    #: The one wide column whose sentinel a write hook destroys before a
    #: record is ever rendered.
    #:
    #: `Book`'s `@validates("cover_url")` runs `covers.https_url` on every
    #: write, so a sentinel that is not a renderable URL is stored as `None`.
    #: The derivation then sees a column that reached no record, where what
    #: happened is that no value was ever stored, and **the two are
    #: indistinguishable from the document**. Measured: of the nineteen wide
    #: columns this is the only one a hook touches.
    #:
    #: **What the exemption costs, which is not nothing.** An `856 $u` fed
    #: from `cover_url` would be invisible to every arm in this class and to
    #: both pins, on a column that may legitimately hold 500 characters. No
    #: such field is written today, and nothing here would say so if one were.
    WRITE_HOOK_DISCARDS = frozenset({"cover_url"})

    #: What a full page of the widest records an API write can produce weighs.
    #:
    #: Measured rather than rounded, and asserted as equality. It names
    #: nothing on its own: see the class docstring, and the arms beside it.
    WIDEST_RESPONSE_BYTES = 5_117_485

    #: How many digits of row identifier the figure above carries, in `001`.
    #:
    #: **Not a decoration.** Fifty rows numbered from one is nine single digit
    #: identifiers and forty one double, and the figure moves by one byte for
    #: every digit. It holds because the engine under the fixtures restarts the
    #: table; a sequence on another engine does not, and this file is outside
    #: the selection that runs there today. Asserted so that arriving on such
    #: an engine is a failure that says what happened rather than a page that
    #: quietly weighs something else.
    IDENTIFIER_DIGITS = 91

    #: Every MARC field this fixture's record carries, by tag.
    #:
    #: **The arm that names a field the widest record renders**, which the
    #: byte pin cannot: the pin sees a number move and the column derivation
    #: sees `Book` columns only. Read off the rendered document rather than
    #: off the writer's source, so it does not care how the value was reached.
    #:
    #: **It reaches a field fed by a relation only where this fixture
    #: populates that relation**, which is `classifications` and nothing else.
    #: A field fed by an empty relation renders nothing, moves no bytes and is
    #: outside every arm in this class.
    FIELD_TAGS = (
        "001",
        "020",
        "041",
        "100",
        "245",
        "264",
        "300",
        "520",
        "655",
        "700",
    )

    #: The language the fixture's records carry, in the column's own spelling.
    #:
    #: **One reader, the builder, and that is deliberate.** An earlier version
    #: had the control arm read it too, which coupled two sites with nothing
    #: enforcing the coupling: measured, moving this onto a six character key
    #: while the builder kept a hardcoded one left every arm green and the
    #: page understating by 150 bytes. The arm reads the code out of the
    #: rendered record instead, so this constant decides what is written and
    #: the record decides what is checked.
    #:
    #: The column is left out of the derived set for the reason in the class
    #: docstring, and what makes that safe is that the code this key renders
    #: is as wide as any code in the table, which is asserted rather than
    #: described.
    FIXTURE_LANGUAGE = "de"

    #: The vocabulary the fixture's headings are in.
    #:
    #: A choice rather than a derivation, and the reason is in
    #: `marc._subject_fields`: an LCSH row stores the authorised heading as its
    #: number and has no separate caption, so one such row carries one value
    #: where a GND row carries a caption and an identifier both. The kind is
    #: derived below; the scheme is not, and no comparison between schemes is
    #: claimed here.
    SCHEME = ClassificationScheme.GND

    #: The fills, and what each is here to show. `w` is the number a careless
    #: version of this class would have taken; `&` is what escaping does to the
    #: same declared maximum.
    FILLS = ("w", "ä", "&")

    #: The most credited names `AUTHOR_LINE_MAX` characters can hold, as
    #: `x,x,x,...`: one character a name and one separator.
    MOST_CREDITS = AUTHOR_LINE_MAX // 2

    #: What one extra credited name costs a record, net and conservatively.
    #:
    #: The `700` scaffolding is the **writer's** property rather than SRU's,
    #: and `tests/routers/test_imports_marc.py` derives the figure from the
    #: field's own subfields at the site that owns it. Asserted as a difference
    #: rather than a ratio for the reason given there: a ratio has the one name
    #: page underneath it and falls as any other bound widens.
    SCAFFOLDING_PER_CREDIT = 100

    @staticmethod
    def wide_columns() -> set[str]:
        """Book columns a value could make long: a declared length, or `Text`.

        The population the derivation below draws from. `Text` is in it because
        the one column this whole class is about declares no length, which is
        the partition one layer down.
        """
        return {
            column.key
            for column in Book.__table__.columns
            if getattr(column.type, "length", None) or isinstance(column.type, Text)
        }

    @classmethod
    def sentinels(cls) -> dict[str, str]:
        """A distinct value per wide column, so no column is credited by another.

        Distinctness is the whole of it. An earlier version filled every column
        with the same character and asked whether each value appeared in the
        record: a 10,000 character run of `w` contains every shorter run of
        `w`, so one column reaching the document answered for all of them.
        """
        return {
            key: f"reaches{index}therecord"
            for index, key in enumerate(sorted(cls.wide_columns()))
        }

    @classmethod
    def emitted_columns(cls) -> set[str]:
        """The wide columns whose own value reaches a rendered record."""
        sentinels = cls.sentinels()
        # A transient Book, never added to a session, so a CHECK constraint on
        # `ownership` or `condition` cannot refuse a sentinel. `id` is set
        # because `001` is written from it and a `None` there is a value of its
        # own. The same arrangement the column boundary class uses.
        book = Book(id=1)
        for key, value in sentinels.items():
            setattr(book, key, value)
        # **Checked before rendering, because a column that never took the
        # sentinel and a column that took it and was not written look the same
        # in the document.** Without this the derivation reports the second
        # where the first happened, which is how `cover_url` fell out silently.
        rewritten = {
            key for key, value in sentinels.items() if getattr(book, key) != value
        }
        # **Equality, not a subtraction.** A subtraction can only ever find the
        # exemption too small: remove the hook and the entry's whole stated
        # reason goes with it while nothing here reddens, leaving a published
        # file asserting a mechanism that no longer exists. The frontend's lint
        # ratchet is bought against the same shape and for the same reason.
        assert rewritten == cls.WRITE_HOOK_DISCARDS, (
            "the set of columns a write hook rewrites before rendering is "
            f"{sorted(rewritten)} and the exemption names "
            f"{sorted(cls.WRITE_HOOK_DISCARDS)}. For a column that is "
            "rewritten and not named, this derivation cannot tell whether the "
            "writer emits it: name it here and say either what the exemption "
            "costs, the way `cover_url` does, or why it costs nothing, and a "
            "column no record could carry at its width costs nothing. For a "
            "column that is named and no longer rewritten, the exemption has "
            "outlived its reason and comes out."
        )
        rendered = ElementTree.tostring(marc.record_element(book), encoding="unicode")
        return {key for key, value in sentinels.items() if value in rendered}

    @classmethod
    def filled(cls) -> dict[str, int]:
        """Every column a fill can widen, at what an API write holds it to."""
        return {
            key: width
            for key, width in sorted(cls.CEILINGS.items())
            if key in cls.emitted_columns()
        }

    @classmethod
    def widest_kind(cls) -> HeadingKind | None:
        """The declared kind whose `$2` is longest, off the writer's own table.

        A kind is something a client posts, and the writer turns it into a
        different vocabulary code as well as a different tag. Derived rather
        than named, so a kind added with a longer code joins the fixture the
        day it lands; `None` where the scheme has no kinded entry at all, which
        is what a scheme with no `_HEADING_KIND_FIELD` row means.
        """
        kinded = {
            kind: source
            for (scheme, kind), (_tag, source) in marc._HEADING_KIND_FIELD.items()
            if scheme is cls.SCHEME
        }
        if not kinded:
            return None
        return max(kinded, key=lambda kind: len(kinded[kind]))

    @staticmethod
    def serial_width(count: int) -> int:
        """Digits enough to tell `count` things apart."""
        return len(str(count - 1))

    def widest_book(self, fill: str, credits: int, group: str) -> Book:
        """Every column a fill can widen at its write bound, and `credits` names.

        **Two values for `credits`, and a third is refused rather than
        clamped**, which is the sibling arm's rule and the same trap: `x,`
        three times is six characters, so a fixture asked for three credits
        would quietly measure a narrow record while reading as a wide one.

        **`group` is what lets the ISBN be at its declared maximum.** The
        uniqueness on that column is partial on `copy_group IS NULL`, so a page
        of declared copies needs no serial in it. The classification numbers
        still do, and that uniqueness is total.
        """
        if credits not in (1, self.MOST_CREDITS):
            raise ValueError(
                f"credits is 1 or {self.MOST_CREDITS}: those are the two that "
                "fill AUTHOR_LINE_MAX, and anything between them measures a "
                "record narrower than this fixture claims to build"
            )
        values: dict[str, Any] = {}
        for key, width in self.filled().items():
            if key == "author":
                values[key] = (
                    fill * width if credits == 1 else (fill + ",") * (width // 2)
                )
            else:
                values[key] = fill * width
        book = Book(
            # Validated for shape as well as length, so each carries a real
            # value: a fill in one of these measures a record the API refuses,
            # and `language` filled with `&` writes no `041` at all.
            language=self.FIXTURE_LANGUAGE,
            year=1974,
            page_count=412,
            series_index=1.0,
            copy_group=group,
            **values,
        )
        tag = self.serial_width(MAX_CLASSIFICATIONS_PER_BOOK)
        kind = self.widest_kind()
        book.classifications = [
            Classification(
                scheme=self.SCHEME,
                number=fill * (CLASSIFICATION_NUMBER_MAX - tag) + f"{k:0{tag}d}",
                label=fill * CLASSIFICATION_LABEL_MAX,
                kind=kind,
            )
            for k in range(MAX_CLASSIFICATIONS_PER_BOOK)
        ]
        return book

    @staticmethod
    def empty_the_shelf(db: Any) -> None:
        """So that a page is the fixture and nothing the fixtures seeded.

        A test measuring two fills stores two pages, and a seeded row carrying
        the fill character would join the page and the bytes would be of a
        document nobody wrote.
        """
        db.query(Classification).delete()
        db.query(Book).delete()
        db.commit()

    def page_bytes(self, db: Any, admin: dict, fill: str, credits: int = 1) -> int:
        self.empty_the_shelf(db)
        group = copy_group_token()
        books = [
            self.widest_book(fill, credits, group) for _ in range(sru.MAX_RECORDS)
        ]
        for book in books:
            book.added_by_user_id = admin["user"]["id"]
        db.add_all(books)
        db.commit()
        digits = sum(len(str(book.id)) for book in books)
        assert digits == self.IDENTIFIER_DIGITS, (
            f"this page carries {digits} digits of row identifier in `001` "
            f"against the {self.IDENTIFIER_DIGITS} every figure here was "
            "measured with, so it weighs "
            f"{digits - self.IDENTIFIER_DIGITS} bytes more than it would have. "
            "The identifiers are not the subject of this class and the byte "
            "pin cannot tell you this is why it moved."
        )
        response = sru.respond(
            urlencode(
                {
                    "operation": "searchRetrieve",
                    # **The term is the fill character itself**, so the fixture
                    # needs no searchable token of its own. A token would be
                    # characters not at the column's bound, and the page would
                    # measure narrower than it reads.
                    "query": fill,
                    "maximumRecords": str(sru.MAX_RECORDS),
                },
            ),
            db,
            SERVER,
        )
        root = ElementTree.fromstring(response)
        assert len(record_ids(root)) == sru.MAX_RECORDS
        # The control: the shelf holds the fixture and nothing else, so these
        # bytes are the page this class claims to have measured.
        assert number_of_records(root) == sru.MAX_RECORDS
        return len(response.encode())

    def test_the_derivation_finds_the_columns_a_fill_can_widen(self):
        """The control, without which every arm below passes on an empty set.

        Three things: the population it draws from is not empty, the sentinels
        really are distinct, and something comes back from the record. The
        second is the one that was wrong before: a shared fill made one
        column's value answer for every shorter one.
        """
        sentinels = self.sentinels()
        assert len(set(sentinels.values())) == len(sentinels)
        assert self.wide_columns() - set(self.CEILINGS), (
            "every wide column now has a write ceiling, so the refusal below "
            "is drawn from an empty population and proves nothing"
        )
        emitted = self.emitted_columns()
        assert emitted <= self.wide_columns()
        assert self.filled(), "the derivation has stopped finding anything at all"
        # **The fact the `language` exemption rests on, asserted rather than
        # described, and it is not the one an earlier version asserted.** That
        # one compared the widest code against the column's ceiling, which is
        # `3 <= 10` and fires at eleven characters, a threshold with no
        # relation to anything: every length from four to ten is the failure
        # it was written for arriving green. The ceiling bounds what is
        # **stored**, the key, and what reaches `041 $a` is the looked up
        # **value**, so a two character key may map to an eleven character
        # code with nothing violated.
        #
        # The fact is that the code this fixture renders is as wide as any
        # code can be. Anything else and the page understates by the
        # difference, whatever the column allows.
        #
        # **Read off the rendered record rather than off the constant**, which
        # is the move this class already makes for columns and states as its
        # own principle: a rendered value is a property of the record and a
        # constant is a spelling. Reading the constant coupled two sites with
        # nothing enforcing the coupling, so moving FIXTURE_LANGUAGE onto a
        # six character key while the builder kept a hardcoded one passed
        # every arm here with the page understating by 150 bytes. It also puts
        # the lookup and its lowercasing back in the writer's hands, where
        # they belong, and removes the bare `KeyError` a constant naming no
        # key at all used to raise here.
        #
        # **An absent `041` fails with the message below** rather than
        # raising, by the empty fallback, and that failure is correct: a
        # fixture rendering no language field at all is a page measured
        # without one. The fallback means exactly that and nothing else,
        # because the writer drops an empty subfield and writes no element
        # when none survives, so the field cannot exist carrying an empty one.
        #
        # **Reading the first subfield is exact because the writer emits one**,
        # a single spec for that tag and one subfield per surviving spec.
        # **That is a property of this writer and not of MARC**, which permits
        # the field to repeat for a work in several languages. If a repeat
        # landed, a fixture at one language would stop being the widest, the
        # byte pin would redden without naming why, and the tag arm would not
        # move at all, since the tag is unchanged. Stated rather than armed,
        # which is this class's standard for a blind spot.
        record = marc.record_element(self.widest_book("&", self.MOST_CREDITS, "copies"))
        rendered_code = next(
            (
                subfield.text or ""
                for field in record
                if field.get("tag") == "041"
                for subfield in field
                if subfield.get("code") == "a"
            ),
            "",
        )
        widest_code = max(len(code) for code in BIBLIOGRAPHIC_CODES.values())
        # **The two branches are not the same quantity, which is why the
        # clause is branched rather than shared.** A narrower code is exactly
        # its own characters fewer. An absent field is the whole field:
        # measured on this fixture, 84 bytes a record and 4,200 a page, where
        # a shared clause computing a code width difference would have
        # printed 3. The absent branch quotes no figure at all, because this
        # arm cannot compute that one.
        shortfall = (
            "The record carries no `041` at all, so what is missing is the "
            "whole field rather than a few characters of it, and the field "
            "tag arm reddens too and names it by its tag."
            if not rendered_code
            else "The page understates by "
            f"{widest_code - len(rendered_code)} bytes a record."
        )
        assert len(rendered_code) == widest_code, (
            f"this fixture renders `041 $a {rendered_code}`, "
            f"{len(rendered_code)} characters, where the widest code in "
            f"`BIBLIOGRAPHIC_CODES` is {widest_code}. {shortfall} Move "
            "FIXTURE_LANGUAGE onto a key whose code is the widest one and "
            "re-measure the figures; do not loosen this assertion, which "
            "would be recording the understatement rather than removing it."
        )

    def test_every_emitted_column_a_fill_could_widen_has_a_width_here(self):
        """A column the record carries that this fixture has no width for.

        Then the page it measures is not the widest one. Named rather than
        filled with nothing, and the message does not prescribe the repair it
        used to: an earlier version told the reader to add the column to
        `catalogue._TEXT_CEILINGS`, which is the import path's ceiling. Doing
        that changes what an import drops from an external record, and for
        `location`, which a schema does bound, it also reddens
        `tests/test_catalogue.py`. **A refusal that misdirects its repair is
        the shape already removed once from this class.**
        """
        loose = self.emitted_columns() - set(self.CEILINGS)
        assert not loose, (
            "the MARC record carries a Book column this fixture has no width "
            f"for: {sorted(loose)}, so the page below is not the widest one. "
            "Two repairs, and they are not interchangeable. If a write path "
            "bounds the column, this fixture needs that bound: note that "
            "catalogue._TEXT_CEILINGS is the catalogue import's ceiling and "
            "not the API's, so adding a column there changes what an import "
            "drops and is a different decision. If nothing bounds it, the "
            "page has no widest and no figure here is one."
        )

    def test_the_record_carries_the_fields_this_page_was_measured_over(self):
        """The arm that names a field the widest record renders.

        Read off the rendered document rather than off the writer's source, so
        how the value was reached does not matter. **What it reaches is one
        record**, so a field fed by a relation this fixture leaves empty
        renders nothing and is named by nothing here; the class docstring has
        the measurement. For `classifications`, the one relation the fixture
        populates, a field is named.
        """
        record = marc.record_element(self.widest_book("&", self.MOST_CREDITS, "copies"))
        # The walrus is what narrows `Element.get` from `str | None` for the
        # type checker; a truthiness filter in the comprehension does not.
        tags = {tag for field in record if (tag := field.get("tag")) is not None}
        assert tags == set(self.FIELD_TAGS), (
            "the widest record's fields are not the ones this page was "
            f"measured over. Gained {sorted(tags - set(self.FIELD_TAGS))}, "
            f"lost {sorted(set(self.FIELD_TAGS) - tags)}."
        )

    def test_the_published_figure_is_this_one(self):
        """`docs/security.md` §SRU tells an operator what this door can emit.

        A number written in prose does not recount itself, and the class above
        exists because a figure this same document published was the wrong one.
        So the two are tied by an arm rather than by somebody remembering.
        """
        published = (
            Path(__file__).resolve().parents[2] / "docs" / "security.md"
        ).read_text(encoding="utf-8")
        assert f"{self.WIDEST_RESPONSE_BYTES:,} bytes" in published, (
            f"docs/security.md does not carry {self.WIDEST_RESPONSE_BYTES:,} "
            "bytes, which is what a page of the widest records weighs. That "
            "document is where an operator is told what a stranger can make "
            "this door emit."
        )
        # The description bound is quoted earlier in the section, in the
        # partition paragraph rather than beside the figure, and it is the
        # fact the figure rests on, so it is recounted rather than left as the
        # one number there that nothing reads back.
        #
        # **Both read-backs are whole document searches with no section
        # anchor.** The byte figure is distinctive enough for that to be
        # sound; the character figure is a round number, occurring once today
        # and with a near twin elsewhere in the tree, so a match here is
        # weaker evidence than the one above it.
        assert f"{DESCRIPTION_MAX:,} characters" in published, (
            f"docs/security.md does not carry {DESCRIPTION_MAX:,} characters, "
            "which is what a write through a schema holds a description to "
            "and is half of why the figure above is a figure at all."
        )

    def test_a_full_page_of_the_widest_records_still_weighs_what_it_did(
        self, db, admin
    ):
        """Equality rather than an inequality: the headroom is the defect.

        **This arm cannot say what changed** and its message does not pretend
        to. It is one integer against another, so a widened column bound, a new
        field and a deleted one are the same failure with different arithmetic,
        and a message instructing a re-pin would train exactly the response the
        arm exists to prevent. The arms above name the field, the column and
        the identifiers; this one says the document moved.

        The assertion is on the finished document, which is not the peak:
        `_serialise` holds the `ElementTree` and the string at once, measured at
        2.47 times for the export's own page.
        """
        measured = self.page_bytes(db, admin, "&", self.MOST_CREDITS)
        assert measured == self.WIDEST_RESPONSE_BYTES, (
            f"the widest page weighs {measured} bytes against the "
            f"{self.WIDEST_RESPONSE_BYTES} this figure was measured at, a "
            f"change of {measured - self.WIDEST_RESPONSE_BYTES}. What moved is "
            "not in this number: read the arms above, which name a field by "
            "its tag, a column by its name and the row identifiers by their "
            "digits."
        )

    def test_the_fill_character_is_part_of_what_decides_the_page(self, db, admin):
        """A `max_length` is characters and a response is bytes."""
        one_byte, two_byte, escaped = (
            self.page_bytes(db, admin, fill) for fill in self.FILLS
        )

        assert one_byte < two_byte < escaped
        assert escaped > 4 * one_byte

    def test_the_number_of_credited_names_is_the_other_half(self, db, admin):
        """Same column, same declared length, more fields.

        No length answers how many fields a record has, so a fixture of one
        long name measures the fewest `700` fields there can be.
        """
        one_name = self.page_bytes(db, admin, "&")
        many_names = self.page_bytes(db, admin, "&", self.MOST_CREDITS)

        extra_names = self.MOST_CREDITS - 1
        assert many_names - one_name > (
            sru.MAX_RECORDS * extra_names * self.SCAFFOLDING_PER_CREDIT
        )


class TestMaximumRecordsIsClamped:
    @pytest.fixture
    def many(self, db, admin):
        books = [
            Book(title=f"Windmill {n:03d}", added_by_user_id=admin["user"]["id"])
            for n in range(sru.MAX_RECORDS + 5)
        ]
        db.add_all(books)
        db.commit()
        return len(books)

    def test_a_request_above_the_cap_gets_the_cap(self, db, many):
        response = respond(
            db, operation="searchRetrieve", query="Windmill", maximumRecords="1000"
        )
        assert len(record_ids(response)) == sru.MAX_RECORDS
        assert number_of_records(response) == many

    def test_a_request_below_the_cap_gets_what_it_asked_for(self, db, many):
        response = respond(
            db, operation="searchRetrieve", query="Windmill", maximumRecords="3"
        )
        assert len(record_ids(response)) == 3

    def test_the_default_is_ten(self, db, many):
        response = respond(db, operation="searchRetrieve", query="Windmill")
        assert len(record_ids(response)) == sru.DEFAULT_RECORDS

    def test_zero_records_is_a_count_with_no_records(self, db, many):
        """A client asking how many there are without wanting any of them."""
        response = respond(
            db, operation="searchRetrieve", query="Windmill", maximumRecords="0"
        )
        assert record_ids(response) == []
        assert number_of_records(response) == many


class TestPagingThroughAResultSet:
    @pytest.fixture
    def many(self, db, admin):
        db.add_all(
            Book(title=f"Windmill {n:03d}", added_by_user_id=admin["user"]["id"])
            for n in range(5)
        )
        db.commit()

    def test_start_record_offsets_the_page(self, db, many):
        first = respond(
            db, operation="searchRetrieve", query="Windmill", maximumRecords="2"
        )
        second = respond(
            db,
            operation="searchRetrieve",
            query="Windmill",
            maximumRecords="2",
            startRecord="3",
        )
        assert not set(record_ids(first)) & set(record_ids(second))

    def test_the_next_position_points_at_the_next_page(self, db, many):
        response = respond(
            db, operation="searchRetrieve", query="Windmill", maximumRecords="2"
        )
        following = response.find(f"{SRW}nextRecordPosition")
        assert following is not None
        assert following.text == "3"

    def test_the_last_page_says_there_is_no_next_one(self, db, many):
        response = respond(
            db,
            operation="searchRetrieve",
            query="Windmill",
            maximumRecords="10",
            startRecord="1",
        )
        assert response.find(f"{SRW}nextRecordPosition") is None

    def test_starting_past_the_end_is_a_diagnostic(self, db, many):
        response = respond(
            db, operation="searchRetrieve", query="Windmill", startRecord="99"
        )
        assert diagnostic_of(response) == sru.Diagnostic.FIRST_RECORD_OUT_OF_RANGE

    def test_starting_past_the_end_of_nothing_is_not_an_error(self, db, many):
        """An empty result set has no end to be past, so a client paging
        through a query that matched nothing is not told it made a mistake."""
        response = respond(
            db, operation="searchRetrieve", query="Sawmill", startRecord="99"
        )
        assert diagnostic_of(response) is None
        assert number_of_records(response) == 0


#: One query per diagnostic, which is what says the register describes the
#: server rather than the specification.
#:
#: Keyed on the diagnostic so `TestEveryDiagnosticIsReachable` can assert the
#: table is total: a member with no row is a diagnostic this server claims to
#: raise and nothing can produce, and a member deleted from the enum leaves a
#: row here naming nothing.
REACHABLE: dict[sru.Diagnostic, dict[str, str]] = {
    sru.Diagnostic.UNSUPPORTED_OPERATION: {"operation": "scan"},
    sru.Diagnostic.UNSUPPORTED_VERSION: {"operation": "explain", "version": "2.0"},
    sru.Diagnostic.UNSUPPORTED_PARAMETER_VALUE: {
        "operation": "searchRetrieve",
        "query": "dog",
        "maximumRecords": "many",
    },
    sru.Diagnostic.MANDATORY_PARAMETER_NOT_SUPPLIED: {"operation": "searchRetrieve"},
    sru.Diagnostic.UNSUPPORTED_PARAMETER: {
        "operation": "searchRetrieve",
        "query": "dog",
        # A parameter nobody has heard of, which is the only thing 8 is for
        # now that the three the specification defines have their own numbers.
        "sortDirection": "ascending",
    },
    sru.Diagnostic.QUERY_SYNTAX_ERROR: {"query": "dog cat"},
    sru.Diagnostic.TOO_MANY_CHARACTERS_IN_QUERY: {"query": "a" * 2000},
    sru.Diagnostic.UNSUPPORTED_USE_OF_PARENTHESES: {"query": "(dog"},
    sru.Diagnostic.UNSUPPORTED_USE_OF_QUOTES: {"query": '"dog'},
    sru.Diagnostic.UNSUPPORTED_CONTEXT_SET: {"query": "zz.title=dog"},
    sru.Diagnostic.UNSUPPORTED_INDEX: {"query": "dc.nowhere=dog"},
    sru.Diagnostic.UNSUPPORTED_RELATION: {"query": "dc.title < 3"},
    sru.Diagnostic.UNSUPPORTED_RELATION_MODIFIER: {"query": "dc.title =/rel dog"},
    sru.Diagnostic.NON_SPECIAL_CHARACTER_ESCAPED: {"query": "dc.title=do\\zg"},
    sru.Diagnostic.EMPTY_TERM: {"query": "dc.title="},
    sru.Diagnostic.TOO_MANY_MASKING_CHARACTERS: {"query": "dc.title=" + "*" * 40},
    sru.Diagnostic.ANCHORING_NOT_SUPPORTED: {"query": "dc.title=^dog"},
    sru.Diagnostic.TERM_IN_INVALID_FORMAT: {"query": "dc.date=recently"},
    sru.Diagnostic.TOO_MANY_BOOLEAN_OPERATORS: {
        "query": " and ".join(f"dc.title=t{n}" for n in range(sru.MAX_CLAUSES + 1))
    },
    sru.Diagnostic.PROXIMITY_NOT_SUPPORTED: {"query": "dog prox cat"},
    sru.Diagnostic.FIRST_RECORD_OUT_OF_RANGE: {
        "query": "Chartreuse",
        "startRecord": "50",
    },
    sru.Diagnostic.UNKNOWN_SCHEMA_FOR_RETRIEVAL: {
        "query": "dog",
        "recordSchema": "info:srw/schema/1/dc-v1.1",
    },
    sru.Diagnostic.RESULT_SETS_NOT_SUPPORTED: {"query": "dog", "resultSetTTL": "60"},
    sru.Diagnostic.UNSUPPORTED_XML_ESCAPING_VALUE: {
        "query": "dog",
        "recordPacking": "string",
    },
    sru.Diagnostic.SORT_NOT_SUPPORTED: {"query": "dog", "sortKeys": "title"},
    sru.Diagnostic.XPATH_RETRIEVAL_UNSUPPORTED: {
        "query": "dog",
        "recordXPath": "/record/datafield",
    },
    sru.Diagnostic.STYLESHEETS_NOT_SUPPORTED: {
        "query": "dog",
        "stylesheet": "https://elsewhere.example/sru.xsl",
    },
}


class TestEveryDiagnosticIsReachable:
    """A diagnostic nothing can produce is a claim no client can act on."""

    def test_the_table_covers_the_register(self):
        assert set(REACHABLE) == set(sru.Diagnostic)

    @pytest.mark.parametrize(
        "expected", list(REACHABLE), ids=lambda d: f"{d.value}-{d.name.lower()}"
    )
    def test_the_query_produces_the_diagnostic(self, db, shelf, expected):
        assert diagnostic_of(respond(db, **REACHABLE[expected])) == expected

    @pytest.mark.parametrize("expected", list(REACHABLE), ids=lambda d: str(d.value))
    def test_a_refusal_is_well_formed_xml_that_names_the_uri(self, db, shelf, expected):
        """The one thing a refusal must not do is refuse in a document the
        client cannot parse. `respond` returns a string, and `ElementTree` is
        the parser that would raise on a control character reaching `<details>`.
        """
        response = respond(db, **REACHABLE[expected])
        uri = response.find(f"{SRW}diagnostics/{DIAG}diagnostic/{DIAG}uri")
        assert uri is not None
        assert uri.text == f"{sru.DIAGNOSTIC_URI}{expected.value}"


class TestAnIntegerTheCatalogueCannotHoldIsRefusedRatherThanRaised:
    """Three unauthenticated 500s, one ceiling, a test at each site.

    `int()` parses any number of digits and SQLite stores 64 bits, so a value in
    between parses here, reaches the driver and raises `OverflowError`. That is
    not an `SruError`, so it left `respond` and arrived as `Internal Server
    Error`. Found independently by both review seats against the running app
    with no credentials.

    The boundaries are asserted rather than described, because the whole defect
    was a boundary nobody had looked for: `2**63 - 1` is accepted at every site
    and `2**63` is refused.
    """

    OVER = str(2**63)
    AT = str(2**63 - 1)

    def test_a_record_id_past_the_range_is_a_diagnostic(self, db, shelf):
        response = respond(db, query=f"rec.id={self.OVER}")
        assert diagnostic_of(response) == sru.Diagnostic.TERM_IN_INVALID_FORMAT

    def test_a_record_id_at_the_range_is_answered(self, db, shelf):
        response = respond(db, query=f"rec.id={self.AT}")
        assert diagnostic_of(response) is None
        assert number_of_records(response) == 0

    def test_a_year_past_the_range_is_a_diagnostic(self, db, shelf):
        response = respond(db, query=f"dc.date>{self.OVER}")
        assert diagnostic_of(response) == sru.Diagnostic.TERM_IN_INVALID_FORMAT

    def test_a_negative_year_past_the_range_is_a_diagnostic(self, db, shelf):
        """**The arm a positive only bound would miss.** `-(2**63) - 1`
        overflows exactly as the positive end does, and a ceiling with no floor
        would have left one of the three routes open."""
        response = respond(db, query=f"dc.date>-{2**63 + 1}")
        assert diagnostic_of(response) == sru.Diagnostic.TERM_IN_INVALID_FORMAT

    def test_a_year_at_the_range_is_answered(self, db, shelf):
        response = respond(db, query=f"dc.date<{self.AT}")
        assert diagnostic_of(response) is None

    def test_a_start_record_past_the_range_is_a_diagnostic(self, db, shelf):
        """**The one the range check could not have caught.**
        `_search_response` runs `page()` with `start_record - 1` before it
        compares `start_record` against the total, so the overflow happened
        inside the query. The fix is at the conversion, not at that check."""
        response = respond(db, query="Chartreuse", startRecord=self.OVER)
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_PARAMETER_VALUE

    def test_a_start_record_at_the_range_is_answered(self, db, shelf):
        response = respond(db, query="Chartreuse", startRecord=self.AT)
        assert diagnostic_of(response) == sru.Diagnostic.FIRST_RECORD_OUT_OF_RANGE

    def test_a_maximum_records_past_the_range_is_a_diagnostic(self, db, shelf):
        """It never reached SQLite, since `min(wanted, MAX_RECORDS)` clamps it.
        Refused anyway, which is the behaviour change `_bounded_int` names: one
        rule at one place beats an exemption for the caller whose value happens
        not to reach the database."""
        response = respond(db, query="Chartreuse", maximumRecords=self.OVER)
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_PARAMETER_VALUE

    def test_a_maximum_records_a_client_might_really_send_is_still_clamped(
        self, db, shelf
    ):
        """The half that says the ceiling did not turn the clamp into a
        refusal for anything anybody sends."""
        response = respond(db, query="Chartreuse", maximumRecords="1000000")
        assert diagnostic_of(response) is None

    def test_a_term_cannot_reach_the_digit_limit_at_all(self, db, shelf):
        """**The two sites have different outer refusals, and this test had it
        wrong.** It asserted 36 for a 5,000 digit term and got 12: a term lives
        inside `query`, `MAX_QUERY_CHARS` is 1024, so the longest term anybody
        can send is about a thousand digits and CPython's own 4,300 digit
        refusal is unreachable here. The range check is the only one that ever
        fires on this path."""
        response = respond(db, query=f"rec.id={'9' * 5000}")
        assert diagnostic_of(response) == sru.Diagnostic.TOO_MANY_CHARACTERS_IN_QUERY

    def test_a_parameter_can_reach_it_and_is_refused_there(self, db, shelf):
        """The other site, where the digit limit is live: `startRecord` is its
        own parameter and no length bound covers it, so a 5,000 digit value
        reaches `int()` and is refused by CPython rather than by the range.

        **Asserted on the details rather than the number.** Both refusers answer
        diagnostic 6, so a test that checked only the number passed whichever
        arm fired and would go on passing with the digit limit gone, which is
        the one asymmetry this test's name claims to pin. "is not a number" is
        `int()` raising; "is outside" is the range.
        """
        response = respond(db, query="Chartreuse", startRecord="9" * 5000)
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_PARAMETER_VALUE
        assert details_of(response) == "startRecord is not a number"

    def test_the_range_and_the_digit_limit_are_told_apart(self, db, shelf):
        """The other half of the pair: the same parameter, the same diagnostic,
        the other refuser."""
        response = respond(db, query="Chartreuse", startRecord=str(2**63))
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_PARAMETER_VALUE
        details = details_of(response)
        assert details is not None
        assert details.startswith("startRecord is outside")


class TestSortingIsRefusedInBothSpellings:
    """SRU 1.2 moved sorting out of the parameters and into CQL.

    So a client using the **current** spelling was being told its query was
    malformed, diagnostic 10, while the retired parameter got the honest 80.
    `_Parser.parse` recognises `sortby` for the same reason `_query` recognises
    `prox`: a named refusal beats a syntax error.
    """

    @pytest.mark.parametrize(
        "spec",
        [
            "dc.date",
            "dc.date/ascending",
            "dc.date/sort.descending",
            "dc.date/ascending dc.title/descending",
        ],
        ids=["bare", "modifier", "qualified modifier", "two keys"],
    )
    def test_every_spelling_of_the_cql_clause_is_refused_as_sorting(
        self, db, shelf, spec
    ):
        """**The family, not the one spelling a review named.**

        A sort spec carries its modifiers on a `/`, and `_tokenise` refuses a
        `/` with diagnostic 20 before a parser exists, so the first version of
        this arm covered only the bare form and answered "no relation
        modifiers" to CQL 1.2's ordinary one. Wrong twice: it is not a relation
        modifier, and the client asked for sorting.
        """
        response = respond(db, query=f"dc.title=Chartreuse sortby {spec}")
        assert diagnostic_of(response) == sru.Diagnostic.SORT_NOT_SUPPORTED

    def test_a_real_relation_modifier_is_still_a_relation_modifier(self, db, shelf):
        """The diagonal. Without it the arm above could answer 80 to every `/`
        and the relation modifier refusal would be unreachable."""
        response = respond(db, query="dc.title =/rel dog")
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_RELATION_MODIFIER

    def test_the_retired_parameter_is_refused_as_sorting_too(self, db, shelf):
        response = respond(db, query="Chartreuse", sortKeys="dc.date")
        assert diagnostic_of(response) == sru.Diagnostic.SORT_NOT_SUPPORTED

    def test_a_quoted_sortby_is_still_a_term(self, db, admin):
        """It is a CQL keyword outside quotes and a word inside them, like the
        booleans. Without this the arm would eat a legitimate search."""
        db.add(Book(title="Sortby And Other Stories", added_by_user_id=admin["user"]["id"]))
        db.commit()
        response = respond(db, query='dc.title="sortby and other"')
        assert diagnostic_of(response) is None
        assert number_of_records(response) == 1


class TestAHostileQueryCannotBreakTheDocument:
    """The response is XML and half of a diagnostic is the client's own text."""

    def test_a_control_character_in_a_query_is_refused(self, db):
        response = respond(db, query="dc.title=do\x01g")
        assert diagnostic_of(response) == sru.Diagnostic.QUERY_SYNTAX_ERROR

    def test_a_control_character_in_an_index_never_reaches_the_details(self, db):
        """The index is echoed in `<details>`, so it is the one place client
        text reaches the document. `_safe` drops what XML cannot carry."""
        response = respond(db, query="dc.no\x0bpe=dog")
        assert "\x0b" not in ElementTree.tostring(response, encoding="unicode")

    def test_a_long_index_name_is_truncated_rather_than_echoed(self, db):
        response = respond(db, query="dc." + "n" * 400 + "=dog")
        details = response.find(f"{SRW}diagnostics/{DIAG}diagnostic/{DIAG}details")
        assert details is not None
        assert details.text is not None
        assert len(details.text) <= 60

    def test_markup_echoed_into_a_diagnostic_is_escaped(self, db):
        """An unsupported parameter's **name** is echoed, and a name is client
        text. Serialised it must be escaped; parsed back it must be the same
        string, which is what says the escaping is escaping rather than
        stripping."""
        raw = sru.respond(
            urlencode(
                {"operation": "searchRetrieve", "query": "dog", "<script>": "1"}
            ),
            db,
            SERVER,
        )
        assert "<script>" not in raw
        assert "&lt;script&gt;" in raw
        response = ElementTree.fromstring(raw)
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_PARAMETER
        details = response.find(f"{SRW}diagnostics/{DIAG}diagnostic/{DIAG}details")
        assert details is not None
        assert details.text == "<script>"

    def test_a_refusal_with_nothing_to_echo_carries_no_details_element(self, db):
        """A blank parameter is kept, so `operation=` is refused with empty
        details, and an empty `<details>` would be noise a client has to read."""
        response = respond(db, operation="")
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_OPERATION
        assert response.find(f"{SRW}diagnostics/{DIAG}diagnostic/{DIAG}details") is None

    def test_a_parameter_sent_twice_is_refused(self, db):
        """Neither taking the first nor taking the last is right, because the
        client cannot tell which it got. `targets.py` records the same hazard
        from the writing side."""
        response = ElementTree.fromstring(
            sru.respond("operation=explain&operation=scan", db, SERVER)
        )
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_PARAMETER_VALUE


class TestMaskingMeansWhatTheClientMeant:
    @pytest.fixture
    def books(self, db, admin):
        titles = ["Discount 100% Cotton", "Discount 100 Percent", "The Windmill"]
        db.add_all(
            Book(title=title, added_by_user_id=admin["user"]["id"]) for title in titles
        )
        db.commit()
        return titles

    def _titles(self, db, query: str) -> set[str]:
        response = respond(db, operation="searchRetrieve", query=query)
        assert diagnostic_of(response) is None
        return {
            "".join(subfield.itertext())
            for datafield in response.iter(f"{MARC21}datafield")
            if datafield.get("tag") == "245"
            for subfield in datafield
            if subfield.get("code") in ("a", "p")
        }

    def test_a_literal_per_cent_is_not_a_wildcard(self, db, books):
        """**The property the escape ordering exists for.** A client searching
        for `100%` means a per cent sign; an unescaped pattern would match the
        book beside it too."""
        assert self._titles(db, 'dc.title="100%"') == {"Discount 100% Cotton"}

    def test_a_literal_underscore_is_not_a_wildcard(self, db, admin):
        db.add_all(
            Book(title=title, added_by_user_id=admin["user"]["id"])
            for title in ("Volume A_B", "Volume AxB")
        )
        db.commit()
        assert self._titles(db, 'dc.title="A_B"') == {"Volume A_B"}

    def test_a_query_of_masks_at_the_bound_is_answered_rather_than_slow(
        self, db, books
    ):
        """The measurement behind `MAX_MASKS_IN_A_TERM`, as a shape it admits.

        **The figure this pinned was taken on a fixture that could not match.**
        `('%a' * 400)` needs 400 literal `a`s inside a 120 character title, so
        it fails at the first position for every row and never backtracks at
        all, and 400 is above the bound anyway. The conclusion held and the
        evidence did not.
        """
        response = respond(
            db,
            operation="searchRetrieve",
            query="dc.title=" + "*t" * sru.MAX_MASKS_IN_A_TERM,
        )
        assert diagnostic_of(response) is None

    def test_a_star_is_a_wildcard(self, db, books):
        assert self._titles(db, "dc.title=Discount*Cotton") == {
            "Discount 100% Cotton"
        }

    def test_an_escaped_star_is_a_literal_asterisk(self, db, admin):
        """The pair that makes the point: one query, one backslash, two answers."""
        db.add_all(
            Book(title=title, added_by_user_id=admin["user"]["id"])
            for title in ("Star*Struck", "Star Really Struck")
        )
        db.commit()
        assert self._titles(db, "dc.title=Star*Struck") == {
            "Star*Struck",
            "Star Really Struck",
        }
        assert self._titles(db, "dc.title=Star\\*Struck") == {"Star*Struck"}

    def test_a_question_mark_matches_one_character(self, db, admin):
        db.add_all(
            Book(title=title, added_by_user_id=admin["user"]["id"])
            for title in ("Cat", "Coat")
        )
        db.commit()
        assert self._titles(db, "dc.title=C?t") == {"Cat"}


class TestTheQueryLanguageBehavesAsCqlSaysRatherThanAsSqlWould:
    @pytest.fixture
    def books(self, db, admin):
        db.add_all(
            [
                Book(
                    title="Alpha",
                    publisher="Gemini",
                    added_by_user_id=admin["user"]["id"],
                ),
                Book(title="Beta", added_by_user_id=admin["user"]["id"]),
                Book(
                    title="Gamma",
                    publisher="Gemini",
                    added_by_user_id=admin["user"]["id"],
                ),
            ]
        )
        db.commit()

    def _count(self, db, query: str) -> int:
        response = respond(db, operation="searchRetrieve", query=query, maximumRecords="50")
        assert diagnostic_of(response) is None
        return number_of_records(response)

    def test_booleans_are_left_associative_with_equal_precedence(self, db, books):
        """CQL has one precedence level and SQL has three. `a or b and c` is
        `(a or b) and c` here, which is the whole reason a client that assumes
        otherwise gets a different answer than it expected."""
        assert self._count(db, "Alpha or Beta and Gamma") == self._count(
            db, "(Alpha or Beta) and Gamma"
        )
        assert self._count(db, "Alpha or Beta and Gamma") != self._count(
            db, "Alpha or (Beta and Gamma)"
        )

    def test_not_is_binary_rather_than_a_negation_of_the_library(self, db, books):
        """Three titles carry an `a` and one of them is Alpha, so `not` leaves
        two. A unary reading would have answered with the rest of the library."""
        assert self._count(db, "dc.title=a") == 3
        assert self._count(db, "dc.title=a not dc.title=Alpha") == 2

    def test_not_does_not_swallow_the_rows_with_nothing_in_that_column(self, db, books):
        """**The NULL guard on every leaf, seen from the outside.**

        Two of the three books have a publisher and one has none. Without the
        guard `NOT (publisher LIKE 'Gemini')` is NULL for that row and it
        disappears, so a client excluding one publisher would silently lose
        every book that names none.
        """
        assert self._count(db, "dc.title=a not dc.publisher=Gemini") == 1

    def test_a_quoted_boolean_is_a_term(self, db, admin):
        db.add(Book(title="And Then There Were None", added_by_user_id=admin["user"]["id"]))
        db.commit()
        assert self._count(db, 'dc.title="and then"') == 1


class TestEveryIndexSearchesOnlyAPublishedColumn:
    """A filter is a read of the column it filters on, one query at a time.

    **The same rule `TestEveryPublicSortOrdersByAPublishedColumn` applies to the
    ORDER BY, applied to the WHERE**, and written in the same shape so there is
    one rule rather than two that resemble each other. That test compiles what
    `order_for` produces and rejects any column `PublicBookOut` withholds; this
    compiles what each index produces and asks the same question.

    It was missing, and the gap was not theoretical: the record writer was
    guarded and the query was not, so an index over `location` would have been
    an oracle a stranger walks one query at a time with the row filter perfectly
    intact. A `dc.subject` pointed at the shelf mark is exactly the shape a
    cataloguer would ask for.

    Scoped to `books` columns. A column on `tags` is a different question and
    `PublicBookOut.tags` answers it.

    **The blind spot that follows is wider than "another table is not checked",
    and is stated rather than left to be found.** An index that reached *only*
    another table would render `books.id` and nothing else, which is published,
    so it would pass this rule while being checked by nothing. No such index
    exists, `dc.subject` being anchored at `books` through the `EXISTS`, and the
    day one does it needs a rule of its own rather than a widening of this one.
    """

    @staticmethod
    def _columns(index: sru.Index) -> set[str]:
        """The `books` columns one index compares against, off the compiled SQL."""
        import re

        from sqlalchemy.dialects import sqlite

        term = "1990" if index.field in (sru.Field.DATE, sru.Field.RECORD_ID) else "x"
        clause = sru.criteria(sru.parse(f'{index.qualified}="{term}"'))
        rendered = str(
            clause.compile(
                dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        return set(re.findall(r"books\.(\w+)", rendered))

    def test_the_rule_can_read_the_columns_at_all(self):
        """Without this the rule below passes on an empty set, which is what a
        change in how SQLAlchemy renders a clause would produce."""
        assert self._columns(sru._BY_NAME["dc.title"]) == {"title"}
        assert self._columns(sru._BY_NAME["cql.serverchoice"]) == {
            "title",
            "author",
            "isbn",
        }

    def test_every_index_names_only_published_columns(self):
        published = set(PublicBookOut.model_fields)
        offenders = {
            index.qualified: sorted(self._columns(index) - published)
            for index in sru.INDEXES
            if self._columns(index) - published
        }
        assert offenders == {}, (
            f"These indexes filter on a column the public payload withholds: "
            f"{offenders}. A filter is a read of its column one query at a "
            "time, and the row filter does not stop it: a stranger binary "
            "searches the value. Either publish the column or take the index "
            "out of INDEXES."
        )

    def test_an_index_over_a_withheld_column_is_what_would_fail(self):
        """The diagonal. Without it the rule above would pass with `_columns`
        returning nothing, or on an `INDEXES` that had quietly become empty."""
        published = set(PublicBookOut.model_fields)
        assert "location" not in published
        rendered = str(sru._matches(Book.location, sru._pieces("study"), contains=True))
        import re

        assert set(re.findall(r"books\.(\w+)", rendered)) - published == {"location"}


class TestTheRecordCarriesNoColumnThePublicPayloadWithholds:
    """The column boundary, applied to a record `marc.py` writes.

    `Shelf.seen_by_the_public` filters **rows**, and a public Book still carries
    what the household paid for it and which room it is in. `schemas/public.py`
    is the column boundary for the JSON catalogue; this is the same boundary for
    the MARC one, and it holds today only because `marc.py` happens to write no
    field for any of it.

    **Asserted by rendering rather than by reading the source.** An AST walk
    would be looking for `book.location`, which is one spelling of a thing that
    has several, and would say nothing about a value reaching the record through
    a helper. This puts a distinctive value in every withheld column, renders
    the record, and looks for it in the bytes.

    **One table, named because both arms here are green and blind past it.**
    The population is `Book.__table__.columns` against `PublicBookOut`, so a
    `classifications` column measured against `PublicClassificationOut` is
    outside both of them and neither says anything about it. That boundary is
    `TestTheRecordCarriesNoClassificationColumnThePublicPayloadWithholds` below,
    and these two are not evidence about it.
    """

    #: Withheld columns this test cannot put a distinctive value in.
    #:
    #: Named rather than skipped silently, and the reason is per column rather
    #: than "the rest": a boolean has two values and both are ordinary, a date
    #: is not a string a search can find, and the two foreign keys point at rows
    #: this test does not create. All five are read by the shelf rather than
    #: written to a record, so a leak through one of them would be a leak of a
    #: row and not of a column, which is the other test in this file.
    UNSENTINELLED = {
        "is_private",
        "deleted_at",
        "added_at",
        "added_by_user_id",
        "collection_id",
    }

    @staticmethod
    def _withheld() -> set[str]:
        return {
            column.key
            for column in Book.__table__.columns
            if column.key not in PublicBookOut.model_fields
        }

    def test_there_are_withheld_columns_to_check(self):
        """Without this the whole class passes on a Book with nothing private
        on it, which is exactly what it would look like if `PublicBookOut` grew
        an exclusion list instead of being a separate model."""
        assert len(self._withheld() - self.UNSENTINELLED) >= 5

    def test_every_withheld_column_is_either_sentinelled_or_named(self):
        assert self._withheld() >= self.UNSENTINELLED

    def test_no_withheld_value_appears_in_a_rendered_record(self):
        sentinels = {
            key: f"withheld{n}sentinel"
            for n, key in enumerate(sorted(self._withheld() - self.UNSENTINELLED))
        }
        # A transient Book, never added to a session, so a CHECK constraint on
        # `ownership` or `condition` cannot refuse a sentinel and there is no
        # row for anything else to reach.
        book = Book(id=1, title="Chartreuse Windmill")
        for key, value in sentinels.items():
            setattr(book, key, value)

        rendered = ElementTree.tostring(marc.record_element(book), encoding="unicode")
        for key, value in sentinels.items():
            assert value not in rendered, (
                f"`{key}` is withheld from the public payload and reached a "
                "MARC record. The SRU server publishes these records, so this "
                "is a column leak. Either the field does not belong in the "
                "record, or the SRU server needs a writer of its own."
            )
        # The control: the record is not empty, so the absences above mean
        # something.
        assert "Chartreuse Windmill" in rendered

    def test_the_marc_writer_reads_nothing_the_payload_withholds(self):
        """The second instrument, and it is a different one on purpose.

        Rendering catches a value that reaches the document. This catches a
        column that is *read* at all, which is the earlier symptom, and it
        catches it for a column whose value happens not to render. Two routes to
        one fact, because agreement between two readings of the same route is
        not evidence.
        """
        # The walk is `book_columns_marc_reads`, which carries what it sees and
        # what it cannot. `getattr(book, name)` is invisible to it and is left
        # to the rendering test above, which does not read source at all.
        read = book_columns_marc_reads()
        assert read, "this guard has stopped finding anything at all"
        assert read <= set(PublicBookOut.model_fields), (
            "marc.py reads a Book column the public payload withholds: "
            f"{sorted(read - set(PublicBookOut.model_fields))}"
        )


class TestTheRecordCarriesNoClassificationColumnThePublicPayloadWithholds:
    """The same column boundary, one table over, which is the table a heading is.

    **The class above is green and stays green while being blind to this**, and
    that is the whole reason this exists rather than a sentence. Its population
    is `Book.__table__.columns` measured against `PublicBookOut`; a heading's
    scheme, number, caption and kind are `classifications` columns measured
    against `PublicClassificationOut`. Neither arm up there looks at this
    boundary, so neither is evidence about it, and the record now carries more
    of this table than it used to.

    **Rendered rather than read out of the source**, for the reason the class
    above gives and for one more that belongs to this table alone: an AST walk
    over attribute names cannot tell whose `id` it found, and `marc.py` reads
    `book.id` for the `001`, so the source instrument reports a leak of the one
    column the two tables share while nothing is wrong.
    """

    @staticmethod
    def _withheld() -> set[str]:
        return {
            column.key
            for column in Classification.__table__.columns
            if column.key not in PublicClassificationOut.model_fields
        }

    def test_there_are_withheld_columns_to_check(self):
        """Without this the arm below passes on a table with nothing withheld,
        which is what it would look like if `PublicClassificationOut` grew into
        a copy of the row."""
        assert len(self._withheld()) >= 3

    def test_no_withheld_value_appears_in_a_rendered_record(self):
        book = Book(id=1, title="Chartreuse Windmill")
        heading = Classification(
            scheme=ClassificationScheme.GND,
            number="4139307-7",
            label="CD-ROM",
            kind=HeadingKind.CARRIER,
        )
        book.classifications.append(heading)
        # **Set after the constructor and after the append, both deliberately.**
        # `Classification._file_the_number` derives `sort_key` on every ORM write
        # of `scheme` or `number`, so a sentinel passed to the constructor is
        # overwritten by the derivation and the arm would assert nothing about
        # that column. A transient row, never added to a session, so no type
        # refuses a string in an integer column and no flush regenerates a key.
        sentinels = {
            key: f"withheldheading{n}sentinel"
            for n, key in enumerate(sorted(self._withheld()))
        }
        for key, value in sentinels.items():
            setattr(heading, key, value)

        rendered = ElementTree.tostring(marc.record_element(book), encoding="unicode")
        for key, value in sentinels.items():
            assert value not in rendered, (
                f"`{key}` is withheld from the public classification payload and "
                "reached a MARC record. The SRU server publishes these records, "
                "so this is a column leak. Either the subfield does not belong "
                "in the record, or the public model should carry the column."
            )
        # The control: the published half of the row did reach the record, so
        # the absences above are about the boundary and not about an empty field.
        assert "CD-ROM" in rendered
        assert "gnd-carrier" in rendered


class TestTheParametersClientsActuallySend:
    """SRU 1.1 and 1.2 make `version` mandatory and real clients omit it."""

    def test_a_request_with_no_version_is_answered(self, db, shelf):
        response = respond(db, operation="searchRetrieve", query="Chartreuse")
        assert diagnostic_of(response) is None
        version = response.find(f"{SRW}version")
        assert version is not None
        assert version.text == sru.DEFAULT_VERSION

    @pytest.mark.parametrize("version", sru.SUPPORTED_VERSIONS)
    def test_a_supported_version_is_echoed_back(self, db, shelf, version):
        response = respond(
            db, operation="searchRetrieve", query="Chartreuse", version=version
        )
        echoed = response.find(f"{SRW}version")
        assert echoed is not None
        assert echoed.text == version

    def test_a_query_with_no_operation_is_a_search(self, db, shelf):
        """SRU 2.0's rule, applied here because it is what clients do."""
        response = respond(db, query="Chartreuse")
        assert response.tag == f"{SRW}searchRetrieveResponse"
        assert number_of_records(response) == 1

    def test_no_parameters_at_all_is_an_explain(self, db):
        response = respond(db)
        assert response.tag == f"{SRW}explainResponse"

    def test_an_x_prefixed_extension_parameter_is_ignored(self, db, shelf):
        """The specification reserves `x-` for extensions, so a client sending
        one must not be refused for it."""
        params = {"operation": "searchRetrieve", "query": "Chartreuse"}
        response = ElementTree.fromstring(
            sru.respond(urlencode(params) + "&x-anything=1", db, SERVER)
        )
        assert diagnostic_of(response) is None

    def test_the_one_packing_this_answers_in_may_be_asked_for(self, db, shelf):
        response = respond(
            db, operation="searchRetrieve", query="Chartreuse", recordPacking="xml"
        )
        assert diagnostic_of(response) is None
        assert number_of_records(response) == 1

    def test_a_query_of_only_spaces_is_a_query_not_supplied(self, db, shelf):
        response = respond(db, operation="searchRetrieve", query="   ")
        assert diagnostic_of(response) == sru.Diagnostic.MANDATORY_PARAMETER_NOT_SUPPLIED

    @pytest.mark.parametrize("name", sorted(sru.SCHEMA_NAMES))
    def test_both_spellings_of_the_marcxml_schema_are_accepted(self, db, shelf, name):
        response = respond(
            db, operation="searchRetrieve", query="Chartreuse", recordSchema=name
        )
        assert diagnostic_of(response) is None

    def test_record_packing_string_is_refused_rather_than_ignored(self, db, shelf):
        """Ignoring it would hand back XML to a client that asked for escaped
        text and cannot read what it got."""
        response = respond(
            db,
            operation="searchRetrieve",
            query="Chartreuse",
            recordPacking="string",
        )
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_XML_ESCAPING_VALUE

    @pytest.mark.parametrize(
        "name", sorted(sru._DECLINED_PARAMETERS), ids=lambda n: n
    )
    def test_a_declined_feature_is_not_reported_as_an_unknown_parameter(
        self, db, shelf, name
    ):
        """**The distinction the table exists for, asserted rather than
        described.** Each of these is a parameter the specification defines and
        this server does not implement, so answering 8 would tell a client there
        is no such parameter when what there is no such thing as is the feature.

        Driven off the table, so a fourth entry is covered the day it is added
        and cannot quietly be given the generic code.
        """
        response = respond(db, query="Chartreuse", **{name: "1"})
        assert diagnostic_of(response) == sru._DECLINED_PARAMETERS[name]
        assert diagnostic_of(response) != sru.Diagnostic.UNSUPPORTED_PARAMETER

    def test_a_parameter_nobody_defines_is_still_the_generic_refusal(self, db, shelf):
        """The other half: without this the table could swallow everything and
        diagnostic 8 would be unreachable with nothing failing."""
        response = respond(db, query="Chartreuse", sortDirection="ascending")
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_PARAMETER


class TestTheResponseIsARecordAnotherSystemCanRead:
    def test_a_record_is_marcxml_in_its_own_namespace(self, db, shelf):
        """**The namespace is on the record and not on the response root.**

        The MARC elements carry unqualified tags, so a record appended into a
        document whose root declares the SRU namespace would arrive at the
        client as SRU elements with MARC names.
        """
        response = respond(db, operation="searchRetrieve", query="Chartreuse")
        record = response.find(
            f"{SRW}records/{SRW}record/{SRW}recordData/{MARC21}record"
        )
        assert record is not None
        assert record.find(f"{MARC21}leader") is not None

    def test_the_schema_and_packing_are_named_on_every_record(self, db, shelf):
        response = respond(db, operation="searchRetrieve", query="Chartreuse")
        for record in response.iter(f"{SRW}record"):
            schema = record.find(f"{SRW}recordSchema")
            packing = record.find(f"{SRW}recordPacking")
            assert schema is not None
            assert schema.text == sru.MARCXML_SCHEMA
            assert packing is not None
            assert packing.text == "xml"

    def test_a_record_reads_back_through_this_application_own_marc_reader(
        self, db, shelf
    ):
        """The strongest test available, and it is `marc.py`'s own: a record
        this server writes is a record this application's live catalogue parser
        accepts, rather than one that merely validates against a schema."""
        response = sru.respond(
            urlencode({"operation": "searchRetrieve", "query": "Chartreuse"}),
            db,
            SERVER,
        )
        root = ElementTree.fromstring(response)
        record = root.find(f"{SRW}records/{SRW}record/{SRW}recordData/{MARC21}record")
        assert record is not None
        collection = ElementTree.Element(
            "collection", {"xmlns": "http://www.loc.gov/MARC21/slim"}
        )
        collection.append(record)
        parsed = marc.read(
            ElementTree.tostring(collection, encoding="unicode").encode()
        )
        assert [entry.title for entry in parsed.records] == [SHARED["title"]]


class TestARecordSaysWhatEachHeadingWasAsserting:
    """A heading leaving this server says what the citing record asserted.

    **Here rather than only in `tests/test_marc.py` because of who reads it.**
    That file holds the round trip, which asks whether this application can read
    its own export back. This asks what an ingest at another institution
    receives from a server that answered without a session: a carrier written
    into a topical field is this catalogue asserting that a disc is what a book
    is about, and nothing in the record they hold contradicts it. The JSON
    payload already publishes the kind for that reason, which
    `schemas/public.py` states; this is the other half of the same server.
    """

    @pytest.fixture
    def disc(self, db, admin):
        """One public book whose GND row the record marked as a carrier.

        A real `Classification` rather than a stand-in, because the kind reaches
        the writer off a stored row and `Classification._file_the_number`
        derives the sort key that the column's NOT NULL demands.
        """
        book = Book(
            isbn="9780000000004", added_by_user_id=admin["user"]["id"], **SHARED
        )
        book.classifications.append(
            Classification(
                scheme=ClassificationScheme.GND,
                number="4139307-7",
                label="CD-ROM",
                kind=HeadingKind.CARRIER,
            )
        )
        db.add(book)
        db.commit()
        db.refresh(book)
        return book.id

    @staticmethod
    def _heading_fields(root: ElementTree.Element) -> list[tuple[str, dict[str, str]]]:
        """Every `65X` field in a response, as `(tag, subfields)`.

        The whole field rather than a search for the code: a test asserting only
        that `gnd-carrier` appears somewhere passes on a `650` carrying it,
        which is the spelling this class exists to refuse.
        """
        return [
            (
                field.get("tag") or "",
                {
                    subfield.get("code") or "": subfield.text or ""
                    for subfield in field.iter(f"{MARC21}subfield")
                },
            )
            for field in root.iter(f"{MARC21}datafield")
            if (field.get("tag") or "").startswith("65")
        ]

    def test_a_carrier_reaches_a_stranger_as_a_carrier(self, db, disc):
        response = respond(db, query=f"rec.id={disc}")
        assert diagnostic_of(response) is None
        assert self._heading_fields(response) == [
            (
                "655",
                {"a": "CD-ROM", "0": "(DE-588)4139307-7", "2": "gnd-carrier"},
            )
        ]

    def test_the_shelf_without_the_row_carries_no_heading_field_at_all(
        self, db, shelf
    ):
        """The control: no row, no field.

        **It holds less than a first version of this docstring claimed**, and
        the narrower statement is the honest one. It takes the shelf without the
        disc, so no `65X` field exists anywhere in that database, and a
        `rec.id` query answers with a single record, so the document and the
        record are the same tree in both tests here. What this catches is a
        reader returning a constant or searching too broadly, **not** a scoping
        error. Catching that needs a response carrying two records, one of them
        holding the carrier row, which is an arm rather than a wording change.
        """
        response = respond(db, query=f"rec.id={shelf['public']}")
        assert self._heading_fields(response) == []


# ── The parser and the escaping as properties ─────────────────────────────────
#
# **Every class above drives one query somebody wrote down.** What is below is
# the two claims the module makes about *every* query: that parsing one answers
# with a tree or with a diagnostic and never with anything else, and that a term
# put into a LIKE pattern matches the text the client asked for and nothing
# else.
#
# Both are claims a case cannot make. The first is about the complement of every
# query anybody thought of, and the complement is where a `ValueError` from
# `int()`, an `OverflowError` from the driver and a `RecursionError` from the
# descent have each already turned a refusal into a 500.

#: Every index name a client might send: the ones this server has, the bare
#: spellings, and names it does not have in both shapes a refusal distinguishes.
_INDEX_NAMES = st.sampled_from(
    [index.qualified for index in sru.INDEXES]
    + list(sru.BARE_INDEXES)
    + ["", "cql.nosuch", "nosuch.title", "nosuch", "9bad", "dc."]
)

#: Every relation, spelled as a symbol and as a word, including the three that
#: are recognised in order to be refused by name.
_RELATIONS = st.sampled_from(
    [*sru._RELATION_SYMBOLS, " all ", " any ", " exact ", " within ", " adj ", ""]
)

#: A term as a client writes one: the masks, the escapes, the anchor, the
#: quote and the space are all in the alphabet, because each of them is a
#: branch of `_pieces` and none of them is a character a term may not contain.
_TERM_TEXT = st.text(alphabet='abZ09*?\\"^ ', max_size=8)

_SINGLE_CLAUSES = st.builds(
    lambda index, relation, term: f"{index}{relation}{term}",
    _INDEX_NAMES,
    _RELATIONS,
    _TERM_TEXT,
)

#: A whole query: clauses, the booleans between them, parentheses, and the
#: `sortby` clause SRU 1.2 moved sorting into.
_GRAMMAR = st.recursive(
    _SINGLE_CLAUSES,
    lambda inner: st.one_of(
        st.builds(
            lambda left, operator, right: f"{left} {operator} {right}",
            inner,
            st.sampled_from(["and", "or", "not", "prox", "AND", "Or"]),
            inner,
        ),
        st.builds(lambda inner_query: f"({inner_query})", inner),
        st.builds(lambda query, key: f"{query} sortby {key}", inner, _INDEX_NAMES),
    ),
    max_leaves=5,
)

#: The shapes that are about a bound rather than about a grammar. Each of the
#: five bounds in this module refuses something a well formed query would
#: otherwise walk straight into, and the depth one is the only thing between a
#: nest of parentheses and a `RecursionError` the router would serve as a 500.
_AT_THE_BOUNDS = st.one_of(
    st.builds(lambda depth: "(" * depth + "a" + ")" * depth, st.integers(1, 400)),
    st.builds(lambda count: " and ".join(["a"] * count), st.integers(1, 40)),
    st.builds(lambda count: "a" + "*" * count, st.integers(1, 20)),
    st.builds(lambda count: "dc.title=" + "w " * count, st.integers(1, 30)),
    st.builds(lambda size: "a" * size, st.integers(1, 1_200)),
    st.builds(lambda digits: f"rec.id={digits}", st.text("0123456789", max_size=40)),
    st.builds(lambda digits: f"dc.date>{digits}", st.text("-0123456789", max_size=40)),
)

#: Everything that reaches `parse`, which is an unauthenticated query string.
ANY_QUERY = st.one_of(st.text(max_size=60), _SINGLE_CLAUSES, _GRAMMAR, _AT_THE_BOUNDS)


@pytest.mark.property
class TestTheGeneratorStillReachesBothAnswers:
    """The control. A generator that had stopped producing parseable queries
    would leave the class below asserting only that refusals are refusals."""

    def test_it_reaches_a_query_that_parses(self):
        witness(ANY_QUERY, _parses, reaches="a query that parses")

    def test_it_reaches_a_query_that_is_refused(self):
        witness(ANY_QUERY, lambda query: not _parses(query), reaches="a refused query")

    def test_it_reaches_a_nest_deep_enough_to_be_refused_for_its_depth(self):
        """The bound that stands between a client and a `RecursionError`."""
        witness(
            ANY_QUERY,
            lambda query: _diagnostic_of(query)
            is sru.Diagnostic.UNSUPPORTED_USE_OF_PARENTHESES,
            reaches="a query refused for its parentheses",
        )

    def test_it_reaches_a_masked_term(self):
        witness(
            ANY_QUERY,
            lambda query: _parses(query) and "*" in query,
            reaches="a term carrying a wildcard",
        )


def _parses(query: str) -> bool:
    try:
        sru.parse(query)
    except sru.SruError:
        return False
    return True


def _diagnostic_of(query: str) -> sru.Diagnostic | None:
    try:
        sru.parse(query)
    except sru.SruError as error:
        return error.diagnostic
    return None


class TestAMalformedQueryIsRefusedByName:
    @pytest.mark.parametrize("query", ["dog and", "(dog or"])
    def test_a_query_that_stops_where_a_clause_must_follow_is_a_syntax_error(self, query):
        assert _diagnostic_of(query) is sru.Diagnostic.QUERY_SYNTAX_ERROR

    def test_a_closing_parenthesis_with_nothing_open_is_refused(self):
        assert _diagnostic_of(")dog") is sru.Diagnostic.UNSUPPORTED_USE_OF_PARENTHESES

    def test_a_bare_index_name_means_the_index_it_abbreviates(self, db, shelf):
        bare = respond(db, query="title = Chartreuse")
        assert diagnostic_of(bare) is None
        assert record_ids(bare) == record_ids(respond(db, query="dc.title = Chartreuse"))
        assert number_of_records(bare) == 1

    def test_a_quoted_term_with_nothing_inside_is_an_empty_term(self):
        assert _diagnostic_of('dc.title = ""') is sru.Diagnostic.EMPTY_TERM

    def test_a_bare_index_name_this_server_does_not_know_is_refused(self, db, shelf):
        response = respond(db, query="nowhere = dog")
        assert diagnostic_of(response) == sru.Diagnostic.UNSUPPORTED_INDEX

    def test_a_masked_term_on_a_numeric_index_is_refused(self, db, shelf):
        response = respond(db, query="dc.date = 19*")
        assert diagnostic_of(response) == sru.Diagnostic.TERM_IN_INVALID_FORMAT


@pytest.mark.property
class TestParsingAQueryHasTwoOutcomesAndNoThird:
    @given(query=ANY_QUERY)
    def test_it_is_a_tree_or_a_diagnostic(self, query):
        """**Anything else is a 500 on an unauthenticated door**, which is the
        distinction `respond` draws on purpose: every refusal this module
        decides is a diagnostic inside an HTTP 200, and an exception that is not
        an `SruError` stays a 500 so a bug is never dressed as a protocol
        answer. Three of those have been real: a `ValueError` from `int()` on a
        long digit run, an `OverflowError` from the driver on a term past
        SQLite's integer range, and a `RecursionError` from the descent.
        """
        try:
            node = sru.parse(query)
        except sru.SruError as error:
            assert isinstance(error.diagnostic, sru.Diagnostic)  # noqa: PT017  raising is optional here
            return
        assert isinstance(node, sru.Clause | sru.Boolean)

    @given(query=ANY_QUERY)
    def test_a_diagnostic_can_always_be_put_in_a_document(self, query):
        """`details` is the only place client text is echoed, and the response
        is XML: a control character copied out of the query produces a document
        no client can parse, which is the one outcome worse than not refusing
        the request at all."""
        try:
            sru.parse(query)
        except sru.SruError as error:
            assert error.details.isprintable() or error.details == ""  # noqa: PT017  optional raise
            assert len(error.details) <= sru._DETAILS_CHARS  # noqa: PT017  optional raise

    @given(query=ANY_QUERY)
    def test_parsing_is_not_a_source_of_state(self, query):
        """Twice in a row is twice the same answer. The parser carries two
        counters that outlive a call, and a counter that outlived the *parse*
        would make the second identical query answer differently."""
        first, second = _diagnostic_of(query), _diagnostic_of(query)
        assert first is second


@pytest.mark.property
class TestAControlCharacterNeverReachesTheTokeniser:
    """One character, generated by category, and the refusal is by category too.

    `_tokenise` asks `str.isprintable()` rather than naming a class of
    characters, so this generates the class the same way: every `Cc` and `Cf`
    codepoint, less the three whitespace characters CQL allows.
    """

    @given(query=text_around(invisible_characters(), padding=6))
    def test_it_is_refused_rather_than_sanitised(self, query):
        """**Refused rather than stripped**, because sanitising turns the query
        somebody asked for into a different query and then answers that one."""
        allowed = set("\t\r\n")
        hostile = [
            character
            for character in query
            if not character.isprintable() and character not in allowed
        ]
        if not hostile:
            return
        with pytest.raises(sru.SruError) as refusal:
            sru.parse(query)
        assert refusal.value.diagnostic is sru.Diagnostic.QUERY_SYNTAX_ERROR

    def test_the_generator_still_reaches_a_character_cql_refuses(self):
        witness(
            text_around(invisible_characters(), padding=6),
            lambda query: any(
                not character.isprintable() and character not in "\t\r\n"
                for character in query
            ),
            reaches="a control character CQL has no meaning for",
        )


#: One SQLite connection, used as the oracle for what a LIKE pattern means.
#:
#: **The real engine rather than a reimplementation of its matching.** A Python
#: model of LIKE would be a second implementation of the thing under test, and
#: the defect this property is about is precisely a disagreement between what
#: the code believes a pattern means and what SQLite does with it.
_ORACLE = sqlite3.connect(":memory:")


def _like(text: str, pattern: str) -> bool:
    """Whether SQLite's LIKE, with this module's escape, matches."""
    matched = _ORACLE.execute(
        "SELECT ? LIKE ? ESCAPE ?", (text, pattern, sru._LIKE_ESCAPE)
    ).fetchone()[0]
    return bool(matched)


#: What a term may hold when the oracle above is the judge, and the two
#: exclusions are the oracle's rather than this server's.
#:
#: **A NUL, because Python's SQLite binding cannot carry one through a
#: parameter**: it truncates there, so `SELECT ? LIKE ?` answers about a
#: shorter string than the one asked about, and the property would be measuring
#: the driver. **It cannot arrive here anyway**, and that is asserted rather
#: than assumed: `_tokenise` refuses every unprintable character before a term
#: exists, which `TestAControlCharacterNeverReachesTheTokeniser` above pins.
#:
#: **A surrogate, because it is not text.** Nothing decodes a query string into
#: one, and SQLite cannot store one either.
_LIKE_ALPHABET = st.characters(codec="utf-8", exclude_characters="\x00")

_LIKE_TEXT = st.text(_LIKE_ALPHABET, max_size=12)


def _folded(value: str) -> str:
    """What SQLite's LIKE treats as equal: ASCII case, and nothing else.

    SQLite folds `A` against `a` and leaves every character outside ASCII
    alone, so a comparison written with `str.lower()` would disagree with the
    engine on the Turkish dotless i and on every other script that has a case.
    """
    return "".join(
        character.lower() if character.isascii() else character for character in value
    )


@pytest.mark.property
class TestAnEscapedTermMeansItsOwnCharacters:
    """The rule stated at two sites in this repository, asked of every string.

    A reader searching for `100%` means four characters, and an unescaped `%`
    in a LIKE pattern means "anything": that search used to match every title
    containing `100`. `_` is the same defect one character wide, and a
    backslash with no `ESCAPE` declared is the same defect again with an extra
    character, because SQLite has no default escape at all.

    **The other site keeps its named cases and has no property**, deliberately.
    `shelf.py` states the same rule at its own door, and the exclusion below is
    what decides that: a NUL cannot reach this pattern builder because
    `_tokenise` refuses it first, and nothing refuses one in front of the other
    site. `docs/decisions.md` carries that argument under the entry naming the
    two sites.
    """

    @given(text=_LIKE_TEXT)
    def test_an_unmasked_term_matches_itself_and_only_itself(self, text):
        pattern = sru._pattern(sru.Term((text,)), contains=False)
        assert _like(text, pattern)

    @given(text=_LIKE_TEXT, other=_LIKE_TEXT)
    def test_nothing_else_of_the_same_kind_matches_it(self, other, text):
        """**The half that fails when the escaping is dropped.** Without it a
        term of `100%` is a pattern that matches `100` followed by anything, so
        this is what turns the property from "the literal matches" into "and
        nothing else does"."""
        pattern = sru._pattern(sru.Term((text,)), contains=False)
        assert _like(other, pattern) is (_folded(other) == _folded(text))

    @given(
        text=st.text(_LIKE_ALPHABET, max_size=8),
        before=st.text(_LIKE_ALPHABET, max_size=4),
        after=st.text(_LIKE_ALPHABET, max_size=4),
    )
    def test_a_contains_pattern_matches_the_term_anywhere_inside(self, text, before, after):
        pattern = sru._pattern(sru.Term((text,)), contains=True)
        assert _like(before + text + after, pattern)

    def test_the_generator_still_reaches_a_term_carrying_a_wildcard_character(self):
        witness(
            _LIKE_TEXT,
            lambda text: any(character in text for character in sru._LIKE_SPECIAL),
            reaches="a term containing a LIKE wildcard or the escape itself",
        )
