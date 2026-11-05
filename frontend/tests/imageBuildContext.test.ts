/**
 * @vitest-environment node
 *
 * The type check the image's build runs reads no file the image lacks.
 *
 * The Dockerfile's frontend stage copies `frontend/` from a build context
 * `.dockerignore` has already filtered, so `tests/` and the rest of what it
 * strips are not there. A checkout has them, so a type check that reads one
 * passes every local run and the gate, then fails the image build on `main`,
 * or quietly checks a different program there.
 *
 * So this asks the compiler which files the build's own `tsc` invocation reads,
 * taken from the `build` script as written, and refuses any that is outside
 * the directory the stage copies or that `.dockerignore` strips.
 * `frontend/node_modules/` is exempt: the stage installs it. The stage's copy
 * is read from the Dockerfile, and an arm refuses any shape but one directory
 * copied whole into the working directory, because a narrower copy would leave
 * this guard passing files the stage no longer has.
 *
 * It sees the compiler's program, not vite's module graph. What vite resolves
 * and the compiler does not follow is outside it: a `?raw` or `?url` suffix
 * (typed by an ambient module, so nothing is listed), an `import.meta.glob`, a
 * `new URL(path, import.meta.url)`, a CSS `@import` and a reference in
 * `index.html`.
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { posix, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const FRONTEND = fileURLToPath(new URL("../", import.meta.url));
const ROOT = resolve(FRONTEND, "..");
const TSC = resolve(FRONTEND, "node_modules/typescript/bin/tsc");

/** A listing of the whole program measures a few seconds in the suite pod. */
const LISTED = 60_000;

/**
 * Whether a `.dockerignore` leaves a context path out, read the way Docker
 * reads it: each pattern cleaned and anchored at the context root, `**`
 * spanning any number of directories including none, `*` and `?` stopping at a
 * slash, a pattern matching a parent directory taking its contents, and the
 * last matching pattern winning, so a `!` line puts a path back.
 *
 * A port of `_ignored` in `backend/tests/test_image_layers.py`, which judges
 * the same file for its secrets arm. The arms at the bottom pin the readings
 * this file's guard relies on.
 */
function ignoredByDocker(path: string, text: string): boolean {
  const parts = path.split("/");
  const parents = parts.map((_, n) => parts.slice(0, n + 1).join("/"));
  let ignored = false;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (line === "" || line.startsWith("#")) continue;
    const pattern = posix
      .normalize(line.replace(/^!/, "").trim())
      .replace(/^\/+/, "")
      .replace(/\/+$/, "");
    let source = "";
    for (let i = 0; i < pattern.length;) {
      if (pattern.startsWith("**", i)) {
        i += pattern.startsWith("**/", i) ? 3 : 2;
        source += i >= pattern.length ? ".*" : "(.*/)?";
        continue;
      }
      const char = pattern[i]!;
      source +=
        char === "*"
          ? "[^/]*"
          : char === "?"
            ? "[^/]"
            : char.replace(/[.+^${}()|[\]\\]/g, "\\$&");
      i += 1;
    }
    const regex = new RegExp(`^${source}$`);
    if (parents.some((parent) => regex.test(parent))) {
      ignored = !line.startsWith("!");
    }
  }
  return ignored;
}

/**
 * The context directory each `COPY` in the Dockerfile's `frontend` stage takes,
 * paired with its destination. A `COPY --from` reads another stage or image,
 * not the context, so it is left out; other flags are dropped.
 */
function frontendStageCopies(): [string, string][] {
  const dockerfile = readFileSync(resolve(ROOT, "Dockerfile"), "utf8");
  const copies: [string, string][] = [];
  let inStage = false;
  for (const raw of dockerfile.split("\n")) {
    const words = raw.trim().split(/\s+/);
    const instruction = words[0]!.toUpperCase();
    if (instruction === "FROM") {
      inStage =
        words.at(-2)?.toUpperCase() === "AS" && words.at(-1) === "frontend";
      continue;
    }
    if (!inStage || instruction !== "COPY") continue;
    const operands = words.slice(1);
    if (operands.some((word) => word.startsWith("--from="))) continue;
    const paths = operands.filter((word) => !word.startsWith("--"));
    for (const source of paths.slice(0, -1))
      copies.push([source, paths.at(-1)!]);
  }
  return copies;
}

/** The arguments the `build` script hands `tsc`, or null where it runs none. */
function buildTypeCheck(): string[] | null {
  const manifest = JSON.parse(
    readFileSync(resolve(FRONTEND, "package.json"), "utf8"),
  ) as { scripts: Record<string, string> };
  for (const command of manifest.scripts.build!.split("&&")) {
    const [tool, ...args] = command.trim().split(/\s+/);
    if (tool === "tsc") return args;
  }
  return null;
}

describe("the image's build type check", () => {
  it("is against a stage that copies one directory, `frontend/`, whole", () => {
    // Any other shape (a narrower copy for layer caching, a second source)
    // means the guard below no longer describes the stage: update its context.
    expect(frontendStageCopies()).toEqual([["frontend/", "."]]);
  });

  it(
    "reads no file the image's build context lacks",
    () => {
      const args = buildTypeCheck();
      expect(args, "the build script runs no tsc").not.toBeNull();
      const listing = execFileSync(
        process.execPath,
        [TSC, ...args!, "--listFilesOnly"],
        { cwd: FRONTEND, encoding: "utf8", timeout: LISTED },
      );
      const read = listing
        .split("\n")
        .filter(Boolean)
        .map((file) => relative(ROOT, file).split("\\").join("/"));
      const own = read.filter(
        (file) => !file.startsWith("frontend/node_modules/"),
      );
      // Not vacuous: the listing is the program, so it carries the app's entry.
      expect(own).toContain("frontend/src/main.tsx");

      const dockerignore = readFileSync(resolve(ROOT, ".dockerignore"), "utf8");
      // `frontend/` is the stage's copy, pinned by the first arm.
      const lacking = own.filter(
        (file) =>
          !file.startsWith("frontend/") || ignoredByDocker(file, dockerignore),
      );
      expect(lacking).toEqual([]);
    },
    LISTED + 5_000,
  );
});

describe("the port of Docker's ignore reading", () => {
  it("takes a directory's contents with it", () => {
    expect(ignoredByDocker("frontend/tests/a/b.ts", "frontend/tests/")).toBe(
      true,
    );
  });

  it("matches a double star at any depth, including none", () => {
    expect(ignoredByDocker(".env", "**/.env")).toBe(true);
    expect(ignoredByDocker("frontend/src/.env", "**/.env")).toBe(true);
  });

  it("lets the last matching line win, so a negation puts a path back", () => {
    const text = "frontend/tests/\n!frontend/tests/kept.ts\n";
    expect(ignoredByDocker("frontend/tests/kept.ts", text)).toBe(false);
    expect(ignoredByDocker("frontend/tests/other.ts", text)).toBe(true);
  });
});
