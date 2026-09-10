/**
 * Where a member's own browser saw one of their book files.
 *
 * **Endpaper never receives the file, and this module is the whole of what it
 * does receive instead**: a root the member picked, the path beneath it, and
 * two things the browser already knew about the entry. No byte of the file is
 * read here and none is sent. `lib/epub.ts` carries the custody statement in
 * full, and it is about the file rather than about the destination.
 *
 * **A path is not the file, and it is not nothing either.** A folder name is a
 * member's own text and reaches every account that can see the book, which for
 * a rapid run is every member: `blankPending` files these public. The picker
 * says so before the press; this module's job is to send only what the browser
 * actually supplied.
 *
 * **What a client may claim and what only the server may say.** `root_label`,
 * `relative_path`, `root_confirmed`, `size_bytes` and `file_modified_at` are
 * this browser's claim. `created_at`, `confirmed_at` and `missing_since` are
 * the server's clock and are ignored on the way in, so nothing here sets one.
 * `docs/api.md` section "Digital references" is the contract.
 */

import type { DigitalReferenceIn } from "../api/generated/model";

/**
 * What this module is given, which is deliberately not the file.
 *
 * **Three scalars a browser filled in about a directory entry.** A `File` is
 * structurally one of these, so the caller hands one over unchanged, and this
 * type refuses to let this module **name** a read: under `strict`, with
 * `typecheck` in the gate, the build breaks rather than a test failing. This is
 * the one module in the family that sends anything at all.
 *
 * **What that is worth, said exactly, because the overclaim is tempting.** The
 * value at runtime is still a `File` carrying `arrayBuffer`, `slice`, `stream`
 * and `text`; nothing here erases them, and this project runs no linter that
 * bans `any`, so a read reached through `as any` or `as unknown` spells none of
 * the six words a guard could look for. **A cast naming the type does not
 * escape**: `as File` and `as Blob` each spell one of them, which is the
 * trigger the paragraph below rests on, so the evasion is narrower than "a
 * cast".
 *
 * **The stronger half is the one this narrowing did not remove.** It keeps this
 * module out of the derived reader population in `tests/houseRules.test.ts`,
 * whose rule refuses a module under `lib/` that names bytes and reaches the
 * network. This module still matches the network half, through its `from
 * "../api/..."` import. So the first time it names `File`, `Blob`,
 * `ArrayBuffer`, `Uint8Array`, `ReadableStream` or `DOMParser` in code it
 * re-enters that population and is an offender in the same run. It did not step
 * outside the rule, it stepped onto its trigger.
 *
 * **`webkitRelativePath` is spelled the vendor's way because it has to be.** A
 * `File` stops being structurally one of these under any other name, and that
 * assignability is what made the narrowing free: no caller and no fixture
 * moved. So the prefix is the obligation written where a caller cannot avoid
 * writing it.
 *
 * **What the narrowing gave up, stated because nothing downstream can check
 * it.** A `File` witnessed `root_confirmed: true`: its `webkitRelativePath` is
 * non empty only after a directory pick, so the constant below was justified by
 * the type. Any object literal satisfies this one, so it now rests on the
 * caller handing over a real directory entry. `docs/api.md` says the server
 * cannot enforce that half either, and `root_confirmed` exists precisely to
 * separate a browser that corroborated a root from a member who supplied one,
 * so a caller building one of these by hand is claiming corroboration nobody
 * gave. One call site today, and every fixture a real `File`.
 */
export interface PickedEntry {
  /** Relative to the folder the member chose, or empty for a bare pick. */
  readonly webkitRelativePath: string;
  readonly size: number;
  readonly lastModified: number;
}

/**
 * How wide `root_label` and `relative_path` may be, together and each.
 *
 * The host's `PATH_MAX` less the NUL and one separator.
 *
 * **One number answering two rules, and only one of them is in the schema.**
 * Each half declares it as a `maxLength`, which
 * `tests/lib/digitalReference.test.ts` recomputes from `openapi.json` rather
 * than restating. The pair is bounded at the same number by a model validator,
 * which no schema carries and nothing here can recompute: that half is stated,
 * the way `bookBounds.PLAUSIBLE_YEARS` is stated, and the two rules do not
 * imply each other. What stands in for the recomputation is the arm driving
 * the pair one character over the budget and the pair exactly on it.
 */
export const PATH_BUDGET = 4094;

/**
 * The largest `size_bytes` the contract takes.
 *
 * `Number.MAX_SAFE_INTEGER`, and it is that number for a reason about the wire
 * rather than about files: the field travels as a JSON number, and past this a
 * value does not survive being one. A `File.size` cannot reach it, so this
 * bound fires on nothing a browser produces and is here because the contract
 * has it.
 */
const MAX_SIZE = Number.MAX_SAFE_INTEGER;

/**
 * A timestamp the server will parse, or `null`.
 *
 * **Three ways `new Date(x).toISOString()` is not a timestamp**, and two of
 * them throw or are refused rather than reading oddly:
 *
 * * `lastModified` absent or not a number makes an invalid `Date`, and
 *   `toISOString` throws `RangeError` on one. Thrown from inside `addAll` it
 *   would mark a book that had just been created as failed, and a member would
 *   add it again into a duplicate.
 * * A year outside 1 to 9999. Past 9999 `toISOString` emits the expanded form,
 *   `+010000-01-01T00:00:00.000Z`, and the server answers 422 for that
 *   spelling. Below 1 there is no expanded form to see: `0000-01-01` is written
 *   as four digits like any other year and is the same 422, because Python's
 *   `MINYEAR` is 1. An extracted archive and a `touch -d` reach both ends.
 * * An entry whose modification time nobody recorded reads as the moment it was
 *   picked, which no check can tell from a real one. That one is sent, because
 *   it is what the browser says and the server stores a claim.
 *
 * `null` rather than an omission or a guess: the field is nullable, and a
 * reference with no date is a sighting that says one less thing.
 */
function modifiedAt(picked: PickedEntry): string | null {
  // `Number.isFinite` rather than a `typeof`: it answers false for `undefined`
  // too, which is the value a browser or a double that has no such property
  // gives, so one check covers both ways this is not a number.
  if (!Number.isFinite(picked.lastModified)) return null;
  const when = new Date(picked.lastModified);
  if (Number.isNaN(when.getTime())) return null;
  // **The year rather than its spelling, and the first draft bounded the
  // spelling.** `/^\d{4}-/` admits `0000-01-01T00:00:00.000Z`, which is the
  // four digit form and is still a 422: Python's `MINYEAR` is 1, so the server
  // takes `0001` and refuses `0000`. Reading the number closes the expanded
  // form and that year with one rule, where matching the shape closed one and
  // left the other one year lower.
  const year = when.getUTCFullYear();
  if (year < 1 || year > 9999) return null;
  return when.toISOString();
}

/** How long a string is to the server, which counts a Python `str`. */
function codePoints(value: string): number {
  return [...value].length;
}

/** The size the contract takes, or `null` where the browser gave no usable one. */
function sizeOf(picked: PickedEntry): number | null {
  const raw = picked.size;
  if (!Number.isInteger(raw)) return null;
  return raw >= 0 && raw <= MAX_SIZE ? raw : null;
}

/**
 * Where this file is, as the server takes it, or `null` where this browser
 * cannot honestly say.
 *
 * **`webkitRelativePath` is the whole input and it is relative to the folder
 * the member chose**, so nothing above that folder is in it: no absolute
 * prefix, no home directory, no drive letter. That is the same basis
 * `hooks.foldersOf` and `calibre.libraryPathOf` read it on.
 *
 * **The picked directory's own name is `root_label` and never part of
 * `relative_path`.** The browser leads the path with it, and this project
 * already contains both spellings, so the rule is written at the one site that
 * sends. Two clients disagreeing about it write two rows for one file, which is
 * the doubling the location identity exists to prevent. The server cannot
 * enforce it.
 *
 * **`null` rather than a guess, in four cases**, and the reason is one reason:
 * a reference is a claim about where a file is, and a claim this browser cannot
 * support is worse than no claim.
 *
 * * **A file picked one at a time carries no path at all.** There is no root,
 *   and no screen in which a member names one, so nothing is sent. This client
 *   therefore never sends `root_confirmed: false`: the flag's `false` is for a
 *   producer that has a root and did not watch a member confirm it.
 * * A path with no separator, or an empty half either side of the first one.
 *   Either half is 1 character at the least and the server answers 422.
 * * A pair over `PATH_BUDGET`. **Dropped and never cut**, which is the rule
 *   `bookBounds.ts` states for `location`: a value cut is a different value, and
 *   a path cut to fit names a different file or none. Not reachable through a
 *   POSIX `PATH_MAX`, which bounds the same path in bytes; a Windows path of
 *   32,767 UTF-16 units reaches it.
 * * A NUL in either half, which the server refuses and no filesystem produces.
 *   Checked because the contract has the rule, not because the arm fires.
 *
 * **What is sent is the raw text the browser gave.** A cleaned path names a
 * different file. The asymmetry to keep is that a value **rendered** on screen
 * goes through `fileName.plainName` first, which is where a bidirectional
 * override in a folder name is debris rather than a name.
 */
export function referenceFor(picked: PickedEntry): DigitalReferenceIn | null {
  const path = picked.webkitRelativePath;
  if (typeof path !== "string" || path === "") return null;

  const cut = path.indexOf("/");
  if (cut <= 0 || cut === path.length - 1) return null;
  const root = path.slice(0, cut);
  const beneath = path.slice(cut + 1);

  // **Counted in code points, never in UTF-16 units**, which is the trap
  // `bookBounds.ts` states at its own site and this one inherited by spelling
  // the count `.length`. The server counts a Python `str`, so `Books/` plus
  // 2044 astral characters plus `.epub` is 2054 there and 4098 here: a path the
  // server would have stored, dropped in silence. An `a.repeat()` fixture
  // cannot see it, which is why the arm below uses an astral character.
  if (codePoints(root) + codePoints(beneath) > PATH_BUDGET) return null;
  if (root.includes("\0") || beneath.includes("\0")) return null;

  return {
    root_label: root,
    relative_path: beneath,
    // A directory was picked and the browser supplied the structure under it,
    // which is exactly what this flag is for.
    root_confirmed: true,
    size_bytes: sizeOf(picked),
    file_modified_at: modifiedAt(picked),
  };
}
