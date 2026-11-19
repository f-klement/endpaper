/**
 * The third party notices for what the browser is served, collected from the
 * build that produced it.
 *
 * Two halves, because the facts live in two places:
 *
 * 1. `bundleRecorder()`, a Vite plugin in `vite.config.ts`, records every
 *    `node_modules` package with a module or an asset in the bundle, the
 *    application's and each worker's, and every file the bundle emitted. It
 *    writes `RECORD` when the application's bundle is written.
 * 2. `collectNotices`, run by `scripts/collect-notices.ts` after the build,
 *    accounts for **every file in `dist/`**: emitted by the bundle, copied from
 *    `public/`, or written by a build tool from its own template (the service
 *    worker). A file it cannot account for fails it, and so does a package
 *    with no licence text. It writes the packages and their texts as JSON for
 *    `docker/notices.py`, which formats the image's one notices file.
 *
 * **Why the module graph and not `package.json`.** The `dependencies` closure
 * both overshoots and misses. It names packages tree shaken out of the bundle,
 * and it misses code a build tool writes in: the Workbox runtime in the service
 * worker, Vite's preload helper, Tailwind's preflight in the stylesheet. None
 * of those is a dependency, all of them ship.
 *
 * **The bound: a file is accounted for, not every byte in it.** A tool that
 * starts injecting a helper of a new package into a file the bundle already
 * emits is not seen. `INJECTED` names the injections known today.
 */
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { Plugin, Rollup } from "vite";

const ROOT = fileURLToPath(new URL("..", import.meta.url)).replace(/\/$/, "");

/** Where the plugin leaves its record: a tool cache, never shipped, never committed. */
export const RECORD = "node_modules/.endpaper/bundle.json";

interface BundleRecord {
  /** Package directories relative to the frontend root, `node_modules/...`. */
  packages: string[];
  /** Module ids outside any file: `\0vite/preload-helper.js` and the like. */
  virtual: string[];
  /** Every file name the bundles emitted, relative to `dist/`. */
  files: string[];
}

/**
 * The package directory a module id lives in, relative to the frontend root,
 * or null for the application's own code. The innermost `node_modules` wins,
 * so a nested copy is credited rather than the hoisted one.
 */
export function packageOf(id: string, root: string): string | null {
  const path = id.split("?")[0]!;
  const at = path.lastIndexOf("/node_modules/");
  if (at < 0) return null;
  const rest = path.slice(at + "/node_modules/".length).split("/");
  const name = rest[0]!.startsWith("@") ? rest.slice(0, 2) : rest.slice(0, 1);
  const directory = path.slice(0, at) + "/node_modules/" + name.join("/");
  return directory.startsWith(root + "/")
    ? directory.slice(root.length + 1)
    : directory;
}

/**
 * Packages whose code a bundle carries under a virtual module id, by prefix.
 * An id with no row here fails the collection: whose code it is has to be
 * decided by somebody reading it, not guessed.
 */
const VIRTUAL: readonly (readonly [prefix: string, owner: string])[] = [
  ["\0vite/", "vite"],
  ["\0rolldown/", "rolldown"],
];

/** The package a virtual module id's code belongs to, or null when unknown. */
export function ownerOfVirtual(id: string): string | null {
  return VIRTUAL.find(([prefix]) => id.startsWith(prefix))?.[1] ?? null;
}

/**
 * The plugin pair: one for the application's bundle and a factory for the
 * worker bundles, sharing one record. Vite bundles a worker while it
 * transforms the module that names it, so every worker has been read before
 * the application's bundle is written and the record with it.
 */
export function bundleRecorder(): { main: Plugin; worker: () => Plugin } {
  const packages = new Set<string>();
  const virtual = new Set<string>();
  const files = new Set<string>();
  const record = (id: string): void => {
    if (id.startsWith("\0")) {
      virtual.add(id);
      return;
    }
    const owner = packageOf(id, ROOT);
    if (owner !== null) packages.add(owner);
  };
  const take = (bundle: Rollup.OutputBundle): void => {
    for (const output of Object.values(bundle)) {
      files.add(output.fileName);
      const sources =
        output.type === "chunk" ? output.moduleIds : output.originalFileNames;
      sources.forEach(record);
    }
  };
  // The application's bundle is read in `writeBundle`, not `generateBundle`:
  // the shell, `index.html`, is emitted by Vite's own `generateBundle`, which
  // runs after this plugin's. A worker's bundle is generated and never
  // written, so it is read where it is generated.
  const main: Plugin = {
    name: "endpaper:bundle-recorder",
    apply: "build",
    writeBundle(_options, bundle) {
      take(bundle);
      const path = join(ROOT, RECORD);
      mkdirSync(dirname(path), { recursive: true });
      const sorted = (set: Set<string>): string[] => [...set].sort();
      const written: BundleRecord = {
        packages: sorted(packages),
        virtual: sorted(virtual),
        files: sorted(files),
      };
      writeFileSync(path, JSON.stringify(written, null, 2));
    },
  };
  return {
    main,
    worker: () => ({
      name: "endpaper:bundle-recorder-worker",
      apply: "build",
      generateBundle(_options, bundle) {
        take(bundle);
      },
    }),
  };
}

/** The Workbox packages a built worker file carries, by the version stamp each module leaves. */
export function workboxPackages(source: string): string[] {
  const names = [...source.matchAll(/workbox:([a-z-]+):\d/g)].map(
    (match) => `workbox-${match[1]!}`,
  );
  return [...new Set(names)].sort();
}

/**
 * Files the PWA plugin writes into `dist/` from its own templates, some after
 * the bundle and some into it, and whose code they carry. `packages` resolve from `from`, the package that pulls them
 * in, the way Node would resolve them. A worker chunk that names no Workbox
 * module fails: it means the stamp this reads has gone, not that it is empty.
 */
interface WrittenByTool {
  file: RegExp;
  from: string;
  packages: (source: string) => string[];
}

const WRITTEN_BY_TOOLS: readonly WrittenByTool[] = [
  {
    // Workbox's service worker template, and the module loader it is wrapped in.
    file: /^sw\.js$/,
    from: "vite-plugin-pwa",
    packages: () => ["workbox-build", "@trickfilm400/rollup-plugin-off-main-thread"],
  },
  {
    file: /^workbox-[0-9a-f]+\.js$/,
    from: "workbox-build",
    packages: workboxPackages,
  },
  {
    // The registration script the plugin writes and the shell loads.
    file: /^registerSW\.js$/,
    from: ".",
    packages: () => ["vite-plugin-pwa"],
  },
];

/**
 * Code a tool writes into a file the bundle emits, with no module of its own,
 * found by the banner it leaves.
 */
const INJECTED: readonly (readonly [banner: RegExp, owner: string])[] = [
  [/\/\*! tailwindcss v/, "tailwindcss"],
];

/**
 * Packages that publish no licence file, and the notice this repository
 * ships for them instead, under `public/`. A row whose package has left the
 * bundle fails, so the table cannot outlive what it describes.
 */
const SHIPPED_NOTICE: Readonly<Partial<Record<string, string>>> = {
  "tesseract.js-core": "licences/tesseract.txt",
  "@tesseract.js-data/eng": "licences/tesseract.txt",
};

/**
 * Whether a file in a package's root is one of its licence or notice texts.
 * `AUTHORS` is not: it names people and grants nothing, so a package carrying
 * only that still has no licence text and fails.
 */
export function isLicenceFile(name: string): boolean {
  return /^(un)?(licen[cs]e|copying|copyright|notice)([.-][\w.-]*)?$/i.test(
    name,
  );
}

/**
 * The licence texts among a package root's files, in name order. A file that
 * is empty or only whitespace is no licence text: counted, it would let a
 * package with nothing to show pass the check that fails the build.
 */
export function licenceTexts(
  names: string[],
  read: (name: string) => string,
): { file: string; text: string }[] {
  return names
    .filter(isLicenceFile)
    .sort()
    .map((file) => ({ file, text: read(file) }))
    .filter(({ text }) => text.trim() !== "");
}

/**
 * Which files in `dist/` nothing accounts for. `files` is relative to `dist/`;
 * a file is accounted for when the bundle emitted it, when `public/` holds it
 * at the same path, or when a `WRITTEN_BY_TOOLS` row names it.
 */
export function unaccounted(
  files: readonly string[],
  emitted: ReadonlySet<string>,
  copied: ReadonlySet<string>,
): string[] {
  return files.filter(
    (file) =>
      !emitted.has(file) &&
      !copied.has(file) &&
      !WRITTEN_BY_TOOLS.some((row) => row.file.test(file)),
  );
}

function filesUnder(directory: string, prefix = ""): string[] {
  if (!existsSync(directory)) return [];
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? filesUnder(join(directory, entry.name), `${prefix}${entry.name}/`)
      : [`${prefix}${entry.name}`],
  );
}

/** Node's resolution of a package name from a directory, upward. */
function resolvePackage(name: string, from: string): string | null {
  for (let directory = from; ; directory = dirname(directory)) {
    const candidate = join(directory, "node_modules", name);
    if (existsSync(join(candidate, "package.json"))) return candidate;
    if (dirname(directory) === directory) return null;
  }
}

interface Notice {
  name: string;
  version: string;
  licence: string;
  texts: { file: string; text: string }[];
  /** A notice this repository serves for the package, as a path under the site root. */
  shipped: string | null;
}

function noticeOf(directory: string, failures: string[]): Notice {
  const manifest = JSON.parse(
    readFileSync(join(directory, "package.json"), "utf8"),
  ) as { name: string; version: string; license?: unknown };
  const texts = licenceTexts(
    readdirSync(directory, { withFileTypes: true })
      .filter((entry) => entry.isFile())
      .map((entry) => entry.name),
    (file) => readFileSync(join(directory, file), "utf8"),
  );
  const shipped = SHIPPED_NOTICE[manifest.name] ?? null;
  if (shipped !== null && !existsSync(join(ROOT, "public", shipped))) {
    failures.push(`${manifest.name}: its shipped notice public/${shipped} is missing`);
  }
  if (texts.length === 0 && shipped === null) {
    failures.push(
      `${manifest.name} ${manifest.version}: no licence text in ${directory} ` +
        "and no row in SHIPPED_NOTICE",
    );
  }
  return {
    name: manifest.name,
    version: manifest.version,
    licence: typeof manifest.license === "string" ? manifest.license : "",
    texts,
    shipped: shipped === null ? null : `/${shipped}`,
  };
}

/** Every package whose code `dist/` carries, as directories, or the failures that stop it. */
function shippedPackages(dist: string, failures: string[]): Set<string> {
  const path = join(ROOT, RECORD);
  if (!existsSync(path)) {
    failures.push(`no ${RECORD}: run the build first, it writes the record`);
    return new Set();
  }
  const record = JSON.parse(readFileSync(path, "utf8")) as BundleRecord;
  const files = filesUnder(dist);
  const present = new Set(files);
  for (const file of record.files) {
    if (!present.has(file)) failures.push(`the record names ${file}, which dist/ lacks: a stale record`);
  }
  for (const file of unaccounted(files, new Set(record.files), new Set(filesUnder(join(ROOT, "public"))))) {
    failures.push(`dist/${file} came from nowhere this collector knows`);
  }
  const directories = new Set(record.packages.map((p) => join(ROOT, p)));
  const require = (name: string, from: string, why: string): void => {
    const found = resolvePackage(name, from);
    if (found === null) failures.push(`${why} names ${name}, which does not resolve`);
    else directories.add(found);
  };
  for (const id of record.virtual) {
    const owner = ownerOfVirtual(id);
    if (owner === null) failures.push(`no owner for the virtual module ${JSON.stringify(id)}`);
    else require(owner, ROOT, `the virtual module ${JSON.stringify(id)}`);
  }
  for (const file of files) {
    const row = WRITTEN_BY_TOOLS.find((candidate) => candidate.file.test(file));
    const source = /\.(js|css|html)$/.test(file) ? readFileSync(join(dist, file), "utf8") : "";
    if (row !== undefined) {
      const from = resolvePackage(row.from, ROOT) ?? ROOT;
      const named = row.packages(source);
      if (named.length === 0) failures.push(`dist/${file} names no package its rule expects`);
      for (const name of named) require(name, row.from === "." ? ROOT : from, `dist/${file}`);
    }
    for (const [banner, owner] of INJECTED) {
      if (banner.test(source)) require(owner, ROOT, `the banner in dist/${file}`);
    }
  }
  return directories;
}

/**
 * Collect the notices into `out` as JSON, or return every reason it could not.
 * Nothing is written unless nothing failed, so a gap never ships half a file.
 */
export function collectNotices(out: string): string[] {
  const failures: string[] = [];
  const directories = shippedPackages(join(ROOT, "dist"), failures);
  const notices = [...directories].map((d) => noticeOf(d, failures));
  const used = new Set(notices.map((notice) => notice.name));
  for (const name of Object.keys(SHIPPED_NOTICE)) {
    if (!used.has(name)) {
      failures.push(`SHIPPED_NOTICE names ${name}, which the bundle no longer carries`);
    }
  }
  if (failures.length > 0) return failures;
  notices.sort((a, b) => a.name.localeCompare(b.name) || a.version.localeCompare(b.version));
  mkdirSync(dirname(resolve(out)), { recursive: true });
  writeFileSync(resolve(out), JSON.stringify(notices, null, 1));
  return [];
}
