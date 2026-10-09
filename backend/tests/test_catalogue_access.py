"""The door every outbound catalogue request goes through, and its bounds.

**These rules replace an `ast` and `symtable` walk over `routers/books.py`.** That
walk asked whether the access handed to each door had come from the resolver in the
same scope without being rebound, which is a dataflow question, and it was a dataflow
question only because the router held the value and passed it. It does not any more:
the access lives inside `Enquiry` and the doors are its methods. So the rule here is
syntactic, which is why it fits on a screen.

**Two things had to change together and neither was enough alone**, which is worth
stating because a later round removing one will find the other still green.
`metadata.Access.logins` losing its default is what makes a hand assembled access a
`mypy` error rather than a silent empty mapping; the door is what stops a handler
reaching a catalogue by a route nothing watches. Compulsory logins alone leave the
second open; the door alone leaves the first.
"""

import ast
import dataclasses
import inspect
import logging
from pathlib import Path

import pytest

import catalogue_access
import metadata
import ratelimit
import settings_store
import sources
from tests.test_house_rules import _source_modules

#: A value shaped like a secret, for asserting that something does not print.
#:
#: Not a real key and not a real login: this file publishes to the mirror.
_A_KEY_SHAPED_VALUE = "a-value-nothing-should-print"


class _StubLogin:
    """The whole of what an outbound door needs of a credential.

    `fetch.Credential` is a protocol of one method, so a login can be stood up here
    without reaching the store or sealing anything.
    """

    def header_for(self, url: str) -> dict[str, str]:
        return {}


#: The module that is allowed to do the things below, spelled as
#: `_source_modules()` keys it.
DOOR = "catalogue_access.py"

#: Every public entry point in `metadata.py` that takes an `Access`.
#:
#: **Pinned rather than derived from the signatures**, for the reason the roster in
#: `test_metadata.py` is: deriving the subject from "which functions take an access"
#: means removing the parameter removes the function from the guard's subject in the
#: same edit, and the guard stays green on the change that broke it.
DOORS_TAKING_AN_ACCESS = frozenset({"lookup", "search", "title_search", "candidates"})

#: The door that takes the key and the plan apart instead, and still may not be
#: called from outside.
#:
#: `lookup_volume` sends no login, so it is exempt from every rule about logins and
#: from none of the rules about who may ask a catalogue at all: a handler calling it
#: directly would spend a Member's quota with no limiter charged.
DOORS_TAKING_THEM_APART = frozenset({"lookup_volume"})

ASKING_DOORS = DOORS_TAKING_AN_ACCESS | DOORS_TAKING_THEM_APART


def _module_aliases(tree: ast.AST, module: str) -> set[str]:
    """Every local name that refers to `module`, however it was imported.

    **The half of the retired walk that had to survive.** `import metadata as m`
    evades a matcher keyed on the literal name `metadata`, and that evasion is
    recorded in this tree rather than hypothetical: it is what the first version of
    the walk this replaces missed. Deleting that walk's dataflow half is exactly where
    this gets thrown out with it.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases |= {
                (entry.asname or entry.name)
                for entry in node.names
                if entry.name == module
            }
    return aliases


#: The named constructors, which are the one legitimate way to mention an asking type.
CONSTRUCTORS = frozenset({"for_a_member_request", "for_a_batch_backfill"})


def _references_to(
    source: str,
    module: str,
    wanted: frozenset[str],
    *,
    ignoring_receivers_of: frozenset[str] = frozenset(),
) -> list[tuple[str, int]]:
    """Every **mention** of one of `wanted` in `module`, called or not.

    **You cannot call what you may not name**, and matching a call's own `func` is
    defeated by binding the name first:

        door = metadata.lookup
        result = await door(isbn, access=...)

    No `ast.Call` there has a door for its `func`. Matching the reference closes the
    shape rather than adding an arm per spelling of it.

    **`ignoring_receivers_of` is what lets one matcher serve both rules.** An asking
    type may be *named* to reach its named constructor, and may not be named to be
    built: `catalogue_access.Enquiry.for_a_member_request(...)` must pass while
    `catalogue_access.Enquiry(...)` must not. Both mention `Enquiry`, and what separates
    them is whether that mention is the receiver of a constructor access. Excluding
    those receivers keeps the legitimate spelling silent without weakening the matcher
    back to call shape, which is how the construction rule kept the very hole the door
    rule was fixed for: `b = catalogue_access.Enquiry` then `b(_access=...)` named no
    type in a call position.

    **One parse, one tree, so identity is the tree's own.** The exemption is a set of
    `id()` values collected from the same object the second walk reads, and every node is
    held through its parent's field for the life of the call, so nothing is collected and
    no id is reused. Re-parsing inside this function would break that **silently**, which
    is why it is worth this clause rather than a parent map buying the same property.

    **The blind spots, stated rather than left to be found**, because the rule this
    replaced carried such a paragraph and it was deleted along with it. Each of these
    fails toward a **missed report**, which is the direction every rule in this file is
    written to fail in, and none appears in the package today:

    * A name reached through `getattr`, so the door or the type is a string.
    * A module that re-exports either, reached as `shim.Enquiry`, since the alias set is
      built from imports of the named module alone.

    **An annotation counts as a mention, and that is deliberate rather than overlooked.**
    `def h(a: metadata.Access)` is reported, because a module that holds one of these is
    what the rule is about whether it built it or was handed it. A site that genuinely
    needs the name for typing alone uses `TYPE_CHECKING` with a string annotation; a site
    that needs it at run time is a new exemption to be argued here.

    **Naming a type immediately before its constructor is refused too**, so
    `e = catalogue_access.Enquiry` then `e.for_a_member_request(...)` is reported. That is
    one edit from the evasion and the exemption cannot tell them apart, so it is refused
    on purpose: write the constructor access in one expression.

    **Measured against five spellings**, two legitimate and three evasions, with no
    false positive on either legitimate one and every evasion caught, including the
    local binding.
    """
    tree = ast.parse(source)
    aliases = _module_aliases(tree, module)
    bare = {
        (entry.asname or entry.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for entry in node.names
        if entry.name in wanted
    }
    exempt = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in ignoring_receivers_of
    }
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if id(node) in exempt:
            continue
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
            and node.attr in wanted
        ):
            found.append((node.attr, node.lineno))
        elif isinstance(node, ast.Name) and node.id in bare:
            found.append((node.id, node.lineno))
    return found


class TestOnlyTheAccessDoorAsksACatalogue:
    """One module reaches `metadata`'s outbound doors, and it is the one that may.

    **What this catches that compulsory logins cannot.** A handler holding a correct
    `Enquiry` can still write `metadata.lookup(isbn, access=enquiry._access)`: the
    logins are real, mypy is happy, and the limiter was never charged because the
    charge lives in the constructor rather than at the door. The retired walk
    reported nothing there either, because the access genuinely did come from the
    resolver. This rule is new work the shrink obliged, not a bonus it came with.
    """

    def test_the_walk_reads_something(self):
        """A rule that parsed nothing anywhere passes, so it has to say it read.

        **The inverted form of the assertion the retired walk carried.** That one
        read one file and asserted the file was not empty of doors, after a version
        pointed at a door free module passed green. This one reads every module and
        expects the doors in exactly one, so the same failure arrives from the other
        end: a corpus that stopped being parsed, or a door set that stopped matching,
        leaves nothing to report and reads as clean.
        """
        source = _source_modules()[DOOR]

        assert _references_to(source, "metadata", ASKING_DOORS), (
            f"{DOOR} asks no catalogue: the walk read nothing, so every other arm "
            "here is passing on an empty result"
        )

    def test_no_other_module_asks_a_catalogue(self):
        offenders = [
            f"{name}:{line} reaches metadata.{door}"
            for name, source in _source_modules().items()
            if name != DOOR
            for door, line in _references_to(source, "metadata", ASKING_DOORS)
        ]

        assert not offenders, (
            f"{offenders} reach a catalogue without going through "
            f"{DOOR}, so no rate limiter was charged and no refusal was applied"
        )

    @pytest.mark.parametrize(
        "spelling",
        [
            "import metadata\nasync def r(e):\n    await metadata.lookup(1, access=e)\n",
            "import metadata as m\nasync def r(e):\n    await m.lookup(1, access=e)\n",
            "from metadata import lookup as g\nasync def r(e):\n    await g(1, access=e)\n",
            "import metadata\nasync def r(e):\n    d = metadata.lookup\n    await d(1, access=e)\n",
        ],
        ids=[
            "a plain module import",
            "an aliased module import",
            "a name imported directly",
            "a door bound to a local first",
        ],
    )
    def test_a_door_is_found_however_it_is_reached(self, spelling):
        """One arm per spelling, so a regression is reported by name.

        A single sample carrying all of them cannot say which one a change stopped
        seeing, and losing a spelling is the evasion the rule this replaces shipped
        with. The last arm is the one a call shaped matcher misses: the call's own
        `func` is a local, and only the binding above it names the door.
        """
        assert _references_to(spelling, "metadata", ASKING_DOORS)

    def test_a_mention_of_something_that_is_not_a_door_is_ignored(self):
        """Lenient in the direction of a missed report rather than a false one."""
        source = "import metadata\nx = metadata.carries_a_credential(t)\n"

        assert _references_to(source, "metadata", ASKING_DOORS) == []


class TestOnlyTheAccessDoorBuildsAnAccess:
    """A `metadata.Access` is built in one module, and so is an asking type that holds one.

    Both halves are here because both are the same hole: a value assembled where
    nothing charged a limiter. Grep for either of the two type names to arrive.

    Compulsory logins make a hand built access hard to get wrong; they do not make
    it impossible to build one somewhere that never charged a limiter or applied a
    refusal. Two production sites existed before this change, in `settings_store`
    and in the router; there is one now.
    """

    def test_nothing_outside_the_door_constructs_one(self):
        offenders = [
            f"{name}:{line}"
            for name, source in _source_modules().items()
            if name != DOOR
            for _, line in _references_to(source, "metadata", frozenset({"Access"}))
        ]

        assert not offenders, (
            f"{offenders} name a metadata.Access outside {DOOR}. Building one there is a "
            "catalogue request assembled where nothing charges a limiter; merely "
            "annotating one is a module holding an access that should not have it, and "
            "the fix for that is TYPE_CHECKING with a string annotation rather than a "
            "wider exemption here"
        )

    def test_the_door_itself_names_one(self):
        """Otherwise the arm above is passing because the matcher stopped matching.

        Named for a mention rather than a build, because that is what the matcher reads.
        """
        assert _references_to(_source_modules()[DOOR], "metadata", frozenset({"Access"}))

    def test_nothing_outside_the_door_builds_an_asking_type_by_hand(self):
        """The charge is in the constructor, so bypassing the constructor bypasses it.

        **Both asking types are dataclasses with a public `__init__`**, so
        `Enquiry(_access=catalogue_access._resolved_access(db))` hands a handler every
        door with no limiter charged. Nothing else here sees it: no `metadata` door
        call appears, no `metadata.Access` is constructed, and `mypy` is satisfied
        because `_access` is a declared field. It is one line inserted into a handler
        with the whole suite green, which is the evasion the retired walk was written
        against, one level up.

        **Reference shaped, not call shaped, and that was a second round finding.** A
        call shaped version of this rule read clean on
        `b = catalogue_access.Enquiry` followed by `b(_access=r(db))`, which is the same
        indirection the door rule had already been fixed for: the correction landing in
        the sibling rule and not in this one. `ignoring_receivers_of` is what keeps the
        named constructors silent without weakening the matcher.
        """
        offenders = [
            f"{name}:{line} names {what}"
            for name, source in _source_modules().items()
            if name != DOOR
            for what, line in _references_to(
                source,
                "catalogue_access",
                frozenset({"Enquiry", "GoogleVolumes", "_resolved_access"}),
                ignoring_receivers_of=CONSTRUCTORS,
            )
        ]

        assert not offenders, (
            f"{offenders} build an asking type or its access by hand, which reaches "
            "every door with no rate limiter charged. Use the named constructors"
        )

    #: Two spellings that must pass and three that must not, one arm each.
    #:
    #: **The legitimate pair is half the point.** A rule that refuses a hand built
    #: `Enquiry` is easy; one that refuses it while letting every real call site through
    #: is what `ignoring_receivers_of` is for, and a regression in either direction is
    #: reported by name rather than as a count.
    _LEGITIMATE = {
        "the module, then the type, then the constructor": (
            "import catalogue_access\n"
            "def h(db, u):\n"
            "    return catalogue_access.Enquiry.for_a_member_request(db, member=u)\n"
        ),
        "a from imported type, then the constructor": (
            "from catalogue_access import Enquiry\n"
            "def h(db, u):\n"
            "    return Enquiry.for_a_member_request(db, member=u)\n"
        ),
    }

    _EVASIONS = {
        "built straight from the module": (
            "import catalogue_access\n"
            "def h(db):\n"
            "    return catalogue_access.Enquiry(\n"
            "        _access=catalogue_access._resolved_access(db))\n"
        ),
        "built from aliased from imports": (
            "from catalogue_access import Enquiry as E, _resolved_access as R\n"
            "def h(db):\n"
            "    return E(_access=R(db))\n"
        ),
        "bound to locals first": (
            "import catalogue_access\n"
            "def h(db):\n"
            "    b = catalogue_access.Enquiry\n"
            "    r = catalogue_access._resolved_access\n"
            "    return b(_access=r(db))\n"
        ),
    }

    @pytest.mark.parametrize("source", _LEGITIMATE.values(), ids=list(_LEGITIMATE))
    def test_a_named_constructor_is_not_a_construction(self, source):
        assert (
            _references_to(
                source,
                "catalogue_access",
                frozenset({"Enquiry", "GoogleVolumes", "_resolved_access"}),
                ignoring_receivers_of=CONSTRUCTORS,
            )
            == []
        )

    @pytest.mark.parametrize("source", _EVASIONS.values(), ids=list(_EVASIONS))
    def test_a_hand_built_asking_type_is_reported(self, source):
        """The last of these was clean until the matcher stopped being call shaped."""
        assert _references_to(
            source,
            "catalogue_access",
            frozenset({"Enquiry", "GoogleVolumes", "_resolved_access"}),
            ignoring_receivers_of=CONSTRUCTORS,
        )


class TestNeitherAskingTypeWidens:
    """Both types are pinned, in both directions, by one instrument.

    **A door widens sideways as readily as it grows a name**, and the thing behind
    both of these is the deployment's own key. `Enquiry` carries the key and the
    keychain; `GoogleVolumes` carries the key. A member added to either receives the
    key by arriving, which is the defect this concept's history is built on.

    **`dir()` rather than `inspect.getmembers(..., isfunction)`**, because that
    predicate is false for a classmethod and for a property, so the first version of
    this pinned neither constructor and could not see a property at all. A one line
    `api_key` property returning the field would have passed a method set pin, a field
    set pin and every arm of the print sweep, while publishing the key. One expression
    closes functions, classmethods, staticmethods, properties and class variables
    together.
    """

    SURFACE = {
        "Enquiry": {
            "for_a_member_request",
            "refuse_if_nothing_is_asked",
            "lookup",
            "title_search",
            "search",
            "candidates",
            "volume",
        },
        "GoogleVolumes": {"for_a_batch_backfill", "volume"},
    }

    FIELDS = {
        "Enquiry": {"_access"},
        "GoogleVolumes": {"_plan", "_api_key"},
    }

    @pytest.mark.parametrize("name", sorted(SURFACE))
    def test_the_public_surface_is_what_it_was(self, name):
        owner = getattr(catalogue_access, name)
        public = {member for member in dir(owner) if not member.startswith("_")}

        assert public == self.SURFACE[name], (
            f"{name}'s public surface moved. Anything reachable here is reachable "
            "with the deployment's key already resolved, so a new member is a new "
            "way to spend it or to read it"
        )

    @pytest.mark.parametrize("name", sorted(FIELDS))
    def test_the_field_set_is_what_it_was(self, name):
        owner = getattr(catalogue_access, name)
        fields = {field.name for field in dataclasses.fields(owner)}

        assert fields == self.FIELDS[name], (
            f"{name} grew or lost a field. A logins mapping on the keyless type is "
            "a keychain round trip for a credential its one door cannot send"
        )

    def test_the_enquiry_is_not_a_google_volumes(self):
        """Two unrelated types, never a base and a subclass.

        Inheritance would share the field set, so "no logins live here" would become
        a question of which class a reader was looking at rather than a fact about
        this one.
        """
        assert not issubclass(catalogue_access.Enquiry, catalogue_access.GoogleVolumes)
        assert not issubclass(catalogue_access.GoogleVolumes, catalogue_access.Enquiry)


class TestTheDoorSaysNothingItWasNotGiven:
    """This module holds the deployment's key and also builds response bodies.

    That combination is the one where an interpolated detail puts a secret on the
    wire, so every refusal sentence is a module level constant and the only argument
    an `HTTPException` takes here is a name.
    """

    def test_no_refusal_is_built_from_a_value(self):
        tree = ast.parse(Path(catalogue_access.__file__).read_text())
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "HTTPException"
            and any(
                isinstance(inner, ast.JoinedStr)
                for argument in [*node.args, *(kw.value for kw in node.keywords)]
                for inner in ast.walk(argument)
            )
        ]

        assert not offenders, (
            f"an HTTPException at {offenders} interpolates a value into its detail, "
            "which is how a key reaches a response body"
        )

    @pytest.mark.parametrize("render", [repr, str, format], ids=["repr", "str", "format"])
    def test_no_public_type_prints_a_secret(self, render):
        """The subject is derived from the module, not listed.

        A third type added here joins this sweep by existing. Listing the two is the
        inclusion list this repository's own rules name as the thing that goes stale.
        """
        secret = _A_KEY_SHAPED_VALUE
        plan = sources.Plan(preferences=())
        built = [
            catalogue_access.Enquiry(
                _access=metadata.Access(plan=plan, api_key=secret, logins={})
            ),
            catalogue_access.GoogleVolumes(_plan=plan, _api_key=secret),
        ]
        public = {
            name
            for name, value in vars(catalogue_access).items()
            if not name.startswith("_")
            and isinstance(value, type)
            and value.__module__ == catalogue_access.__name__
        }

        assert public == {type(one).__name__ for one in built}, (
            f"{public} is not the set this sweep builds, so a public type here is "
            "printing unchecked"
        )
        for one in built:
            assert secret not in render(one), f"{type(one).__name__} leaked its key"

    def test_the_sweep_would_have_seen_it(self):
        """The diagonal: the key really would have been there without the rule."""
        plan = sources.Plan(preferences=())
        access = metadata.Access(plan=plan, api_key=_A_KEY_SHAPED_VALUE, logins={})

        assert _A_KEY_SHAPED_VALUE in repr(dataclasses.astuple(access))


class TestTheDoorCannotReachABook:
    """Nothing here takes a `User` or reaches `user.id`, so nothing here can query.

    **The privacy rule constrains this module's shape rather than being checked
    after it.** `shelf.py` is the only way into a many Book query, and the way this
    module stays outside that rule is by never holding the thing a query needs. The
    limiter is keyed on a username, which is a string.
    """

    def test_no_constructor_takes_a_user(self):
        """The two named constructors are the only members that take anything.

        **`inspect.isfunction` is false for a classmethod**, so the first version of
        this iterated the six instance methods, none of which could plausibly take a
        `User`, and skipped both constructors, which are the only members that receive
        anything from the request. A test named for what it checks is not evidence that
        it checks it.
        """
        checked = 0
        for owner in (catalogue_access.Enquiry, catalogue_access.GoogleVolumes):
            for name in dir(owner):
                if name.startswith("_"):
                    continue
                member = inspect.getattr_static(owner, name)
                function = member.__func__ if isinstance(member, classmethod) else member
                if not callable(function):
                    continue
                checked += 1
                annotations = {
                    str(parameter.annotation)
                    for parameter in inspect.signature(function).parameters.values()
                }
                assert not any("User" in one for one in annotations), (
                    f"{owner.__name__}.{name} takes a User, so this module can "
                    "reach user.id and build a query outside the shelf module"
                )

        # Both constructors plus every instance method, or the loop above skipped the
        # members it exists to read.
        assert checked == sum(
            len(names) for names in TestNeitherAskingTypeWidens.SURFACE.values()
        )

    def test_the_module_imports_no_model(self):
        """The refusal in this module's docstring, given an enforcement.

        **A `Book` parameter passes every other rule here**: it is not a `User`, and it
        builds no query. So "this module does not decide how to identify a book" rested
        on prose alone, and the proposal it refuses would have imported a model to do
        exactly that. Importing none is the property that makes the refusal survive a
        reader who disagrees with it.
        """
        tree = ast.parse(_source_modules()[DOOR])
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            entry.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for entry in node.names
        }

        assert "models" not in imported, (
            f"{DOOR} imports from models. Which book to ask about is the handler's "
            "decision; this module answers whether it may ask at all"
        )

    def test_this_module_is_exempted_from_no_query_rule(self):
        """The diagonal, which is what was actually missing here.

        **A book query in this module already fails a rule that walks the whole of
        `backend/` by exclusion**, with an allowlist of one name, so restating it here
        as a list of forbidden spellings was both redundant and short: two versions of
        that list missed `models.Book` as an attribute and a `from models import Book as
        B` rebinding.

        What nothing caught is a later round quietly adding this module to one of those
        allowlists, which would exempt every future query in it. That is the cost
        `test_shelf.py` records paying for one module and reversing the same day.
        """
        from tests import test_shelf

        exempted = (
            test_shelf.QUERY_BUILDERS
            | test_shelf.JOIN_CALLERS
            | test_shelf.INDIRECT_READERS
            | test_shelf.PREDICATE_IMPORTERS
        )

        assert DOOR not in exempted, (
            f"{DOOR} has been added to one of the shelf rule's allowlists, which "
            "exempts every future query in it rather than the one it was added for"
        )


class TestABareCatalogueIsAudible:
    """The credential gap's runtime half, which nothing was invoking.

    **This is the half that can actually fire.** The test in
    `test_settings_store.py` says the two predicates agree on today's roster, which is a
    fact about the seed table; this says that when they do not agree, or when a key is
    rotated between the two keychain reads, the request that goes out with no credential
    says so. Before this arm the warning was at the **stated** rung: deleting its body
    left nothing red.

    `settings_store.catalogue_logins` carries why this is a warning and not a refusal.
    """

    def _access_with_a_bare_source(self) -> metadata.Access:
        """A plan asking a credentialled catalogue, with no login resolved for it.

        **The plan asks the whole roster, not the one source named.** `sources.parse`
        appends every source the stored value did not mention, enabled, so naming one
        here does not narrow it. That is fine for this arm, whose subject is a source in
        `asked` with no entry in `logins`, and it is why the silent arm below supplies a
        login for **every** door that carries one rather than for the first.
        """
        source = settings_store.sources_whose_door_carries_a_login()[0]
        plan = sources.parse({"sources": [{"source": source.value, "enabled": True}]})
        return metadata.Access(plan=plan, api_key="", logins={})

    def test_a_source_asked_with_no_login_is_named(self, caplog):
        access = self._access_with_a_bare_source()
        expected = settings_store.sources_whose_door_carries_a_login()[0]

        with caplog.at_level(logging.WARNING, logger=catalogue_access.logger.name):
            catalogue_access._warn_about_any_source_asked_with_no_login(access)

        assert [record.levelname for record in caplog.records] == ["WARNING"]
        assert expected.value in caplog.records[0].getMessage()

    def test_a_plan_whose_logins_are_all_resolved_says_nothing(self, caplog):
        """The diagonal: otherwise the arm above passes on a warning that always fires.

        **A login for every door that carries one, not for the first.** The roster holds
        one such source today and is expected to grow; supplying only the first would
        leave the second bare, and then this arm goes red for a reason that is not its
        subject.
        """
        plan = sources.parse({})
        access = metadata.Access(
            plan=plan,
            api_key="",
            logins={
                source: _StubLogin()
                for source in settings_store.sources_whose_door_carries_a_login()
            },
        )

        with caplog.at_level(logging.WARNING, logger=catalogue_access.logger.name):
            catalogue_access._warn_about_any_source_asked_with_no_login(access)

        assert caplog.records == []

    def test_the_warning_carries_no_secret(self, caplog):
        """The arm that rots: a later version interpolating the key or a login.

        Read off the **rendered** message rather than the template, because `%s`
        formatting puts a value on a record that the template does not contain.
        """
        source = settings_store.sources_whose_door_carries_a_login()[0]
        plan = sources.parse({"sources": [{"source": source.value, "enabled": True}]})
        access = metadata.Access(plan=plan, api_key=_A_KEY_SHAPED_VALUE, logins={})

        with caplog.at_level(logging.WARNING, logger=catalogue_access.logger.name):
            catalogue_access._warn_about_any_source_asked_with_no_login(access)

        assert caplog.records, "nothing warned, so this arm proves nothing"
        for record in caplog.records:
            assert _A_KEY_SHAPED_VALUE not in record.getMessage()


class TestEachDoorChargesItsOwnLimiter:
    """Which limiter guards which route, asserted rather than left to five call sites.

    **This is the finding the ticket led with.** The pairing used to be a hand
    written first line in each handler, so a handler added with neither was caught by
    nothing. It is a property of the constructor now, and there is no way to obtain
    either type without one having been charged.
    """

    @pytest.mark.parametrize(
        ("constructor", "limiter"),
        [
            ("Enquiry.for_a_member_request", "metadata_limiter"),
            ("GoogleVolumes.for_a_batch_backfill", "identifier_backfill_limiter"),
        ],
    )
    def test_the_constructor_charges_its_limiter(self, constructor, limiter):
        owner, _, method = constructor.partition(".")
        source = inspect.getsource(getattr(getattr(catalogue_access, owner), method))

        assert f"{limiter}.check(" in source, (
            f"{constructor} no longer charges {limiter}, so this route's outbound "
            "traffic is bounded by nothing"
        )

    def test_the_two_do_not_share_a_counter(self):
        """A batch spends many requests per call where a lookup spends a handful.

        Sharing would let one backfill exhaust a Member's scanning budget, which is
        the reason `identifier_backfill_limiter` exists at all.
        """
        assert (
            ratelimit.metadata_limiter
            is not ratelimit.identifier_backfill_limiter
        )


class TestALocallyRefusedRequestSpendsNoBudget:
    """A request that reaches no catalogue must not cost a Member their allowance.

    **Two routes disagreed about this and no test said which was right.**
    `refresh_metadata` answered 400 for a book with no ISBN before charging;
    `lookup_isbn` charged and then answered 400 for a malformed one. The limiter's
    subject is outbound catalogue traffic, so counting a request that makes none
    decouples the counter from what it bounds, and the visible cost is a Member who
    scans three damaged barcodes and is then refused a good one.

    Both orders agree now, and these are what stop one drifting back.
    """

    def _charged(self, member: dict) -> int:
        hits = ratelimit.metadata_limiter._hits
        return len(hits.get(member["user"]["username"], ()))

    def test_a_malformed_isbn_is_refused_before_the_charge(self, client, member):
        # A wrong check digit rather than an obviously silly string: ten zeroes is
        # a *valid* ISBN-10, which the first draft of this arm used and which made
        # it pass for the wrong reason.
        res = client.get(
            "/api/books/lookup",
            params={"isbn": "9780306406158"},
            headers=member["headers"],
        )

        assert res.status_code == 400
        assert self._charged(member) == 0

    def test_a_book_with_no_isbn_is_refused_before_the_charge(
        self, client, member, make_book
    ):
        book = make_book(member["headers"], title="No barcode here")

        res = client.put(f"/api/books/{book['id']}/refresh", headers=member["headers"])

        assert res.status_code == 400
        assert self._charged(member) == 0


class TestAnUnauthenticatedCallerIsNeverToldAboutTheSettings:
    """401 before 409, on every route behind this door.

    **The hazard is real and was measured rather than assumed.** A gate declared as a
    sibling of the session check answers this route's 409 to a caller with no
    session, because FastAPI resolves dependencies in declaration order and a route
    level `dependencies=[...]` entry is inserted ahead of every signature parameter.
    That would tell anybody who can reach the port whether this deployment has
    catalogues configured.

    The door is constructed in the handler body, below the session check, so the
    question cannot arise. These arms are what say it still cannot.
    """

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/books/lookup?isbn=9780306406157"),
            ("get", "/api/books/search?q=dune"),
            ("post", "/api/books/identifiers/backfill"),
            ("put", "/api/books/1/refresh"),
            ("post", "/api/books/1/enrich"),
            ("get", "/api/books/1/enrich/candidates"),
        ],
    )
    def test_no_route_answers_a_refusal_to_a_caller_with_no_session(
        self, client, method, path
    ):
        res = getattr(client, method)(path)

        assert res.status_code == 401, (
            f"{method.upper()} {path} answered {res.status_code} with no session. "
            "A 409 here would tell an anonymous caller what this library has "
            "switched on"
        )

    #: The handlers that construct a door, so the parametrisation above is complete.
    #:
    #: **Derived rather than listed, because the path list cannot be.** Nothing links a
    #: URL to this concept cheaply, and walking the app's route table would admit every
    #: unrelated route. What is derivable is which handlers reach a constructor, and a
    #: seventh appearing here fails by name: the edit it then demands is to add the
    #: handler and its path together, which is the remedy that keeps the two in step.
    HANDLERS = {
        "lookup_isbn",
        "search_books",
        "backfill_from_identifiers",
        "refresh_metadata",
        "enrich_book",
        "enrichment_candidates",
    }

    def test_every_handler_behind_the_door_is_covered_above(self):
        tree = ast.parse(_source_modules()["routers/books.py"])
        constructors = {"for_a_member_request", "for_a_batch_backfill"}
        reaching = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            for inner in ast.walk(node)
            if isinstance(inner, ast.Attribute) and inner.attr in constructors
        }

        assert reaching == self.HANDLERS, (
            f"the handlers constructing a door are {sorted(reaching)}, which is not "
            f"{sorted(self.HANDLERS)}. Add the new one here and its path to the "
            "parametrisation above, or an unauthenticated caller reaches it unchecked"
        )
