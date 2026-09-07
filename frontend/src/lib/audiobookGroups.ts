/**
 * When sibling audio files are one book.
 *
 * **This is the whole of the audiobook ticket.** For every other format one
 * file is one book, and a picker that keeps that assumption turns one
 * forty chapter audiobook into forty rows: the mess is proportional to the size
 * of somebody's library, which makes the feature worse than not having it.
 *
 * **Strings in, structures out, and no `Blob` anywhere in this module.** The
 * bytes were read by `lib/audiobook.ts` and what arrives here is what the files
 * said. Keeping it that way is what makes the rule testable by writing down a
 * folder rather than by building one.
 *
 * ## The rule
 *
 * **A book's identity is what its files claim, and its folder is where the
 * claim is trusted.**
 *
 * 1. **A file that names an album** belongs to the book that album names, among
 *    the files on the same **shelf**.
 * 2. **A file that names no album, in a track container**, belongs to the book
 *    its own folder is.
 * 3. **A file that names no album, in a book container**, is a book on its own.
 *
 * **The shelf is the folder one level above the file's own folder**, and it is
 * the only part of this that is a choice rather than a reading. The album
 * already says which book; the shelf is there so that two different books that
 * happen to share a title do not merge, and one level up is where a library on
 * disk puts an author, a series or its own root. It is also what keeps a book
 * **that named an album** split across `Book/CD1` and `Book/CD2` together,
 * since those share it.
 *
 * ## What it was measured against
 *
 * The household's Calibre library holds no audio at all, so the corpus for this
 * rule is four LibriVox items, which that collection publishes as public domain
 * by its own policy and which are exactly the shapes this rule is about. The
 * reader's corpus is wider and `lib/audiobook.ts` describes its own.
 *
 * | shape, from real items | what the rule does |
 * |---|---|
 * | 40 chapter MP3s, 20 chapters at two bitrates, one `TALB` (`robinson_crusoe_librivox`) | one candidate |
 * | `Part 1.m4b` and `Part 2.m4b`, one `©alb` | one candidate |
 * | 10 works, one folder, one album, ten artists (`short_story_029_0805_librivox`) | one candidate, ten authors |
 * | a folder of untagged `.m4b` | one candidate each, by rule 3 |
 *
 * **A published LibriVox folder holds every chapter twice**, at two bitrates,
 * and that is a file count rather than a chapter count: the numbers above are
 * files, because files are what the member picks and what the row counts. The
 * duplicates need no rule of their own, since both copies name the same album
 * and land in the same candidate.
 *
 * ## The exclusions, because they are real
 *
 * **A folder of untagged unrelated MP3s is one candidate.** Rule 2 says so, and
 * it is the honest floor: nothing in those files said otherwise. It is why the
 * member is shown the file count and offered a split before anything is added.
 *
 * **Files picked one at a time carry no folder at all**, so untagged ones are
 * on one nameless folder and become one candidate. That is the right default
 * for the ordinary case, which is somebody selecting a book's chapters out of a
 * dialog, and the split is there for the other one.
 *
 * **Two different books on one shelf sharing an album name merge**, and there
 * is no signal here that could separate them: they claim to be the same book.
 *
 * **A book whose own files disagree about their album is several candidates**,
 * and there is no merge to undo that. Merging would be the member asserting
 * something the files deny, and the resulting books are editable.
 *
 * **An untagged book split across two disc folders is two candidates**, because
 * rule 2 keys on the file's own folder and not on the shelf. Keying it on the
 * shelf instead would merge every untagged book under one author folder into
 * one, which is the larger mistake; this is the price of refusing it, and there
 * is no merge for it either.
 */

import type { AudioTags } from "./audiobook";

/** One picked audio file, as the grouping rule may see it. */
export interface AudioFileNaming {
  /** Identity in the queue, and what dedup is decided on. Never content. */
  key: string;
  name: string;
  /** Enclosing folders, outermost first. Empty for a file picked on its own. */
  folders: readonly string[];
  /** What the file said, or null when it said nothing readable. */
  tags: AudioTags | null;
  /** True when one file of this kind is a whole book, which is `.m4b`. */
  whole: boolean;
  /** Why this one file said nothing, if it said nothing. */
  note?: string;
}

/** Which of the three rules put a group together, so the member can be told. */
export type GroupedBy = "album" | "folder" | "file";

/** One candidate book, and the files it was made of. */
export interface AudiobookGroup {
  /** The member files, in the order they were picked. Never empty. */
  files: readonly AudioFileNaming[];
  by: GroupedBy;
  /** The album as the first file spelled it, or null when none named one. */
  album: string | null;
  /**
   * Every distinct artist across the group, in the order first seen.
   *
   * **Distinct rather than the first**, because a collection is one audiobook
   * by ten writers: `short_story_029_0805_librivox` is one album whose ten
   * files carry ten different `TPE1` values, and taking the first would file
   * nine of them under Guy de Maupassant.
   */
  authors: readonly string[];
  /**
   * The one file's own title, where the group is one file.
   *
   * Null for a group of several, where a file's own title is a chapter name and
   * would be a worse title than the folder's. Set even where that one file also
   * named an album, which `album` then wins over: the two are separate answers
   * and this one is what a split falls back to.
   */
  title: string | null;
}

/**
 * How many distinct artists a group carries into its author line.
 *
 * **A bound on the value as well as on the work, which is worth saying because
 * the first draft here denied it.** Twenty ordinary names join to about 200
 * characters, well inside the 500 `bookBounds.TEXT_CEILINGS.author` allows, so
 * a collection by twenty five writers loses five of them here rather than at
 * the ceiling. That is the trade: an anthology names as many authors as a
 * reader will read, and a pick of ten thousand files each naming a different
 * artist cannot make this build a list per group without a stop in it.
 */
const MAX_AUTHORS = 20;

/**
 * The picked audio files, as candidate books.
 *
 * Groups come back in the order their first file was picked, and the files
 * inside one keep their pick order, which for a folder pick is the order the
 * browser walked the directory.
 */
export function groupAudiobooks(
  files: readonly AudioFileNaming[],
): AudiobookGroup[] {
  const groups = new Map<string, AudioFileNaming[]>();
  const rules = new Map<string, GroupedBy>();

  for (const file of files) {
    const [identity, by] = identityOf(file);
    const existing = groups.get(identity);
    if (existing) existing.push(file);
    else {
      groups.set(identity, [file]);
      rules.set(identity, by);
    }
  }

  return [...groups].map(([identity, members]) =>
    describe(members, rules.get(identity)!),
  );
}

/**
 * Which book this one file belongs to, and which rule said so.
 *
 * **The parts are joined with a NUL**, which no filesystem lets a folder name
 * hold, so no folder name can be spelled to look like an album.
 *
 * **The album is the operand that could carry one, and `normalise` is what
 * stops it.** A tag is a stranger's bytes and nothing about a filesystem
 * applies to it: an album of `a<NUL>b` on the shelf `S` would forge the identity
 * of a different book on the shelf `S/a`. `lib/audiobook.ts` also happens to
 * map control characters to a space, which made this unreachable through that
 * reader and stated nowhere; the defence belongs in the module whose identity
 * it is.
 */
function identityOf(file: AudioFileNaming): [string, GroupedBy] {
  const album = normalise(file.tags?.album ?? "");
  if (album !== "")
    return [`album\u0000${shelfOf(file)}\u0000${album}`, "album"];
  if (!file.whole)
    return [`folder\u0000${file.folders.join("\u0000")}`, "folder"];
  return [`file\u0000${file.key}`, "file"];
}

/**
 * The folder above the file's own folder.
 *
 * Empty for a file picked on its own and for one at the top of the folder that
 * was picked, both of which is right: a member who pointed at one book's folder
 * has already said everything under it is on one shelf.
 */
function shelfOf(file: AudioFileNaming): string {
  return file.folders.slice(0, -1).join("\u0000");
}

/** Casefolded, whitespace collapsed, and composed so that two spellings meet. */
function normalise(value: string): string {
  return (
    value
      .normalize("NFC")
      // Control characters included, and the NUL among them is load bearing: it
      // is the separator the identity is joined on. See `identityOf`.
      .replace(/[\p{Cc}\p{Zl}\p{Zp}]/gu, " ")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase()
  );
}

function distinctArtists(files: readonly AudioFileNaming[]): string[] {
  const authors: string[] = [];
  for (const file of files) {
    for (const artist of file.tags?.artists ?? []) {
      const value = artist.trim();
      if (value === "" || authors.length >= MAX_AUTHORS) continue;
      if (!authors.some((seen) => normalise(seen) === normalise(value))) {
        authors.push(value);
      }
    }
  }
  return authors;
}

function describe(files: AudioFileNaming[], by: GroupedBy): AudiobookGroup {
  return {
    files,
    by,
    album: files.find((file) => file.tags?.album)?.tags?.album ?? null,
    authors: distinctArtists(files),
    // Only where the group is one file. A chapter file's own title is the
    // chapter, and "Chapter 1" is a worse name for a book than its folder.
    title: files.length === 1 ? (files[0]!.tags?.title ?? null) : null,
  };
}

/**
 * The same files, one book each.
 *
 * What the member presses when the rule put together files that are not one
 * book. **It is not the only direction the rule can be wrong in**, and the
 * module's exclusions name the other: files that disagree about their album,
 * and an untagged book split across two disc folders, both arrive as several
 * candidates and there is no merge. This undoes the direction that has one.
 *
 * **The shared album does not survive the press.** The member has just said
 * these are not one book, so keeping it would name every one of them after a
 * record they have rejected. What is left is each file's own title, and under
 * that its name.
 */
export function splitApart(group: AudiobookGroup): AudiobookGroup[] {
  return group.files.map((file) => ({
    files: [file],
    by: "file" as const,
    album: null,
    authors: distinctArtists([file]),
    title: file.tags?.title ?? null,
  }));
}
