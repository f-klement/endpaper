/**
 * @vitest-environment node
 *
 * Touches no DOM and no bytes. The rule under test is strings in, structures
 * out, which is the property that lets a folder be written down rather than
 * built.
 */
/**
 * Tests for src/lib/audiobookGroups.ts.
 *
 * **The shapes are real ones**, from the Internet Archive's LibriVox
 * collection, and each is named where it decides a case. The household's
 * Calibre library holds no audio at all, so nothing here could be measured
 * against it.
 */

import { describe, expect, it } from "vitest";

import {
  groupAudiobooks,
  splitApart,
  type AudioFileNaming,
} from "../../src/lib/audiobookGroups";

/** One picked file, with the tags it carried. */
function picked(
  path: string,
  tags?: { album?: string; artist?: string; title?: string },
): AudioFileNaming {
  const parts = path.split("/");
  const name = parts.pop()!;
  return {
    key: `file:${path}`,
    name,
    folders: parts,
    tags: tags
      ? {
          album: tags.album ?? null,
          artists: tags.artist ? [tags.artist] : [],
          title: tags.title ?? null,
        }
      : null,
    whole: name.toLowerCase().endsWith(".m4b"),
  };
}

/** Every group as its title and how many files it claims. */
function shape(files: readonly AudioFileNaming[]) {
  return groupAudiobooks(files).map((group) => ({
    album: group.album,
    files: group.files.length,
    by: group.by,
  }));
}

describe("the grouping rule", () => {
  it("makes one book of a folder of chapter files that name one album", () => {
    // **The folder as `robinson_crusoe_librivox` publishes it**: 20 chapters at
    // two bitrates, so 40 files, every one of them `TALB='Robinson Crusoe'`.
    // One row rather than forty is the whole ticket, and the duplicate chapters
    // need no rule of their own because both copies name the same album.
    const files = Array.from({ length: 20 }, (_, index) => [
      `robinson_crusoe_${index + 1}_defoe.mp3`,
      `robinson_crusoe_${index + 1}_defoe_64kb.mp3`,
    ]).flatMap((names, chapter) =>
      names.map((name) =>
        picked(`Robinson Crusoe/${name}`, {
          album: "Robinson Crusoe",
          artist: "Daniel Defoe",
          title: `Chapter ${chapter + 1}`,
        }),
      ),
    );

    expect(shape(files)).toEqual([
      { album: "Robinson Crusoe", files: 40, by: "album" },
    ]);
  });

  it("makes one book of the two M4B halves of one recording", () => {
    // LibriVox splits a long book into parts, which carry one `©alb` between
    // them and a `©nam` each.
    const files = [
      picked("Robinson Crusoe/RobinsonCrusoePart1_librivox.m4b", {
        album: "Robinson Crusoe",
        title: "Robinson Crusoe Part 1",
      }),
      picked("Robinson Crusoe/RobinsonCrusoePart2_librivox.m4b", {
        album: "Robinson Crusoe",
        title: "Robinson Crusoe Part 2",
      }),
    ];

    expect(shape(files)).toEqual([
      { album: "Robinson Crusoe", files: 2, by: "album" },
    ]);
  });

  it("keeps a collection of separate works together, with every author", () => {
    // `short_story_029_0805_librivox`: ten works by ten writers in one folder
    // under one album. It is one audiobook, and taking the first artist would
    // file nine of them under Guy de Maupassant.
    const writers = [
      "Guy de Maupassant",
      "Anton Chekhov",
      "Lord Dunsany",
      "Saki",
      "Mark Twain",
      "William Caine",
      "James Joyce",
      "Kate Chopin",
      "Beatrix Potter",
      "Israel Zangwill",
    ];
    const files = writers.map((writer, index) =>
      picked(`Short Story Collection 029/shortstory029_${index}.mp3`, {
        album: "LibriVox Short Story Collection Vol. 029",
        artist: writer,
      }),
    );

    const groups = groupAudiobooks(files);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.authors).toEqual(writers);
  });

  it("makes a book of each untagged M4B in one folder", () => {
    // One file is one book for this container, so a folder of them is a folder
    // of books whatever the folder is called.
    const files = [
      picked("Terry Pratchett/Mort.m4b"),
      picked("Terry Pratchett/Guards Guards.m4b"),
    ];

    expect(shape(files)).toEqual([
      { album: null, files: 1, by: "file" },
      { album: null, files: 1, by: "file" },
    ]);
  });

  it("makes one book of the untagged chapter files in one folder", () => {
    // The honest floor for anything somebody ripped themselves: nothing in the
    // files said otherwise, and the member is shown the count and a split.
    const files = [
      picked("The Hobbit/01.mp3"),
      picked("The Hobbit/02.mp3"),
      picked("The Hobbit/03.mp3"),
    ];

    expect(shape(files)).toEqual([{ album: null, files: 3, by: "folder" }]);
  });

  it("keeps untagged chapter files in different folders apart", () => {
    const files = [
      picked("Library/The Hobbit/01.mp3"),
      picked("Library/The Hobbit/02.mp3"),
      picked("Library/Dune/01.mp3"),
    ];

    expect(shape(files)).toEqual([
      { album: null, files: 2, by: "folder" },
      { album: null, files: 1, by: "folder" },
    ]);
  });

  it("keeps a book split across two discs together", () => {
    // The two folders share the folder above them, which is what the shelf is
    // and the reason it is a level up rather than the file's own folder.
    const files = [
      picked("The Hobbit/CD1/01.mp3", { album: "The Hobbit" }),
      picked("The Hobbit/CD2/01.mp3", { album: "The Hobbit" }),
    ];

    expect(shape(files)).toEqual([
      { album: "The Hobbit", files: 2, by: "album" },
    ]);
  });

  it("splits an untagged book across its two disc folders", () => {
    // **The rule's other wrong direction, written down because there is no
    // merge for it.** Rule 2 keys on the file's own folder rather than on the
    // shelf, so two untagged disc folders are two candidates. Keying rule 2 on
    // the shelf instead would put every untagged book under one author folder
    // into one candidate, which is the larger mistake.
    const files = [
      picked("The Hobbit/CD1/01.mp3"),
      picked("The Hobbit/CD2/01.mp3"),
    ];

    expect(shape(files)).toEqual([
      { album: null, files: 1, by: "folder" },
      { album: null, files: 1, by: "folder" },
    ]);
  });

  it("keeps two books that share a title on different shelves apart", () => {
    // The case the shelf exists for. Both claim to be `Selected Poems` and
    // neither is the other.
    const files = [
      picked("Library/Blake/Selected Poems/01.mp3", {
        album: "Selected Poems",
      }),
      picked("Library/Rilke/Selected Poems/01.mp3", {
        album: "Selected Poems",
      }),
    ];

    expect(shape(files)).toEqual([
      { album: "Selected Poems", files: 1, by: "album" },
      { album: "Selected Poems", files: 1, by: "album" },
    ]);
  });

  it("reads two spellings of one album as one", () => {
    const files = [
      picked("a/01.mp3", { album: "The  Hobbit" }),
      picked("a/02.mp3", { album: "the hobbit " }),
    ];

    expect(shape(files)).toEqual([
      { album: "The  Hobbit", files: 2, by: "album" },
    ]);
  });

  it("cannot be made to read a forged separator inside an album", () => {
    // **The half the first version of this guard did not cover.** A folder name
    // cannot hold a NUL, and a tag is a stranger's bytes that can: an album of
    // `a`, NUL, `b` on the shelf `S` would otherwise forge the identity of a
    // different book on the shelf `S/a`. `normalise` is what stops it, and this
    // is the only place that says so.
    const files = [
      picked("S/own/01.mp3", { album: "a\u0000b" }),
      picked("S/a/own/01.mp3", { album: "b" }),
    ];

    expect(groupAudiobooks(files)).toHaveLength(2);
  });

  it("cannot be made to read a shelf name as part of an album", () => {
    // The evasion this refuses, spelled out: with any separator a folder name
    // may contain, shelf `a` with album `b c` and shelf `a`, `b` with album `c`
    // are the same string, and two unrelated books merge. The identity joins on
    // the one character no filesystem lets a name hold.
    const files = [
      picked("a/book/01.mp3", { album: "b c" }),
      picked("a/b/book/01.mp3", { album: "c" }),
    ];

    expect(groupAudiobooks(files)).toHaveLength(2);
  });

  it("splits a folder where only some of the chapters carry tags", () => {
    // **Written down because it is the rule's worst case, not its best.** A
    // file that named an album is on rule 1 and one that did not is on rule 2,
    // so a folder half of whose chapters lost their tags arrives as two
    // candidates. The member sees both, with the file count on each; there is
    // no merge, and the reason is in the module's own exclusions.
    const files = [
      picked("The Hobbit/01.mp3"),
      picked("The Hobbit/02.mp3", { album: "The Hobbit" }),
    ];

    expect(shape(files)).toEqual([
      { album: null, files: 1, by: "folder" },
      { album: "The Hobbit", files: 1, by: "album" },
    ]);
  });

  it("keeps only one file's own title, never a chapter name for a book", () => {
    const one = groupAudiobooks([picked("Mort.m4b", { title: "Mort" })]);
    const many = groupAudiobooks([
      picked("The Hobbit/01.mp3", { title: "Chapter 1" }),
      picked("The Hobbit/02.mp3", { title: "Chapter 2" }),
    ]);

    expect(one[0]?.title).toBe("Mort");
    expect(many[0]?.title).toBeNull();
  });

  it("does not let one artist per file build an unbounded author line", () => {
    const files = Array.from({ length: 500 }, (_, index) =>
      picked(`a/${index}.mp3`, { album: "One", artist: `Writer ${index}` }),
    );

    expect(groupAudiobooks(files)[0]?.authors).toHaveLength(20);
  });

  it("does not care how deep or how wide the folders are", () => {
    // A thousand siblings and a deep nest are both a member's own disk, and
    // neither is a shape this has an opinion about.
    const deep = "a/".repeat(200);
    const files = [
      ...Array.from({ length: 1000 }, (_, index) =>
        picked(`wide/${index}.mp3`, { album: "One" }),
      ),
      picked(`${deep}b.mp3`, { album: "Two" }),
    ];

    expect(shape(files)).toEqual([
      { album: "One", files: 1000, by: "album" },
      { album: "Two", files: 1, by: "album" },
    ]);
  });
});

describe("splitting a candidate apart", () => {
  it("files each part as its own book", () => {
    const [group] = groupAudiobooks([
      picked("Mixed/one.mp3", { album: "Mixed", title: "One" }),
      picked("Mixed/two.mp3", { album: "Mixed", title: "Two" }),
    ]);

    expect(splitApart(group!).map((part) => part.files.length)).toEqual([1, 1]);
  });

  it("drops the album the member has just rejected", () => {
    // Keeping it would name every one of them after a record they said was
    // wrong, so what is left is each file's own title.
    const [group] = groupAudiobooks([
      picked("Mixed/one.mp3", { album: "Mixed", title: "One" }),
      picked("Mixed/two.mp3", { album: "Mixed", title: "Two" }),
    ]);

    expect(splitApart(group!).map((part) => [part.album, part.title])).toEqual([
      [null, "One"],
      [null, "Two"],
    ]);
  });

  it("keeps each part's own author", () => {
    const [group] = groupAudiobooks([
      picked("C/one.mp3", { album: "C", artist: "Saki" }),
      picked("C/two.mp3", { album: "C", artist: "Mark Twain" }),
    ]);

    expect(splitApart(group!).map((part) => part.authors)).toEqual([
      ["Saki"],
      ["Mark Twain"],
    ]);
  });
});
