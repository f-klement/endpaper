/**
 * The highlights in a KOReader sidecar, `metadata.<ext>.lua`, and the
 * fingerprint of the book file it sits beside.
 *
 * **Two shapes, both read.** Current KOReader writes one `annotations` array;
 * older versions wrote `bookmarks` and a `highlight` table keyed by page, and
 * KOReader converts them only when the book is next opened, so a book not
 * opened since still carries them. Where `annotations` is present it is the
 * whole truth, as it is to KOReader.
 *
 * **A page bookmark is not a highlight.** In `annotations` a highlight has a
 * `drawer`; in `bookmarks` it is `highlighted`. Bookmarks are counted, not
 * read.
 *
 * **Positions are passed on as identity, not interpreted.** A reflowable
 * book's are XPointer strings and pass through. A fixed layout book's are
 * coordinate tables, written here as one canonical string (keys sorted,
 * `key=value` joined by `;`), so the same mark reads the same way on every
 * import. Changing that spelling would make every such mark look new.
 *
 * **The time is KOReader's local wall clock with no zone**, passed through as
 * the sidecar wrote it.
 *
 * Nothing here reaches the network: the page sends what this returns.
 */

import {
  readLuaTable,
  type LuaKey,
  type LuaTable,
  type LuaValue,
} from "./luaTable";

/** One highlight as a request carries it. */
export interface SidecarHighlight {
  readonly pos0: string;
  readonly pos1: string;
  readonly text: string;
  readonly note: string | null;
  readonly chapter: string | null;
  readonly page: number | null;
  /** `YYYY-MM-DD HH:MM:SS` on the device's clock, or null. */
  readonly highlightedAt: string | null;
}

export type SidecarReading =
  | {
      readonly ok: true;
      /** `partial_md5_checksum`: what the book's file is matched by. */
      readonly partialMd5: string;
      /** `doc_props.title`, to name the sidecar to the member. */
      readonly title: string | null;
      readonly highlights: readonly SidecarHighlight[];
      /** Marks left out because a field is past what the server stores. */
      readonly oversized: number;
    }
  | {
      readonly ok: false;
      readonly reason: "unreadable" | "too-large" | "no-fingerprint";
    };

/**
 * The server's bounds (`models.HIGHLIGHT_*`, `KOREADER_POSITION_MAX`,
 * `MAX_PAGE_NUMBER_IN_A_BOOK`). A mark past one is left out and counted
 * rather than sent, so one long passage does not refuse the whole book.
 */
const TEXT_MAX = 10_000;
const NOTE_MAX = 10_000;
const CHAPTER_MAX = 1_000;
const POSITION_MAX = 4_096;
const PAGE_MAX = 100_000;

const DIGEST = /^[0-9a-f]{32}$/;
const WALL_CLOCK = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;

function table(value: LuaValue | undefined): LuaTable | null {
  return value instanceof Map ? value : null;
}

function text(value: LuaValue | undefined): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/** A table's positional values, `[1]` upwards, as Lua's `ipairs` reads them. */
function items(value: LuaValue | undefined): LuaTable[] {
  const found: LuaTable[] = [];
  const source = table(value);
  if (!source) return found;
  for (let index = 1; source.has(index); index += 1) {
    const item = table(source.get(index));
    if (item) found.push(item);
  }
  return found;
}

/** A position as one string: an XPointer as is, a coordinate table canonical. */
function position(value: LuaValue | undefined, page?: LuaKey): string | null {
  if (typeof value === "string") return value === "" ? null : value;
  if (typeof value === "number") return String(value);
  const coordinates = table(value);
  if (!coordinates) return null;
  const entries = new Map(coordinates);
  // An old fixed layout highlight's coordinates omit the page they are on;
  // KOReader adds it from the key the highlight was filed under.
  if (page !== undefined && !entries.has("page"))
    entries.set("page", page as LuaValue);
  const parts: string[] = [];
  for (const [key, inner] of [...entries].toSorted(([a], [b]) =>
    String(a) < String(b) ? -1 : String(a) > String(b) ? 1 : 0,
  )) {
    const rendered =
      inner instanceof Map ? `{${position(inner)}}` : String(inner);
    parts.push(`${String(key)}=${rendered}`);
  }
  return parts.join(";");
}

/** A page to add to coordinates: only a number is one, an XPointer is not. */
function pageKey(value: LuaValue | undefined): LuaKey | undefined {
  return typeof value === "number" ? value : undefined;
}

function pageOf(value: LuaValue | undefined): number | null {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= 1 &&
    value <= PAGE_MAX
    ? value
    : null;
}

/**
 * The time as written, if it is one. **A date or a time that does not exist
 * is dropped from its mark** rather than sent, since the server refuses the
 * whole sidecar for one; the mark then keys on its positions. KOReader writes
 * neither. Year 0 is refused too, as the server's calendar starts at 1.
 */
function wallClock(value: LuaValue | undefined): string | null {
  if (typeof value !== "string" || !WALL_CLOCK.test(value)) return null;
  const [year, month, day, hour, minute, second] = value
    .split(/[- :]/)
    .map(Number) as [number, number, number, number, number, number];
  // `setUTCFullYear` rather than `Date.UTC`, which reads years 0 to 99 as 1900
  // onwards and so would let year 0 through.
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  const real =
    year >= 1 &&
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day &&
    hour < 24 &&
    minute < 60 &&
    second < 60;
  return real ? value : null;
}

interface Draft {
  pos0: string | null;
  pos1: string | null;
  text: string | null;
  note: string | null;
  chapter: string | null;
  page: number | null;
  highlightedAt: string | null;
}

/** From the current `annotations` array: entries with a `drawer`. */
function fromAnnotations(annotations: LuaValue | undefined): Draft[] {
  return items(annotations)
    .filter((entry) => entry.get("drawer") != null)
    .map((entry) => ({
      pos0: position(entry.get("pos0")),
      pos1: position(entry.get("pos1")),
      text: text(entry.get("text")),
      note: text(entry.get("note")),
      chapter: text(entry.get("chapter")),
      page: pageOf(entry.get("pageno")),
      highlightedAt: wallClock(entry.get("datetime")),
    }));
}

/**
 * Whether an old bookmark's `text` is KOReader's own filler rather than a
 * note: empty, the highlighted passage again, or `<Page> <page> <passage> @
 * <datetime>`, whose first word is translated. KOReader's
 * `isBookmarkAutoText` is the rule this follows.
 */
function isAutoText(bookmark: LuaTable): boolean {
  const own = bookmark.get("text");
  const passage = bookmark.get("notes");
  if (typeof own !== "string" || own.trim() === "") return true;
  if (own === passage) return true;
  const datetime = bookmark.get("datetime");
  return (
    typeof passage === "string" &&
    typeof datetime === "string" &&
    own.endsWith(` ${passage} @ ${datetime}`)
  );
}

/**
 * From the older `bookmarks` and `highlight` pair. A highlighted bookmark
 * carries the passage in `notes` and the member's note in `text`. Highlights
 * from before 2014 were never added to the bookmarks, and KOReader imports
 * them from `highlight` unless `highlights_imported` says it already did.
 */
function fromBookmarks(sidecar: LuaTable): Draft[] {
  const drafts: Draft[] = items(sidecar.get("bookmarks"))
    .filter((bookmark) => bookmark.get("highlighted") === true)
    .map((bookmark) => ({
      // KOReader's own migration adds a fixed layout bookmark's page to its
      // positions, so the same mark reads the same after it has migrated.
      pos0: position(bookmark.get("pos0"), pageKey(bookmark.get("page"))),
      pos1: position(bookmark.get("pos1"), pageKey(bookmark.get("page"))),
      text: text(bookmark.get("notes")),
      note: isAutoText(bookmark) ? null : text(bookmark.get("text")),
      chapter: text(bookmark.get("chapter")),
      page: pageOf(bookmark.get("page")),
      highlightedAt: wallClock(bookmark.get("datetime")),
    }));
  if (sidecar.get("highlights_imported") === true) return drafts;

  const seen = new Set(
    drafts.map((draft) => `${draft.pos0}\u0000${draft.pos1}`),
  );
  for (const [page, marks] of table(sidecar.get("highlight")) ?? []) {
    for (const mark of items(marks)) {
      const pos0 = position(mark.get("pos0"), page);
      const pos1 = position(mark.get("pos1"), page);
      if (pos0 === null || seen.has(`${pos0}\u0000${pos1}`)) continue;
      seen.add(`${pos0}\u0000${pos1}`);
      drafts.push({
        pos0,
        pos1,
        text: text(mark.get("text")),
        note: null,
        chapter: text(mark.get("chapter")),
        page: pageOf(page as LuaValue),
        highlightedAt: wallClock(mark.get("datetime")),
      });
    }
  }
  return drafts;
}

function fits(draft: Draft): draft is Draft & {
  pos0: string;
  pos1: string;
  text: string;
} {
  return (
    draft.pos0 !== null &&
    draft.pos1 !== null &&
    draft.text !== null &&
    draft.pos0.length <= POSITION_MAX &&
    draft.pos1.length <= POSITION_MAX &&
    !draft.pos0.includes("\u0000") &&
    !draft.pos1.includes("\u0000") &&
    draft.text.length <= TEXT_MAX &&
    (draft.note === null || draft.note.length <= NOTE_MAX)
  );
}

/** The highlights a sidecar holds, or why it could not be read. */
export function readSidecar(source: string): SidecarReading {
  const read = readLuaTable(source);
  if (!read.ok)
    return {
      ok: false,
      reason: read.reason === "too-large" ? "too-large" : "unreadable",
    };
  const sidecar = read.table;
  const digest = sidecar.get("partial_md5_checksum");
  if (typeof digest !== "string" || !DIGEST.test(digest))
    return { ok: false, reason: "no-fingerprint" };

  const drafts =
    table(sidecar.get("annotations")) !== null
      ? fromAnnotations(sidecar.get("annotations"))
      : fromBookmarks(sidecar);
  // A mark with no passage or no position is not one the server can key, and
  // was never a highlight a member could see; it is dropped, not counted.
  const marks = drafts.filter(
    (draft) =>
      draft.pos0 !== null && draft.pos1 !== null && draft.text !== null,
  );
  const highlights = marks.filter(fits).map((draft): SidecarHighlight => ({
    pos0: draft.pos0,
    pos1: draft.pos1,
    text: draft.text,
    note: draft.note,
    chapter:
      draft.chapter !== null && draft.chapter.length <= CHAPTER_MAX
        ? draft.chapter
        : null,
    page: draft.page,
    highlightedAt: draft.highlightedAt,
  }));
  return {
    ok: true,
    partialMd5: digest,
    title: text(table(sidecar.get("doc_props"))?.get("title")),
    highlights,
    oversized: marks.length - highlights.length,
  };
}
