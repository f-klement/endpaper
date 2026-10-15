/**
 * Load, before a file's first test, every module a hook can reach through an
 * `import()`.
 *
 * **A `waitFor` runs on the default 1000 ms, and a test whose action reaches
 * an `import()` pays for loading that module inside it.** Under
 * `isolate: false` the load is cold only for the first test in a worker to
 * need it, so whether it fits turns on which files the worker ran first and on
 * how busy the transform is. Measured on the scan page: the first PDF pick
 * failed at 1009 ms in a 59 file run while the tests either side of it took
 * about 106 ms. With the PDF reader made to load slowly, it failed when the
 * file had a module registry of its own and passed when an earlier file in the
 * worker had loaded the reader. Loaded in a `beforeAll`, the cost is paid under
 * the hook timeout and no test's budget depends on the order.
 *
 * **This removes a cost of the test runner's transform, and says nothing about
 * the browser's**: a member's first pick of a kind fetches a chunk over the
 * network, which no test here measures.
 *
 * **What is loaded is derived from the source by walking the module graph**,
 * parsed rather than matched as text so a comment naming `import()` is not a
 * call. Every static import and re-export that is not type only is followed,
 * because a lazy import behind a static edge is reached all the same:
 * `lib/stores.ts`, imported statically by the library settings hooks, opens
 * its readers lazily. Following an edge no test drives over approximates,
 * which loads a module nobody needed and never misses one. A file only has to
 * name the hook module it tests.
 */
import { parseAst } from "vite";

import { sourceModules, sourceText } from "./sourceModules";
import { isNode, resolvePath, walk } from "./sourceReader";

/**
 * One loader for each module the hooks under test reach lazily, by its path
 * below `src/`.
 *
 * **Literals, because a specifier Vite cannot read statically is not resolved
 * to the module the application loads**, and loading a second copy warms
 * nothing. `unloadable` reports a module reached lazily and missing here.
 */
const LOADERS: Record<string, () => Promise<unknown>> = {
  "lib/adobeDigitalEditions.ts": () =>
    import("../src/lib/adobeDigitalEditions"),
  "lib/appleBooks.ts": () => import("../src/lib/appleBooks"),
  "lib/audiobook.ts": () => import("../src/lib/audiobook"),
  "lib/audiobookGroups.ts": () => import("../src/lib/audiobookGroups"),
  "lib/calibre.ts": () => import("../src/lib/calibre"),
  "lib/calibreFolder.ts": () => import("../src/lib/calibreFolder"),
  "lib/cbz.ts": () => import("../src/lib/cbz"),
  "lib/epub.ts": () => import("../src/lib/epub"),
  "lib/fb2.ts": () => import("../src/lib/fb2"),
  "lib/fileReaders.ts": () => import("../src/lib/fileReaders"),
  "lib/kindle.ts": () => import("../src/lib/kindle"),
  "lib/kobo.ts": () => import("../src/lib/kobo"),
  "lib/mobi.ts": () => import("../src/lib/mobi"),
  "lib/moonReader.ts": () => import("../src/lib/moonReader"),
  "lib/pdf.ts": () => import("../src/lib/pdf"),
  "lib/sqlite.ts": () => import("../src/lib/sqlite"),
  "lib/takeout.ts": () => import("../src/lib/takeout"),
  "lib/zip.ts": () => import("../src/lib/zip"),
};

/**
 * The module below `src/` a relative specifier in `from` names, or `null` for
 * one outside the source modules: a package, or a stylesheet.
 *
 * Tries the specifier as written, then with `.ts` or `.tsx`, then as a
 * directory's `index`, which is every form the tree resolves today.
 */
function resolved(from: string, specifier: string): string | null {
  if (!specifier.startsWith(".")) return null;
  const stem = resolvePath(from.split("/").slice(0, -1), specifier).join("/");
  const modules = sourceModules();
  return (
    [stem, `${stem}.ts`, `${stem}.tsx`, `${stem}/index.ts`, `${stem}/index.tsx`]
      .filter((one) => /\.tsx?$/.test(one))
      .find((one) => one in modules) ?? null
  );
}

/** What one module imports statically and what it imports lazily. */
function edgesOf(path: string): { statically: string[]; lazily: string[] } {
  const statically: string[] = [];
  const lazily: string[] = [];
  const ast = parseAst(sourceText(path), {
    lang: path.endsWith(".tsx") ? "tsx" : "ts",
  });
  walk(ast, (node) => {
    const source = isNode(node.source) ? node.source : null;
    if (
      (node.type === "ImportDeclaration" && node.importKind !== "type") ||
      ((node.type === "ExportNamedDeclaration" ||
        node.type === "ExportAllDeclaration") &&
        node.exportKind !== "type")
    ) {
      if (source?.type !== "Literal") return;
      const target = resolved(path, String(source.value));
      if (target !== null) statically.push(target);
      return;
    }
    if (node.type !== "ImportExpression") return;
    // A specifier that is not a plain string cannot be resolved here, so it
    // refuses rather than leaving its module cold inside somebody's `waitFor`.
    if (source?.type !== "Literal" || typeof source.value !== "string") {
      throw new Error(`src/${path} has an import() this walk cannot resolve`);
    }
    const target = resolved(path, source.value);
    if (target === null) {
      throw new Error(
        `src/${path} lazily imports ${source.value}, not a module`,
      );
    }
    lazily.push(target);
  });
  return { statically, lazily };
}

/** Every module `path` can reach through an `import()`, by any route, sorted. */
export function lazyImportsOf(path: string): string[] {
  const visited = new Set<string>([path]);
  const pending = [path];
  const lazy = new Set<string>();
  while (pending.length > 0) {
    const { statically, lazily } = edgesOf(pending.pop()!);
    for (const module of lazily) lazy.add(module);
    for (const module of [...statically, ...lazily]) {
      if (visited.has(module)) continue;
      visited.add(module);
      pending.push(module);
    }
  }
  return [...lazy].toSorted();
}

/** The modules `path` reaches lazily that have no loader above. */
export function unloadable(path: string): string[] {
  return lazyImportsOf(path).filter((module) => !(module in LOADERS));
}

/**
 * Load every module `path` reaches lazily. **Skips one with no loader rather
 * than throwing**, so the file's own test names it instead of a failed hook
 * hiding every test in the file.
 */
export async function loadLazyImportsOf(path: string): Promise<void> {
  await Promise.all(
    lazyImportsOf(path).flatMap((module) => LOADERS[module]?.() ?? []),
  );
}
