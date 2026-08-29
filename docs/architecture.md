# Architecture

## One container, two languages

The deployed artifact is a single image. FastAPI owns port 8000 and serves three things:

| Path prefix | Served by | Notes |
|---|---|---|
| `/api/*`, `/auth/*` | FastAPI routers | The JSON API |
| unmatched `/api/*`, `/auth/*` | a fallback router | JSON 404, see below |
| `/covers/*` | a FastAPI router | Uploaded cover images, from `DATA_DIR/covers` |
| `/api/healthz` | a FastAPI route | Liveness and readiness. Runs a query **and** stats the data directory under its own timeout |
| everything else | `StaticFiles(html=True)` | The compiled React bundle |

`/covers` is a **router, not a `StaticFiles` mount**, and that is a security fix rather
than a stylistic choice. A mount has no dependencies, so nothing authenticates or
authorizes it, and cover filenames are the book id: any member could read another
member's private book cover by counting. `routers/covers.py` applies the same
`visible_to()` rule the rest of the API does. Do not turn it back into a mount.

Mount order in `main.py` is load-bearing. The SPA is mounted **last**, at `/`, so every
router wins over it.

**`SERVE_FRONTEND=false` skips that mount**, leaving the API on its own. The shipped image
always contains `static/`, so absence never happens in production and this is the only way
to ask for it. It is one flag on one image rather than a second image: the compiled files
sit on disk unused. With it set, the whole last row of the table above is gone and an
unmatched path is a plain 404 rather than the shell. That is correct rather than a
regression: the fallback below exists so a *client route* survives a refresh, and a host
serving no frontend has no client routes.

**`html=True` alone does not make it a catch-all**, and believing it did was a real bug:
Starlette serves `index.html` for `/` and for a directory, and answers anything else 404.
Measured in the running container, with a valid session, `/book/12`, `/settings` and
`/quotes` were all 404, so a bookmark, a refresh anywhere but home, and a shared link to a
book were all broken. `CachePolicyStaticFiles.get_response` is what actually serves the
shell for an unmatched path, under three conditions: not an API path, a request that
accepts `text/html` (a navigation, not a `fetch`), and not under `assets/`. The last two
are why a missing hashed chunk still fails cleanly as a 404 instead of arriving as HTML
inside a script tag.

The covers router is registered before the mount, or cover requests would be answered with
the shell.

Between the routers and the mount sits a fallback matching `/api/{rest:path}` and
`/auth/{rest:path}`, returning a JSON 404. Its job is the **body**, not the status: without
it an unknown API path reaches the SPA mount, which refuses it the shell (`wants_html`
excludes API prefixes) and 404s, but a `fetch()` would then get this app's HTML error page
rather than the JSON every other failure returns. It is also the second of the two guards
that stop an API typo becoming a 200 with HTML in it, which is what it was written for.

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
Stage 1  python:3.14-alpine  compile YAZ                    →  /opt/yaz-runtime
Stage 2  oven/bun:alpine     bun install --frozen-lockfile  →  bun run build  →  dist/
Stage 3  python:3.14-alpine  uv sync --frozen --no-dev  +  COPY --from=stage2 dist ./static
                                                       +  COPY --from=stage1 /opt/yaz-runtime
```

Only the compiled assets cross from stage 2, so Bun, `node_modules` and the TypeScript
sources are absent from the shipped image.

Both stages install from a lockfile (`bun.lock`, `uv.lock`) and both base images are pinned
by digest, so rebuilding a commit produces the same dependency set. `--no-dev` keeps pytest,
ruff and mypy out of the runtime image, which runs as **uid 1000, non-root**.

Every stage is Alpine, which sets a bar for new Python dependencies. A C-extension package
with no musllinux wheel does not fail politely: uv tries to build it from source and dies
for want of a compiler, in CI, at image-build time.

### The Z39.50 client library

Stage 1 compiles **YAZ**, IndexData's Z39.50 implementation, because national library
catalogues speak Z39.50 and nothing else reaches several of them. Six of the eight targets
surveyed run YAZ as their server.

**What uses it.** `backend/z3950.py` is the transport and `backend/z3950_provisional.py`
is the client behind its seam, binding `libyaz.so.5` through `ctypes`. The client is
explicitly provisional: the route was not settled when the transport was written, and the
seam exists so that changing it is a change to one function. Nothing in the metadata source
chain reaches either module yet, so a running deployment loads the library and asks no
target anything.

**Alpine packages no YAZ.** Checked across edge, v3.22, v3.21 and the pinned base's own
3.24.1, in main, community and testing: no `yaz`, no `yaz-dev`. So it is either compiled or
the base image changes, and the base image is the expensive half: `python:3.14.7-slim` is
41.4 MB compressed against alpine's 16.9 MB, so moving to Debian for a packaged `libyaz5`
costs 24.5 MB before YAZ is installed at all, and buys a larger scan surface against a
release gate that refuses a fixable HIGH. Compiling costs about a minute, once.

It compiles clean against musl with no patches, which is a narrower claim than it sounds:
configure and make complete, which is not the same as the sources being musl-correct.
Upstream 5.36.0 carries a fix, "expose gethostbyaddr with `_GNU_SOURCE`", that a clean
build would not have revealed.

What the runtime image pays, measured on the pinned base with `du -sk /` before and after,
Alpine 3.24.1, package count 30 to 32 to 40:

| | |
|---|---|
| `libxml2` and `libxslt` | 1,384 KiB |
| `gnutls`, plus nettle, gmp, p11-kit, libtasn1, libunistring, brotli-libs and libidn2 | 7,704 KiB |
| `/opt/yaz` itself, stripped: `libyaz.so.5` and `yaz-client` | 1,844 KiB |
| | **10,932 KiB** |

`gnutls` and the seven packages behind it are **70% of that**, 85% of the package cost
alone, and buy Z39.50 over TLS, which no surveyed target uses: every one answers plaintext.
Removing them is two edits rather than one, `./configure --without-gnutls` and dropping
`gnutls` from the runtime package line, and it is a capability decision rather than a build
tidy-up.

**The size is not the cost. The advisory stream is.** The three libraries and everything
they pull in carry **94 distinct CVE ids** in Alpine's security database: 52 against the
gnutls group, of which gnutls alone accounts for 36, and 42 against libxml2 and libxslt.
Counted at two scopes, v3.24 main alone and v3.24 with v3.21 and v3.19 across main and
community, which agree. They land on the scan that blocks a release, which refuses a
fixable HIGH or CRITICAL, so each one is a release held until the base image carries the
fix.

**All three are equally optional to the build**: YAZ offers `--with-xml2` and `--with-xslt`
beside `--with-gnutls`, and a build without any of them links none of them. So the 52 is
the price of TLS only against a judgement, not against a build constraint. The judgement is
about record handling: the catalogue records this application exists to read are parsed and
converted through libxml2 and libxslt, so dropping those would cost a feature, while
dropping gnutls would cost an encrypted transport that no surveyed target offers. That is
the argument for treating the 52 as separable and the 42 as not, and it is a claim about
what this application needs rather than about what YAZ requires.

**Nothing watches the library itself.** `/opt/yaz/lib/libyaz.so.5` is compiled here rather
than installed from a package, so no package database lists it and the image scanners
enumerate nothing for it: they read package manifests and lockfiles, and a C library built
from a tarball appears in neither. A YAZ advisory reaches this repository only through the
dependency bot watching upstream's release tags, and the version and its hash are then
bumped by hand together.

**What that TLS is worth is worth knowing.** YAZ performs no certificate verification in
any released version: `verify_peers`, `set_x509_system_trust`, `session_set_verify_cert`,
`set_x509_trust_file` and `GNUTLS_CERT` appear nowhere in its `src/` or `client/`, on
5.35.1 or on 5.37.3. It allocates certificate credentials and initialises a client session
without ever loading a trust store. An `ssl:` target is therefore encrypted against a
passive listener and not authenticated against anyone able to answer for the address.

**The install prefix is load bearing.** libtool records `/opt/yaz/lib` as `yaz-client`'s
RUNPATH, which is why the binary resolves its library with no `LD_LIBRARY_PATH` and no
symlink into `/usr/lib`, and why the tree has to land at exactly that path. A Python client
should load the library by absolute path for the same reason.

#### The compile does not run on every build

`docker/build-yaz.sh` stamps the tree it produces with a **build id** naming the three
things that decide what gets built: the version, the sha256 of the tarball, and the sha256
of the recipe itself. Handed a tree already carrying that id it does nothing; handed
anything else it compiles. So the build stage can take a prebuilt image as its base and an
ordinary build becomes a layer fetch.

**The id deliberately names nothing about the environment**, and that is the second
attempt. It briefly carried the musl version, so the runtime stage could refuse a library
built against a different libc. That was wrong in three ways at once. The value had to be
read before the compiler was installed, and installing it can move musl, because
`musl-dev` depends on an exact musl version. It said nothing about libxml2, libxslt or
gnutls, which libyaz also links. And it was **too strict**: measured, a YAZ compiled on
Alpine 3.24.1 against `musl-1.2.6-r2` loads and runs clean on Alpine 3.21.7 against
`musl-1.2.5-r11`, three Alpine releases apart, with `LD_BIND_NOW` set so nothing is
deferred to first call.

**That is one ordered pair, and which pair it is matters.** It runs a newly built binary
against an older libc, which is the harder direction, since symbols a new build expects
need not exist in an old library. The scenario the musl term was for is the other way
round, an older binary on a newer libc, so this result covers that case a fortiori.

So, at the strength the evidence carries: **on one pair three releases apart, in the harder
direction, a base image bump that keeps a YAZ built against the previous musl is not a
breakage.** That is a strong directional result and not a proof about every pair, and the
design does not rest on it either way. Where the ABI is compatible there is nothing to
detect; where it is not, **the load check below detects it**. What the version-and-digest
naming is worth is that the artefact is reproducible and attributable, rather than that it
averts a breakage nobody has yet been able to produce.

So the environment is not compared as a string. **It is checked by running the library**,
in the runtime stage, once its dependencies are installed: the shipped `yaz-client` is
executed and required to report the pinned version. That single line covers musl, all three
shared libraries, and the install prefix, since libtool baked `/opt/yaz/lib` into the binary
as its RUNPATH and a tree copied anywhere else cannot find itself. `LD_BIND_NOW` makes that
the whole `DT_NEEDED` closure rather than one library: everything must load and fully bind,
which is strictly more than the musl version string ever compared. **What it cannot cover is
what is loaded later by `dlopen`**, and gnutls does exactly that with p11-kit at TLS setup
time rather than at load. Moot while nothing here speaks TLS, and worth knowing before
anything does. The release smoke test
runs the same command again on the finished image, which is not duplication: the first
fails the build, in any build including somebody's own `docker build`, and the second
proves it in the artefact about to be published.

The stamp is compared once more in the runtime stage, against the tree it received. In an
ordinary build that cannot fire, because both stages inherit the same pins and copy the
same recipe file, so the two ids are equal by construction. It is a check on where the
`COPY` points, and narrower than that sounds in the safe direction: it does **not** fire
when the `COPY` points at a different subset of the same build, because the recipe writes
the same id into both `/opt/yaz` and `/opt/yaz-runtime`. Copying the full tree instead of
the runtime subset would pass this check and silently ship the headers, the documentation
and the two libraries the subset exists to leave out. It is not the guarantee that the
library works.

All of this is in this repository and in the published image's own Dockerfile. The build
pipeline additionally names its prebuilt image after the same facts so it knows when to
rebuild one, but that is a way of not paying the minute rather than a safety property.

The version and its hash are bumped by hand, together. The hash is **trust on first use**:
IndexData publish no signature and no checksum file beside the release, so it records the
bytes one fetch saw and pins them against a later substitution, which is the threat it can
actually address.

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
├── library.db          SQLite: every table
└── covers/
    ├── 12.jpg          uploaded cover, named by book id
    └── login_bg.png    the admin-set login background
```

Backing up means copying that directory. There is no cache and no external service to
keep in step.

Cover files are named by book id, so a book has at most one uploaded cover and re-uploading
replaces it. The handler deletes any existing file with a different extension first, or
`12.jpg` and `12.png` could both exist and which one won would depend on lookup order.

SQLite is a fit here rather than a stopgap: a handful of member making occasional
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
**The settings table** holds what a library decides and may change on a Tuesday.

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
`active_loan`, `my_status` and the reading-progress fields are not columns: they are
computed per request and depend on who is asking. The obvious implementation queries for
each of them per book, which is what this used to do, and listing 25 books cost 53 SELECTs
(`1 + 2N`). Each is now fetched once per page instead.

**`serialisation.books_to_out` holds the measured numbers**, and this page deliberately does
not repeat them: the count has been restated wrongly here twice, both times by someone
editing the sentence rather than measuring. The short version is that `GET /api/books` is
flat at 5 and at 25 books, and that a caller which fetches books *without*
`joinedload(Book.added_by)` pays one extra statement per distinct author, because
`BookOut` reads that relationship.

`_latest_progress` is the one to copy if a new field needs the *newest* row per book rather
than one row per book. It ranks with a window function in a single statement rather than
fetching every row and picking in Python, so a member with a long reading history costs the
same as one with none.

If you add another per-request field to `BookOut`, batch it the same way in `books_to_out()`
rather than reaching for it inside the loop. `tests/routers/test_loans.py` holds a bound on
the count, which is the thing that catches a regression here.

## Error responses

`errors.py` content-negotiates: a browser navigating to a non-API path gets a styled HTML
page from `templates/error.html`, anything else gets `{"detail": ...}`. A catch-all handler
turns an unhandled exception into a generic 500. The traceback is logged and **never**
returned: it names internal paths and can quote request data back to whoever triggered it.

The handlers are registered against **Starlette's** `HTTPException`, not FastAPI's subclass.
Routing failures (an unmatched path, a method not allowed) are raised by Starlette itself as
the base class, so a handler bound only to the subclass never sees them and every mistyped
URL falls back to a bare JSON 404.
