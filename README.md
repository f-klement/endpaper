# Endpaper

A self-hosted PWA for cataloging your family's physical book collection.

## Quick Start

Run the published image. No build step, nothing to clone:

```bash
curl -O https://raw.githubusercontent.com/f-klement/endpaper/main/docker-compose.deploy.yml
# edit SECRET_KEY first: it signs the login tokens
docker compose -f docker-compose.deploy.yml up -d
```

Images are on Docker Hub as [`fklement/endpaper`](https://hub.docker.com/r/fklement/endpaper):
`:latest` tracks the newest release; every release also gets an immutable `:vX.Y.Z` tag.
Pin that one to decide for yourself when to upgrade. Currently amd64 only.

What changed in each release is in [CHANGELOG.md](CHANGELOG.md).

Or build from source instead:

```bash
docker compose up --build
```

Then open **server-ip:port** you set in your yml in your browser (or your local IP on your phone).

## Features

### Getting books in

- **Barcode scanning**: point your phone camera at a book's barcode, or type the ISBN
- **Rapid mode**: scan a whole shelf without stopping, review the batch, then commit it
- **Auto metadata**: title, author, publisher, page count, language and cover art, merged
  from four catalogues (the German National Library, K10plus, Open Library, Google Books)
- **Covers that are actually there**: every candidate image is fetched and checked before
  it is saved, so you get a cover rather than a broken one
- **Covers are downloaded and served from here**, not linked to somebody else's server, so
  a shelf does not go blank when an image service moves a URL. Settings has a button that
  fetches the ones already missing, and your browser never tells a third party which books
  the household owns
- **Add without a barcode**: search by title across the same catalogues and pick the
  edition, including books printed before ISBNs existed. Works with no API key
- **Five languages resolve**: English, German, French, Spanish and Portuguese titles, from
  the national catalogues that actually hold them
- **Library import**: bring a library across from Goodreads, LibraryThing, StoryGraph,
  Libib or Openreads. The columns are worked out for you and shown before anything is saved

### Living with a shared shelf

- **Per-book privacy**: a book can be yours alone inside a shared household catalogue.
  Nobody else sees it, in listings, in search, in stats or by guessing a URL
- **Reading status**: per-person "unread / want to read / reading / read / did not finish",
  with ratings, notes and the dates you started and finished. A book you gave up on keeps
  the date you started it and is never counted as finished
- **Reading progress**: record the page you reached, or a percentage for an audiobook, as
  often as you like. It is a log, not one number, so it can say how much you read in March
  as well as where you are now. Recording a page starts the book for you
- **On the shelf or not**: what you own, tracked separately from what you have read
- **Loan tracking**: record who borrowed what, set a due date, and see what is overdue.
  The borrower does not need an account: lend to a neighbour by typing their name
- **Overdue reminders**: Endpaper can POST a digest of every overdue loan to a webhook you
  choose, on a schedule you set, signed so the receiver can check it came from here.
  Private books are never included: a webhook goes to a channel with no account behind it
- **Multiple accounts**: the first account is admin, whichever way you sign in

### Keeping it tidy

- **Series gaps**: which volumes of a series you are missing, worked out for you
- **Duplicate detection and merge**: fold two records into one, keeping the best of both
- **Undo a delete**: deleted books go to a trash and come back whole, with their notes,
  tags, loans and reading history
- **Bulk edits**: tag, re-shelve, set a status or delete a whole selection at once
- **Two ways to look at it**: a grid of covers whose cards fold out for the details, or a
  table of nineteen metadata columns. Your choice is remembered in your browser
- **Backup and restore**: download the whole library, covers included, and put it back

### Finding things again

- **Tags**: 105 curated ones in three categories, plus any your household invents
- **Search and filters**: by title, author, ISBN, tag, series, shelf location or format
- **Saved views**: keep a filter combination under a name, including a wishlist of books
  you want but do not own
- **Statistics**: what is on the shelf, who reads what, what got finished when, and how
  many pages you read each month

### Running it

- **PWA installable**: "Add to Home Screen" on iOS and Android
- **German and English**: switch in Settings; new visitors follow their browser
- **Seven palettes and ten wallpapers**: pick a palette, light or dark, and a background
  pattern, or a different one every visit. Chosen on a screen of its own, where the preview
  is your own shelf rather than invented sample books
- **Light and dark**: follows the system unless you say otherwise, and every part of the
  look is saved to your account rather than to the browser, so it follows you between
  devices
- **Directory sign-in**: optional LDAP or reverse-proxy auth instead of local accounts
- **Health endpoint**: `GET /api/healthz` for container probes. It runs a query and stats
  the data directory under its own timeout, so it fails when the database or the storage
  does rather than when the web server does

## Local Development

Two processes: the API on `:8000` and the Vite dev server on `:5173`, which proxies
`/api`, `/auth` and `/covers` across to the API. Run them in separate terminals.

**Backend**, with [uv](https://docs.astral.sh/uv/) and Python 3.14:
```bash
cd backend
uv sync                       # creates .venv and installs from uv.lock
DATA_DIR=./data uv run uvicorn main:app --reload
```
`DATA_DIR` decides where the SQLite file and uploaded covers live. It defaults to
`/app/data` (the path inside the container), so set it when running outside one.
Interactive API docs are then at `http://localhost:8000/docs`.

**Frontend**, with [Bun](https://bun.com) 1.3:
```bash
cd frontend
bun install
bun run dev
```

### Testing

Tests live in a mirror tree, never beside the file under test. `backend/tests/` mirrors
`backend/`; `frontend/tests/` mirrors `frontend/src/`. So `backend/routers/books.py` is
tested at `backend/tests/routers/test_books.py`.

What each suite covers is written down: [`backend/tests/COVERAGE.md`](backend/tests/COVERAGE.md)
and [`frontend/tests/COVERAGE.md`](frontend/tests/COVERAGE.md).

```bash
cd backend   && uv run pytest              # pytest, no network access
cd frontend  && bun run test               # vitest + Testing Library
```

Useful variants:

| Command | What it does |
|---|---|
| `uv run pytest --cov` | Backend coverage report |
| `uv run ruff check .` | Backend lint |
| `uv run mypy .` | Backend type check (strict) |
| `bun run api:generate` | Regenerate the API client from the backend schema |
| `bun run test:watch` | Re-run frontend tests on change |
| `bun run test:coverage` | Frontend coverage report |
| `bun run typecheck` | TypeScript, no emit |

Neither suite touches the network or a real database. The backend tests run against a
throwaway SQLite file and stub outbound calls; the frontend tests stub `fetch` outright.

### Dependency security

`bun install` screens every incoming package through Bun's security-scanner API
(`frontend/bunfig.toml`) before any package code executes. A critical finding aborts the
install. No account needed.

## Production Notes

- Change `SECRET_KEY` before deploying. It signs the login tokens.
- Camera access on phones requires HTTPS. Deploy behind Caddy or nginx with TLS.
- Data lives in `./data/library.db` (bind-mounted). Back up by copying it.
- `ALLOW_REGISTRATION=false` closes signups without affecting existing accounts.

## Architecture

Single Docker container: FastAPI (Python 3.14) serves the REST API and the compiled
React 19 PWA as static files. SQLite for storage. The multi-stage build compiles the
frontend with Bun, then copies only the built assets into the Python image. Bun and
`node_modules` are not in the shipped image.

```
Phone (PWA) ──► FastAPI ──► scan an ISBN:  DNB + K10plus  (together, merged)
                  │                       ↳ Open Library  (fallback)
                  │                       ↳ Google Books  (needs a key)
                  │
                  │          search a title: Open Library + K10plus + DNB
                  │                       + BnF + Library of Congress
                  │                       + Google Books (needs a key)
                  │                       ranked, denoised and merged here
              SQLite DB (./data/)
```

Environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev placeholder | Signs the JWTs. **Change this.** |
| `DATABASE_URL` | `sqlite:///$DATA_DIR/library.db` | SQLAlchemy URL |
| `DATA_DIR` | `/app/data` | SQLite file + uploaded covers |
| `ALLOW_REGISTRATION` | `true` | `false` closes new signups |
| `APP_ENV` | `prod` | `dev` relaxes the startup secret-key check |
| `AUTH_MODE` | `local` | `local`, `ldap` or `proxy`. See below. |
| `GOOGLE_BOOKS_API_KEY` | none | Supplies the key from the deployment instead of the settings screen |
| `ENABLE_OVERDUE_TICKER` | `true` | `false` stops the hourly overdue digest. Set it when running more than one web process, or when driving `POST /api/loans/overdue/notify` from cron instead |

**Where the Google Books key lives.** By default an admin pastes it into Settings and it is
stored in the database. Setting `GOOGLE_BOOKS_API_KEY` instead hands that job to the
deployment: the environment value **wins**, the field in Settings is greyed out, and the
app refuses to overwrite it rather than accepting a change that would be undone at the
next restart. Either way the key is never shown again once set.

**Directory sign-in.** `AUTH_MODE=ldap` checks credentials against a directory instead of
this app's own table. Accounts are created here on first sign-in, so books and notes still
have an owner. `AUTH_MODE=proxy` takes the identity from headers set by a reverse proxy and
hides the login form entirely.

**Test accounts.** In any of the three modes, an admin can create a local account with a
password in Settings and switch into it, which is how you see the library the way an
ordinary member sees it when the directory owns everybody's password. Under `ldap` and
`proxy` they are not offered at the login screen, because that screen offers nothing at
all there; under `local` one signs in through the ordinary form like any other account.
They are never admins, and they are the only accounts a switch will accept: nobody can be
signed in as a real member this way.

| Variable | Default | Purpose |
|---|---|---|
| `LDAP_URL` | none | e.g. `ldaps://directory.example:636`. Required for `ldap` |
| `LDAP_USER_BASE_DN` | none | Where to search for accounts. Required for `ldap` |
| `LDAP_BIND_DN` | none | Service account for the search. Leave empty to search anonymously |
| `LDAP_BIND_PASSWORD` | none | **Required if `LDAP_BIND_DN` is set.** The app refuses to start otherwise. |
| `LDAP_USER_FILTER` | `(&(objectClass=person)(uid={username}))` | `{username}` is substituted and escaped |
| `LDAP_USERNAME_ATTRIBUTE` | `uid` | The attribute holding the login name |
| `LDAP_ADMIN_GROUP` | none | Members of this group get admin, re-checked at each sign-in |
| `LDAP_START_TLS` | `false` | Upgrade a plain connection with StartTLS |
| `PROXY_USER_HEADER` | `Remote-User` | Header naming the signed-in account |
| `PROXY_GROUPS_HEADER` | `Remote-Groups` | Comma-separated group list |
| `PROXY_ADMIN_GROUP` | none | Membership of this group grants admin |

> **`AUTH_MODE=proxy` trusts headers.** Safe only behind a proxy that sets them itself
> *and strips any arriving from the client*. Exposed directly, anyone can claim to be admin.
> An `LDAP_BIND_DN` with a blank password is refused at startup for a similar reason: most
> directories accept it as an anonymous bind and quietly return nothing.

**Google Books and Goodreads** are configured in the app, not here: sign in as an admin
and open Settings. The API key is stored in the database and never shown again after saving.

Design notes (data model, the privacy rule, auth, testing) are in [`docs/`](docs/).
