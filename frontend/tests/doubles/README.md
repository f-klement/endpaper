# Doubles

A module that must not be the real one during tests is replaced **here**, once,
for the whole suite, by an entry in `test.alias` in `vite.config.ts`. Not with
`vi.mock`, which `tests/houseRules.test.ts` fails the build on.

## Why not vi.mock

The suite runs with `isolate: false`, so the test files in a worker share one
module registry. A `vi.mock` is a claim one file makes about a module that
another file may already have evaluated, and when it loses it loses silently:
the mock is dropped, the real module is what the test gets, and nothing reports
that anything was replaced.

Both directions were measured on this suite, with everything else green:

| Order                                          | What the second file got | Result                                   |
| ---------------------------------------------- | ------------------------ | ---------------------------------------- |
| `App.test.tsx`, then `BarcodeScanner.test.tsx` | the real ZXing decoder   | 15 of 33 tests failed                    |
| `App.test.tsx`, then `BookDetail.test.tsx`     | the real `useNavigate`   | the one test asserting on the spy failed |

Both files pass alone, and pass in the other order. `src/app/routes.tsx`
imports every page eagerly, so rendering the route table evaluates the scanner
and the router for real, and the shuffle decides the rest. One shuffled seed in
eight failed the whole suite this way.

An alias has no ordering, because there is no real module left to lose to.
Every importer resolves here, cached or not, first or last.

## Adding one

1. Write the double in this directory. Export the spies the tests assert on and
   a `reset` function, which step 4 wires up: the module is evaluated once per
   worker, so its spies outlive a single test file.
2. Add the specifier to `test.alias` in `vite.config.ts`. Use `test.alias` and
   never `resolve.alias`, or the application build gets the double too.
3. If the double installs anything on a global, restore it in
   `tests/setup.ts`. `Object.defineProperty` is not something vitest undoes,
   which is why `navigator.mediaDevices`, `window.location` and the document
   URL are all put back there.
4. Call its reset from `tests/setup.ts` too, not from a test file. An alias is
   always in force, so a file can reach a double's spies without knowing the
   double exists, and a file that does not know cannot remember to reset it.
   The camera is the exception and shows where the line is: it is a global
   rather than a module, it is absent unless a file asks for it, and
   `installCamera()` resets it as part of installing it.

## What this cannot do

**A double is suite-wide, so a module that has its own test file cannot be
one.** There is no per-file replacement here and there is not going to be:
`vi.mock` is a failing test, and the only per-file control over isolation is a
`projects` split, which broke the run outright when it was tried (see the note
at the top of `vite.config.ts`).

So this is the wrong tool for keeping one page's tests focused. Where a page
pulls in a component it does not want to exercise, pass the dependency in as a
prop rather than reaching for a replacement.

## What is here

| Double      | Replaces                 | Why                                                                                                                     |
| ----------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `zxing.ts`  | `@zxing/library`         | There is no camera, and the decoder is not what the scanner's tests are about.                                          |
| `camera.ts` | `navigator.mediaDevices` | Same, one layer down. Not an alias: a global rather than a module, installed per test and restored by `tests/setup.ts`. |

## The stub that used to be here

`ScanPage.test.tsx` replaced the whole `BarcodeScanner` component with a pair of
buttons that emitted a fixed ISBN. It was deleted rather than converted, and the
reason is the constraint above rather than a judgement about its value: the
scanner has its own test file, so it could never have been a double.

What replaced it is the page rendering the real scanner over these doubles,
which costs one `waitFor` on the camera opening. The scanner's own file runs 33
tests that way in 93ms to 159ms across runs on the builder worker, so the price is
small, but it was
not the deciding argument and should not be read as one.
