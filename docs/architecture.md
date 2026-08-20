# Architecture

## One container, two languages

The deployed artifact is a single image. FastAPI owns port 8000 and serves three things:

| Path prefix | Served by | Notes |
|---|---|---|
| `/api/*`, `/auth/*` | FastAPI routers | The JSON API |
| unmatched `/api/*`, `/auth/*` | a fallback router | JSON 404, see below |
| `/covers/*` | a FastAPI router | Uploaded cover images, from `DATA_DIR/covers` |
| `/api/healthz` | a FastAPI route | Liveness and readiness, runs a query |
| everything else | `StaticFiles(html=True)` | The compiled React bundle |

`/covers` is a **router, not a `StaticFiles` mount**, and that is a security fix rather
than a stylistic choice. A mount has no dependencies, so nothing authenticates or
authorizes it, and cover filenames are the book id: any member could read another
member's private book cover by counting. `routers/covers.py` applies the same
`visible_to()` rule the rest of the API does. Do not turn it back into a mount.

Mount order in `main.py` is load-bearing. The SPA is mounted at `/` with `html=True`,
making it a catch-all that returns `index.html` for any unmatched path. That is what lets
client-side routes like `/book/12` survive a refresh, and why it must be mounted **last**.
The covers router is registered before it, or cover requests would be answered with the
HTML shell.

Routers are registered before either mount, so they win over both. Between them sits a
fallback router matching `/api/{rest:path}` and `/auth/{rest:path}`, returning a JSON 404.
Without it an unknown API path falls through to the SPA mount and answers `index.html` with
a **200**, so a typo in a `fetch()` call looks like a successful request that returned HTML.

Serving the API and the bundle from one origin means the browser never makes a cross-origin
request in production, which is why CORS is **off** by default. Vite proxies rather than
making cross-origin calls, so dev does not need it either. Set `CORS_ORIGINS` only for a
genuinely separate frontend host.

## Development runs as two processes

```
        bun run dev                        uv run uvicorn
   ┌──────────────────────┐          ┌───────────────────────┐
   │ Vite dev server      │  proxy   │ FastAPI               │
   │ :5173                │─────────►│ :8000                 │
   │ HMR, React Refresh   │          │ /api /auth /covers    │
   └──────────────────────┘          └───────────────────────┘
```

`vite.config.ts` proxies `/api`, `/auth` and `/covers` to `localhost:8000`, so the frontend
uses the same relative URLs in both environments. The generated client emits origin-relative
paths and `src/api/mutator.ts` adds no base URL, so there is no `VITE_API_URL` to get wrong.

`bun run api:generate` regenerates that client from the backend's schema. The output is
committed, so neither the build nor the test suite needs a Python toolchain.

## The build

```
Stage 1  oven/bun:alpine     bun install --frozen-lockfile  →  bun run build  →  dist/
Stage 2  python:3.14-alpine  uv sync --frozen --no-dev  +  COPY --from=stage1 dist ./static
```

Only the compiled assets cross between stages, so Bun, `node_modules` and the TypeScript
sources are absent from the shipped image.

Both stages install from a lockfile (`bun.lock`, `uv.lock`) and both base images are pinned
by digest, so rebuilding a commit produces the same dependency set. `--no-dev` keeps pytest,
ruff and mypy out of the runtime image, which runs as **uid 1000, non-root**.

Both stages are Alpine, which sets a bar for new Python dependencies. A C-extension package
with no musllinux wheel does not fail politely: uv tries to build it from source and dies
for want of a compiler, in CI, at image-build time.

## Startup sequence

`main.py` runs this at import, before the app object exists:

1. `validate_secret_key()`: **refuse to boot** outside `APP_ENV=dev` if `SECRET_KEY` is a
   shipped placeholder or shorter than 32 bytes. With the example key every session token is
   forgeable by anyone who has read the repository. The alternative to failing loudly is an
   app that looks healthy while being impersonable.
2. `ensure_data_dirs()`: create `DATA_DIR/covers` if missing.
3. `validate_auth_config()`: **refuse to boot** on an auth setup that would silently
   misbehave, mainly an `LDAP_BIND_DN` with no bind password. See [security.md](security.md).
4. `ensure_schema()`: create or migrate the database with Alembic (see below).
5. `seed_tags()`: insert any predefined tag that is missing.

Steps 2 to 5 are idempotent, so a restart is always safe and a fresh volume
self-initialises. There is no bootstrap command.

`assert_unique_operation_ids()` runs immediately after the routers are registered and fails
startup if two handlers share a name. [decisions.md](decisions.md) covers why that matters,
and how its first version managed to check nothing.

### Migrations

Schema changes go through **Alembic** (`backend/migrations/`), run automatically at startup
by `backend/schema.py`. `create_all()` adds new *tables* but never new *columns or indexes
on existing ones*, so anything added after a release needs a migration.

`ensure_schema()` handles three cases, and the middle one is the awkward part:

| The database is | What happens |
|---|---|
| Empty | Create everything, stamp it at head |
| Pre-Alembic (real tables, no `alembic_version`) | **Stamp the baseline, then upgrade.** Running the baseline would try to create tables that already exist |
| Already managed | Upgrade to head |

Two details that cost time to find:

- **`render_as_batch=True`.** SQLite cannot `ALTER TABLE` to add or change a constraint;
  batch mode rebuilds the table instead. Without it most non-trivial migrations fail on the
  only database this app uses.
- **Alembic's `fileConfig()` replaces process-wide logging.** Running a migration in-process
  at startup silently reconfigured the application's own loggers. `env.py` honours a
  `configure_logger` attribute so the app can suppress it. The symptom was a `caplog`
  assertion going quiet, not an error.

The unique index on `user_books (user_id, book_id)` deduplicates existing rows first.
Nothing prevented duplicates before, so creating it would otherwise fail on any real
database. It is an *index* rather than a constraint for the batch-mode reason above.

## State and persistence

Everything mutable lives under `DATA_DIR`:

```
$DATA_DIR/
├── library.db          SQLite: all seven tables
└── covers/
    ├── 12.jpg          uploaded cover, named by book id
    └── login_bg.png    the admin-set login background
```

Backing up means copying that directory. There is no cache and no external service to
keep in step.

Cover files are named by book id, so a book has at most one uploaded cover and re-uploading
replaces it. The handler deletes any existing file with a different extension first, or
`12.jpg` and `12.png` could both exist and which one won would depend on lookup order.

SQLite is a fit here rather than a stopgap: a handful of family members making occasional
writes. The one thing to know is that `check_same_thread` is disabled, because FastAPI runs
synchronous endpoints in a worker thread pool, so the session is created on one thread and
used on another.

## Authentication modes

`AUTH_MODE` picks one of three backends (`backend/auth_backends.py`). It is an environment
variable, so a deployment chooses without a code change, and `local` is the default.

| Mode | Where identities live | The login screen |
|---|---|---|
| `local` | This app's `users` table | Shown |
| `ldap` | A directory; accounts are provisioned there | Shown, credentials are checked against the directory |
| `proxy` | Whatever the upstream proxy asserts in headers | **Not shown** |

`ldap` binds twice: a service account searches for the user, then the app rebinds as that
user to verify the password. It upserts a local row so books, notes and loans still have
something to point at, and re-applies group membership on every sign-in, so revoking admin
in the directory takes effect at the next login rather than never.

`proxy` is the mode with a sharp edge. It trusts request headers, which is safe only behind
a proxy that sets them and strips incoming ones. The frontend knows which mode is running
and drops its login form entirely under `proxy`.

## Runtime settings

Some things are configured by an admin in the app rather than by an environment variable
and a restart: the Google Books toggle and API key, the Goodreads lookup toggle, and the
default language. They live in a `settings` table behind `backend/settings_store.py`.

The split is deliberate. **Environment** holds what a deployment decides and what must be
right before the app can serve a request: the secret key, the auth mode, the data directory.
**The settings table** holds what a family decides and may change on a Tuesday.

`GET /api/settings/features` exposes only the flags, publicly, because the login page is
localised and needs the default language before anyone has a token. The full record,
including the masked API key, is admin-only.

Two flags describe Google Books rather than one. `google_books_enabled` is the admin's
toggle; `google_books_ready` is whether it will actually work, meaning the toggle is on
**and** a key exists. The UI needs the second to decide between offering a control and
greying it out, because a toggle with no key behind it produces a button that can only ever
400. Neither reveals the key.

**The key has two possible homes, and the environment wins.** `GOOGLE_BOOKS_API_KEY` in the
environment overrides anything stored, cannot be edited through the app, and causes a write
attempt to be **refused rather than ignored**: silently accepting a value that does nothing
would leave an admin believing they had changed the key. The stored value is left in place
rather than deleted, so unsetting the variable restores it.
`settings_store.google_books_api_key()` is the single place that resolves the precedence.

## Query cost

Listing endpoints are paginated and serialise a page in a **constant** number of queries.
`active_loan` and `my_status` are not columns: they are computed per request and depend on
who is asking. The obvious implementation queries for each of them per book, which is what
this used to do, and listing 25 books cost 53 SELECTs (`1 + 2N`). Both are now fetched once
per page, so a page costs about 6 statements whether it holds 1 book or 100.

If you add another per-request field to `BookOut`, batch it the same way in
`_books_to_out()` rather than reaching for it inside the loop.

## Error responses

`errors.py` content-negotiates: a browser navigating to a non-API path gets a styled HTML
page from `templates/error.html`, anything else gets `{"detail": ...}`. A catch-all handler
turns an unhandled exception into a generic 500. The traceback is logged and **never**
returned: it names internal paths and can quote request data back to whoever triggered it.

The handlers are registered against **Starlette's** `HTTPException`, not FastAPI's subclass.
Routing failures (an unmatched path, a method not allowed) are raised by Starlette itself as
the base class, so a handler bound only to the subclass never sees them and every mistyped
URL falls back to a bare JSON 404.
