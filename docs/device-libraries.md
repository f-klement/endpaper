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

**What this did not settle, and what has since settled it.** Two questions were left open here
and both are now answered below, by measurement rather than by argument. A store that is not
SQLite needs no engine: `frontend/src/lib/kindle.ts` reads XML and loads nothing. And Apple Books'
plist is not read at all, because it is not part of the library the SQLite half holds. **Adobe
Digital Editions is the one still owed**, and it is XML, so the answer is expected rather than
known.

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

## The stores that were built

Kobo, in `frontend/src/lib/kobo.ts`, chosen for being the best documented rather than the most
wanted: calibre's KoboTouch driver is a working implementation of the same read, so the schema
is verifiable from a primary source instead of from memory. That module carries the schema, its
provenance, and the fields a Kobo cannot supply.

**No Kobo device was read.** The schema and the test fixtures come from that driver, at the
commit and date the module names, and the fixtures are constructed rather than captured. What
that leaves open is whether real hardware carries a value none of this expects, which is the same
thing every paragraph above is about.

Google Play Books, in `frontend/src/lib/takeout.ts`, is a store rather than a device and needs no
engine at all: a Takeout archive is a zip of EPUBs and their sidecars, so it reuses the EPUB
reader the scan page already ships. That module carries what one real export held on one day.

Apple Books, in `frontend/src/lib/appleBooks.ts`, is the second store over the engine and the one
that proved the engine argument: it costs its reader and nothing else. It reads the Core Data
store on a member's own Mac. **A member who copies only `BKLibrary-*.sqlite` and leaves its `-wal`
sidecar behind gets a store that reads as empty**, measured at 0 rows from the file alone against
3 with the sidecar, which is why the card says so where the copy is made rather than after it
fails.

Kindle for PC, in `frontend/src/lib/kindle.ts`, is the first store that is not SQLite, and it has
a section of its own below because what it settles is larger than the store.


## The plist half, measured

This page owed a measurement on Apple Books' plist before that store could be called covered. It
is owed no longer, and the answer is that no plist is read.

**The two are not two halves of one library.** Measured 2026-09-10 against
`github.com/tnahs/readstor` at `main`, which exports an Apple Books library and ships the
artefacts it is tested against: its macOS path opens `BKLibrary*.sqlite` and reads no plist, and
its iOS path reads `Books.plist` off a device over AFC. The SQLite store is the macOS library;
the plist is the iOS one.

**And the plist is a strict subset besides.** Its 15 keys carry four things a catalogue needs,
`Name`, `Artist`, `Publisher Unique ID` and `MIME Type`, and `ZBKLIBRARYASSET`, which has 86
columns and none of them named for an ISBN, carries all four and the year, the language and the
description as well. So the engine question settles Apple Books after all: one reader, no parser,
no bytes beyond a second SQLite reader's own.

**Whether that plist is binary or XML has two answers and neither had to be chosen.** readstor's
shipped iOS samples begin `<?xml`; a 2014 report of a macOS `Books.plist` under
`com.apple.BKAgentService` describes a binary one under different keys. A store nothing reads is a
format nothing has to parse.

## The store that is not SQLite

Kindle for PC, in `frontend/src/lib/kindle.ts`. The catalogue is `KindleSyncMetadataCache.xml`
under the app's `Cache/` directory and **it is XML**, so this store answers the question the
measurement above left open: a store that is not SQLite costs its reader and no engine at all,
because it never loads one. That is structural rather than a byte figure, and the figure is owed
once the reader is wired.

`book_asset.db` sits beside it, is SQLite, and is not a library: nine tables of its own, a
download ledger of asins, guids, sizes and local filenames, with no title, author or publisher in
any of them. **The SQLite file is the wrong file**, which is worth stating because the engine
already being carried is what would make it the first one somebody opened.

**The identifier is an ASIN and it is never an ISBN.** That is what this route was preferred for:
the Amazon account data export was refused on carrying neither. Measured over two published
captures totalling 1,032 entries, every one carries a distinct ASIN, a title and at least one
author, and none carries an ISBN, because the format has no element for one.

**Kindle for PC only, and that is the finding rather than the scope.** Windows writes this file on
every line of the app. The current Kindle for Mac does not write it at all: it keeps a different
database, and reaching a Mac library needs a second reader and its own judgement about where
metadata ends.

**Metadata only, and this is the store where that line is closest.** The protected book file sits
beside this catalogue. Nothing here reads, names or looks for it.

**No machine was read.** The schema and the fixtures come from those published captures, at the
blobs and dates the module names, and the fixtures are constructed rather than copied: the
captures are real people's libraries.

## Where a member picks one

`frontend/src/lib/stores.ts` is the registry, and a store is a row in it: what it is called, what
file to pick, what has not been tested, and an opener that loads its reader on demand. The card
is `LibrarySettingsPage/components/StoreImport.tsx`, which draws one row per entry and names no
store itself. **Adding a store is a row plus its reader**, which is the property this page's
engine measurement was taken to make affordable.

**A member picks several at once, and that is where the rule above becomes visible.** Each source
reads on its own, the totals are over the ones that read, and a source that could not be read is
named on its own row with the reason. `StoreFailure` is the union of every reader's reasons and
the card holds a total `Record` over it, so a reader that grows a reason without a sentence for a
member fails the build.

## tolino, and what naming it rests on

**The Kobo row names tolino and states its bound in the same sentence.** tolino runs Kobo derived
firmware and keeps the same database, and the KoboTouch driver this reader was built from handles
both devices through one path, which is why `kobo.ts` reads both spellings of `IsDownloaded`
through one predicate, calibre's own `in ('true', 1)`.

**No tolino has been read, and there is none to read.** Owner's decision, 2026-09-10: build from
the driver and say what that rests on. So the claim a member meets is that a tolino is expected
to work, was built from calibre's driver, and has never been run against one. A sentence claiming
support without that bound would convert an inference into a promise, which is the failure this
was written to avoid.

`kobo.ts` carries the two places a difference would surface, the schema 188 boolean and Adobe
fulfilled shop titles, beside the code each would break in. Not repeated here.
