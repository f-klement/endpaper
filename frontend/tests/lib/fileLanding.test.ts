/**
 * Tests for src/lib/fileLanding.ts: the holder lookup and one landing, with
 * every request a stub. What each page makes of a landing is its own hook's
 * test.
 */

import { describe, expect, it, vi } from "vitest";

import {
  BookFormat,
  type AskedFileIn,
  type DigitalReferenceIn,
  type HolderOut,
  type HoldersOut,
} from "../../src/api/generated/model";
import { ApiError } from "../../src/api/mutator";
import {
  askWhoHolds,
  countLandings,
  FILES_PER_LOOKUP,
  land,
  reportEach,
  type Held,
  type LandingPorts,
  type LandingRequest,
} from "../../src/lib/fileLanding";
import { boundOf, propertiesOf } from "../committedSchema";

/** A reference to `path` under the picked folder `Books`. */
function at(path: string): DigitalReferenceIn {
  return { root_label: "Books", relative_path: path, root_confirmed: true };
}

/** A request for one EPUB book, its holder answer given. */
function request(
  held: Held | null | undefined,
  fields: Partial<LandingRequest<string>> = {},
): LandingRequest<string> {
  return {
    body: "the body",
    references: [at("Dune.epub")],
    format: BookFormat.ebook,
    held,
    identifierWasRead: true,
    ...fields,
  };
}

type Ports = LandingPorts<string>;

/** Every port a stub; `create` answers a new Book 50 unless told otherwise. */
function ports(create: Ports["create"] = async () => ({ id: 50 })) {
  return {
    create: vi.fn<Ports["create"]>(create),
    report: vi.fn<Ports["report"]>(async () => ({})),
    copiesOf: vi.fn<Ports["copiesOf"]>(async () => [
      { id: 77, format: BookFormat.ebook },
    ]),
  };
}

/** One holder as the lookup answers it. */
function holder(fields: Partial<HolderOut>): HolderOut {
  return {
    book_id: 1,
    format: null,
    reference_id: 1,
    same_location: true,
    same_partial_md5: true,
    ...fields,
  };
}

describe("asking which Book already holds a file", () => {
  it("asks in chunks no larger than the schema takes", () => {
    const files = propertiesOf("HoldersIn")["files"]!;

    expect(FILES_PER_LOOKUP).toBe(boundOf(files, "maxItems"));
  });
});

describe("reportEach", () => {
  it("sends the next reference only once the one before it is answered", async () => {
    // The per book ceiling is held on the server whatever arrives; a client
    // sending a book's files at once is the client that makes it race.
    let answer!: () => void;
    const post = vi.fn<(reference: string) => Promise<void>>(
      () =>
        new Promise<void>((resolve) => {
          answer = resolve;
        }),
    );

    const sending = reportEach(["first", "second"], post);
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    answer();
    await vi.waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    answer();
    await sending;

    expect(post.mock.calls.map(([reference]) => reference)).toEqual([
      "first",
      "second",
    ]);
  });
});

describe("landing one book", () => {
  it("writes nothing and names the holder when only a Book of another format holds the files", async () => {
    // The Scan page threw here and the Settings card counted; both now read
    // this one outcome.
    const stubs = ports();

    const landing = await land(request({ bookId: 7, lands: false }), stubs);

    expect(landing).toEqual({ kind: "other-format", holderId: 7 });
    expect(stubs.create).not.toHaveBeenCalled();
    expect(stubs.report).not.toHaveBeenCalled();
  });

  it("answers at the ceiling when the holder refuses a file for holding as many as a Book may", async () => {
    // The Scan page had no arm for this and failed the row with the 409's
    // words.
    const stubs = ports();
    stubs.report.mockRejectedValue(
      new ApiError("full", 409, undefined, "reference_ceiling"),
    );

    const landing = await land(request({ bookId: 7, lands: true }), stubs);

    expect(landing).toEqual({ kind: "at-ceiling" });
  });

  it("puts no file on a duplicate's holder when the identifier was read out of a name", async () => {
    // The Settings card had no such guard; its identifiers are never a name's,
    // so it says so and passes through the same rule.
    const duplicate = new ApiError("already", 409, 77);
    const stubs = ports(() => Promise.reject(duplicate));

    const landing = await land(
      request(null, { identifierWasRead: false }),
      stubs,
    );

    expect(landing).toEqual({ kind: "failed", thrown: duplicate });
    expect(stubs.copiesOf).not.toHaveBeenCalled();
    expect(stubs.report).not.toHaveBeenCalled();
  });

  it("answers a tie, and lands no file, for a duplicate naming no Book", async () => {
    // Two Books outside one copy group carry the identifier, so naming the
    // lower would pick between two different Books.
    const tie = new ApiError("already", 409);
    const stubs = ports(() => Promise.reject(tie));

    const landing = await land(request(null), stubs);

    expect(landing).toEqual({ kind: "tie", thrown: tie });
    expect(stubs.copiesOf).not.toHaveBeenCalled();
    expect(stubs.report).not.toHaveBeenCalled();
  });

  it("answers in the trash rather than a tie for the add door's trash refusal", async () => {
    // It names no Book either, and a tie's sentence would tell the member it
    // is already in the catalogue when it is in their trash view.
    const inTrash = new ApiError("in the trash", 409, undefined, "in_trash");
    const stubs = ports(() => Promise.reject(inTrash));

    const landing = await land(request(null), stubs);

    expect(landing).toEqual({ kind: "in-trash", thrown: inTrash });
    expect(stubs.report).not.toHaveBeenCalled();
  });

  it("leaves a file whose location only a print copy holds there, and records the book's other files", async () => {
    // A reference left on a print row before the landing rule: sent to the
    // ebook holding the same bytes, the server refuses it on every add, and it
    // used to stop the book's later files with it.
    const lookup = async (files: AskedFileIn[]): Promise<HoldersOut[]> =>
      files.map((file) => ({
        holders:
          file.relative_path === "Dune.epub"
            ? [
                holder({ book_id: 3, format: BookFormat.paperback }),
                holder({
                  book_id: 9,
                  format: BookFormat.ebook,
                  same_location: false,
                }),
              ]
            : [holder({ book_id: 9, format: BookFormat.ebook })],
      }));
    const references = [at("Dune.epub"), at("Dune.pdf")];
    const held = await askWhoHolds(
      [{ key: "dune", references, format: BookFormat.ebook }],
      lookup,
    );
    const stubs = ports();

    const landing = await land(
      request(held.get("dune"), { references }),
      stubs,
    );

    expect(stubs.report.mock.calls).toEqual([[9, at("Dune.pdf")]]);
    expect(landing).toEqual({ kind: "on-holder", left: 1 });
  });

  it("leaves a file the server says another Book holds there, and still sends the book's next file", async () => {
    // A stale holder answer, or a lookup chunk that failed for this file
    // alone: the refusal is about that one file, and stopping on it left the
    // rest unrecorded while the page said they were recorded.
    const stubs = ports();
    stubs.report.mockRejectedValueOnce(
      new ApiError("held", 409, 3, "file_held_elsewhere"),
    );
    const references = [at("Dune.epub"), at("Dune.pdf")];

    const landing = await land(
      request({ bookId: 7, lands: true }, { references }),
      stubs,
    );

    expect(stubs.report.mock.calls).toEqual([
      [7, at("Dune.epub")],
      [7, at("Dune.pdf")],
    ]);
    expect(landing).toEqual({ kind: "on-holder", left: 1 });
  });

  it("leaves a file another Book holds when the Book was just made, and still sends its next file", async () => {
    // The holder path's rule, at the create: stopping there left the rest
    // unrecorded and both pages said a second pick would record them, which
    // the server refuses the same way.
    const stubs = ports();
    stubs.report.mockRejectedValueOnce(
      new ApiError("held", 409, 3, "file_held_elsewhere"),
    );
    const references = [at("Dune.epub"), at("Dune.pdf")];

    const landing = await land(request(undefined, { references }), stubs);

    expect(stubs.report.mock.calls).toEqual([
      [50, at("Dune.epub")],
      [50, at("Dune.pdf")],
    ]);
    expect(landing).toEqual({ kind: "added", left: 1 });
    expect(countLandings([landing]).filesLeft).toBe(1);
  });
});
