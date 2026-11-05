"""Every route path the published prose writes in backticks is one the app serves.

The rule and its blind spots are `tests/route_mentions.py`'s docstring. Each arm
below plants text in a temporary tree and changes one thing.
"""

from pathlib import Path

import pytest

from main import app, iter_api_routes
from tests.corpus import REPO, markdown_files
from tests.declaration import SENTENCE as DECLARATION
from tests.declaration import declares_itself_internal
from tests.route_mentions import REMEDY, dead_mentions, refusal, route_table

TREE_GUARDS = {
    "test_the_published_prose_names_no_route_the_app_does_not_serve": ("markdown_files",),
    "test_a_dead_route_in_backticks_is_refused": ("markdown_files",),
    "test_a_live_route_or_no_mention_passes": ("markdown_files",),
    "test_a_document_declaring_itself_internal_is_not_read": ("markdown_files",),
    "test_a_refusal_names_the_line_and_the_history_marker": ("markdown_files",),
}

TABLE = route_table(iter_api_routes(app.routes))


def published_documents(root: Path) -> list[Path]:
    """The prose the mirror publishes: every versioned Markdown document that
    does not declare itself internal, by the publish gate's own rule."""
    return [path for path in markdown_files(root) if not declares_itself_internal(path)]


def _dead(tmp_path: Path, text: str) -> list[str]:
    (tmp_path / ".gitignore").write_text("")
    document = tmp_path / "docs" / "planted.md"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(f"# Planted\n\n{text}\n", encoding="utf-8")
    return dead_mentions(published_documents(tmp_path), TABLE, tmp_path)


def test_the_published_prose_names_no_route_the_app_does_not_serve():
    documents = published_documents(REPO)

    assert len(documents) > 10
    dead = dead_mentions(documents, TABLE, REPO)
    assert dead == [], refusal(dead)


@pytest.mark.parametrize(
    "text",
    [
        "`POST /api/books/bulk/ownership`",
        "`/api/peer/pair`",
        "`/api/books/bulk/ownership`",
        "`POST /api/books/{book_id}`",
        "`POST\n/api/books/bulk/ownership`",
        "`/api/nothing/*`",
        "`/api/nothing/...`",
        "`DELETE /api/books/5/tags`",
    ],
)
def test_a_dead_route_in_backticks_is_refused(tmp_path: Path, text: str):
    assert len(_dead(tmp_path, text)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "POST /api/books/bulk/ownership, without backticks, is history.",
        "`/api/{rest:path}`",
        "`DELETE /api/books/5`",
        "`/covers/<id>`",
        "`/covers/<id>.<ext>`",
        "`/api/imports/*`",
        "`/api`",
        "`GET /api/books/series?limit=5`",
        "```\nPOST /api/books/bulk/ownership\n```",
        "`GET /api/books/:book_id`",
        "`/api/books/...`",
        "`GET /api/healthz/`",
    ],
)
def test_a_live_route_or_no_mention_passes(tmp_path: Path, text: str):
    assert _dead(tmp_path, text) == []


def test_a_document_declaring_itself_internal_is_not_read(tmp_path: Path):
    text = "`/api/peer/pair`"

    assert _dead(tmp_path, f"{DECLARATION}\n\n{text}") == []
    assert len(_dead(tmp_path, text)) == 1


def test_a_refusal_names_the_line_and_the_history_marker(tmp_path: Path):
    """The fix is a convention, so the failure has to say what it is."""
    dead = _dead(tmp_path, "`POST /api/books/bulk/ownership`")
    message = refusal(dead)

    assert dead[0] in message
    assert REMEDY in message
