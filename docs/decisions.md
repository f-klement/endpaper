# Decisions

Things that look wrong, redundant or old-fashioned until you know why. Read the relevant
entry before "fixing" one.

## Backend

### `bcrypt` directly, not `passlib`

`passlib` is unmaintained and its last release predates modern `bcrypt`, which is why the
dependency list used to pin `bcrypt==4.0.1`. That pin blocked every security update to the
library doing the actual hashing.

`auth.py` now calls `bcrypt` directly. The hash format is unchanged (passlib was only ever
delegating), so **existing passwords keep working**, proved by a regression test holding a
hard-coded pre-migration hash.

One wrinkle this exposed: bcrypt hashes at most the first 72 bytes. The C implementation
truncates silently, the Python binding raises. `auth.py` truncates explicitly, reproducing
the old behaviour rather than turning long passwords into 500s.

### Settings are functions, not module constants

`config.py` exposes `secret_key()`, `registration_enabled()` and friends rather than
constants. `ALLOW_REGISTRATION` used to be read once at import, which made it untestable
without reimporting and meant closing signups needed a restart. Reading per call costs
nothing at this scale.

`DATA_DIR` is the deliberate exception: resolved once at import, because the directory must
exist before the app starts serving from it.

### `DATA_DIR` exists at all

Paths were hard-coded to the in-container `/app/data` in three modules, which made the
backend impossible to run or test outside a container.

### `visible_to()` is a function

It must be applied by every query that returns or counts books, and a predicate retyped at
six call sites is one that will eventually be forgotten at one of them. Note the
`.is_(False)` rather than `not Book.is_private`: the latter evaluates the Column's Python
truthiness and collapses to a constant, quietly matching every row. It looks more idiomatic
and is completely wrong.

### Book access lives in dependencies, not in handlers

See [security.md](security.md). Endpoints ask for a book through `book_for_read` /
`book_for_write` / `book_for_owner` rather than fetching one and writing their own checks,
because when they wrote their own checks, fourteen of them wrote none at all.

### Login has its own schema

`LoginRequest`, not `UserCreate`. Registration's 8-character floor must not apply to
sign-in, or every account created before the policy is locked out. A 422 "too short" also
leaks that the stored password is short.

### The rate limiter is hand-rolled

Not slowapi. The useful key is the *username being attempted*, and a middleware-style
limiter cannot see it: its key function runs before the body is parsed. Full reasoning in
[security.md](security.md).

### Loans are ordered by `(loaned_at DESC, id DESC)`

The `id` tiebreak is not decorative. SQLite's `CURRENT_TIMESTAMP` has second resolution, so
two loans recorded in the same second tie and come back in whatever order the planner
chooses. Found by a test that lent two books in a row.

### `/export` is declared before `/{book_id}`

FastAPI matches in declaration order. Reversed, `/api/books/export` is a request for the
book with id `"export"`. Moving route definitions around in `routers/books.py` is not the
free reordering it appears to be.

### A unique *index*, not a unique constraint, on `user_books`

SQLite cannot add a constraint to an existing table without rebuilding it, but it can
create an index, which is applicable to a live database. It deduplicates existing rows
first, or the creation would fail.

### `generate_unique_id_function`

FastAPI's default operationId mangles the path in, so `list_books` becomes
`list_books_api_books_get` and the generated client turns that into
`useListBooksApiBooksGet()`. Using the handler name instead requires those names to be
unique, which `assert_unique_operation_ids()` enforces at startup.

That guard's first version iterated `app.routes` filtering on `APIRoute` and found
**nothing**: `include_router()` does not splice child routes in, it appends a wrapper. The
check passed while inspecting zero routes. It now descends into the wrappers and fails
loudly if it ever finds none again.

### Alembic, adopted rather than more hand-written ALTERs

Schema changes used to be hand-written steps in `migrate_schema()`. That is exactly the
failure mode migration tools exist to prevent, so Alembic runs at startup instead. The
adoption path for an existing database (stamp the baseline, then upgrade) is in
[architecture.md](architecture.md). `render_as_batch=True` is mandatory for SQLite.

### Ownership is a separate axis from read status

`books.ownership` answers "is a copy physically here"; `user_books.status` answers "has this
person read it". They are independent claims about different things: a library borrowing is
read and not owned. Collapsing them is what makes an imported reading history look like a
catalogue of possessions. `unknown` exists because a Goodreads export cannot answer the
ownership question at all, and guessing either way would assert something nobody checked.

### `categories` is joined with a semicolon, not a comma

Google's own category names contain commas ("Fiction, general"), so a comma-joined list
cannot be split back apart. `google_books.join_categories` / `split_categories` are the only
two places that know the delimiter, and the API serves the field as a **list** so no client
has to know it at all.

### The Goodreads integration is a CSV import and a link

Goodreads shut its public API to new developers in December 2020 and has issued no keys
since. There is no supported way to authenticate an account or read a shelf live, so
"connect your Goodreads account" is not an option that could be built. It is one that could
be built and never work.

### Reading dates are derived, not entered

Nobody fills in a date field. Everybody moves a book to "reading" when they start it, so
the transition is the signal. The rules and the reasons are in
[data-model.md](data-model.md); the one worth repeating is that only unset dates are
stamped, because a UI with pressable buttons makes re-selecting the current status easy.

### Series is two columns, not a table

A series has no attributes here beyond a name, and both questions asked of it are answered
by grouping on that name. A table would add a join and an orphan-cleanup problem to buy
nothing. `series_index` is a float because omnibus editions really are numbered 2.5.

### Location is free text

Nobody knows their own shelf taxonomy before they start, and a vocabulary imposed up front
is worse than a slightly untidy one that grows. `GET /api/books/locations` returns what is
actually in use, which the UI offers as suggestions, because free text with *no*
suggestions becomes six spellings of "living room" inside a week.

### Duplicate detection matches on title and author, not ISBN

The unique ISBN already makes exact repeats impossible. The case left to catch is a
hardback and a paperback, which are the same book and two legitimately different ISBNs.
Matching is deliberately lossy because it is a suggestion a person confirms, not an
automatic merge.

### Merging repoints through the ORM, not a bulk UPDATE

A bulk `UPDATE ... synchronize_session=False` leaves the session's loaded collections
stale, and the `db.delete()` that follows cascades straight through them, deleting exactly
the notes, loans and statuses just moved to the survivor. The rows are reassigned object by
object and the losers are expired before deletion.

Relatedly, the losers release their ISBN in **its own flush** before the keeper absorbs it.
Doing both in one flush puts them in a single `executemany` where the set lands before the
clear and trips the unique index.

### One bulk endpoint, not six

Every verb shares the same three steps: resolve the ids the caller may actually touch,
apply, report. Six handlers would be six copies of the permission walk, and the fifth one
added would be the one that forgot it.

### `unrated` names its correlation explicitly

`.correlate(Book)` is not decoration. When the status filter has added its own `UserBook`
join, SQLAlchemy otherwise auto-correlates `UserBook` out of the subquery too, leaving it
with no FROM clause and raising rather than filtering. Found by a test that combined the
two filters.

### Python 3.14 is a hard requirement, and PEP 649 is why

`schemas/book.py` and `schemas/loan.py` reference each other under `TYPE_CHECKING`, with
unquoted annotations naming types that do not exist at runtime. That works only because
3.14 defers annotation evaluation. On 3.13 it raises `NameError` at import.

## Frontend

### Page-centric colocation

One page goes in that page's folder, several pages in `pages/components/`, general and
domain-free in `src/components/`. See [frontend.md](frontend.md).

### Types are generated, not hand-written

`src/types.ts` used to mirror `backend/schemas.py` by hand, with nothing enforcing the
mirror. Orval now generates the DTOs from the OpenAPI schema, so a backend field rename is
a compile error rather than a runtime surprise. The generated output is committed so a
fresh clone needs no Python toolchain.

### No top-level `query` block in `orval.config.ts`

**The most dangerous configuration line in this project, by omission.** Setting one applies
to every operation including DELETE, which orval then generates as `useQuery`. A query runs
on mount and on retry, so `useDeleteBook(id)` would delete the book as soon as a component
rendered. Scope query options per operation.

### `includeHttpResponseReturnType: false`

Orval's built-in fetch client returns `{ data, status, headers }`; our mutator returns the
parsed body and throws on non-2xx. Leaving the envelope on would make every generated type
describe a shape the code never produces.

### `api/mutator.ts` throws on 401, except on the credential endpoints

It previously returned `undefined` after redirecting, so callers rendered with missing data.
Treating a 401 from `/auth/login` as an expired session also cleared the stored session and
replaced "Incorrect username or password" with "Your session has expired": wrong, and
nonsense for someone who was never signed in.

### The multipart path does not set `Content-Type`

The browser must set it itself to include the multipart boundary. Adding it by hand
produces a request the server cannot parse.

### Tailwind 4 has no config file

`tailwind.config.js` and `postcss.config.js` are gone; configuration is `@theme` in
`src/index.css` and `@tailwindcss/vite` runs the pipeline.

### `/login` is routable while signed in

So "Switch Account" can show the form without destroying the current session first.

### The scanner filters barcodes before reporting

Only Bookland EAN-13 and 10-digit ISBNs, or any barcode in view triggers a lookup.

### No i18n library

Two languages and a flat key set. The whole mechanism is an object lookup plus placeholder
substitution; a library would add a dependency, a bundle and a plural-rules engine nothing
here needs. The one property worth having is kept by the type system instead: `de.ts` is
typed as `Messages`, so a missing translation is a compile error.

### No dashes as punctuation, anywhere

Not in UI strings, docs or comments. Em and en dashes do not survive translation cleanly,
they are awkward on the phone keyboards this app is mostly used from, and German typography
uses them differently. Use a colon, a comma, parentheses or a full stop. A test asserts it
for the message catalogues, because a dash is easy to paste in and invisible when skimming.

Related: translate **whole phrases, never fragments**. `"Loaned to {to} by {by}"` is one key
rather than three concatenated pieces, because German does not keep that word order.

### The Google Books search is submitted, not debounced

The library search box debounces; this one does not. Each search is a billed call against
somebody's Google Books quota, and typing "the hobbit" would spend ten of them to answer one
question. Different cost, different interaction.

### `mutate`, not `mutateAsync`, for fire-and-forget writes

`mutateAsync` rejects on failure, so `void save(...)` leaves an unhandled promise rejection
in the console on every failed request. The error is already in the mutation's state, which
is what the UI renders. Found by a vitest unhandled-error report on an otherwise passing
test.

### A selected card is a checkbox, not a disabled link

In selection mode `BookCard` renders as `role="checkbox"` rather than as a `Link` with its
navigation suppressed. At that moment it genuinely is a checkbox, and announcing it as a
link that goes nowhere is worse than useless to anyone using a screen reader.

### The login tabs have `aria-label`s that differ from their text

The tab and the submit button below it show the same words ("Sign In"). Without distinct
accessible names a screen reader announces two identical buttons and neither says which one
switches the form. The labels say "Switch to sign in" / "Switch to registration".

### Debounce tests use `fireEvent`, not `user-event`

`user-event` deadlocks against fake timers. See [testing.md](testing.md).

## Tooling

### Bun, not npm

`bun.lock` is the lockfile. The Docker build uses `oven/bun` for the frontend stage only:
the shipped image is a Python image with no JavaScript toolchain in it.

### `bunfig.toml` configures a security scanner

`bun install` screens packages before any package code executes, the only moment a
supply-chain check is worth anything. Two consequences. If the scanner package is missing,
**`bun install` fails closed** rather than skipping the check. And the scan is an outbound
call made during the Docker build's frontend stage, so a sandbox with no egress fails the
install. Allow the host rather than removing the config.

### `--import-mode=importlib` for pytest

Required by the mirrored layout, not a preference. See [testing.md](testing.md).

### Alpine, and the musl bar for new dependencies

Both stages are Alpine. The runtime moved off Debian because its userland is findings
waiting to happen against software the container never executes.

This matters when adding a Python dependency. **A C-extension package with no musllinux
wheel does not fail politely:** uv tries to build it from source and dies for want of a
compiler, in CI, at image-build time. The current native set (bcrypt, pydantic-core, uvloop,
httptools, watchfiles, greenlet, sqlalchemy) was verified to install from musllinux wheels
*and* to run on musl before the switch.

### TypeScript's strictest options are on

`noUncheckedIndexedAccess` in particular, which is why array access reads `tags[1]!` in
places. That is honest about the fact that an index may miss.
