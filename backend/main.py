import logging
from collections.abc import Iterable, Iterator
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession
from starlette.routing import BaseRoute

from config import (
    cors_origins,
    ensure_data_dirs,
    validate_auth_config,
    validate_secret_key,
)
from database import engine
from dependencies import DbSession
from enums import TagCategory
from errors import register_error_handlers
from middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from models import Tag
from routers import (
    auth,
    backup,
    books,
    covers,
    imports,
    loans,
    settings,
    stats,
    users,
)
from schema import upgrade_to_head

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("endpaper")

PREDEFINED_TAGS: list[tuple[str, TagCategory]] = [
    # The vocabulary a household gets before it has typed anything, which is
    # the whole reason for having a curated list at all (Jelu and Openreads
    # make every tag free-form and start empty).
    #
    # **Additive only.** `seed_tags()` matches on name and skips what exists,
    # so a tag can be added here freely and it appears at the next restart.
    # Renaming or recategorising one needs a migration, because seeding alone
    # would leave the old row in place and insert a second beside it. That has
    # already happened once: see 95b6a61d6668.
    #
    # Long on purpose. A picker of thirty tags is a list; a picker of a hundred
    # and thirty is a vocabulary, and it is why the categories collapse in the
    # UI rather than all being on screen at once.

    # ── Type: what kind of thing it is ──────────────────────────────────────
    ("Fiction", TagCategory.TYPE),
    ("Non-Fiction", TagCategory.TYPE),
    ("Reference", TagCategory.TYPE),
    ("Textbook", TagCategory.TYPE),
    ("Anthology", TagCategory.TYPE),
    ("Comics", TagCategory.TYPE),
    ("Manga", TagCategory.TYPE),
    ("Play", TagCategory.TYPE),
    ("Essays", TagCategory.TYPE),
    ("Picture Book", TagCategory.TYPE),

    # ── Genre: fiction ──────────────────────────────────────────────────────
    ("Adventure", TagCategory.GENRE),
    ("Classic", TagCategory.GENRE),
    ("Contemporary Fiction", TagCategory.GENRE),
    ("Crime", TagCategory.GENRE),
    ("Detective", TagCategory.GENRE),
    ("Dystopian", TagCategory.GENRE),
    ("Epic Fantasy", TagCategory.GENRE),
    ("Fairy Tales", TagCategory.GENRE),
    ("Fantasy", TagCategory.GENRE),
    ("Folklore", TagCategory.GENRE),
    ("Gothic", TagCategory.GENRE),
    ("Graphic Novel", TagCategory.GENRE),
    ("Historical Fiction", TagCategory.GENRE),
    ("Horror", TagCategory.GENRE),
    ("Humour", TagCategory.GENRE),
    ("Literary Fiction", TagCategory.GENRE),
    ("Magical Realism", TagCategory.GENRE),
    ("Mystery", TagCategory.GENRE),
    ("Mythology", TagCategory.GENRE),
    ("Noir", TagCategory.GENRE),
    ("Paranormal", TagCategory.GENRE),
    ("Poetry", TagCategory.GENRE),
    ("Post-Apocalyptic", TagCategory.GENRE),
    ("Romance", TagCategory.GENRE),
    ("Satire", TagCategory.GENRE),
    ("Science Fiction", TagCategory.GENRE),
    ("Short Stories", TagCategory.GENRE),
    ("Space Opera", TagCategory.GENRE),
    ("Speculative Fiction", TagCategory.GENRE),
    ("Spy Fiction", TagCategory.GENRE),
    ("Steampunk", TagCategory.GENRE),
    ("Suspense", TagCategory.GENRE),
    ("Thriller", TagCategory.GENRE),
    ("Urban Fantasy", TagCategory.GENRE),
    ("War", TagCategory.GENRE),
    ("Western", TagCategory.GENRE),

    # ── Genre: non-fiction ──────────────────────────────────────────────────
    ("Anthropology", TagCategory.GENRE),
    ("Archaeology", TagCategory.GENRE),
    ("Architecture", TagCategory.GENRE),
    ("Art", TagCategory.GENRE),
    ("Astronomy", TagCategory.GENRE),
    ("Autobiography", TagCategory.GENRE),
    ("Biography", TagCategory.GENRE),
    ("Biology", TagCategory.GENRE),
    ("Business", TagCategory.GENRE),
    ("Chemistry", TagCategory.GENRE),
    ("Computing", TagCategory.GENRE),
    ("Cooking", TagCategory.GENRE),
    ("Design", TagCategory.GENRE),
    ("Diaries and Letters", TagCategory.GENRE),
    ("Economics", TagCategory.GENRE),
    ("Education", TagCategory.GENRE),
    ("Environment", TagCategory.GENRE),
    ("Ethics", TagCategory.GENRE),
    ("Feminism", TagCategory.GENRE),
    ("Film and TV", TagCategory.GENRE),
    ("Finance", TagCategory.GENRE),
    ("Gardening", TagCategory.GENRE),
    ("Geography", TagCategory.GENRE),
    ("Health and Fitness", TagCategory.GENRE),
    ("History", TagCategory.GENRE),
    ("Journalism", TagCategory.GENRE),
    ("Language", TagCategory.GENRE),
    ("Law", TagCategory.GENRE),
    ("Linguistics", TagCategory.GENRE),
    ("Mathematics", TagCategory.GENRE),
    ("Medicine", TagCategory.GENRE),
    ("Memoir", TagCategory.GENRE),
    ("Music", TagCategory.GENRE),
    ("Nature", TagCategory.GENRE),
    ("Parenting", TagCategory.GENRE),
    ("Philosophy", TagCategory.GENRE),
    ("Photography", TagCategory.GENRE),
    ("Physics", TagCategory.GENRE),
    ("Politics", TagCategory.GENRE),
    ("Popular Science", TagCategory.GENRE),
    ("Psychology", TagCategory.GENRE),
    ("Religion", TagCategory.GENRE),
    ("Science", TagCategory.GENRE),
    ("Self-Help", TagCategory.GENRE),
    ("Sociology", TagCategory.GENRE),
    ("Sports", TagCategory.GENRE),
    ("Technology", TagCategory.GENRE),
    ("Theatre", TagCategory.GENRE),
    ("Travel", TagCategory.GENRE),
    ("True Crime", TagCategory.GENRE),
    ("Urbanism", TagCategory.GENRE),
    ("Wine and Drink", TagCategory.GENRE),

    # ── Age: who it is for ──────────────────────────────────────────────────
    ("Baby and Toddler (0-3)", TagCategory.AGE),
    ("Children (0-8)", TagCategory.AGE),
    ("Early Reader (5-8)", TagCategory.AGE),
    ("Middle Grade (8-12)", TagCategory.AGE),
    ("Young Adult (13-18)", TagCategory.AGE),
    ("New Adult (18-25)", TagCategory.AGE),
    ("Adult", TagCategory.AGE),
]


# ── Schema management ─────────────────────────────────────────────────────────
#
# Migrations live in migrations/versions and are applied by schema.py.


def seed_tags() -> None:
    """Insert any predefined tag that is missing. Idempotent, so a restart
    never duplicates and a tag deleted by hand comes back.

    Only these carry `is_predefined`. A tag the household invented is left
    alone here, which is the whole reason the flag exists: without it a
    restart would either delete their tags or adopt them.
    """
    with DBSession(engine) as db:
        existing = {name for (name,) in db.query(Tag.name).all()}
        for name, category in PREDEFINED_TAGS:
            if name not in existing:
                db.add(Tag(name=name, category=category, is_predefined=True))
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

# Added first, so it sits innermost: the refusal still happens before anything
# reads the body, and it picks up the security and CORS headers of the layers
# around it rather than answering bare.
app.add_middleware(BodySizeLimitMiddleware)
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
app.include_router(backup.router)
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


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/api/healthz", tags=["system"])
def healthz(db: DbSession) -> dict[str, str]:
    """Whether this container can actually serve.

    The Kubernetes probes used to request `/`, which the SPA mount answers from
    disk: a pod whose database had gone (an unmounted volume, a corrupt file)
    stayed Ready and kept taking traffic, because index.html was still readable.
    Touching the database is the whole point, so this is a query rather than a
    constant.

    Unauthenticated, deliberately: a probe holds no token, and the only thing
    disclosed is that the service is up, which anyone can tell by connecting.
    """
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


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

# Uploaded covers. A router rather than a StaticFiles mount, and that is a
# security fix rather than a refactor: a mount has no dependencies, so nothing
# authenticated or authorized that path, and cover filenames are the book id.
# Any member could read another member's private book cover by counting. See
# routers/covers.py. Registered before the SPA catch-all, which would otherwise
# swallow these paths.
app.include_router(covers.router)

# The compiled PWA. `html=True` makes it a catch-all returning index.html for
# unmatched paths, which is what lets client-side routes survive a refresh.
# including the frontend's own 404 page.
static_dir = Path(__file__).parent / "static"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
else:
    logger.info("No ./static directory, running API-only (frontend served by Vite).")
