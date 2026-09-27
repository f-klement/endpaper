"""What the repository's ignore file says is not source, parsed and matched once.

**This module is the one home of a rule that had three.** Three copies, not
three files: one in this test tree, read by four guards; one in a guard that runs
in a job installing none of the application's dependencies; and one in the corpus
behind the rule that every command a published document offers is a command this
repository runs. The three had already drifted, in three directions, each missing
a half the others had. So this carries the **union** rather than the widest.

**Stdlib only, and that is the whole reason one home is possible.** One of the
consumers ran its own copy because it needs no application dependency and could
not import one. `fnmatch` and `pathlib` cost it nothing.

**Three refusals, and they are not one rule with three spellings.** The failure
direction differs by consumer, which is why the third is a parameter rather than
a constant:

* **An ignore file that is not there.** A population derived from a rule that is
  missing is a population with no bound.
* **A form this cannot honour**: a negation, a backslash, a `**`, a bare `*`, and
  a wildcard inside an anchored pattern, because that arm compares text rather
  than matching. Approximating wide drops a versioned file from the walk, which
  is the defect the walk exists to stop; approximating narrow walks a directory
  the repository ignores, which is how the publish tooling's own output came to
  be read as source.
* **A parse that yields nothing**, only where the caller says so. See
  `refuse_empty`.

**The negation is refused by the marker's position and the backslash rides with
it.** git's negation marker is the first character of a line, so `notes!draft.md`
is a literal git honours and a refusal by containment turns a versioned file into
a hard failure. Narrowing to the position opens a silent hole in the same move,
which is why the two are one change: `\\!foo` is git's escape for a literal
`!foo`, it carries no marker in first position once the escape is read, and
`fnmatch` reads the backslash as an ordinary character, so that entry matches a
five character name and not the file git ignores. Narrow, and silent. The whole
backslash class is refused rather than the escape alone, because every other use
of it is the same mis-evaluation.

**A bare `*` is refused by equality and never by containment.** It matches every
component, so every population derived from this walk goes to zero at once while
the parse is still non-empty.

**That failure is loud rather than silent, and this refusal does not close a
hole.** Measured with a star appended to a copy of this repository's ignore file:
nine arms across four files go red, three of those files in this test tree and one
outside the published tree, and the consumer that runs as a script refuses on its
own. What the refusal buys is the **shape** of the failure, which is the only
thing it buys: one refusal here naming the entry, instead of nine reds in four
files that each report an empty population and none of which names the line that
emptied it. Three of the 25 entries in this repository's own ignore file carry a
star, so a containment test refuses that file on the spot.

**That is not the class "anything this cannot evaluate exactly".** A POSIX
character class is still evaluated, wrongly and in silence, and it **fails
narrow**, which is the direction named above as the live one rather than the
latent one: `[[:alpha:]]` becomes a set of the six characters `[:ahlp` followed
by a **literal `]`**, so it matches a two character string such as `a]` and no
single character at all. Counted against `fnmatch.translate`, which yields
`[\\[:alpha:]\\]`. So it matches nothing a letter class is written for. Anchored,
the wildcard clause takes it; unanchored it passes.

That form is not in this repository's ignore file. Naming what is refused is
honest; a further predicate for each shape somebody thinks of is the enumeration
these walks replaced.

**Asking `git` would be better and is not available.** Measured 2026-09-06 in the
pod the suites run in: no `git` binary, and no `.git`, because the runner ships a
tar that excludes it. A rule reaching for git there is a rule that fails or,
worse, quietly answers nothing.

**Nested ignore files are not read.** Git honours one per directory and this
reads the root's, so a nested one leaves its subject in the population. Whether
that is refused or ignored is the consumer's call and is made at the walk, since
only the walk sees the directories.

**Every refusal raises rather than asserting.** Two of the three replaced homes
spelled it `assert`, which is removable: under `-O` their whole contract compiled
out and every consumer would have walked an unevaluated tree. Nothing here runs
`-O`, counted, so that half was latent and this module holds no assertion for it
to reach. What is not latent is that one consumer is run directly rather than
under a test runner, for which `SystemExit` is the exit a refusal wants and a
traceback is not. `SystemExit` also descends from `BaseException`, so no
consumer's `except Exception` can swallow a refusal; nothing wraps a call that way
today, so that half is a property being kept rather than a bug being fixed.

**A consumer that cannot import this loads it by path.** Two consumers are
stripped from the published tree and run outside the test runner, so neither can
`import` from this package. Each loads this file through `importlib`, and each
checks the path exists first, because a spec built for a missing file carries a
loader and fails as a traceback out of the exec rather than as the refusal above.
**Not by putting the application's directory on `sys.path`**: that would put its
sixty top level modules in front of the standard library for the rest of the
process, and the day one of them is named for a standard module the failure
arrives somewhere with no connection to an ignore file. None is today, counted.
Loading by path cannot go stale that way. Each load site points here rather than
repeating this, because two copies of one reason is the shape this module exists
to remove and they had already drifted apart when they were written.
"""

from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import Path

#: A parsed entry: the pattern, whether it is anchored to the root, and whether
#: it carries git's directory only marker.
IgnoreEntry = tuple[str, bool, bool]


def ignore_patterns(ignore_file: Path, *, refuse_empty: bool) -> list[IgnoreEntry]:
    """The entries in `ignore_file`, in the order it lists them.

    **`refuse_empty` has no default, deliberately**, for the reason `is_ignored`
    gives about `is_dir`: a default is the answer a call site forgets to give,
    and here the two answers are opposite failure directions.

    **One property decides the answer: whether an ignore file holding no entries
    is a legitimate input to that caller.** A caller passes `False` only where a
    fixture in this test tree hands it such a file on purpose, because the rule
    under test has to apply without one. **Every other caller passes `True`**,
    whether it reads the repository's own file, walks a tree handed to it, or writes
    its own ignore file, because for those a parse yielding nothing is a broken
    bound rather than a legitimate tree.

    **Stated as the condition and not as a count of either side.** A count here was
    wrong twice: neither "takes the tree as a parameter" nor "is driven by a
    fixture" is the rule, because an arm can do both and still want the refusal, and
    one fixture that writes a silent ignore file never reaches this function at all.
    The condition is what a new call site can be checked against, and checking it
    costs reading that call site rather than recounting the others.

    **What each answer buys.** Where a silent ignore file is legitimate the rule
    under test has to apply without one, and a file with entries in it would let the
    walk pass by reading the file instead of by applying the rule. Everywhere else an
    unbounded population is the silent direction: where that population is permissive
    evidence a parse yielding nothing reads the caches, the dependency trees and the
    build output and **accepts more** of whatever it is evidence for, failing no
    test, and where it is a walk over the real tree refusing costs nothing, that file
    always parsing to something.

    **The file is named rather than derived from a root**, because a caller that
    reads a constructed ignore file elsewhere is how the empty parse refusal is
    driven at all.
    """
    if not ignore_file.is_file():
        raise SystemExit(f"no ignore file at {ignore_file}, so the walk has no rule")
    patterns: list[IgnoreEntry] = []
    # **`utf-8-sig`, because a byte order mark disarms whichever entry is on line
    # 1.** Read as plain `utf-8` the mark stays on the text, so the first entry
    # parses to a pattern beginning with a character no path holds and matches
    # nothing: the entry is still counted, so the parse is non-empty and no
    # refusal fires. The blast radius is then the ignore file's line order, which
    # is the arming-by-data shape this module has already paid for. On a file
    # with no mark the two encodings are the same bytes.
    for line in ignore_file.read_text(encoding="utf-8-sig").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        # A pattern with a slash left in it after the markers come off is
        # anchored to the root, which is git's own rule and the difference
        # between `backend/data/` meaning that one directory and meaning any
        # `data` anywhere.
        anchored = entry.startswith("/")
        # **Read here, before the anchor and directory markers come off, because
        # that is where git defines it.** A negation marker is the line's first
        # character; `notes!draft.md` is a literal git honours, so a containment
        # test refuses a versioned file. Asked after the `strip("/")` below it is
        # the other false refusal: `/!foo` is an anchored literal path whose `!`
        # is not in first position, and stripping the anchor moves it there.
        #
        # **First character of the line as `line.strip()` leaves it, which is not
        # quite git's position.** Git honours a leading space, so ` !foo` is a
        # literal name beginning with a space and this refuses it. Loud rather
        # than silent, over a name nothing in this tree has, and it is stated here
        # rather than armed because an arm would pin a pathological filename.
        negated = entry.startswith("!")
        # A trailing slash is git's directory only marker, and dropping it with
        # the anchor marker hides a versioned **file** of that name: unanchored,
        # `data/` would also hide a file called `data`; anchored, `backend/data/`
        # would also hide the file `backend/data`. All 16 marked entries move
        # this function's answer for a file of their own name and none of those
        # 16 files exists, counted, so it is latent rather than failing. It was
        # live in the copy that dropped the marker.
        directory_only = entry.endswith("/")
        entry = entry.strip("/")
        anchored = anchored or "/" in entry
        # The anchored arm compares text rather than matching, so a wildcard
        # there would read as "never matches" instead of raising.
        #
        # **The backslash class is here because `negated` is a position test.**
        # Containment on `!` used to refuse `\!foo` as a side effect; by position
        # it passes, and `fnmatch` then reads the backslash as an ordinary
        # character and matches a name git never ignores. Narrow and silent, so
        # removing either of these two re-opens the other's hole.
        #
        # **`entry == "*"` and never `"*" in entry`.** A bare star matches every
        # component, which takes a population derived from this walk to zero with
        # the parse non-empty and any ratchet over it comparing nothing. By
        # containment it would refuse three of this repository's own 25 entries.
        # What goes past: `?` and a character class each match a component
        # narrower than every name, so neither empties a population on its own,
        # and the extent of what some other spelling of "matches everything" does
        # here is not claimed.
        #
        # **The message carries which term fired, because five terms sharing one
        # sentence tell a contributor to teach the walk about a form when the fix
        # is a character.** The backslash is the term most likely to be met, by
        # somebody writing a path the way their shell does, and the answer to it
        # is one sentence rather than a change here.
        refused = None
        if negated:
            refused = "a negation, whose marker git reads in the line's first position"
        elif "\\" in entry:
            refused = (
                "a backslash: git spells every pattern with forward slashes, and "
                "`fnmatch` reads the character as ordinary rather than as an escape"
            )
        elif "**" in entry:
            refused = "a `**`, which this matches one component at a time"
        elif entry == "*":
            refused = "a bare `*`, which matches every component and empties the walk"
        elif anchored and set(entry) & set("*?["):
            refused = "a wildcard inside an anchored pattern, which is compared as text"
        if refused is not None:
            raise SystemExit(
                f"unsupported .gitignore form, teach this walk about it: {entry} "
                f"({refused})"
            )
        patterns.append((entry, anchored, directory_only))
    if refuse_empty and not patterns:
        raise SystemExit(f"{ignore_file} parsed to no patterns, so the population has no bound")
    return patterns


def is_ignored(relative: Path, patterns: Sequence[IgnoreEntry], *, is_dir: bool) -> bool:
    """Whether the repository ignores `relative`, which is a directory when `is_dir`.

    **`is_dir` is what carries the directory only marker**, and every caller
    already knows it without asking the filesystem a second time. It is
    keyword-only and has no default, both deliberately and for one reason: a
    default is the answer a call site forgets to give, a positional is the answer
    a call site gives without reading, and a wrong answer here drops a versioned
    file in silence. `refuse_empty` is spelled the same way for the same reason,
    and `test_house_rules.py` pins both rather than leaving them to convention.

    **The separator in the anchored arm is load bearing.** Written
    `startswith(pattern)` it silently drops `backend/database.py`, because
    `backend/data` is an anchored entry in this repository's own ignore file.
    That consequence is live rather than latent, which is why it has an arm of
    its own, `test_an_anchored_rule_stops_at_the_separator_rather_than_the_prefix`.

    **Three mutations of this function were unobservable in this tree and are
    not any more.** The fold gave a caller that does not walk the marker, so a
    single arm over a constructed ignore file now reaches all three. Each is red on
    the arm that pins which side of the marker a file of an ignored directory's own
    name falls, and the first two were reachable by no arm at all before it:

    * Requiring `is_dir` on the anchored **exact** match, or dropping the marker
      there. In this repository's own file the class is one anchored entry without
      the marker against six with, and it names a directory, so no walk asks about
      it as a file; the arm asks anyway, over an entry it writes itself.
    * Honouring the marker on the anchored **subtree** match, which moves only a
      file under an ignored directory, and every walk prunes that directory before
      reaching the file.
    * Reading only the **last** component in the unanchored arm, which breaks
      ancestor semantics that no walk can see, because the walks prune the ancestor
      first and every unanchored entry without the marker names a file.

    **One mutation remains unobserved, and it is at a call site rather than
    here**: asking this with `is_dir=False` where a walk prunes moves only which of
    two arms drops the entry, because the arm for files decides the same question
    one component further down. An arm is the wrong answer to it, because an arm
    asserting a fixture nothing reaches asserts the fixture.

    **Pruning is also why two mutations here mask each other through any walk**,
    which is the general shape rather than a detail of these two. Dropping `is_dir`
    from the unanchored arm, and shortening that arm's components to nothing, are
    each green alone against every walk and red together: the walk never reaches a
    file under an ignored directory, so each removes the evidence the other would
    have left. **So an arm over this asks it directly rather than through a walk**,
    and then sees each alone. The two direct pins are not interchangeable and
    measuring which catches what is the only way to know: the anti vacuity pin in
    the guard over the strip list catches the shortening and is **green** on the
    `is_dir` drop, and the marker arm above catches both.
    """
    text = str(relative)
    for pattern, anchored, directory_only in patterns:
        if anchored:
            # An anchored pattern matches the path itself, where the marker
            # decides, or anything under it, where it cannot.
            matched = (
                (is_dir or not directory_only)
                if text == pattern
                else text.startswith(f"{pattern}/")
            )
        else:
            # A directory only pattern still matches a **directory component**
            # of a file's path. The last component is the entry itself and is a
            # directory only when the caller says so; every component before it
            # is one by construction.
            parts = relative.parts if (is_dir or not directory_only) else relative.parts[:-1]
            matched = any(fnmatch(part, pattern) for part in parts)
        if matched:
            return True
    return False
