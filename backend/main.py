import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Final, NamedTuple

import anyio.to_thread
from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute
from starlette.types import Scope

import notifications
from config import (
    DATA_DIR,
    cors_origins,
    ensure_data_dirs,
    overdue_ticker_enabled,
    serve_frontend,
    validate_auth_config,
    validate_secret_key,
)
from database import engine
from dependencies import DbSession
from enums import TagCategory, TagKey
from errors import register_error_handlers, wants_html
from middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from models import Tag

# `collections` here is `routers/collections.py`, not the standard library's.
# The `from collections.abc import ...` above binds only the names it lists, so
# the two coexist; writing `collections.abc` anywhere in this module would not.
from routers import (
    auth,
    backup,
    books,
    collections,
    covers,
    imports,
    loans,
    public,
    settings,
    stats,
    users,
)
from schema import upgrade_to_head

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("endpaper")


class PredefinedTag(NamedTuple):
    """One entry in the curated vocabulary: what it is, what it is called, where it files.

    `key` is the identity and `name` is only the English name. The two are
    separate so a name can be corrected without a library's German tags
    silently changing which translation they get, and so a household that
    renamed a row can be told apart from one that did not. See `TagKey`.
    """

    key: TagKey
    name: str
    category: TagCategory


PREDEFINED_TAGS: list[PredefinedTag] = [
    # The vocabulary a library gets before it has typed anything, which is
    # the whole reason for having a curated list at all (Jelu and Openreads
    # make every tag free-form and start empty).
    #
    # **Additive only.** `seed_tags()` matches on name and skips what exists,
    # so a tag can be added here freely and it appears at the next restart.
    # Renaming or recategorising one needs a migration, because seeding alone
    # would leave the old row in place and insert a second beside it. That has
    # already happened once: see 95b6a61d6668.
    #
    # **A tag added here needs three things, not one**: a `TagKey` member, an
    # entry below, and a German name in `frontend/src/i18n/tagNames.ts`. The
    # third is a compile error if it is missing, because that table is typed
    # `Record<TagKey, string>` against the generated client. Regenerate it
    # (`bun run api:generate`) or the new key is not in the union yet.
    #
    # Long on purpose. A picker of thirty tags is a list; a picker of a hundred
    # and thirty is a vocabulary, and it is why the categories collapse in the
    # UI rather than all being on screen at once.

    # ── Type: what kind of thing it is ──────────────────────────────────────
    PredefinedTag(TagKey.FICTION, "Fiction", TagCategory.TYPE),
    PredefinedTag(TagKey.NON_FICTION, "Non-Fiction", TagCategory.TYPE),
    PredefinedTag(TagKey.REFERENCE, "Reference", TagCategory.TYPE),
    PredefinedTag(TagKey.TEXTBOOK, "Textbook", TagCategory.TYPE),
    PredefinedTag(TagKey.ANTHOLOGY, "Anthology", TagCategory.TYPE),
    PredefinedTag(TagKey.COMICS, "Comics", TagCategory.TYPE),
    PredefinedTag(TagKey.MANGA, "Manga", TagCategory.TYPE),
    PredefinedTag(TagKey.PLAY, "Play", TagCategory.TYPE),
    PredefinedTag(TagKey.ESSAYS, "Essays", TagCategory.TYPE),
    PredefinedTag(TagKey.PICTURE_BOOK, "Picture Book", TagCategory.TYPE),

    # ── Genre: fiction ──────────────────────────────────────────────────────
    PredefinedTag(TagKey.ADVENTURE, "Adventure", TagCategory.GENRE),
    PredefinedTag(TagKey.CLASSIC, "Classic", TagCategory.GENRE),
    PredefinedTag(TagKey.CONTEMPORARY_FICTION, "Contemporary Fiction", TagCategory.GENRE),
    PredefinedTag(TagKey.CRIME, "Crime", TagCategory.GENRE),
    PredefinedTag(TagKey.DETECTIVE, "Detective", TagCategory.GENRE),
    PredefinedTag(TagKey.DYSTOPIAN, "Dystopian", TagCategory.GENRE),
    PredefinedTag(TagKey.EPIC_FANTASY, "Epic Fantasy", TagCategory.GENRE),
    PredefinedTag(TagKey.FAIRY_TALES, "Fairy Tales", TagCategory.GENRE),
    PredefinedTag(TagKey.FANTASY, "Fantasy", TagCategory.GENRE),
    PredefinedTag(TagKey.FOLKLORE, "Folklore", TagCategory.GENRE),
    PredefinedTag(TagKey.GOTHIC, "Gothic", TagCategory.GENRE),
    PredefinedTag(TagKey.GRAPHIC_NOVEL, "Graphic Novel", TagCategory.GENRE),
    PredefinedTag(TagKey.HISTORICAL_FICTION, "Historical Fiction", TagCategory.GENRE),
    PredefinedTag(TagKey.HORROR, "Horror", TagCategory.GENRE),
    PredefinedTag(TagKey.HUMOUR, "Humour", TagCategory.GENRE),
    PredefinedTag(TagKey.LITERARY_FICTION, "Literary Fiction", TagCategory.GENRE),
    PredefinedTag(TagKey.MAGICAL_REALISM, "Magical Realism", TagCategory.GENRE),
    PredefinedTag(TagKey.MYSTERY, "Mystery", TagCategory.GENRE),
    PredefinedTag(TagKey.MYTHOLOGY, "Mythology", TagCategory.GENRE),
    PredefinedTag(TagKey.NOIR, "Noir", TagCategory.GENRE),
    PredefinedTag(TagKey.PARANORMAL, "Paranormal", TagCategory.GENRE),
    PredefinedTag(TagKey.POETRY, "Poetry", TagCategory.GENRE),
    PredefinedTag(TagKey.POST_APOCALYPTIC, "Post-Apocalyptic", TagCategory.GENRE),
    PredefinedTag(TagKey.ROMANCE, "Romance", TagCategory.GENRE),
    PredefinedTag(TagKey.SATIRE, "Satire", TagCategory.GENRE),
    PredefinedTag(TagKey.SCIENCE_FICTION, "Science Fiction", TagCategory.GENRE),
    PredefinedTag(TagKey.SHORT_STORIES, "Short Stories", TagCategory.GENRE),
    PredefinedTag(TagKey.SPACE_OPERA, "Space Opera", TagCategory.GENRE),
    PredefinedTag(TagKey.SPECULATIVE_FICTION, "Speculative Fiction", TagCategory.GENRE),
    PredefinedTag(TagKey.SPY_FICTION, "Spy Fiction", TagCategory.GENRE),
    PredefinedTag(TagKey.STEAMPUNK, "Steampunk", TagCategory.GENRE),
    PredefinedTag(TagKey.SUSPENSE, "Suspense", TagCategory.GENRE),
    PredefinedTag(TagKey.THRILLER, "Thriller", TagCategory.GENRE),
    PredefinedTag(TagKey.URBAN_FANTASY, "Urban Fantasy", TagCategory.GENRE),
    PredefinedTag(TagKey.WAR, "War", TagCategory.GENRE),
    PredefinedTag(TagKey.WESTERN, "Western", TagCategory.GENRE),

    # ── Genre: non-fiction ──────────────────────────────────────────────────
    PredefinedTag(TagKey.ANTHROPOLOGY, "Anthropology", TagCategory.GENRE),
    PredefinedTag(TagKey.ARCHAEOLOGY, "Archaeology", TagCategory.GENRE),
    PredefinedTag(TagKey.ARCHITECTURE, "Architecture", TagCategory.GENRE),
    PredefinedTag(TagKey.ART, "Art", TagCategory.GENRE),
    PredefinedTag(TagKey.ASTRONOMY, "Astronomy", TagCategory.GENRE),
    PredefinedTag(TagKey.AUTOBIOGRAPHY, "Autobiography", TagCategory.GENRE),
    PredefinedTag(TagKey.BIOGRAPHY, "Biography", TagCategory.GENRE),
    PredefinedTag(TagKey.BIOLOGY, "Biology", TagCategory.GENRE),
    PredefinedTag(TagKey.BUSINESS, "Business", TagCategory.GENRE),
    PredefinedTag(TagKey.CHEMISTRY, "Chemistry", TagCategory.GENRE),
    PredefinedTag(TagKey.COMPUTING, "Computing", TagCategory.GENRE),
    PredefinedTag(TagKey.COOKING, "Cooking", TagCategory.GENRE),
    PredefinedTag(TagKey.DESIGN, "Design", TagCategory.GENRE),
    PredefinedTag(TagKey.DIARIES_AND_LETTERS, "Diaries and Letters", TagCategory.GENRE),
    PredefinedTag(TagKey.ECONOMICS, "Economics", TagCategory.GENRE),
    PredefinedTag(TagKey.EDUCATION, "Education", TagCategory.GENRE),
    PredefinedTag(TagKey.ENVIRONMENT, "Environment", TagCategory.GENRE),
    PredefinedTag(TagKey.ETHICS, "Ethics", TagCategory.GENRE),
    PredefinedTag(TagKey.FEMINISM, "Feminism", TagCategory.GENRE),
    PredefinedTag(TagKey.FILM_AND_TV, "Film and TV", TagCategory.GENRE),
    PredefinedTag(TagKey.FINANCE, "Finance", TagCategory.GENRE),
    PredefinedTag(TagKey.GARDENING, "Gardening", TagCategory.GENRE),
    PredefinedTag(TagKey.GEOGRAPHY, "Geography", TagCategory.GENRE),
    PredefinedTag(TagKey.HEALTH_AND_FITNESS, "Health and Fitness", TagCategory.GENRE),
    PredefinedTag(TagKey.HISTORY, "History", TagCategory.GENRE),
    PredefinedTag(TagKey.JOURNALISM, "Journalism", TagCategory.GENRE),
    PredefinedTag(TagKey.LANGUAGE, "Language", TagCategory.GENRE),
    PredefinedTag(TagKey.LAW, "Law", TagCategory.GENRE),
    PredefinedTag(TagKey.LINGUISTICS, "Linguistics", TagCategory.GENRE),
    PredefinedTag(TagKey.MATHEMATICS, "Mathematics", TagCategory.GENRE),
    PredefinedTag(TagKey.MEDICINE, "Medicine", TagCategory.GENRE),
    PredefinedTag(TagKey.MEMOIR, "Memoir", TagCategory.GENRE),
    PredefinedTag(TagKey.MUSIC, "Music", TagCategory.GENRE),
    PredefinedTag(TagKey.NATURE, "Nature", TagCategory.GENRE),
    PredefinedTag(TagKey.PARENTING, "Parenting", TagCategory.GENRE),
    PredefinedTag(TagKey.PHILOSOPHY, "Philosophy", TagCategory.GENRE),
    PredefinedTag(TagKey.PHOTOGRAPHY, "Photography", TagCategory.GENRE),
    PredefinedTag(TagKey.PHYSICS, "Physics", TagCategory.GENRE),
    PredefinedTag(TagKey.POLITICS, "Politics", TagCategory.GENRE),
    PredefinedTag(TagKey.POPULAR_SCIENCE, "Popular Science", TagCategory.GENRE),
    PredefinedTag(TagKey.PSYCHOLOGY, "Psychology", TagCategory.GENRE),
    PredefinedTag(TagKey.RELIGION, "Religion", TagCategory.GENRE),
    PredefinedTag(TagKey.SCIENCE, "Science", TagCategory.GENRE),
    PredefinedTag(TagKey.SELF_HELP, "Self-Help", TagCategory.GENRE),
    PredefinedTag(TagKey.SOCIOLOGY, "Sociology", TagCategory.GENRE),
    PredefinedTag(TagKey.SPORTS, "Sports", TagCategory.GENRE),
    PredefinedTag(TagKey.TECHNOLOGY, "Technology", TagCategory.GENRE),
    PredefinedTag(TagKey.THEATRE, "Theatre", TagCategory.GENRE),
    PredefinedTag(TagKey.TRAVEL, "Travel", TagCategory.GENRE),
    PredefinedTag(TagKey.TRUE_CRIME, "True Crime", TagCategory.GENRE),
    PredefinedTag(TagKey.URBANISM, "Urbanism", TagCategory.GENRE),
    PredefinedTag(TagKey.WINE_AND_DRINK, "Wine and Drink", TagCategory.GENRE),

    # ── Age: who it is for ──────────────────────────────────────────────────
    PredefinedTag(TagKey.BABY_AND_TODDLER, "Baby and Toddler (0-3)", TagCategory.AGE),
    PredefinedTag(TagKey.CHILDREN, "Children (0-8)", TagCategory.AGE),
    PredefinedTag(TagKey.EARLY_READER, "Early Reader (5-8)", TagCategory.AGE),
    PredefinedTag(TagKey.MIDDLE_GRADE, "Middle Grade (8-12)", TagCategory.AGE),
    PredefinedTag(TagKey.YOUNG_ADULT, "Young Adult (13-18)", TagCategory.AGE),
    PredefinedTag(TagKey.NEW_ADULT, "New Adult (18-25)", TagCategory.AGE),
    PredefinedTag(TagKey.ADULT, "Adult", TagCategory.AGE),
]


# ── Schema management ─────────────────────────────────────────────────────────
#
# Migrations live in migrations/versions and are applied by schema.py.


def seed_tags() -> None:
    """Insert any predefined tag that is missing. Idempotent, so a restart
    never duplicates and a tag deleted by hand comes back.

    Only these carry `is_predefined`. A tag the library invented is left
    alone here, which is the whole reason the flag exists: without it a
    restart would either delete their tags or adopt them.

    **Still matched on name, not on key**, which is what keeps this idempotent
    for the library that renamed a seeded tag: that row lost its key in the
    migration and is theirs now, and matching on key would find the vocabulary
    short and insert an English second copy beside their own word. The key is
    written on the rows this inserts, and set on the rows the migration
    recognised. Nothing here ever writes one onto a row that lacks it.
    """
    with DBSession(engine) as db:
        existing = {name for (name,) in db.query(Tag.name).all()}
        for key, name, category in PREDEFINED_TAGS:
            if name not in existing:
                db.add(Tag(key=key, name=name, category=category, is_predefined=True))
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


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the overdue ticker with the app, and stop it with the app.

    One task, started here rather than from a module-level `create_task`,
    because there is no running event loop at import time and because a task
    nobody holds a reference to can be garbage collected mid-await.

    Cancelled on shutdown and awaited. Without the await the interpreter can
    exit while the task is between statements, which surfaces as a
    "Task was destroyed but it is pending" on every container stop.

    Off entirely when `ENABLE_OVERDUE_TICKER=false`, which is what the test
    suite sets and what a deployment running the digest from cron sets.
    """
    task: asyncio.Task[None] | None = None
    if overdue_ticker_enabled():
        task = asyncio.create_task(notifications.ticker())
        logger.info("Overdue reminder ticker started")

    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


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
    description="Catalogue, lend and track a collection of physical books, shared by the people who use it.",
    generate_unique_id_function=custom_operation_id,
    lifespan=lifespan,
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
app.include_router(collections.router)
app.include_router(imports.router)
app.include_router(loans.router)
# Before the SPA mount, like every router, and that matters more here than
# elsewhere: this one owns `/robots.txt`, which a build emitting one would
# otherwise be answered from disk. It is also the one router whose routes
# answer without a session, which is why its own module opens by naming the
# four rules that apply to it.
app.include_router(public.router)
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


#: How long the storage check waits before calling it dead.
#:
#: **Must stay comfortably under the deployment probe's own `timeoutSeconds`,
#: which Kubernetes defaults to 1 and which therefore has to be set.** If this
#: is the longer of the two, the kubelet gives up while the handler is still
#: waiting and the pod reports a hang rather than a failure, which is the thing
#: this whole check exists to avoid. `docs/api.md` states the numbers a deployer
#: has to set; the chart lives in another repository.
STORAGE_TIMEOUT_SECONDS: Final = 2

#: One thread, and it is never joined. A hung NFS call blocks in uninterruptible
#: sleep and cannot be cancelled or interrupted, so the thread that made it is
#: gone for the life of the process. Running the stat inline instead would leak
#: a thread from FastAPI's own pool on every probe until the app stopped
#: answering anything at all, which is a worse failure than the one being
#: detected. This bounds the loss at exactly one thread.
_storage_probe = ThreadPoolExecutor(max_workers=1, thread_name_prefix="healthz-storage")

_pending_stat: Future[os.stat_result] | None = None


def storage_is_reachable() -> bool:
    """Whether a namespace operation on the data directory comes back.

    `SELECT 1` does not answer this. On an already-open SQLite handle it is
    served from the page cache and issues no RPC, so it crosses no wire and
    cannot fail when the wire is what is broken.

    The deeper point, and the one worth keeping: **storage death can only ever
    reach a probe as a timeout.** A hung NFS call does not return an error, it
    does not return. So a check that never reaches the mount can never fail in
    the mode that matters, and a check that does reach it needs its own clock.
    """
    global _pending_stat

    if _pending_stat is not None and not _pending_stat.done():
        # The previous stat has still not come back. That is exactly what a hung
        # mount looks like, and re-queueing behind it would only grow a backlog
        # of calls that will never run.
        return False

    _pending_stat = _storage_probe.submit(os.stat, DATA_DIR)
    try:
        _pending_stat.result(timeout=STORAGE_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        logger.error("Data directory did not answer within %ds", STORAGE_TIMEOUT_SECONDS)
        return False
    except OSError as error:
        logger.error("Data directory is unreachable: %s", error)
        return False
    return True


@app.get("/api/healthz", tags=["system"])
def healthz(db: DbSession) -> dict[str, str]:
    """Whether this container can actually serve.

    The Kubernetes probes used to request `/`, which the SPA mount answers from
    disk: a pod whose database had gone (an unmounted volume, a corrupt file)
    stayed Ready and kept taking traffic, because index.html was still readable.
    Touching the database is the whole point, so this is a query rather than a
    constant.

    **That was not enough, and the correction is the interesting half.**
    Measured during a total NFS outage on 2026-08-22: `/api/healthz` answered
    200 continuously and the pod stayed 1/1 Ready for 39 hours while the volume
    was unresponsive to every new namespace operation. `SELECT 1` on an
    already-open SQLite handle is served from the page cache and issues no RPC,
    so the query crossed no wire. Readiness built on a long-lived handle
    measures the process, not its storage: an unmounted volume would have been
    caught, a hung one could not be, by construction.

    So the query is joined by a `stat` of the data directory, which is a
    namespace operation and therefore has to cross the wire, under its own
    timeout. See `storage_is_reachable`.

    **This is the liveness probe as well as readiness, and the consequence is
    intended.** Once the check works, a hung mount restarts the pod, and the
    restarted pod blocks in `init_db()` on the same mount, so it stays down and
    visible rather than coming back. A container in `CrashLoopBackOff` reaches
    every alert a library has; a pod that is 1/1 Ready and serving nothing
    reaches none of them, which is what the 39 hours above were. It recovers by
    itself when the mount does.

    Unauthenticated, deliberately: a probe holds no token, and the only thing
    disclosed is that the service is up, which anyone can tell by connecting.
    """
    db.execute(text("SELECT 1"))
    if not storage_is_reachable():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage is not reachable",
        )
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

    The job is the **body**, not the status. Without this the request reaches
    the SPA mount, which refuses it the shell (`wants_html` excludes the API
    prefixes) and 404s, but a `fetch()` would then be handed this app's HTML
    error page rather than the JSON every other failure returns.

    It is also the first of the two guards against the bug it was written for, a
    typo in a `fetch()` call answering **200 with HTML** and so looking like a
    success. That is no longer what happens if this router is removed, and the
    reason is that `CachePolicyStaticFiles` refuses API paths as well. Two
    independent guards on one rule, kept deliberately: this one is the one a
    reader of the route table can see.
    """
    raise HTTPException(status_code=404, detail="Endpoint not found")


app.include_router(_fallback)

# Uploaded covers. A router rather than a StaticFiles mount, and that is a
# security fix rather than a refactor: a mount has no dependencies, so nothing
# authenticated or authorized that path, and cover filenames are the book id.
# Any member could read another member's private book cover by counting. See
# routers/covers.py. Registered before the SPA mount, which would otherwise
# answer a missing cover with the shell: see `CachePolicyStaticFiles`.
app.include_router(covers.router)

# Vite's `build.assetsDir`. Every filename it emits there carries a content
# hash, so the name changes whenever the bytes do.
HASHED_ASSET_DIR: Final = "assets"

# A year, and `immutable` so a reload does not even send a conditional request.
# Safe only because the name is content addressed: a changed file is a changed
# URL, so nothing can be stale.
CACHE_IMMUTABLE: Final = "public, max-age=31536000, immutable"

# Not `no-store`. `no-cache` means "ask before reusing", not "do not keep": the
# copy stays in the cache and the ETag turns the next request into a 304 with no
# body. `no-store` would throw that away and re-download the file every time for
# no gain.
CACHE_REVALIDATE: Final = "no-cache"


def cache_control_for(full_path: str | os.PathLike[str]) -> str:
    """How long a built file may be reused without asking.

    One rule: **a name that changes with its content may be cached, and a name
    that does not must be revalidated.** Only `assets/` is content addressed, so
    everything else revalidates: index.html, manifest.json, sw.js, registerSW.js
    and the icons all keep their names across builds while their bytes change.

    Getting index.html wrong breaks a release, and the mechanism is worth
    stating because the obvious reason is the wrong one. With no `Cache-Control`
    at all a browser applies *heuristic* freshness: it may reuse the shell for a
    while without asking. That shell names its scripts by content hash, and a
    deploy deletes the hashes it no longer builds, so a reader holding
    yesterday's index.html requests `assets/index-<hash>.js` and gets a 404. A
    blank page after a release, with nothing wrong on the server.

    Not an authentication fix, and the difference matters. A heuristically fresh
    shell cannot re-create the endless-spinner bug on its own, because both
    recovery paths already reach the network: signing out navigates to `/login`,
    a URL no cache entry answers, and a reload navigation is fetched with cache
    mode "reload", which skips the freshness check by specification. The service
    worker fault was worse precisely because the precache answered the reload
    too. That is fixed in `frontend/vite.config.ts`; this is about deploys.

    Keyed on the directory rather than on the shape of the filename, because
    the directory is what Vite guarantees and a "does this look hashed" regex is
    a guess. If `assetsDir` is ever renamed, files fall out of the fast case
    into the safe one, which costs a conditional request and cannot serve
    anything stale.
    """
    return (
        CACHE_IMMUTABLE
        if Path(full_path).parent.name == HASHED_ASSET_DIR
        else CACHE_REVALIDATE
    )


SHELL = "index.html"


class CachePolicyStaticFiles(StaticFiles):
    """`StaticFiles` that states a cache lifetime per file, and serves the shell.

    Starlette sends an ETag and a Last-Modified and no `Cache-Control` at all,
    which leaves every file to the browser's *heuristic* freshness: reuse it
    without asking for some fraction of its age. Heuristics are the wrong thing
    to leave the app shell to, hence this.

    A subclass rather than middleware, and that is the point of it: middleware
    on this app would see every response, including the API's, and would have to
    re-derive which ones came off the disk. This can only ever run for a file
    this mount served.

    Both status codes are covered. `file_response` returns either a 200 or the
    304 Starlette builds when the request's validator still matches, and setting
    the header on whichever came back keeps the two consistent: a 304 that
    dropped the policy would answer the next request from a cache with no policy
    on it.
    """

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = cache_control_for(full_path)
        return response

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Answer a browser navigating to a client route with the shell.

        **`html=True` does not do this**, which is the whole reason for the
        override. It serves index.html for `/` and for a directory, and nothing
        else: an unmatched path falls to its `404.html` branch and then to a
        404. Measured on the running container, with a valid session:
        `/` and `/index.html` 200, `/book/12`, `/settings` and `/quotes` all
        **404**. So a bookmark, a refresh anywhere but home, and a shared link
        to a book were all broken, and `docs/architecture.md` had been
        promising the opposite since the mount was written.

        Three conditions, and each one is a way this could go wrong:

        * **Not a path the API owns.** The gate is `is_api_path`, and its list
          is all six of `errors.API_PREFIXES`: `/api/`, `/auth/`, `/covers/`,
          `/openapi.json`, `/docs`, `/redoc`. Not `_fallback`, which claims only
          the first two: the covers router and FastAPI's own routes claim the
          rest, and `wants_html` refuses all six here regardless. An API typo
          must stay a JSON 404 rather than becoming a 200 with HTML in it, which
          is the confusing bug `_fallback` was written for.

          Worth knowing before adding a route: `_fallback` claims `/auth/*` for
          all seven methods ahead of this mount, so a **client** route under
          `/auth` would JSON-404 rather than render, which is the shape an OIDC
          callback at `/auth/callback` would take.
        * **A navigation, not a fetch.** `wants_html` is the same predicate the
          error pages use: a browser navigation sends `text/html`, a `fetch`
          sends a wildcard. So an unknown path requested by code still 404s.
          Only GET and HEAD arrive here at all; `StaticFiles.get_response`
          answers anything else 405 before this runs.
        * **Never under the assets directory.** Content-addressed names, so a
          request for one that is missing means the client is holding a stale
          shell. Answering that with HTML turns a clean failure into a parse
          error inside a script tag. The `Accept` test alone would cover the
          browser's own loads, which send a wildcard; this makes it true of a
          typed URL as well, rather than resting on a header nobody here
          controls.

        Deliberately not keyed on the path having a file extension, which is the
        usual shortcut: `/authors/J.R.R. Tolkien` is a real client route.
        """
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not self._serves_the_shell(path, scope):
                raise
        else:
            # A 404 can be *returned* rather than raised: Starlette's `html=True`
            # serves a `404.html` if the build has one, and it builds that
            # response with `FileResponse` directly rather than through
            # `file_response`, so it would carry no `Cache-Control` either. This
            # branch means a navigation gets the shell whichever way the 404
            # arrived. The build emits no `404.html` today, so it is unreachable
            # rather than dormant, and it stays that way: a 404.html for a
            # missing *asset* would still be answered without the policy.
            if response.status_code != 404 or not self._serves_the_shell(path, scope):
                return response

        full_path, stat_result = await anyio.to_thread.run_sync(self.lookup_path, SHELL)
        if stat_result is None:
            raise StarletteHTTPException(status_code=404)

        # Through `file_response`, so the shell carries the same `no-cache` it
        # carries at `/`. A deep link served without it would be cached under
        # its own URL, which is the staleness this class exists to prevent.
        return self.file_response(full_path, stat_result, scope)

    # **This branch cannot serve a requested path, by construction.** The lookup
    # above is `lookup_path(SHELL)`, and SHELL is a module constant: `path`
    # reaches this method only to be tested for the `assets/` prefix, and is
    # never looked up, joined or opened. So a total failure of the containment
    # check in `lookup_path` would still not turn this into a file read. That is
    # the guarantee worth knowing, because the obvious argument, that
    # `lookup_path` refuses an escape, is the weaker one: it is true (verified
    # on the real mount with twelve escape shapes and three symlinks pointing
    # out of the tree, all fifteen answering the shell and none the planted
    # sentinel) and it depends on Starlette continuing to behave that way, where
    # this does not depend on anything outside these six lines.

    def _serves_the_shell(self, path: str, scope: Scope) -> bool:
        """Whether a missing `path` should be answered with the shell."""
        if path.split("/", 1)[0] == HASHED_ASSET_DIR:
            return False
        return wants_html(Request(scope))


def mount_spa(app: FastAPI, directory: Path) -> None:
    """Serve the compiled PWA from `directory`.

    A function so the suite can mount a directory shaped like a build and drive
    it, rather than restating this line and then testing its own copy. Swapping
    the class back for a plain `StaticFiles` has to fail a test, and it only
    does if there is one mount and the tests use it.

    `html=True` serves index.html for a request to `/` itself and for nothing
    else. What makes a client route survive a refresh is
    `CachePolicyStaticFiles.get_response`, which is where that is explained.
    """
    app.mount(
        "/", CachePolicyStaticFiles(directory=str(directory), html=True), name="static"
    )


def mount_frontend_if_enabled(app: FastAPI, directory: Path) -> bool:
    """Mount the SPA unless it is switched off or is not there. Says which.

    Two ways to end up API-only, and they are not the same thing. A dev run has
    no `static/` because Vite is serving it; a relay has one and does not want
    it (`SERVE_FRONTEND=false`), because a host with no reader should not carry
    the shell, the asset routes and the SPA fallback. The shipped image always
    contains the directory, so without the flag the second case cannot happen.

    A function with one caller in the app, the line below it, and six in the
    suite, so the tests drive the decision production makes: an inlined `if`
    could only be tested by a copy, and a copy keeps passing after this stops
    being wired up.
    """
    if not serve_frontend():
        logger.info("SERVE_FRONTEND=false, running API-only (headless).")
        return False
    if not directory.is_dir():
        logger.info("No ./static directory, running API-only (frontend served by Vite).")
        return False
    mount_spa(app, directory)
    return True


mount_frontend_if_enabled(app, Path(__file__).parent / "static")
