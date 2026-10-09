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
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree

import pytest

import marc
import sru
from enums import TagCategory
from models import Book, Tag
from schemas.public import PublicBookOut

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
    assert element is not None and element.text is not None
    return int(element.text)


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
            assert name is not None and name.text is not None
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
        assert following is not None and following.text == "3"

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
        assert details is not None and details.startswith("startRecord is outside")


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
        assert details is not None and details.text is not None
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
        assert details is not None and details.text == "<script>"

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
        source = (Path(marc.__file__)).read_text()
        # **Every attribute access whose name is a Book column, whatever it is
        # read off.** The first version tested `node.value.id == "book"`, which
        # is one receiver name out of four: a rebound local, a helper parameter
        # and `getattr` all walked past it, and `marc.py` already has two
        # helpers that take a Book. Measured, both versions read the identical
        # twelve columns today, so widening it costs nothing and closes three
        # shapes.
        #
        # `getattr(book, name)` is still invisible to this pass and is left to
        # the rendering test above, which does not read source at all.
        read = {
            node.attr for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Attribute)
        }
        columns = {column.key for column in Book.__table__.columns}
        assert read & columns, "this guard has stopped finding anything at all"
        assert (read & columns) <= set(PublicBookOut.model_fields), (
            "marc.py reads a Book column the public payload withholds: "
            f"{sorted((read & columns) - set(PublicBookOut.model_fields))}"
        )


class TestTheRecordSizeThatDecidedTheCap:
    """What `MAX_RECORDS` costs, measured against the writer rather than guessed.

    `520 $a` carries the description and no schema bounds it, so a record has no
    size the constant could have been derived from. What can be measured is a
    realistic worst case, and that is what decides whether 50 is a page or a
    download.
    """

    #: A description at the long end of what a publisher supplies.
    DESCRIPTION_CHARS = 2000

    #: What a full page of such records may weigh.
    #:
    #: A quarter of a mebibyte. Not a bound the code enforces: it is the number
    #: this test fails on, so that raising `MAX_RECORDS` or adding a large field
    #: to the writer is a decision somebody makes rather than one that happens.
    CEILING_BYTES = 262_144

    def test_a_full_page_of_fat_records_stays_under_the_ceiling(self, db, admin):
        db.add_all(
            Book(
                title=f"Chartreuse Windmill {n:03d}",
                subtitle="a study of the keepers of the windmills",
                author="Ada Example, Bertha Example",
                publisher="Gemini Press",
                year=1974,
                language="de",
                page_count=412,
                isbn=f"978000000{n:04d}",
                description="w" * self.DESCRIPTION_CHARS,
                added_by_user_id=admin["user"]["id"],
            )
            for n in range(sru.MAX_RECORDS)
        )
        db.commit()
        response = sru.respond(
            urlencode(
                {
                    "operation": "searchRetrieve",
                    "query": "Chartreuse",
                    "maximumRecords": str(sru.MAX_RECORDS),
                }
            ),
            db,
            SERVER,
        )
        assert len(record_ids(ElementTree.fromstring(response))) == sru.MAX_RECORDS
        assert len(response.encode()) < self.CEILING_BYTES


class TestTheParametersClientsActuallySend:
    """SRU 1.1 and 1.2 make `version` mandatory and real clients omit it."""

    def test_a_request_with_no_version_is_answered(self, db, shelf):
        response = respond(db, operation="searchRetrieve", query="Chartreuse")
        assert diagnostic_of(response) is None
        version = response.find(f"{SRW}version")
        assert version is not None and version.text == sru.DEFAULT_VERSION

    @pytest.mark.parametrize("version", sru.SUPPORTED_VERSIONS)
    def test_a_supported_version_is_echoed_back(self, db, shelf, version):
        response = respond(
            db, operation="searchRetrieve", query="Chartreuse", version=version
        )
        echoed = response.find(f"{SRW}version")
        assert echoed is not None and echoed.text == version

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
            assert schema is not None and schema.text == sru.MARCXML_SCHEMA
            assert packing is not None and packing.text == "xml"

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
