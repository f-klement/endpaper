/**
 * Refuses `vitest related` under `isolate: false`, before a worker starts.
 *
 * **Under that pair vitest runs `tests/setup.ts` once per worker per
 * environment, not once per file.** Measured on vitest 5.0.5, one worker, by a
 * setup that failed the first test of each file evaluating it: 22 of 22 files
 * under `vitest run`, and one file per environment under `vitest related`.
 * Every later file of its environment in that worker runs with no
 * `cleanup()`, no storage cleared, no `fetch` stub and none of the setup's
 * guards. What a reader sees is a later file finding the earlier files'
 * unmounted trees ("Found multiple elements"), a test green alone and red in
 * the related subset every time, with no file leaking anything.
 *
 * **Why, inferred from vitest's source and not proven**: a worker invalidates
 * the setup module before importing it again only once it has been evaluated,
 * and the server answers from its cache when the module graph already holds a
 * transform, which a related run builds while walking every test file's
 * graph. Nothing here rests on that reading; the effect is what is measured.
 *
 * **`--isolate` is the way through**, a fresh module registry per file and so
 * a fresh setup, and the frontend tree guards mode passes it.
 *
 * **`--changed` is refused too.** vitest 5.0.5 resolves it through
 * `filterTestsBySource`, which sets `related` from the VCS before global setup
 * runs, so this sees it as a related run (read from the source, not driven).
 *
 * **The symptom has a guard of its own**, `setupRan.reporter.ts`, which fails
 * any run where a test passed without the setup, whatever command caused it.
 * This stays because it answers before the run rather than after it, and names
 * the command and the flag rather than the files.
 *
 * An exit and not a throw, for the reason `sanctionedRun.globalSetup.ts`
 * gives.
 */

import { writeSync } from "node:fs";

import type { TestProject } from "vitest/node";

import { REFUSED } from "./sanctionedRun.globalSetup";

/** The two settings the refusal reads, typed from vitest's own. */
export interface RelatedRunSettings {
  readonly globalConfig: Pick<TestProject["globalConfig"], "related">;
  readonly config: Pick<TestProject["config"], "isolate">;
}

/** Why this run must not start, or `null` when it may. */
export function refusal({
  globalConfig,
  config,
}: RelatedRunSettings): string | null {
  if (globalConfig.related === undefined || config.isolate) return null;
  return (
    "refusing to run: vitest related under isolate: false evaluates " +
    "tests/setup.ts once per worker and environment, not per file, so every " +
    "later file runs without its cleanup and guards. Pass --isolate; " +
    "tests/relatedRun.globalSetup.ts says why.\n"
  );
}

export function setup(project: TestProject): void {
  const refused = refusal(project);
  if (refused === null) return;
  writeSync(2, refused);
  process.exit(REFUSED);
}
