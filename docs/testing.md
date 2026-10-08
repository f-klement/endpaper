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
cd backend  && uv run pytest        # the whole suite
cd frontend && bun run test         # the whole suite
```

**Neither line quotes a size.** Both registers state theirs, and both are now recomputed
by the run that reads them, so a count copied here would be a third home for a figure that
has one. These two were 102 and 30 out against the tree they described.

| Command | Purpose |
|---|---|
| `uv run pytest --cov --cov-report=term-missing` | Backend coverage with unhit lines |
| `uv run pytest tests/test_dependencies.py -k private` | One file, matching tests |
| `uv run pytest -m property` | Only the tests whose inputs hypothesis generates |
| `uv run pytest --hypothesis-profile thorough` | The same properties at ten times the examples |
| `uv run mypy .` | Type check, strict |
| `uv run ruff check .` | Backend lint. There is no formatter step: nothing here configures or runs `ruff format` |
| `bun run test:watch` | Re-run on change |
| `bun run test:coverage` | Frontend coverage |
| `bun run typecheck` | `tsc --noEmit`, includes the test tree |

Neither suite touches the network. Both are safe to run alongside a live dev server.

**A command these documents offer is checked against the project.** Offered means written
in code, inline or fenced, headed by `uv`, `bun`, `uvx` or `bunx`. That prefix is what
separates an instruction to run something from the row above, which names `ruff format` as
the thing nothing here runs and has to stay writable. A `bun run` script has to be one
`frontend/package.json` declares. A program under `uv run` has to be one
`backend/pyproject.toml` declares or one this repository invokes, and a verb after it,
`check` in `ruff check`, has to appear in a command this repository runs. A command
satisfying none of those fails the suite by name.

**What it does not reach**, so nobody reads it as more than it is: a command written with
no runner in front of it, and a flag written before the verb, which drops the check back to
the program alone. Checking flags means a copy of every tool's argument grammar.

The row that bought this stood under "Lint / format" and ran the lint step and
`ruff format` together, in one cell, while nothing here configured or ran the second half,
so following it rewrote most of the backend. [`README.md`](../README.md) named the same job
correctly and neither document pointed at the other. **Quoting that cell here would offer
it again**, which is why this paragraph describes it instead: the check reads a document
the way a reader does and cannot tell an example from an instruction.

## Generated input

Both suites generate inputs for the rules that are complements of what anybody would think to
write down, and above all for the **byte doors**: functions that turn bytes or text somebody
other than this application wrote into a value of this application. A byte door answers that
value, or a refusal its own module declares, and nothing else. Each suite derives its own
population of byte doors; the rules they are held to are here, once, and an empty cell would be
a gap stated rather than a lesson that did not travel.

| Rule | Frontend | Backend |
|---|---|---|
| The outcome is named: the answer, or a refusal the byte door's own module declares | `expectNamedOutcome` | `strategies.answer_of`, which refuses a refusal class defined outside the module of the callable it is handed; a wrapper beside its own class passes it, so a wrapper is read by eye |
| Where a byte door can multiply its input, counted work is held to its own declared bound, because "did not throw" passes an inflation | the meter: reads, inflation, parser input | at the three XML byte doors, `tracemalloc`'s peak against the door's `ALLOCATION_FACTOR` times its input, plus `xml_parse.ALLOCATION_FLOOR`; the archive door's bounds are its size and compression ratio checks, held by named cases, and its decompression is not metered |
| Draw the structure and build the bytes, plus a few single byte patches | arbitraries over a builder's spec | strategies over a spec dataclass, built at the transport's seam |
| A long run of one unit is a named atom, so it is drawn at every seed and prints as itself | named atoms at, around and far past a bound | `FAR_PAST_ANY_DEPTH`, `WIDE`, `MANIFEST_DEPTH` |
| Every class a property's oracle depends on has a witness, asked of what the byte door did rather than of the spec where the door can be asked | per module, at a fresh seed | `strategies.witness` beside each property; the catalogue surrogate witness asks the response's bytes, since after the repair no door can show one |
| Every bound a byte door declares has a positive control in the same file | the ledger refuses a missing one | a named case at the bound and one past it, reading the module's constant |
| The population of byte doors is derived, not remembered | every module the six roots reach | `_BYTE_DOORS` in `tests/test_house_rules.py`, the functions calling an entry point of the XML, JSON, zip and CSV readers, each row naming the property that drives the byte door above it; `parse_qs` and the hand written CQL parser are outside it, with properties of their own |
| A fresh seed every run; nothing cached, nothing committed | the runner prints the seed | not derandomised, no example database |
| The examples that run are counted against a floor | `propertyBudget.test.ts` | `test_property_budget.py` |

**What a counterexample becomes**, in either suite:

1. A named test in the file holding the property, rebuilding the literal the runner printed
   through the property's own builder and asserting the **exact** answer, never only that
   nothing threw.
2. **In the same commit as its fix, never ahead of it.** The test tree publishes, so a case
   parked as a skipped or expected failure is a working exploit against the shipped version.
3. Named for the behaviour, never for a seed or a run. No seed, replay path or example list
   is pinned in a committed file, and the property stays.
4. The spec, never opaque bytes: a bomb committed as a literal costs the mirror and reads as
   nothing in review. A run of zeroes or of repeated text is drawn as a named atom so it prints
   as one.

**What none of this sees** is CPU spent without allocating, in either language. A pattern that
backtracks is neither a wrong outcome nor a size, and a wall clock deadline is refused for the
reason [`decisions.md`](decisions.md) gives under the property budget. Where one was found, its
named case is sized so the old form cannot finish inside the per test ceiling.

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

### Every test is bounded, and the local bound is still the rule

`addopts` carries `--timeout`, `--timeout-method=signal` and `--max-worker-restart=0`,
and the three are one mechanism. A test that hangs used to end the whole job with nothing
naming it. The ceiling turns it into a named failure, the signal method keeps the worker
alive so the rest of the run still reports, and zero restarts stops one worker death
becoming nine: under `--dist loadfile` a dead worker hands its item to the replacement,
which dies on it too.

**Turning the parallel runner off is now `-n 0`, and `-p no:xdist` is not the way to do
it.** Measured three ways, because the reason matters more than the refusal. Typed plainly
it is a usage error, exit 4, `unrecognized arguments: -n --dist --max-worker-restart=0`:
the flags above are in `addopts`, so argument parsing refuses before anything else can.
Neutralise `addopts` as well and it becomes an internal error, exit 3, because
`conftest.py` names a hook the parallel runner owns and pytest refuses an unknown one. The
control says that is the reason: the same run with the plugin left in place and `-n 0`
passes. Both layers are the self enforcing property the flags were put in `addopts` for,
and neither is a graceful degradation, so `-n 0` is the shape to use.

**The ceiling is a backstop, not a deadline.** Its value has a floor derived from the tree:
strictly above the largest ceiling anything in the test tree declares, which
`tests/test_a_hung_test_is_named.py` asserts by walking the tree. A test that later
declares a longer wait reddens that guard and forces a decision, instead of being halved
by a line nobody re-read. A test that legitimately needs longer takes
`@pytest.mark.timeout(n)` at its own site.

**Anything with a real deadline of its own bounds itself, in its own fixture**, and the
global must not become the reason nobody writes a local one.
`_WAITED_PAST_EVERY_DEADLINE_SECONDS` in `tests/routers/test_books_identifier_backfill.py`
is the shape: a wait justified as ten times the largest deadline any arm sets, so it never
fires while the deadline is where it belongs and it accuses the handler when it is not.

**What the ceiling does not reach**, so nobody reads it as a bound on hangs in general: a
test that blocks SIGALRM, a hang inside a C call that never returns to the interpreter, a
hang during collection or module import, and a hang in the controller itself. Each of those
still ends the job rather than a test.

**Under all of it, the session reconciles itself.** `conftest.py` compares the tests the
session collected against the ones that produced a report and refuses a short run, naming
what went missing. A worker that dies for any other reason, a truncated session and a
report that never arrived are the same defect one level up from a hang, and this is what
makes them loud rather than a smaller number nobody compares. A run stopped early on
purpose is exempt, and so is `--collect-only`.

**How that exemption is decided is worth one line, because the obvious answer is wrong.**
It asks the session's own stop state, `shouldfail` for `-x` and `--maxfail` and
`shouldstop` for `--stepwise`, and not the exit status: `-x` with no xdist arrives as an
ordinary `TESTS_FAILED`, so a status only rule refuses the commonest debugging run there
is, and `--pdb` forces no xdist. The status is still asked afterwards, for the stops that
set neither flag, which are an interrupt and a bare `pytest.exit(reason)`. The same call
given a `returncode` inside pytest's own set arrives as an ordinary run of that status, so
a test lost in one is still refused.

### Properties, and what they are allowed to spend

Some rules are not a list of cases. The character classes two schema validators refuse, the
strings an ISBN reader has to answer for, and the queries a CQL parser must answer with a
tree or a diagnostic are all **complements of what anybody would think to write down**, and
a sweep written by hand is a claim about its own bounds with nothing in it saying so. One in
this tree read `range(0x11000)` as though it covered Unicode, which is a sixteenth of the
codepoints.

So `hypothesis` generates the inputs for those, marked `property` and running in the
ordinary suite. Two rules hold over every one of them.

**Derive the generator from the rule, never from a list of the ways the rule can break.**
The invisible characters come from the Unicode categories. The catalogue wordings come from
the patterns under test. A check digit comes from the arithmetic and never from the function
being checked, which would agree with it whatever it did.

**A property is only a claim about what its generator can reach**, so one about a hostile
class carries a `strategies.witness` beside it: it searches the same strategy for a value in
the class and fails by name when it cannot find one. Narrow a generator and the witness
says so; without it the property stays green and stops testing anything.

**A shrunk failure is pinned as its own deterministic test**, by the rules under
[Generated input](#generated-input). The example database is off, so nothing is cached: the
defect is named in the tree or it is not recorded at all.

**A property drives the byte door, never a step inside it**: `marc.read`,
`backup.read_manifest`, `opds.read_page`, and both SRU functions with the response built as
a `fetch.Fetched`. A string drawn directly reaches values the transport's own decoding never
produces, which would be counterexamples to nothing. The decoders in `metadata.READERS` and
`opds.READERS` are handed a parsed element rather than bytes, so theirs is a property of the
contract below a byte door, and it asserts the answer's type alone. The printed literal can come out blank in the suite pod, where
`Failing test case` lists every argument empty; replay the printed `@reproduce_failure` blob
in one process to read it.

`tests/test_property_budget.py` holds the floor under the example count and measures the
examples that actually run, because a profile somebody lowers to one is a suite that passes
in the usual time and tests nothing.

### Where the databases live, and how you know

Every test drops and recreates the schema, so the run is tens of thousands of writes that are
deleted immediately. They go to `/dev/shm`, which is memory, and `conftest` **falls back to
disk silently** when that is missing or unwritable: the suite still passes, and the only
difference is how long it takes.

So every run prints one line saying which it got:

```
endpaper scratch: /dev/shm (tmpfs)
endpaper scratch: /tmp (DISK, /dev/shm unavailable)
```

Read it before concluding a machine is slow.

### The network is stubbed

`respx` intercepts outbound HTTP, so Open Library and Google Books are never called for
real and the suite works offline.

### The schema driven run, which is a tool rather than part of the suite

`tests/api_contract.py` reads the committed `frontend/openapi.json` and generates requests
for every operation in it, asserting two things and no third: no generated request is a
server error, and every response matches the schema that declares it. It runs as an
ordinary member, against the suite's own throwaway database, through the in process
application object, so there is no address at which it could reach a deployment.

**The suite does not collect it.** The collector takes `test_*.py` and this is
`api_contract.py`, so it runs only when the run names the file. `schemathesis` is
declared in the dev group, so nothing else has to be supplied. Like every other suite
here it goes to a worker node rather than to the development host.

**The whole invocation is deliberately not written out** on this page, and the reason is
the publish gate: the wrapper that takes a run to a worker node lives under a directory
the mirror strips, and a published page may not name one.

The module's docstring says what it covers, what it deliberately does not, and what would
make it a gate. `docs/decisions.md` records what it finds today.

## Frontend

Vitest in happy-dom, with Testing Library. **Three environments, not one**, chosen per
file by a docblock:

* **happy-dom** by default, because it builds a DOM substantially faster than jsdom for
  the API surface this suite uses, and that cost is paid once per file.
* **`@vitest-environment node`** for the files that touch no DOM at all, because
  building one costs more than they spend running.
* **`@vitest-environment jsdom`** where happy-dom gets something wrong that a file depends
  on, pinned deliberately and said in each file's own docblock: happy-dom does not inherit
  CSS custom properties down the tree, which the files solving colours against a palette
  need, and its XML parser misreads documents the readers of a member's files parse.
  `docs/decisions.md` records that the palette pin comes off if happy-dom fixes it. **One
  reader's file runs happy-dom on purpose**: `fb2.test.ts`, whose named case for a header its
  parser throws on asserts how the FictionBook reader answers a parser that throws, which is
  happy-dom's behaviour.

Which files those are is the docblocks' to say; list them with
`grep -rlE '^\s*\*\s*@vitest-environment jsdom' frontend/tests`.

The suite runs with `isolate: false`, so the files in a worker share one environment. That
is worth roughly half the wall clock and it is what the module rule below exists to pay
for.

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

### Properties over a member's file

The readers that parse a file a member picked, and the doors a picked file's name and path go
through, are fuzzed with `fast-check`, pinned to an exact version. A bump is merged without a
person when it only moves a patch or minor version, so what holds it is the guard's pinned export
list: a version adding a runner or a plugin reds there, and that red stops the merge until
somebody decides which side of the door the new name is on.

- **One door.** `tests/property.ts` is the only module that runs a property: a property calls
  `holds(arbitrary, predicate)` inside `it(name, PROPERTY, body)` and passes no options, so it
  cannot lower its own example count, pin a seed or add a plugin. The runner fails a run that
  executed fewer examples than its profile. `tests/propertyBudget.test.ts` holds the door by
  parse over every module under `frontend/` but `src/`, refusing the package named by any string
  that is not an import's specifier, and finds a property by what it binds to rather than by
  its name. It pins the generator's export list, so a version adding a runner reds once.
- **Never in the application.** A house rule refuses the package named by a string anywhere
  under `src/`. The build refuses a bundle that loads it, in the page build and in every worker
  build, and one that emits it, checking each chunk's modules and each asset's source files, since
  the image installs development dependencies before it builds. Both match a path into
  `node_modules`, so a copy of the package's bytes committed elsewhere is named by neither.
- **A fresh seed per property per run**, as the backend draws one: a fixed seed would sweep
  the same inputs forever. No timer in this suite's runtimes can interrupt a synchronous loop,
  so the runner writes `property <name> seed <s>` and then `run <i>` to standard error before
  each example, written synchronously. The last line before a killed run names the input, and
  `replay(arbitrary, seed, i)` regenerates it. Setting `ENDPAPER_PROPERTY_SEED` pins a seed for
  reproducing a red, and the runner refuses it where `CI` is set. The budget guard refuses the
  name in any module under `frontend/` and in the manifest; refuses a dotenv file at the top of
  `frontend/` by its existence, since bun and Vite each load one into the workers; reads Vite's
  resolved configuration for where it loads one, which variables it copies and the suite's own
  environment, refusing a second suite configuration by its existence; and pins the keys of
  bun's configuration, whose `preload` runs code in every worker. That configuration is resolved
  as the worker running the guard resolves it, so one that answers differently in vitest's main
  process, which is the one that loads the environment, passes as the worker sees it. Code that
  runs before the runner can still set the variable under a computed name, and a configuration
  vitest is pointed at by a flag or a project is read only for the name spelled out; none of that
  reads either.
- **Counted work is the oracle, not "did it throw".** The PDF reader once charged bytes read
  and not bytes inflated, and answered `ok` with nothing thrown. `tests/lib/meter.ts` counts
  what a reader reads off the file it was handed, what comes out of the inflater and what is
  handed to the XML parser, and holds each to the reader's own exported bound.
- **One contract.** `expectNamedOutcome(door, input)` and `expectAnswer(door, value)` in
  `tests/lib/readerContract.ts` read the meter, then refuse a throw the door's own module does
  not export.
- **Arbitraries draw a builder's spec, not bytes**, total over the spec by type, plus a few
  single byte patches. A run of zeroes is a named atom at, around and far past a bound, so a
  counterexample prints as a literal a person can read. An XML document is drawn as a tree over
  the reader's own element names, and text as code points up to the bound its callers enforce
  and one past it.
- **Every module with a property has a witness for each**: at a fresh seed of its own, the
  values an arbitrary draws include each hostile shape named, and the witness throws naming
  the one it missed. A witness holds at any seed or it is a witness of one, so each class is
  weighted until a run from any seed draws it.
- **A property over a door that inflates, slices or queries names what its run must reach**,
  asked of what the meter counted or the door answered rather than of the spec: a bomb drawn
  behind a header the reader refuses first reaches no inflater and satisfies any predicate over
  the spec. Each reach follows the run's own seed. A property over a door handed a string or a
  tree names none; its witness is what says the shape is drawn. The budget guard pins how many
  properties in each file name one, so a reach dropped is a red.
- **Every bound a door declares has a positive control in the same file**: a stub reading,
  inflating or parsing past it under the door's own ceilings, which must be refused by name. A
  property is green over a correct reader whatever its door declares, so without one a ceiling
  deleted or loosened reds nothing. A ledger the suite's setup keeps per file refuses a bound a
  driven door declared and no control in that file overran.
- **Every door has a property**, or is named as reached only through one: every module the
  six roots named in `tests/propertyBudget.test.ts` reach for a value, following every relative
  import under `src/` but the generated client's. A door outside what those roots reach is
  outside the rule, and the budget guard names the one there is.

What a counterexample becomes is one rule for both suites, under
[Generated input](#generated-input).

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

### Replacing a module

**Not with `vi.mock`, which fails the build.** The suite shares one module registry
between the files in a worker, so a `vi.mock` is a claim one file makes about a module
another file may already have evaluated: it is then dropped, silently, and the real module
is what the test gets. Measured in both directions before the rule existed, on a suite
that was otherwise green.

A module that must not run for real is replaced once, for every file, by a double in
`frontend/tests/doubles/` and an entry in `test.alias`. `@zxing/library` is the one there
today, because no test environment has a camera. `frontend/tests/doubles/README.md` is the
argument and the recipe, including the one thing the recipe cannot do.

Two consequences worth knowing before reaching for a double:

* **A double is suite-wide**, so a module that has its own test file cannot be one. Pass
  the dependency in as a prop instead.
* **A global is the other half.** `navigator.mediaDevices` is installed per test by
  `tests/doubles/camera.ts` and put back by `tests/setup.ts`, along with
  `window.location` and the document URL. `Object.defineProperty` is not something vitest
  undoes, so anything installed that way leaks into every later file until something
  restores it.

Navigation is asserted on where the router ended up, through the `path()` that
`renderWithProviders` returns, rather than on a spy standing in for `useNavigate`. That is
the better assertion regardless: it says the reader arrived at the book.

## The shared conformance suite

Some rules have to give the same answer in Python and in TypeScript. Those rules
are pinned by one language neutral fixture set in
[`conformance/`](../conformance/README.md). Each domain there has a case file, a
schema, a document and a runner in each of `backend/tests/conformance/` and
`frontend/tests/conformance/`. Both runners read the same JSON, so a
disagreement between the two implementations is a failing test on the side that
is wrong rather than a support ticket a year later.

**Named as a directory and not as a list of domains**, because the list grows
and a list written here is the copy that stops being edited.

**Adding a case is editing JSON, not either test file.** Each runner holds the
mapping onto its own spelling, plus the guards that stop it passing while
testing nothing. Changing an expectation is changing the protocol, and lands on
both sides together. `conformance/README.md` has the rules, the measurements,
and why the directory exists at all; each domain's own document has what a case
is there and what each one pins.

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
- **A property ships with the proof that its generator still reaches the interesting
  input.** `strategies.witness` is that proof, and it is the same rule as the guard that
  inspects nothing above, one level up: a property over a generator that cannot produce the
  class it is about is green and empty, and nothing in the run distinguishes it from one
  that holds.
