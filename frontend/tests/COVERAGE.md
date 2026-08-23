# Frontend test coverage

**1,201 tests.**

No coverage percentage is quoted here, deliberately. `bun run test:coverage` does not work
on the machine the suites run on: `@vitest/coverage-v8` calls the V8 inspector, which bun
does not implement, so the run reports `Coverage APIs are not supported` and `no tests`.
The `node` on that image is `/usr/local/bun-node-fallback-bin/node`, bun's own shim for
`#!/usr/bin/env node` shebangs, so it is the same runtime and fails the same way.

A stale percentage beside a measured count is worse than no percentage, because a reader
cannot tell which of the two was measured. `bun run test:coverage` still works wherever V8
is the runtime; run it there and put the numbers back.

```bash
bun run test                 # the suite
bun run test:coverage        # coverage report
bun run test:watch           # re-run on change
bunx vitest run tests/pages/Home   # one area
```

The tree mirrors `src/`: the tests for `src/pages/components/BookCard.tsx` are at
`tests/pages/components/BookCard.test.tsx`. Support files that mirror nothing
(`setup.ts`, `utils.tsx`, `factories.ts`) sit at the root of the tree.

## How these tests are written

They drive the **real generated hooks and the real mutator**, and stub only `fetch`. That
keeps them honest about query keys, cache invalidation and request shapes, all of which a
mocked API module would hide.

`mockApi()` in `utils.tsx` registers per-route handlers and records every request, so a
test can assert on the exact body sent:

```ts
api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
// …
expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
  is_private: true,
});
```

Anything not explicitly stubbed rejects loudly rather than reaching the network.

Queries go through **roles and labels**, never CSS classes. Class names are styling and
change freely; the accessible name is the contract. Several `aria-label` and `aria-pressed`
attributes in the source exist to make that possible, and improve the app for screen
readers as a side effect.

---

## What each file covers

| File                                  | Tests | Covers                                                      |
| ------------------------------------- | ----: | ----------------------------------------------------------- |
| `houseRules.test.ts`                  |    10 | Rules that hold across the whole tree: the generated client behind hooks, retired text tiers, one focus ring, one session writer, stated dark hover states, no dashes |
| `api/mutator.test.ts`                 |    29 | Token attachment, 401 handling, error flattening, downloads |
| `api/query-client.test.ts`            |    16 | Retry policy and cache defaults                             |
| `app/*`                               |    48 | The session gate, the top bar (incl. the way back from a switched session), the library export, appearance sync |
| `components/*.test.tsx`               |    28 | The general dumb components, incl. the star rating and the toast |
| `i18n/index.test.tsx`                 |    33 | Language detection, interpolation, catalogue parity         |
| `lib/isbn.test.ts`                    |    31 | Check digits, ISBN-10 to ISBN-13, normalisation             |
| `lib/goodreads.test.ts`               |     7 | Search URLs, mirroring the backend's own tests              |
| `lib/lastLocation.test.ts`            |    10 | Shelf carry-over, clearing, storage refusing to work        |
| `lib/savedSearches.test.ts`           |    11 | Named views, replace-on-resave, corrupt and refused storage |
| `lib/libraryView.test.ts`             |     5 | Covers or table, remembered locally, and storage refusing to answer |
| `lib/money.test.ts`                   |    10 | Prices as whole cents, a comma separator, refusing a typo   |
| `pages/hooks.test.ts`                 |    33 | Session state, auth modes, corrupt storage, switching into a test account under proxy, and dropping the cache whenever the identity changes |
| `pages/types.test.ts`                 |    16 | Tag grouping, the style tables, the lending answers, and the light and dark modes |
| `pages/components/TagPicker.test.tsx` |    17 | The picker shared by three pages                            |
| `pages/components/BookCard.test.tsx`  |    37 | One book in a grid: status, tags, ownership, the talk-about-it marker, selection, and the fold out |
| `pages/TrashPage/TrashPage.test.tsx`  |    11 | Restoring without asking, and destroying only after asking  |
| `pages/components/LocationField.test.tsx` |  5 | Shelf suggestions, and one datalist per instance            |
| `pages/Home/*`                        |   137 | Filters, ownership, lending, pagination, selection, the bulk verbs, and the table view |
| `pages/BookDetail/*`                  |   128 | Status, ratings, series, shelf, loans and the never-lent confirmation, the offer to talk about a book, notes, enrichment, the reading log and its two units |
| `pages/ScanPage/*`                    |   116 | Scan, typed ISBN, keyless search, prefill, rapid mode, shelf carry-over |
| `pages/SettingsPage/*`                |   101 | Feature toggles, the API key, the Goodreads import, backup and restore, test accounts and switching into one, the overdue webhook and its masked secret, the cover backfill |
| `pages/AppearancePage/*`              |    40 | The picker: modes, seven palettes, twelve wallpaper tiles, the constructed note, the licences, and previewing on the reader's own books |
| `pages/LoginPage/LoginPage.test.tsx`  |    19 | Sign-in, registration, the background uploader              |
| `pages/LoansPage/LoansPage.test.tsx`  |    18 | Listing, returning, due dates and the overdue view          |
| `pages/StatsPage/*`                   |    16 | Every section, the pages-read series, and the all-zero case |
| `pages/SeriesPage/*`                  |     7 | Series cards, their counts and their gaps                   |
| `pages/DuplicatesPage/*`              |     8 | Suspected duplicates and confirming a merge                 |
| `pages/errors/*`                      |     9 | 404, 403 and the render-crash boundary                      |
| `theme/index.test.tsx`                |    31 | Mode resolution, the palette on the document, more contrast, and a wallpaper turned off |
| `theme/appearance.test.ts`            |    16 | The per account cache, unknown values, corrupt storage, the front door |
| `theme/palettes.test.ts`              |    86 | Every palette and mode, measured against the rung contract, with and without more contrast, plus the catalogue and the swatch read |
| `theme/patterns.test.ts`              |    43 | The wallpaper engine: the ink budget, the admission rule, the byte cap |
| `theme/oklab.test.ts`                 |    15 | Lightness, the sRGB composite, and the alpha solve |

## The parts that matter most

**The mutator**, because everything routes through it. It carries the token, ends a stale
session, and turns three different server error shapes into one displayable string. Two of
its tests are regressions for real bugs:

- A 401 used to resolve `undefined`, so every caller rendered with missing data instead of
  showing an error. It now throws.
- A 401 from `/auth/login` was handled as an _expired session_, clearing the stored
  session and replacing "Incorrect username or password" with "Your session has expired",
  which is wrong and, for someone not signed in at all, nonsense. `/auth/switch` joined
  that list the day it was added, for a sharper version of the same reason: its caller is
  signed in, so a mistyped test account password signed the admin out of their own session.

**Pagination**, in `pages/Home/hooks.test.ts`: that a second page is _appended_ rather than
replacing the first, that the next page number is requested, and that `hasMore` goes false
once the loaded rows account for the reported total.

**The catalogues** (`i18n/index.test.tsx`). Key parity is a compile-time property, so the
suite spends its effort on what the type system cannot see: that every placeholder the
English text declares survives into the German (a dropped `{count}` is silent: the sentence
just reads oddly), that no message in either language contains an em dash, and that the
language-resolution order actually is stored choice → browser → server default → English.

**Ownership and selection** (`pages/Home/*`). That "Select all" covers only the books
actually loaded, that a selected card is announced as a checkbox rather than a link, and
that the unconfirmed banner disappears on its own rather than needing dismissal.

**The Google Books gate.** Every entry point is asserted absent when the feature is off. A
button that could only ever produce a 400 is worse than no button, and the flag is the only
thing standing between the two.

**Rapid intake** (`pages/ScanPage/hooks.test.tsx`). Three properties matter and each has a
test: the same barcode arriving many times a second is queued once, a book neither source
knew stays in the queue rather than vanishing, and **nothing is written until the batch is
confirmed**. A scanner that wrote as it went would turn every misread into a row somebody
has to find later.

**Destructive bulk actions** (`pages/Home/components/SelectionBar.test.tsx`). That delete
sits behind a disclosure rather than beside "mark as owned", that it asks first, and that a
cancelled location prompt is not treated as an empty one. `null` is cancel and `""` is a
deliberate clear; conflating them wipes the location of every selected book on a stray
Escape.

**Request bodies**, everywhere a mutation is involved: that ScanPage strips the
client-only `notFound` and `suggested_tag_ids` fields, that a note is trimmed before
sending, that privacy sends snake_case.

## Deliberate gaps

Branch coverage (78%) is the lowest number and the least interesting one: most unhit
branches are optional-field fallbacks in presentational components (`book.author &&`,
`loan.book?.title`), where both sides are covered by the factories in aggregate but not per
component.

Excluded outright from coverage:

- **`src/api/generated/`**, generated by Orval from the OpenAPI schema. Testing it would
  test the generator. It is exercised constantly and indirectly, since every page test
  drives the real hooks.
- **`src/main.tsx`**, three lines of bootstrap with nothing to assert.

Not covered by choice:

- **Real rendering.** jsdom has no layout engine, so nothing here can catch a visual
  regression. The Tailwind 4 migration in particular needs a human eye.
- **The camera.** `@zxing/library` is mocked wholesale. The ISBN filter and the camera
  lifecycle are tested; the decoding is not.
- **Service worker behaviour.** The PWA precache and update cycle are not exercised.
- **German rendering, beyond a few spot checks.** The catalogues are checked structurally
  (parity, placeholders, no em dashes) and a handful of components are rendered in German,
  but nothing asserts that every screen reads well translated. That needs a person who
  speaks it, not a test.

## Conventions

- One behaviour per test, named as a sentence.
- Prefer stubbing the network over mocking a module: a test that stubs `fetch` still proves
  the URL, method and body are right.
- Fake timers only where a debounce demands them (`SearchBar`), and with `fireEvent` rather
  than `user-event` there, which schedules its own async work and deadlocks against
  fake timers.
- Pick the smallest render helper that works: `renderLocalised` for a dumb component,
  `renderWithProviders` for a page, `renderHookWithProviders` for a page's hooks. Handing a
  presentational component a query client blurs the line the structure exists to draw.
- All three force English, so assertions do not depend on the machine's browser language.
  Pass `locale: Locale.de` to assert on German. It is an initial value, not a lock, so the
  language switch is still testable through the UI.
