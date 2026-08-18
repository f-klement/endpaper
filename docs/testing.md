# Testing

Two suites, one rule: **tests never sit beside the code they test.** Each mirrors its
source tree in a separate directory.

```
backend/                          backend/tests/
├── auth.py                 →     ├── test_auth.py
├── dependencies.py         →     ├── test_dependencies.py
├── uploads.py              →     ├── test_uploads.py
└── routers/books.py        →     └── routers/test_books.py

frontend/src/                     frontend/tests/
├── api/mutator.ts          →     ├── api/mutator.test.ts
├── app/components/NavBar   →     ├── app/components/NavBar.test.tsx
└── pages/Home/
    ├── hooks.ts            →         ├── pages/Home/hooks.test.ts
    └── components/         →         └── pages/Home/components/
        └── BookCard.tsx    →             └── BookCard.test.tsx
```

To find the tests for a file, take its path, swap the root, and add the test suffix. A new
source file gets a new mirrored test file in the same relative position.

Support files that mirror nothing live at the root of each tree: `conftest.py`,
`helpers.py`, `setup.ts`, `utils.tsx`, `factories.ts`.

**What each suite actually covers, area by area, with its deliberate gaps, is in
[`backend/tests/COVERAGE.md`](../backend/tests/COVERAGE.md) and
[`frontend/tests/COVERAGE.md`](../frontend/tests/COVERAGE.md).** This page is about how to
work in them.

## Running

```bash
cd backend  && uv run pytest        # 432 tests
cd frontend && bun run test         # 282 tests
```

| Command | Purpose |
|---|---|
| `uv run pytest --cov --cov-report=term-missing` | Backend coverage with unhit lines |
| `uv run pytest tests/test_dependencies.py -k private` | One file, matching tests |
| `uv run mypy .` | Type check, strict |
| `uv run ruff check . && uv run ruff format .` | Lint / format |
| `bun run test:watch` | Re-run on change |
| `bun run test:coverage` | Frontend coverage |
| `bun run typecheck` | `tsc --noEmit`, includes the test tree |

Neither suite touches the network. Both are safe to run alongside a live dev server.

## Backend

`pytest`, driving the real FastAPI app through `TestClient`. Integration tests by
preference: they exercise a route end to end against a real (temporary) SQLite database,
because that is where the interesting behaviour is: the privacy predicate, the cascades,
the status codes.

### The import-order rule in `conftest.py`

`config.py` resolves `DATA_DIR` at import, and `database.py` builds the engine at import.
So `conftest.py` sets `DATA_DIR`, `DATABASE_URL`, `SECRET_KEY` and `APP_ENV` in a
module-level block **above** any application import. That block is not stylistic: moving an
import above it points the suite at the real database.

### Fixtures

| Fixture | Gives you |
|---|---|
| `client` | `TestClient` for the app |
| `db` | A session, to arrange state directly |
| `admin` / `member` / `other_user` | Accounts, with `["headers"]` ready to pass |
| `make_book` | Creates a book via the API |
| `covers_dir` | The temporary cover directory |

`clean_database` and `reset_rate_limits` are autouse, so every test starts with empty
tables, freshly seeded tags and cleared rate-limit counters. The last matters
because the limiters are process-global, and without it a test that logs in repeatedly
would start tripping the limiter partway through the suite, with the failure depending on
ordering.

Account fixtures insert rows **directly** and mint a token rather than calling
`/auth/register`. bcrypt is intentionally slow and most tests need an account; hashing per
test cost more than the rest of the suite combined. The registration and hashing paths are
still covered end to end in `tests/test_auth.py` and `tests/routers/test_auth.py`.

The same reasoning applies to the rate-limit tests, which run against a deliberately
tightened limit (`RateLimit(max_attempts=2)`) rather than making ten real login attempts.
The configured production values are pinned separately in `TestLimitsAreSane`.

### Two settings that are load-bearing

- **`--import-mode=importlib`.** The mirror layout means `tests/test_auth.py` and
  `tests/routers/test_auth.py` share a basename. Pytest's default "prepend" mode derives
  module names from the basename, hits the collision and refuses to collect the second one.
  This flag is the direct cost of mirroring, and the fix.
- **`explicit_package_bases` + `mypy_path = "."`.** The same collision stops mypy dead:
  it aborts before checking anything at all. These two make it derive module names from the
  path instead.

### The network is stubbed

`respx` intercepts outbound HTTP, so Open Library and Google Books are never called for
real and the suite works offline.

## Frontend

Vitest in jsdom, with Testing Library.

Tests drive the **real generated hooks and the real mutator**, stubbing only `fetch`. That
keeps them honest about query keys, cache invalidation and request shapes, all of which a
mocked API module would hide.

`mockApi()` registers per-route handlers and records every request:

```ts
const api = mockApi();
api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
// …
expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({ is_private: true });
```

Anything not explicitly stubbed rejects loudly rather than reaching the network.

### Three render helpers, by how much context the subject needs

| Helper | Supplies | For |
|---|---|---|
| `renderLocalised` | Locale + router | A dumb component |
| `renderWithProviders` | Locale + router + query client | A page |
| `renderHookWithProviders` | The same, for `renderHook` | A page's hooks |

The query client has **retries off**. A retrying client makes a test asserting an error
state wait through two extra attempts.

The split is not bookkeeping. Giving a presentational component a query client in its test
blurs exactly the line the structure exists to draw: `BookCard` takes a plain object and
fetches nothing, and its test should be able to say so. Components still need the locale,
because their text is translated, and some render a `Link`.

All three **force the locale to English** rather than letting it resolve normally. Left to
detection it would follow the machine's browser language, so the same assertions would pass
here and fail on a German laptop. It is an *initial* value, not a lock, so a test can still
exercise the language switch. Pass `locale: Locale.de` to assert on the German text.

A nested `MemoryRouter` inside one of these helpers is an error in React Router 7, not a
harmless duplicate.

### Queries go through roles and labels

`getByRole("button", { name: "Sign In" })`, never `.btn-primary`. Class names are styling
and change freely; the accessible name is the contract. Several `aria-label` and
`aria-pressed` attributes in the source exist to make that possible, and improve the app
for screen readers as a side effect.

### Fake timers

Only `SearchBar` needs them, for its 300 ms debounce. Those tests drive the input with
`fireEvent` rather than `user-event`: `user-event` schedules its own async work and
deadlocks against fake timers unless the two are carefully bridged. A `change` event is
exactly what a keystroke produces there, so nothing is lost.

Everywhere else use `user-event`, which models real interaction far better.

### Mocking modules

Two are mocked wholesale: **`@zxing/library`**, because jsdom has no camera, and
**`BarcodeScanner`** itself in `ScanPage.test.tsx`, replaced by a button that emits a fixed
ISBN: that test is about the scan, lookup and confirm flow, not the camera. `useNavigate`
is mocked where a test asserts navigation.

## Conventions

- **One behaviour per test**, named as a sentence about behaviour:
  `test_export_excludes_other_users_private_books`, not `test_export_2`.
- **Comment the non-obvious ones.** Where a test encodes a trap (route ordering, SQLite's
  second-resolution timestamps, the `useQuery`-vs-`useMutation` generation hazard) that
  comment is what stops someone "simplifying" the guard away later.
- **Test the contract, not the implementation.** Status codes, response bodies, rendered
  output, request bodies.
- **Document real behaviour, even when it is a wart.**
  `test_passwords_differing_past_the_limit_collide` asserts that bcrypt ignores everything
  past 72 bytes. That is true, surprising, and better pinned than pretended away.
- **A guard that inspects nothing is worse than no guard.** `assert_unique_operation_ids()`
  fails loudly if it finds zero routes, because its first version silently checked nothing
  and read as coverage.
