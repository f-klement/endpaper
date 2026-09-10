# Reading a library off a device somebody owns

A Kobo, an Apple Books library, a Kindle desktop install, Adobe Digital Editions and several
reader applications each keep a catalogue on the member's own machine. Most of those
catalogues are SQLite.

**None of this is an integration with a company.** Each is a file the member already has on
hardware they own, read in their browser and never uploaded. No vendor supports these layouts
and any update may change one. Nothing here opens, decrypts or converts a protected file: it
reads catalogue metadata about what somebody owns.

## The question this page settles

Reading SQLite in a browser needs a WebAssembly engine of real size. Whether that is worth
carrying decides the whole family at once: if it is not, these stores become an export file
route or they do not ship.

**It is already carried, and a second store adds no engine bytes.**

What the engine weighs, how it is loaded and why only a session that opens an import card pays
for it are `frontend/src/lib/sqlite.ts`'s facts, stated in that module and deliberately not
restated here. The Calibre library import already ships it. What this page adds is the one thing
that decides the family: what a **second** reader over it costs.

## The measurement

Two production builds, `bun run build`, both exiting 0. Sizes do not vary by machine, so no
machine is named. The second build is this branch with the reader wired to a page, which no
commit carries, so the patch is here rather than described: apply it to a copy, build, compare.

```ts
// frontend/src/pages/ScanPage/hooks.ts, inside readFiles, after the first import
const device = files.find((one) => one.name === "KoboReader.sqlite");
if (device !== undefined) {
  const { openSqliteFile } = await import("../../lib/sqlite");
  const { readKoboLibrary } = await import("../../lib/kobo");
  const opened = await openSqliteFile(device);
  if (opened.ok) {
    const read = readKoboLibrary(opened.database);
    opened.database.close();
    if (read.ok) settle(pickedKey(device), {});
  }
}
```

That page is a second lazy importer of the engine, independent of the Calibre import card, which
is what the comparison is for.

| | one importer | two importers |
|---|---|---|
| the engine asset | one, sized in `sqlite.ts` | the same file, the same content hash |
| the engine's wrapper chunk | one | one, unchanged in size |
| `kobo-*.js`, the new reader | no such chunk | 2.53 kB, gzip 1.20 kB |
| the main chunk | 1,272.57 kB, gzip 340.09 kB | 1,272.96 kB, gzip 340.22 kB |

**A second SQLite backed store costs 1.20 kB gzipped for its reader, plus its own page code,
which was 0.13 kB here.** It costs no engine at all: the asset is byte identical across the two
builds and a second lazy importer shares the one wrapper chunk rather than emitting another.

**What this does not settle.** A store that is not SQLite. Adobe Digital Editions keeps an XML
catalogue and Apple Books keeps a plist beside its database, and neither needs an engine: each is
a separate measurement, and the plist one is owed before Apple Books can be called covered.

## What follows for a store reader

One reader per store, each a pure function from something that answers SQL to records, in the
shape `frontend/src/lib/calibre.ts` already has. `frontend/src/lib/sqlite.ts` opens the file,
bounds it and refuses to write to it; a reader believes nothing about the file it is handed.

**An unreadable store is one skipped source, never a broken import.** A vendor can change a
local schema in any update, so a reader that names a column believes a version. Every outcome is
a value in a closed union and none is a thrown error, which is what lets a member importing
several sources at once lose the one that moved and keep the rest. A device that is not one, a
device with nothing on it, and a device holding only rows the member does not own are three
different answers, because they are three different sentences to the person holding the file.
`frontend/tests/lib/kobo.test.ts` asserts that against databases built to break the reader, under
`an unreadable store is one skipped source, never a broken import`.

## The store that was built

Kobo, in `frontend/src/lib/kobo.ts`, chosen for being the best documented rather than the most
wanted: calibre's KoboTouch driver is a working implementation of the same read, so the schema
is verifiable from a primary source instead of from memory. That module carries the schema, its
provenance, and the fields a Kobo cannot supply.

**No Kobo device was read.** The schema and the test fixtures come from that driver, at the
commit and date the module names, and the fixtures are constructed rather than captured. What
that leaves open is whether real hardware carries a value none of this expects, which is the same
thing every paragraph above is about.
