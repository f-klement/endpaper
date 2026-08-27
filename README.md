# Endpaper

[![license](https://img.shields.io/github/license/f-klement/endpaper)](LICENSE)
[![release](https://img.shields.io/github/v/tag/f-klement/endpaper?label=release)](https://github.com/f-klement/endpaper/tags)
[![docker hub](https://img.shields.io/docker/v/fklement/endpaper?label=docker%20hub&logo=docker)](https://hub.docker.com/r/fklement/endpaper)
[![docker pulls](https://img.shields.io/docker/pulls/fklement/endpaper)](https://hub.docker.com/r/fklement/endpaper)
![languages](https://img.shields.io/badge/languages-DE%20%7C%20EN-blue)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-buy%20me%20a%20coffee-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/fklement)

A self-hosted catalogue for the books you share.

Built for a household's shelves and for the library or archive that has outgrown a
spreadsheet. Scan a barcode, get a real bibliographic record, and know who has what across
the people and places that share it.

Like Endpaper or find it useful? Offer me a coffee. It helps pay for the public
server that lets two copies of Endpaper reach each other. All features are free
either way.

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
- **Barcode scanning**: point your phone camera at a book's barcode, or type the ISBN
- **Auto metadata**: title, author, publisher, page count, language and cover art, merged
  from five catalogues (the German National Library, K10plus, the Austrian National
  Library, Open Library, Google Books).
  A catalogue's Dewey number is kept and read as a suggested tag, so a German record and an
  English one suggest the same one
- **Covers are downloaded and served from here**, not linked to somebody else's server, so
  a shelf does not go blank when an image service moves a URL. Settings has a button that
  fetches the ones already missing, and your browser never tells a third party which books
  the library holds
- **Library import**: bring a library across from Goodreads, LibraryThing, StoryGraph,
  Libib or Openreads. The columns are worked out for you and shown before anything is saved
- **Per-book privacy**: a book can be yours alone inside a shared library catalogue.
  Nobody else sees it, in listings, in search, in stats or by guessing a URL
- **Reading status**: per-person "unread / want to read / reading / read / did not finish",
  with ratings, notes and the dates you started and finished. A book you gave up on keeps
  the date you started it and is never counted as finished
- **Quotes**: copy out a passage worth keeping, with the page it is on and a line about
  why. Every quote the library can see is on one page, newest first
- **More than one copy**: two paperbacks of the same title are two objects, each with its
  own shelf, condition, price and loan. Scanning a book you already own still asks before
  it adds anything, so a mis-scan is caught and a real second copy is one more press
- **Collections**: split the shelf the way your library already does, physical from
  ebook, kept from sold, yours from mine. A book is in one or in none, and filing it
  changes nothing about who can see it: that is still up to whether it is private
- **Loan tracking**: record who borrowed what, set a due date, and see what is overdue.
  The borrower does not need an account: lend to a neighbour by typing their name
- **Overdue reminders**: Endpaper can send a digest of every overdue loan on a schedule
  you set, by email, to a Telegram chat, or to a webhook you choose (signed, so the
  receiver can check it came from here). Switch on as many as you like; they all carry the
  same list. Private books are never included: every one of those goes to a place with no
  single account behind it
- **Three ways to look at it**: a grid of covers whose cards fold out for the details, a
  dense list of one line per book, or a table of twenty one metadata columns. Your choice
  is remembered in your browser
- **Backup and restore**: download the whole library, covers included, and put it back
- **Search and filters**: by title, author, ISBN, tag, series, shelf location or format
- **Author pages**: everybody your shelf credits, with their books behind one click. Where
  one person has ended up under two spellings, fold them together: your books are never
  edited, and any fold can be undone
- **PWA installable**: "Add to Home Screen" on iOS and Android
- **Directory sign-in**: optional LDAP or reverse-proxy auth instead of local accounts

**That is the shape of it. The complete list, including what Endpaper
deliberately does not do**, is in [`docs/featurelist.md`](docs/featurelist.md):
no public catalogue, no offline mode, no circulation desk. Worth knowing before
you install it rather than after.

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
                  │                       ↳ Austrian National Library (fallback)
                  │                       ↳ Open Library  (fallback)
                  │                       ↳ Google Books  (needs a key)
                  │
                  │          search a title: Open Library + K10plus + DNB
                  │                       + BnF + Library of Congress
                  │                       + Austrian National Library
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
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_USE_TLS`, `MAIL_USE_SSL`, `MAIL_DEFAULT_SENDER` | none, `587`, none, none, `true`, `false`, none | The seven standard mail names, for reminders sent by email. `MAIL_DEBUG` is deliberately not honoured: smtplib writes the AUTH exchange to stderr under it |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | none | For reminders sent to a Telegram chat |
| `ENABLE_OVERDUE_TICKER` | `true` | `false` stops the hourly overdue digest. Set it when running more than one web process, or when driving `POST /api/loans/overdue/notify` from cron instead |
| `SERVE_FRONTEND` | `true` | `false` runs the API without mounting the compiled frontend. For a host with no reader; an unmatched path is then a plain 404, because there are no client routes to serve the shell for |

**Where a credential lives.** By default an admin pastes it into Settings and it is stored
in the database. Setting the matching environment variable instead hands that job to the
deployment: the environment value **wins**, the field in Settings is greyed out, and the
app refuses to overwrite it rather than accepting a change that would be undone at the next
restart. Either way it is never shown again once set. This holds for
`GOOGLE_BOOKS_API_KEY`, the seven `MAIL_*` names and the two `TELEGRAM_*` ones alike.

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
