/**
 * Hands the suite the configuration vitest loaded, as its main process holds it.
 *
 * **The main process is the one that loads the environment**, and every
 * worker inherits it. A worker resolving `vite.config.ts` again answers for
 * itself, so a configuration that set where Vite loads a dotenv file only
 * outside a worker pinned every property seed while the seed guard, resolving
 * in its worker, was green: measured by a security review. So the guard in
 * `tests/propertyBudget.test.ts` reads what was loaded, handed over here with
 * `provide`, rather than resolving it a second time.
 */

import type { TestProject } from "vitest/node";

/** What the seed guard asks of the loaded configuration. */
export interface RunConfiguration {
  readonly root: string;
  readonly configFile: string | null;
  /** Where Vite loads a dotenv file from, or `false` for nowhere. */
  readonly envDir: string | false;
  /** A prefix of the configuration's own, or `null` for Vite's default. */
  readonly envPrefix: string | readonly string[] | null;
  /**
   * The names of the variables the configuration has vitest add to the
   * environment each worker inherits from this process. **Not that environment itself**: what the
   * configuration's own code or a `define` key put into this process's
   * environment reaches every worker and is not listed here.
   */
  readonly workerEnv: readonly string[];
  /**
   * The string keyed aliases this process resolves by, `test.alias` among
   * them: vitest moves it into `resolve.alias` here. The door walk applies
   * these, so its aliases are the run's rather than a second load's. A
   * `customResolver` on an alias is not carried.
   */
  readonly aliases: readonly { find: string; replacement: string }[];
}

declare module "vitest" {
  export interface ProvidedContext {
    runConfiguration: RunConfiguration;
  }
}

export function setup(project: TestProject): void {
  const vite = project.vite.config;
  project.provide("runConfiguration", {
    root: vite.root,
    configFile: vite.configFile ?? null,
    envDir: vite.envDir,
    envPrefix: vite.envPrefix ?? null,
    workerEnv: Object.keys(project.serializedConfig.env),
    aliases: vite.resolve.alias.flatMap(({ find, replacement }) =>
      typeof find === "string" ? [{ find, replacement }] : [],
    ),
  });
}
