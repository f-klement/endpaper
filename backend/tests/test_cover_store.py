"""Tests for backend/cover_store.py: the one door into the covers directory.

Three kinds of test live here.

`TestTheDirectoryHasOneOwner` is the **house rule**, and it is what the ticket
this module came from asked for: the directory had five importers, each composing
`<base>.<ext>` itself and each choosing between two writers whose difference is a
cover somebody can see. Two `ast` passes ask whether any module but this one
still knows either fact.

The rest drive the module itself. The two that matter most are the pair that
tells the writers apart: `save` sweeps the other formats of a book and `restore`
must not, and neither an argument nor a comment is worth much on its own, so both
directions are asserted.

`_to_serve` and `_within` are reached directly by the containment tests below.
They are private, and they are reached anyway because the arm they guard is
unreachable through the public functions: a book id is an `int` and the login
background's base is a constant. Asserting it through the route instead would
assert the route's own regex, and the check exists for the day somebody changes
that regex. It was `# pragma: no cover` at its old site for exactly this reason.
"""

import ast
from pathlib import Path

import pytest

import cover_store
from config import ALLOWED_IMAGE_EXTENSIONS, COVERS_DIR
from tests.helpers import JPEG_BYTES, NOT_AN_IMAGE, PNG_BYTES, WEBP_BYTES
from tests.test_house_rules import _source_modules

#: The module that defines where the directory is, and the module that owns it.
#:
#: Stated as the exclusion rather than as a list of the modules that are allowed
#: an import: the corpus is every backend module, so a module added tomorrow is
#: covered with no edit here.
_ALLOWED_TO_KNOW_THE_DIRECTORY = {"config.py", "cover_store.py"}

#: `uploads.py` defines the two writers; `cover_store.py` is the one caller.
_ALLOWED_TO_WRITE = {"uploads.py", "cover_store.py"}

_THE_WRITERS = {"write_image", "replace_image"}

#: One sample of every format `uploads.sniff_image_extension` recognises.
#:
#: `jpeg` is in the allowlist and is not here, because the sniffer answers "jpg"
#: for both so that a book has one predictable cover filename rather than two.
#: The route still serves a `.jpeg` a legacy archive holds.
_EVERY_FORMAT = (JPEG_BYTES, PNG_BYTES, WEBP_BYTES)


def _names_used(source: str) -> set[str]:
    """Every identifier this module names, by all three spellings.

    `COVERS_DIR`, `config.COVERS_DIR` and `from config import COVERS_DIR` are the
    same knowledge, and a rule seeing one of them is evaded by the other two.

    **The import is the arm that was missing**, measured: a mutation adding
    `from uploads import read_image_upload, replace_image` to `routers/books.py`
    was caught by nothing, because an `ast.alias` is neither a `Name` nor an
    `Attribute` and the mutation did not call what it imported. The two arms that
    were there both passed their own mutation, which is why the third was written
    only once somebody tried to get past them.

    `asname` and `name` both, so `import replace_image as write` is one lookup
    rather than two.
    """
    tree = ast.parse(source)
    return (
        {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        | {
            name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in node.names
            for name in (alias.name, alias.asname)
            if name is not None
        }
    )


def _composes_the_directory(source: str) -> bool:
    """Whether this module builds the covers path out of `DATA_DIR` itself.

    The second way to know where covers live, and the one an import rule cannot
    see. `config.DATA_DIR / "covers"` is the expression `config.py` uses, so it
    is the expression a module avoiding `COVERS_DIR` would reach for.
    """
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        right = node.right
        if isinstance(right, ast.Constant) and right.value == "covers":
            return True
    return False


class TestTheDirectoryHasOneOwner:
    """Where a cover lives, and which writer puts it there, are decided once.

    **What these two passes do not see**, stated because a guard whose blind
    spots are unwritten gets trusted past them:

    - a module that hardcodes `/app/data/covers`, or builds it from a string
      this rule cannot recognise. Nothing reaches the directory that way today
      and the rule would not notice if something did. `_composes_the_directory`
      matches one statement kind, so `DATA_DIR.joinpath("covers")` and
      `DATA_DIR / Path("covers")` are both past it, measured. If they then reach
      one of the two writers the arm below sees them; a bare `write_bytes`
      reaches neither pass.
    - `getattr(uploads, "write_image")` and the same through `__dict__`, which
      no arm here sees. Not a one word edit, which is the shape these two
      passes are for.
    - a module that takes a `Path` from this one and walks to `.parent`.
    - the test tree, which is not in the corpus and does write cover files by
      hand. A test writing `7.jpg` is the fixture for a rule, not a caller.
    - `open()` on a path this module returned, which is a read of a file this
      module chose rather than a second opinion about where it lives.
    """

    def test_no_other_module_knows_where_covers_live(self) -> None:
        offenders = sorted(
            name
            for name, source in _source_modules().items()
            if name not in _ALLOWED_TO_KNOW_THE_DIRECTORY
            and ("COVERS_DIR" in _names_used(source) or _composes_the_directory(source))
        )
        assert not offenders, (
            "these address the covers directory themselves, so the name a cover "
            f"is stored under is decided in more than one place: {offenders}"
        )

    def test_no_other_module_reaches_the_two_writers(self) -> None:
        """The sweep is the difference between them, and it is not a caller's choice."""
        offenders = sorted(
            name
            for name, source in _source_modules().items()
            if name not in _ALLOWED_TO_WRITE and _THE_WRITERS & _names_used(source)
        )
        assert not offenders, (
            "these call a writer directly, so which of them sweeps the other "
            f"formats of a base is decided at a call site again: {offenders}"
        )

    def test_the_corpus_is_the_backend_and_holds_the_modules_this_rule_is_about(
        self,
    ) -> None:
        """A rule over an empty corpus passes, so say what was actually read.

        The five names are the importers the ticket measured. If the corpus ever
        stops holding them, the two passes above are green over nothing.
        """
        corpus = set(_source_modules())
        assert {
            "backup.py",
            "covers.py",
            "routers/books.py",
            "routers/covers.py",
            "routers/settings.py",
        } <= corpus
        assert corpus >= _ALLOWED_TO_KNOW_THE_DIRECTORY
        assert corpus >= _ALLOWED_TO_WRITE


class TestSavingABookCover:
    def test_it_names_the_file_from_the_bytes(self, covers_dir):
        """Whatever anybody called it, and whatever format the last one was.

        **Not a JPEG**, measured: a mutation naming every file `jpg` outright
        passed this test when it stored one, and was caught only by the sweep
        and the allowlist tests next door. The test named for the property is
        the one that has to see it.
        """
        assert cover_store.save(7, PNG_BYTES).name == "7.png"
        assert cover_store.save(8, WEBP_BYTES).name == "8.webp"

    def test_it_sweeps_the_other_formats_of_the_same_book(self, covers_dir):
        cover_store.save(7, JPEG_BYTES)
        cover_store.save(7, PNG_BYTES)

        assert sorted(path.name for path in covers_dir.glob("7.*")) == ["7.png"]

    def test_it_leaves_another_book_alone(self, covers_dir):
        cover_store.save(7, JPEG_BYTES)
        cover_store.save(8, PNG_BYTES)

        assert (covers_dir / "7.jpg").is_file()
        assert (covers_dir / "8.png").is_file()

    def test_it_refuses_bytes_that_are_not_an_image(self, covers_dir):
        """The rule the five call sites used to keep by hand, kept here instead."""
        with pytest.raises(cover_store.NotAnImage):
            cover_store.save(7, NOT_AN_IMAGE)

        assert list(covers_dir.iterdir()) == []

    def test_the_login_background_is_not_a_book(self, covers_dir):
        cover_store.save_login_background(PNG_BYTES)

        assert (covers_dir / "login_bg.png").is_file()
        assert cover_store.book_ids() == set()

    def test_it_refuses_a_login_background_that_is_not_an_image(self, covers_dir):
        with pytest.raises(cover_store.NotAnImage):
            cover_store.save_login_background(NOT_AN_IMAGE)


class TestRestoringFromAnArchive:
    """The writer that must not sweep. `cover_store.restore` says why."""

    def test_it_leaves_a_sibling_the_same_archive_wrote(self, covers_dir):
        """The defect the split exists to prevent, asserted as the difference.

        `save` in the same position deletes the loser, and a row naming it then
        404s with the restore's own count still reporting it.
        """
        cover_store.restore("1.jpg", JPEG_BYTES)
        cover_store.restore("1.png", PNG_BYTES)

        assert sorted(path.name for path in covers_dir.glob("1.*")) == ["1.jpg", "1.png"]

    def test_it_keeps_a_name_the_bytes_disagree_with(self, covers_dir):
        """A legacy archive holds PNG bytes called `1.jpg`, and that displays.

        Renaming it to match would leave the row's `cover_url` naming a file
        that no longer exists, which is the same cover lost by another route.
        """
        assert cover_store.restore("1.jpg", PNG_BYTES).name == "1.jpg"

    def test_it_lowercases_the_extension(self, covers_dir):
        """The cover route composes a lowercased name, so `1.JPG` would be
        unreachable on a case sensitive filesystem."""
        assert cover_store.restore("1.JPG", JPEG_BYTES).name == "1.jpg"

    def test_it_leaves_the_stem_alone(self, covers_dir):
        """Folding a stem would merge two entries an archive spelled apart."""
        assert cover_store.restore("Login_BG.png", PNG_BYTES).name == "Login_BG.png"

    def test_it_refuses_bytes_that_are_not_an_image(self, covers_dir):
        with pytest.raises(cover_store.NotAnImage):
            cover_store.restore("1.jpg", NOT_AN_IMAGE)

        assert list(covers_dir.iterdir()) == []

    @pytest.mark.parametrize(
        "name",
        ["../1.jpg", "sub/1.jpg", "1.svg", "1", ".jpg", "", "1\x00.jpg"],
        ids=[
            "parent",
            "subdirectory",
            "not served",
            "no extension",
            "no stem",
            "empty",
            "a NUL in the stem",
        ],
    )
    def test_it_refuses_a_name_that_is_not_a_cover(self, name, covers_dir):
        """`backup._safe_cover_name` refuses these first. This is what holds if
        a second archive reader is ever written."""
        with pytest.raises(ValueError):
            cover_store.restore(name, JPEG_BYTES)

        assert list(covers_dir.iterdir()) == []

    def test_it_refuses_a_destination_that_is_a_link_out_of_the_directory(
        self, covers_dir, tmp_path
    ):
        """The containment arm, which no name above reaches.

        Every refusal above is the name check one line earlier, so the
        destination check was at "stated" until this.

        **Not a write through the link**: `write_image` promotes with
        `os.replace`, and `rename(2)` replaces the link rather than following it,
        so the target is safe either way and the refusal is about what this
        module will write at all. What the arm costs is a restore declining a
        cover the bare write would have healed, and only for a **dangling** link:
        `backup.restore` calls `clear` first, which unlinks a live one.
        """
        outside = tmp_path / "elsewhere.jpg"
        outside.write_bytes(PNG_BYTES)
        (covers_dir / "1.jpg").symlink_to(outside)

        with pytest.raises(ValueError):
            cover_store.restore("1.jpg", JPEG_BYTES)

        assert (covers_dir / "1.jpg").is_symlink()


class TestFindingWhatIsStored:
    def test_a_book_with_no_cover_is_none(self, covers_dir):
        assert cover_store.path_of(7) is None

    def test_it_finds_whichever_format_is_there(self, covers_dir):
        cover_store.save(7, WEBP_BYTES)

        assert cover_store.path_of(7) == covers_dir / "7.webp"

    def test_two_formats_of_one_book_resolve_the_same_way_every_time(
        self, covers_dir, monkeypatch
    ):
        """A restore can leave two, and `ALLOWED_IMAGE_EXTENSIONS` is a frozenset.

        Re-presenting the allowlist in a different order is what a second process
        does. This asserts **stability, not a winner**: the order is arbitrary
        and being the same order twice is the whole requirement.
        """
        cover_store.restore("7.jpg", JPEG_BYTES)
        cover_store.restore("7.png", PNG_BYTES)

        seen = set()
        for order in (["jpg", "png", "webp", "jpeg"], ["webp", "png", "jpeg", "jpg"]):
            monkeypatch.setattr(cover_store, "ALLOWED_IMAGE_EXTENSIONS", order)
            seen.add(cover_store.path_of(7))

        # `None not in`, because a lookup that stopped finding anything returns
        # {None}, which is the most stable answer there is.
        assert None not in seen
        assert len(seen) == 1

    def test_the_login_background_resolves_the_same_way(self, covers_dir, monkeypatch):
        cover_store.restore("login_bg.jpg", JPEG_BYTES)
        cover_store.restore("login_bg.png", PNG_BYTES)

        seen = set()
        for order in (["jpg", "png", "webp", "jpeg"], ["webp", "png", "jpeg", "jpg"]):
            monkeypatch.setattr(cover_store, "ALLOWED_IMAGE_EXTENSIONS", order)
            seen.add(cover_store.login_background_path())

        assert None not in seen
        assert len(seen) == 1

    def test_a_directory_named_like_a_cover_is_not_one(self, covers_dir):
        (covers_dir / "7.jpg").mkdir()
        try:
            assert cover_store.path_of(7) is None
            assert cover_store.book_ids() == set()
            assert cover_store.files() == []
        finally:
            # The `covers_dir` fixture unlinks files and would leave this for
            # every test after it.
            (covers_dir / "7.jpg").rmdir()

    def test_book_ids_skips_a_name_that_is_not_a_number(self, covers_dir):
        cover_store.save(7, JPEG_BYTES)
        cover_store.save_login_background(PNG_BYTES)

        assert cover_store.book_ids() == {7}

    def test_files_holds_the_login_background_too(self, covers_dir):
        """An archive that dropped it would restore a library with no login page
        background and no way to tell that it once had one."""
        cover_store.save(7, JPEG_BYTES)
        cover_store.save_login_background(PNG_BYTES)

        assert [path.name for path in cover_store.files()] == ["7.jpg", "login_bg.png"]


class TestServingOne:
    def test_it_answers_with_the_file(self, covers_dir):
        cover_store.save(7, JPEG_BYTES)

        assert cover_store.cover_to_serve(7, "jpg") == covers_dir / "7.jpg"

    def test_a_format_that_is_not_there_is_none(self, covers_dir):
        """A book holding a JPEG says nothing about a request for its PNG."""
        cover_store.save(7, JPEG_BYTES)

        assert cover_store.cover_to_serve(7, "png") is None

    def test_the_extension_is_matched_case_insensitively(self, covers_dir):
        cover_store.save(7, JPEG_BYTES)

        assert cover_store.cover_to_serve(7, "JPG") == covers_dir / "7.jpg"

    def test_an_extension_outside_the_allowlist_is_none(self, covers_dir):
        """`svg` is the one that matters: it is an `image/*` that carries script,
        and it would run under this app's own origin."""
        (covers_dir / "7.svg").write_bytes(NOT_AN_IMAGE)

        assert cover_store.cover_to_serve(7, "svg") is None

    def test_the_login_background_is_found_by_name(self, covers_dir):
        cover_store.save_login_background(PNG_BYTES)

        assert cover_store.login_background_to_serve("png") == covers_dir / "login_bg.png"

    def test_a_base_reaching_out_of_the_directory_is_none(self, covers_dir):
        """The file it reaches is created, so the refusal is the containment
        check and not the file simply being absent.

        Unreachable through the two public callers, which is why it is asked of
        the private one: a book id is an `int` and the other base is a constant.
        This is what still holds when that stops being true.
        """
        outside = covers_dir.parent / "secret.jpg"
        outside.write_bytes(JPEG_BYTES)
        try:
            assert cover_store._to_serve("../secret", "jpg") is None
        finally:
            outside.unlink()

    def test_a_base_reaching_into_a_subdirectory_is_none(self, covers_dir):
        """Contained and still refused: this directory is flat, so a file in a
        subdirectory is one `files` and `book_ids` cannot see."""
        (covers_dir / "sub").mkdir()
        (covers_dir / "sub" / "1.jpg").write_bytes(JPEG_BYTES)
        try:
            assert cover_store._to_serve("sub/1", "jpg") is None
        finally:
            (covers_dir / "sub" / "1.jpg").unlink()
            (covers_dir / "sub").rmdir()

    def test_a_cover_that_is_a_link_out_of_the_directory_is_not_served(
        self, covers_dir, tmp_path
    ):
        """Nothing this app writes creates one, so this is about what a cover
        file is allowed to be rather than about a caller."""
        outside = tmp_path / "elsewhere.jpg"
        outside.write_bytes(JPEG_BYTES)
        (covers_dir / "7.jpg").symlink_to(outside)

        assert cover_store.cover_to_serve(7, "jpg") is None


class TestMovingAndCopying:
    def test_copy_leaves_the_source_where_it_was(self, covers_dir):
        cover_store.save(7, JPEG_BYTES)

        assert cover_store.copy(8, 7) == covers_dir / "8.jpg"
        assert (covers_dir / "7.jpg").is_file()

    def test_move_takes_the_source_with_it(self, covers_dir):
        cover_store.save(7, JPEG_BYTES)

        assert cover_store.move(8, 7) == covers_dir / "8.jpg"
        assert not (covers_dir / "7.jpg").exists()

    def test_nothing_to_move_is_none(self, covers_dir):
        assert cover_store.move(8, 7) is None
        assert cover_store.copy(8, 7) is None

    def test_the_name_travels_rather_than_the_bytes_deciding(self, covers_dir):
        """A legacy cover whose name and bytes disagree keeps its name.

        Re-deriving it here would rename the file and leave the `cover_url` the
        caller is about to write pointing at the name that was there before.
        """
        cover_store.restore("7.jpg", PNG_BYTES)

        assert cover_store.move(8, 7) == covers_dir / "8.jpg"

    def test_moving_a_book_onto_its_own_id_keeps_the_cover(self, covers_dir):
        """Unreachable through `merge_books`, which passes two distinct ids. What
        it would cost is a deleted cover reported as a successful move."""
        cover_store.save(7, JPEG_BYTES)

        assert cover_store.move(7, 7) == covers_dir / "7.jpg"
        assert (covers_dir / "7.jpg").is_file()

    def test_the_receiving_book_keeps_one_cover(self, covers_dir):
        cover_store.save(7, JPEG_BYTES)
        cover_store.save(8, PNG_BYTES)
        cover_store.move(8, 7)

        assert sorted(path.name for path in covers_dir.glob("8.*")) == ["8.jpg"]


class TestRemovingAndClearing:
    def test_remove_takes_every_format_of_one_book(self, covers_dir):
        cover_store.restore("7.jpg", JPEG_BYTES)
        cover_store.restore("7.png", PNG_BYTES)
        cover_store.save(8, JPEG_BYTES)

        cover_store.remove(7)

        assert [path.name for path in cover_store.files()] == ["8.jpg"]

    def test_remove_leaves_the_login_background(self, covers_dir):
        """It is not a book, so no book id can reach it."""
        cover_store.save_login_background(PNG_BYTES)

        cover_store.remove(7)

        assert cover_store.login_background_path() is not None

    def test_clear_empties_the_directory(self, covers_dir):
        cover_store.save(7, JPEG_BYTES)
        cover_store.save_login_background(PNG_BYTES)

        cover_store.clear()

        assert cover_store.files() == []

    def test_clear_creates_the_directory_when_it_is_gone(self, covers_dir):
        """A restore is the caller, and it must not fail on a volume that has
        never held a cover."""
        covers_dir.rmdir()

        cover_store.clear()

        assert COVERS_DIR.is_dir()


class TestTheNamesThisModuleOwns:
    def test_the_login_background_base_is_not_a_number(self):
        """`book_ids` reads an integer stem, so a numeric base would make the
        login background look like a book and put it in front of `remove`."""
        assert not cover_store.LOGIN_BG_BASE.isdigit()

    def test_it_writes_every_format_the_app_serves_and_no_other(self, covers_dir):
        """Driven with a sample of each rather than read off a list beside the
        allowlist. A format the app serves that the store cannot write is a
        cover nobody can upload; one it writes that the app does not serve is a
        file the cover route will never hand back."""
        written = {cover_store.save(7, body).suffix.lstrip(".") for body in _EVERY_FORMAT}

        assert written == set(ALLOWED_IMAGE_EXTENSIONS) - {"jpeg"}


class TestContainment:
    def test_a_path_inside_the_directory_is_within_it(self, covers_dir):
        assert cover_store._within(COVERS_DIR / "7.jpg")

    def test_a_path_outside_it_is_not(self, tmp_path):
        assert not cover_store._within(tmp_path / "7.jpg")

    def test_the_directory_itself_is_not_a_name_inside_it(self, covers_dir):
        """`relative_to` answers yes here, which is the difference between the
        two spellings and the reason this one is not it."""
        assert not cover_store._within(COVERS_DIR)

    def test_a_subdirectory_of_it_is_not(self, covers_dir):
        assert not cover_store._within(COVERS_DIR / "sub" / "7.jpg")

    def test_a_link_pointing_out_is_not(self, covers_dir, tmp_path):
        outside = tmp_path / "elsewhere.jpg"
        outside.write_bytes(JPEG_BYTES)
        link = covers_dir / "7.jpg"
        link.symlink_to(outside)

        assert not cover_store._within(link)

    def test_it_answers_rather_than_raising_on_a_path_it_cannot_resolve(self, covers_dir):
        """A name with a NUL byte raises out of `resolve()` on some platforms and
        not on others, and either way this is a "no" and not a 500."""
        assert not cover_store._within(Path("\x00"))
