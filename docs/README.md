# Developer documentation

The top-level [`README`](../README.md) covers running and operating Endpaper. These
pages are for changing it.

| Document | What it covers |
|---|---|
| [featurelist.md](featurelist.md) | What the app does today, and what it deliberately does not |
| [architecture.md](architecture.md) | How the pieces fit: the single-container model, request routing, the build |
| [data-model.md](data-model.md) | The thirteen tables, the relationships, and the privacy rule that every query must honour |
| [api.md](api.md) | Every endpoint, its auth requirement, and the status codes it returns |
| [theming.md](theming.md) | The seven palettes and the rule that generated them, the sixteen wallpapers and the rule that admits them, the picker, and where an appearance is stored |
| [frontend.md](frontend.md) | Component and page layout, state handling, the typed API client |
| [security.md](security.md) | The authorization model, rate limiting, uploads, headers, and the known limits |
| [testing.md](testing.md) | How the mirrored test tree works and the conventions to follow when adding tests |
| [legend.md](legend.md) | The library science vocabulary this codebase borrows: the catalogues, MARC, the classification and authority schemes, and the codes inside a record. |
| [decisions.md](decisions.md) | Choices that look odd until you know why. Read before "fixing" one. |

## Orientation

```
endpaper/
├── backend/              FastAPI application
│   ├── main.py           app wiring, tag seeding, the ad-hoc migration
│   ├── serialisation.py  assembling BookOut, and the per-request fields
│   ├── config.py         environment-driven settings + the startup secret guard
│   ├── dependencies.py   book access control and pagination
│   ├── models.py         ORM models and the visible_to() predicate
│   ├── schemas/          request/response contracts, one module per domain
│   ├── auth.py           password hashing and JWTs
│   ├── auth_backends.py  local / LDAP / proxy identity sources
│   ├── settings_store.py runtime settings (feature flags, the API key)
│   ├── isbn.py           parsing, validation, ISBN-10 to ISBN-13
│   ├── ddc.py            Dewey headings, and the divisions that suggest a tag
│   ├── google_books.py   metadata lookup, search and the gap-filling merge
│   ├── goodreads.py      reading a CSV export
│   ├── schema.py         Alembic runner: create, adopt or upgrade
│   ├── migrations/       Alembic revisions
│   ├── ratelimit.py      the login/registration limiter
│   ├── uploads.py        content-sniffed image validation
│   ├── errors.py         content-negotiated error responses
│   ├── middleware.py     security headers
│   ├── routers/          one module per domain
│   └── tests/            mirrors backend/, see its COVERAGE.md
├── frontend/             React PWA
│   ├── src/
│   │   ├── api/          mutator, query client, generated/ (Orval output)
│   │   ├── app/          shell: routing, providers, top bar
│   │   ├── components/   general dumb components only
│   │   ├── i18n/         English and German message catalogues
│   │   ├── lib/          pure helpers: ISBN parsing, Goodreads URLs
│   │   └── pages/        one folder per page, with its own hooks/types/components
│   └── tests/            mirrors frontend/src/, see its COVERAGE.md
└── docs/                 you are here
```

## The shortest useful summary

One container. FastAPI serves both the JSON API and the compiled React bundle, so there
is no CORS problem in production and no second web server. Authentication is a stateless
JWT in `localStorage`. Storage is a single SQLite file plus a directory of uploaded cover
images, both under `DATA_DIR`. Book metadata is fetched on demand from the German
National Library and K10plus together, with Open Library, the Austrian National Library
and Google Books as fallbacks. Google Books needs a key you supply, so a stock install
runs the other four.

The frontend's API client and its React Query hooks are **generated** from the backend's
OpenAPI schema, so the two halves cannot drift apart silently. Access to a book is decided
in one place, `backend/dependencies.py`, and the rules are in [security.md](security.md).

Nothing in the stack requires a network connection except the metadata lookup, and
nothing in the test suite requires one at all.
