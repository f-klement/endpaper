"""House rules that are cheaper to enforce than to review for.

Each class here exists because the same defect was found by a person, twice or
in two places, and the finding was mechanical enough that nobody should have to
find it a third time. Adding one is the right answer to "a reviewer caught this
again".
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def _python_sources() -> list[Path]:
    """Every backend module, excluding the tests and the generated migrations."""
    return [
        path
        for path in BACKEND.rglob("*.py")
        if "tests" not in path.parts
        and "migrations" not in path.parts
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
    ]


class TestEveryNumericQueryParamIsBoundedBothWays:
    """A numeric `Query()` needs `le` as well as `ge`.

    Python integers have no ceiling and SQLite's does: a value above 2**63-1
    reaches the driver and raises `OverflowError`, which lands in
    `unhandled_exception_handler` and answers **500**. That is the app calling
    its own code buggy over a value a caller chose.

    Measured: `POST /api/books/covers/backfill?after_id=9999999999999999999999`
    was a 500 for every member, from one query parameter, until `le` was added.
    Every other numeric parameter in the tree was already bounded at both ends,
    which is exactly why the missing one was easy to miss.

    A parameter may opt out with a `# unbounded ok:` comment giving the reason.
    """

    #: Keywords that make a parameter numeric. A `str` bound by `pattern` or
    #: `max_length` is a different question and not this one.
    NUMERIC_BOUNDS = ("ge", "gt", "le", "lt")

    def test_every_numeric_query_parameter_has_an_upper_bound(self) -> None:
        offenders: list[str] = []

        for path in _python_sources():
            source = path.read_text()
            tree = ast.parse(source)
            lines = source.splitlines()

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else None
                )
                if name != "Query":
                    continue

                keywords = {k.arg for k in node.keywords if k.arg}
                # Not a numeric constraint at all, so not this rule's business.
                if not (keywords & {"ge", "gt"}):
                    continue
                if keywords & {"le", "lt"}:
                    continue

                line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                nearby = "\n".join(lines[max(0, node.lineno - 4) : node.lineno])
                if "unbounded ok:" in nearby or "unbounded ok:" in line:
                    continue

                offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno}")

        assert not offenders, (
            "These numeric Query parameters have a lower bound and no upper one, so a "
            "caller-supplied value can overflow SQLite's INTEGER and turn into a 500:\n  "
            + "\n  ".join(offenders)
            + "\nAdd `le=...`, or a `# unbounded ok:` comment saying why not."
        )


class TestTheBoundsActuallyRefuse:
    """The rule above is a lint; these are the behaviours it stands for.

    Both were 500s before the bound existed, and a 500 is the app calling its
    own code buggy over a value the caller chose. 422 is the honest answer.
    """

    def test_an_absurd_page_number_is_refused_not_a_500(self, client, admin) -> None:
        response = client.get(
            "/api/books",
            params={"page": 9_999_999_999_999_999_999_999},
            headers=admin["headers"],
        )
        assert response.status_code == 422

    def test_the_largest_accepted_page_still_works(self, client, admin) -> None:
        from dependencies import MAX_PAGE_NUMBER

        response = client.get(
            "/api/books", params={"page": MAX_PAGE_NUMBER}, headers=admin["headers"]
        )
        assert response.status_code == 200
        assert response.json()["items"] == []
