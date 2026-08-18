import logging
from collections.abc import Iterable, Iterator
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session as DBSession
from starlette.routing import BaseRoute

from config import (
    COVERS_DIR,
    cors_origins,
    ensure_data_dirs,
    validate_auth_config,
    validate_secret_key,
)
from database import engine
from enums import TagCategory
from errors import register_error_handlers
from middleware import SecurityHeadersMiddleware
from models import Tag
from routers import auth, books, imports, loans, settings, stats, users
from schema import upgrade_to_head

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("endpaper")

PREDEFINED_TAGS: list[tuple[str, TagCategory]] = [
    # Fiction type
    ("Fiction", TagCategory.TYPE),
    ("Non-Fiction", TagCategory.TYPE),
    # Genre
    ("Adventure", TagCategory.GENRE),
    ("Art", TagCategory.GENRE),
    ("Biography", TagCategory.GENRE),
    ("Business", TagCategory.GENRE),
    ("Cooking", TagCategory.GENRE),
    ("Fantasy", TagCategory.GENRE),
    ("Graphic Novel", TagCategory.GENRE),
    ("Historical Fiction", TagCategory.GENRE),
    ("History", TagCategory.GENRE),
    ("Horror", TagCategory.GENRE),
    ("Literary Fiction", TagCategory.GENRE),
    ("Memoir", TagCategory.GENRE),
    ("Mystery", TagCategory.GENRE),
    ("Philosophy", TagCategory.GENRE),
    ("Poetry", TagCategory.GENRE),
    ("Psychology", TagCategory.GENRE),
    ("Religion", TagCategory.GENRE),
    ("Romance", TagCategory.GENRE),
    ("Science", TagCategory.GENRE),
    ("Science Fiction", TagCategory.GENRE),
    ("Self-Help", TagCategory.GENRE),
    ("Short Stories", TagCategory.GENRE),
    ("Technology", TagCategory.GENRE),
    ("Thriller", TagCategory.GENRE),
    ("Travel", TagCategory.GENRE),
    ("True Crime", TagCategory.GENRE),
    # Age demographic
    ("Children (0-8)", TagCategory.AGE),
    ("Middle Grade (8-12)", TagCategory.AGE),
    ("Young Adult (13-18)", TagCategory.AGE),
    ("Adult", TagCategory.AGE),
]


# ── Schema management ─────────────────────────────────────────────────────────
#
# Migrations live in migrations/versions and are applied by schema.py.


def seed_tags() -> None:
    """Insert any predefined tag that is missing. Idempotent, so a restart
    never duplicates and a tag deleted by hand comes back."""
    with DBSession(engine) as db:
        existing = {name for (name,) in db.query(Tag.name).all()}
        for name, category in PREDEFINED_TAGS:
            if name not in existing:
                db.add(Tag(name=name, category=category))
        db.commit()


def init_db() -> None:
    # Checked before anything else: booting production with the example
    # signing key means every session token is forgeable.
    validate_secret_key()
    validate_auth_config()
    ensure_data_dirs()
    # Alembic owns the schema, including creating it from nothing. There is no
    # create_all() here on purpose: two things that both create tables is how
    # a database ends up in a shape no migration accounts for.
    upgrade_to_head()
    seed_tags()


init_db()


# ── App ───────────────────────────────────────────────────────────────────────


def custom_operation_id(route: APIRoute) -> str:
    """Use the handler's own name as the OpenAPI operationId.

    FastAPI's default mangles the path into the id, so `list_books` becomes
    `list_books_api_books_get` and the generated TypeScript client turns that
    straight into `useListBooksApiBooksGet()`. Handler names are unique across
    this app, and `assert_unique_operation_ids()` below keeps it that way.
    """
    return route.name


app = FastAPI(
    title="Endpaper",
    version="1.0.0",
    description="Catalogue, lend and track a family's physical book collection.",
    generate_unique_id_function=custom_operation_id,
)

app.add_middleware(SecurityHeadersMiddleware)

# Same-origin by default: FastAPI serves the API and the compiled frontend
# together, so no cross-origin request happens in a normal deployment. The
# previous "*" with credentials let any site make authenticated calls.
_origins = cors_origins()
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

register_error_handlers(app)

app.include_router(auth.router)
app.include_router(books.router)
app.include_router(imports.router)
app.include_router(loans.router)
app.include_router(settings.router)
app.include_router(stats.router)
app.include_router(users.router)


def iter_api_routes(routes: Iterable[BaseRoute]) -> Iterator[APIRoute]:
    """Yield every APIRoute, descending into included routers.

    `app.include_router()` does not splice the child's routes into
    `app.routes`; it appends a wrapper holding the original router. Iterating
    `app.routes` and filtering on APIRoute therefore finds only the handful of
    routes declared directly on the app, and silently skips every real
    endpoint, which is exactly how the first version of the check below
    passed while testing nothing.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        # Included routers (attribute name varies by FastAPI version) and
        # Mounts both nest their real routes one level down.
        nested = getattr(route, "original_router", None) or getattr(route, "routes", None)
        if nested is not None:
            yield from iter_api_routes(getattr(nested, "routes", nested))


def assert_unique_operation_ids() -> None:
    """Fail at startup if two handlers share a name.

    custom_operation_id() drops the path from the id, so a duplicate name would
    produce two operations with the same id, and a generated client where one
    endpoint silently overwrites the other.
    """
    seen: dict[str, str] = {}
    checked = 0
    for route in iter_api_routes(app.routes):
        checked += 1
        if route.name in seen:
            raise RuntimeError(
                f"Duplicate operationId '{route.name}': {seen[route.name]} and {route.path}. "
                "Rename one of the handlers."
            )
        seen[route.name] = route.path

    # A guard that inspects nothing is worse than no guard, because it reads
    # as coverage. If the route layout changes again, fail loudly here.
    if checked == 0:
        raise RuntimeError(
            "assert_unique_operation_ids() found no routes to check. "
            "iter_api_routes() no longer understands this FastAPI's route layout."
        )


assert_unique_operation_ids()


# ── Fallbacks ─────────────────────────────────────────────────────────────────
#
# Registered after the real routers and before the SPA mount, so they catch
# only paths nothing else claimed.

_fallback = APIRouter(include_in_schema=False)


@_fallback.api_route(
    "/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
)
@_fallback.api_route(
    "/auth/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
)
async def api_not_found(rest: str) -> None:
    """Unknown API paths must answer JSON 404.

    Without this they fall through to the SPA mount below and receive
    index.html with a 200, so a typo in a fetch() call looks like a
    successful request returning HTML, which is a genuinely confusing bug.
    """
    raise HTTPException(status_code=404, detail="Endpoint not found")


app.include_router(_fallback)

# Uploaded covers. Mounted before the SPA catch-all, which would otherwise
# swallow these paths.
app.mount("/covers", StaticFiles(directory=str(COVERS_DIR)), name="covers")

# The compiled PWA. `html=True` makes it a catch-all returning index.html for
# unmatched paths, which is what lets client-side routes survive a refresh.
# including the frontend's own 404 page.
static_dir = Path(__file__).parent / "static"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
else:
    logger.info("No ./static directory, running API-only (frontend served by Vite).")
