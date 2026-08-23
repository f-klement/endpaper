/**
 * The little of Node that `vite.config.ts` needs, declared rather than depended on.
 *
 * `tsconfig.json` sets `types` to an explicit allowlist, which is what keeps `process`
 * and the rest of Node out of `src/`: nothing in a browser bundle should reach for them,
 * and a missing global is the cheapest way to enforce that. Adding `@types/node` for the
 * two symbols below would hand them to every component and test as well.
 *
 * These exist only while the config is being evaluated, never in the shipped bundle.
 */
declare const process: {
  env: Record<string, string | undefined>;
};

declare module "node:child_process" {
  export function execSync(
    command: string,
    options?: {
      cwd?: string;
      stdio?: readonly ("ignore" | "pipe" | "inherit")[];
    },
  ): { toString(): string };
}
