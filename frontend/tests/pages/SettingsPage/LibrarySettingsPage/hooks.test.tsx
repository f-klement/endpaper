/**
 * Tests for `useCalibreImport` and `useStoreImport` in
 * src/pages/SettingsPage/LibrarySettingsPage/hooks.ts.
 *
 * The reader has its own file; what is pinned here is the orchestration, which
 * is where a nine hundred book import can go wrong in ways no unit answers: how
 * many requests are made and in what order, what happens to the eight hundredth
 * when the fourth is refused, and whether stopping stops.
 *
 * **The engine is loaded for real.** `fetch` is replaced here rather than
 * through `mockApi`, because the module fetches its own `.wasm` asset and a
 * stub with no `arrayBuffer` would report every run as a browser that cannot
 * compile WebAssembly. Replacing the global is what `tests/setup.ts` already
 * does before every test, so this is that stub with two more URLs in it and not
 * a module mock.
 */

import { act, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useCalibreImport,
  useStoreImport,
} from "../../../../src/pages/SettingsPage/LibrarySettingsPage/hooks";
import { CALIBRE_SCHEMA, databaseOf } from "../../../lib/sqliteFixtures";
import { renderHookWithProviders } from "../../../utils";

const require = createRequire(import.meta.url);

interface Posted {
  url: string;
  body: Record<string, unknown>;
}

const posted: Posted[] = [];
/** Statuses to answer with, one per request, `null` for the ordinary 201. */
let answers: (number | null)[] = [];

beforeEach(() => {
  posted.length = 0;
  answers = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      if (url.endsWith(".wasm")) {
        const path = require.resolve("sql.js/dist/sql-wasm-browser.wasm");
        const bytes = readFileSync(path);
        return {
          ok: true,
          status: 200,
          arrayBuffer: async () =>
            bytes.buffer.slice(
              bytes.byteOffset,
              bytes.byteOffset + bytes.byteLength,
            ),
        } as unknown as Response;
      }
      const body =
        typeof init.body === "string"
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : {};
      posted.push({ url, body });
      const status = answers.shift() ?? null;
      return {
        ok: status === null,
        status: status ?? 201,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () =>
          status === null ? { id: posted.length } : { detail: "no" },
      } as unknown as Response;
    }),
  );
});

/** A library with `count` books, the odd ones carrying an ISBN and a series. */
async function libraryFile(count: number): Promise<File> {
  const rows: string[] = [];
  for (let id = 1; id <= count; id += 1) {
    rows.push(
      `INSERT INTO books (id, title, pubdate, series_index, path)
         VALUES (${id}, 'Book ${id}', '2001-01-01 00:00:00+00:00', ${id}.0,
                 'Author/Book ${id} (${id})')`,
      `INSERT INTO authors (id, name) VALUES (${id}, 'Author ${id}')`,
      `INSERT INTO books_authors_link (book, author) VALUES (${id}, ${id})`,
      `INSERT INTO data (book, format, name) VALUES (${id}, 'EPUB', 'Book ${id}')`,
    );
    if (id % 2 === 1) {
      rows.push(
        `INSERT INTO identifiers (book, type, val) VALUES (${id}, 'isbn', '9780441013593')`,
        `INSERT INTO series (id, name) VALUES (${id}, 'A Series')`,
        `INSERT INTO books_series_link (book, series) VALUES (${id}, ${id})`,
      );
    }
  }
  const bytes = await databaseOf(...CALIBRE_SCHEMA, ...rows);
  return new File([bytes], "metadata.db");
}

/** A `metadata.opf` as a directory picker would hand it over. */
function opfFile(directory: string, xml: string): File {
  const file = new File([xml], "metadata.opf");
  Object.defineProperty(file, "webkitRelativePath", {
    value: `Calibre/${directory}/metadata.opf`,
  });
  return file;
}

function importHook() {
  return renderHookWithProviders(() => useCalibreImport());
}

/** The hook's own source, for the one property no assertion on it can see. */
const HOOKS_SOURCE = Object.values(
  import.meta.glob(
    "../../../../src/pages/SettingsPage/LibrarySettingsPage/hooks.ts",
    { query: "?raw", import: "default", eager: true },
  ),
)[0] as string;

describe("what a session that never opens this card pays", () => {
  it("reaches the engine through await import and never at the top", () => {
    // A static import compiles, passes every other test in this file, and moves
    // a third of a megabyte of WebAssembly into the chunk the shell loads. The
    // type import is exempt because it is erased before a bundler sees it.
    // **The statement, not the line.** A line anchored, newline bounded pattern
    // is evaded by prettier: one more name in the braces and the import is
    // broken across lines, after which no single line both starts with `import`
    // and names the module. `[^;]` is what makes this a statement: every import
    // ends in a semicolon, so the match cannot run on into the next one.
    expect(HOOKS_SOURCE).not.toMatch(
      /^import(?!\s+type\b)[^;]*?from "[^"]*lib\/sqlite"/m,
    );
    // The call form, not `await import(...)` adjacent: prettier puts the two
    // dynamic imports inside a `Promise.all` and breaks the line between them,
    // so an assertion on the adjacency fails on formatting rather than on the
    // property. `import(` is a call and a static import is `from "..."`, so
    // the two cannot be confused.
    expect(HOOKS_SOURCE).toMatch(
      /[^.\w]import\("\.\.\/\.\.\/\.\.\/lib\/sqlite"\)/,
    );
  });
});

describe("reading a Calibre index", () => {
  it("reports what the library holds before anything is written", async () => {
    const { result } = importHook();
    const file = await libraryFile(4);

    await act(async () => result.current.choose(file));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    expect(result.current.preview).toMatchObject({
      total: 4,
      importable: 4,
      withIsbn: 2,
      withSeries: 2,
      withFile: 4,
      crossChecked: 0,
    });
    expect(posted).toHaveLength(0);
  });

  it("names the refusal for a file that is not a database", async () => {
    const { result } = importHook();

    await act(async () =>
      result.current.choose(new File(["not a database"], "metadata.db")),
    );
    await waitFor(() => expect(result.current.failure).not.toBeNull());

    expect(result.current.failure).toBe("not-a-database");
    expect(result.current.preview).toBeNull();
  });
});

describe("checking against the files beside the books", () => {
  it("fills what the index left empty and counts it", async () => {
    const { result } = importHook();
    await act(async () => result.current.choose(await libraryFile(1)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    await act(async () =>
      result.current.crossCheck([
        opfFile(
          "Author/Book 1 (1)",
          `<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
             <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
               <dc:title>Book 1</dc:title>
               <dc:publisher>Chilton Books</dc:publisher>
             </metadata>
           </package>`,
        ),
      ]),
    );
    await waitFor(() => expect(result.current.preview?.crossChecked).toBe(1));

    expect(result.current.preview).toMatchObject({
      crossChecked: 1,
      filled: 1,
      disagreed: 0,
    });
  });

  it("loses one unreadable file and not the pass", async () => {
    // A file removed between the pick and the pass, or a share that went away.
    // Without a `try` around the one read, the throw reaches the caller's catch
    // and the whole cross check is lost on a screen that then says every book
    // was left with what the index held.
    const { result } = importHook();
    await act(async () => result.current.choose(await libraryFile(2)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    const gone = opfFile("Author/Book 1 (1)", "<package/>");
    Object.defineProperty(gone, "text", {
      value: () => Promise.reject(new Error("the file is gone")),
    });

    await act(async () =>
      result.current.crossCheck([
        gone,
        opfFile(
          "Author/Book 2 (2)",
          `<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
             <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
               <dc:title>Book 2</dc:title>
               <dc:publisher>Chilton Books</dc:publisher>
             </metadata>
           </package>`,
        ),
      ]),
    );
    await waitFor(() => expect(result.current.preview?.crossChecked).toBe(1));

    expect(result.current.error).toBeNull();
    expect(result.current.preview).toMatchObject({
      crossChecked: 1,
      filled: 1,
    });
  });

  it("leaves a book alone when no file sits beside it", async () => {
    const { result } = importHook();
    await act(async () => result.current.choose(await libraryFile(1)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    await act(async () =>
      result.current.crossCheck([opfFile("Somewhere/Else (9)", "<package/>")]),
    );
    await waitFor(() => expect(result.current.isReading).toBe(false));

    expect(result.current.preview?.crossChecked).toBe(0);
  });
});

describe("writing the library", () => {
  it("makes one request a book and reports what landed", async () => {
    const { result } = importHook();
    await act(async () => result.current.choose(await libraryFile(3)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    await act(async () => result.current.confirm());
    await waitFor(() => expect(result.current.result).not.toBeNull());

    expect(posted).toHaveLength(3);
    expect(posted.every((one) => one.url.endsWith("/api/books/scan"))).toBe(
      true,
    );
    expect(result.current.result).toEqual({
      added: 3,
      failures: [],
      stopped: false,
    });
  });

  it("carries the series and the ISBN onto the wire", async () => {
    const { result } = importHook();
    await act(async () => result.current.choose(await libraryFile(1)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    await act(async () => result.current.confirm());
    await waitFor(() => expect(result.current.result).not.toBeNull());

    expect(posted[0]!.body).toMatchObject({
      title: "Book 1",
      author: "Author 1",
      isbn: "9780441013593",
      series_name: "A Series",
      series_index: 1,
      year: 2001,
      format: "ebook",
    });
  });

  it("keeps a refused book by name and still writes the rest", async () => {
    // "Sixty could not be added" after nine hundred is unrecoverable: nothing
    // says which sixty, and the list that knew has just been cleared.
    const { result } = importHook();
    await act(async () => result.current.choose(await libraryFile(3)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());
    answers = [null, 409, null];

    await act(async () => result.current.confirm());
    await waitFor(() => expect(result.current.result).not.toBeNull());

    expect(posted).toHaveLength(3);
    expect(result.current.result).toEqual({
      added: 2,
      failures: [{ title: "Book 2", status: 409 }],
      stopped: false,
    });
  });

  it("stops when it is told to, and says it was stopped", async () => {
    const { result } = importHook();
    await act(async () => result.current.choose(await libraryFile(5)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    await act(async () => {
      result.current.confirm();
      result.current.stop();
    });
    await waitFor(() => expect(result.current.result).not.toBeNull());

    expect(result.current.result?.stopped).toBe(true);
    expect(posted.length).toBeLessThan(5);
    // The preview survives a stop, which is what lets somebody press again
    // rather than picking the file a second time.
    expect(result.current.preview).not.toBeNull();
  });
});

/**
 * A Kobo device holding `count` books, plus one row nobody owns.
 *
 * Built through the real engine and read back through the real reader, so what
 * is exercised is the seam this hook actually has rather than a stand in told
 * what to answer.
 */
async function deviceFile(count: number): Promise<File> {
  const rows: string[] = [
    `INSERT INTO content
       (ContentID, MimeType, BookID, Title, Accessibility, IsDownloaded)
       VALUES ('advert', 'application/epub+zip', NULL, 'Try this', 4, 'true')`,
  ];
  for (let id = 1; id <= count; id += 1) {
    rows.push(
      `INSERT INTO content
         (ContentID, MimeType, BookID, Title, Attribution, Accessibility,
          IsDownloaded)
         VALUES ('book-${id}', 'application/epub+zip', NULL, 'Book ${id}',
                 'Author ${id}', 1, 'true')`,
    );
  }
  const bytes = await databaseOf(
    `CREATE TABLE content (
       ContentID TEXT NOT NULL PRIMARY KEY,
       MimeType TEXT,
       BookID TEXT,
       Title TEXT,
       Attribution TEXT,
       Accessibility INTEGER,
       IsDownloaded BOOL
     )`,
    ...rows,
  );
  return new File([bytes], "KoboReader.sqlite");
}

function storeHook() {
  return renderHookWithProviders(() => useStoreImport());
}

describe("what a session that never opens the store card pays", () => {
  it("reaches every store reader through the registry's own thunks", () => {
    // The engine and both readers are behind `lib/stores.ts`, whose openers
    // import them. A static import of a reader here would compile, pass every
    // other test in this file, and put a third of a megabyte of WebAssembly in
    // the chunk the shell loads.
    expect(HOOKS_SOURCE).not.toMatch(
      /^import(?!\s+type\b)[^;]*?from "[^"]*lib\/(sqlite|kobo|takeout)"/m,
    );
  });
});

describe("picking one store", () => {
  it("reports what the device held before anything is written", async () => {
    const { result } = storeHook();

    await act(async () => result.current.choose("kobo", await deviceFile(4)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    expect(result.current.preview).toEqual({ total: 4, importable: 4 });
    // The advert row is on the source rather than in the total: which device a
    // number came from is what a member needs, and the card reads it there.
    expect(result.current.sources.kobo).toMatchObject({
      status: "read",
      library: { skipped: 1, refused: 0 },
    });
    expect(posted).toHaveLength(0);
  });

  it("writes one request a book, in order, and clears the pick", async () => {
    const { result } = storeHook();
    await act(async () => result.current.choose("kobo", await deviceFile(3)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    await act(async () => result.current.confirm());
    await waitFor(() => expect(result.current.result).not.toBeNull());

    expect(posted.map((one) => one.body["title"])).toEqual([
      "Book 1",
      "Book 2",
      "Book 3",
    ]);
    expect(result.current.result?.added).toBe(3);
    expect(result.current.sources).toEqual({});
  });

  it("keeps a refused book with its title rather than counting it", async () => {
    answers = [null, 409, null];
    const { result } = storeHook();
    await act(async () => result.current.choose("kobo", await deviceFile(3)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    await act(async () => result.current.confirm());
    await waitFor(() => expect(result.current.result).not.toBeNull());

    expect(result.current.result?.added).toBe(2);
    expect(result.current.result?.failures).toEqual([
      { title: "Book 2", status: 409 },
    ]);
  });

  it("stops when it is told to, and keeps the pick so it can be pressed again", async () => {
    const { result } = storeHook();
    await act(async () => result.current.choose("kobo", await deviceFile(5)));
    await waitFor(() => expect(result.current.preview).not.toBeNull());

    await act(async () => {
      result.current.confirm();
      result.current.stop();
    });
    await waitFor(() => expect(result.current.result).not.toBeNull());

    expect(result.current.result?.stopped).toBe(true);
    expect(posted.length).toBeLessThan(5);
    expect(result.current.sources.kobo?.status).toBe("read");
  });
});

/**
 * A file whose bytes arrive when the test says so.
 *
 * **A `File` shaped argument, not a module double**, which is what the
 * registry's openers take, so nothing here is a `vi.mock` and nothing is
 * replaced. `zip.openZip` reads `size` and then awaits
 * `slice(...).arrayBuffer()`, and holding that one promise is what lets two
 * picks for one store settle in a chosen order. **Chosen rather than raced**: a
 * race decided by which file is larger is a flake, and the guard under test is
 * the one that only matters when the earlier read finishes last.
 *
 * The bytes it eventually gives are zeros, so the archive fails as
 * `not-an-archive`. What is being asserted is which answer is written, not
 * which answer it is.
 */
function heldFile(name: string) {
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const bytes = new Uint8Array(64);
  const file = {
    name,
    size: bytes.byteLength,
    slice: () => ({
      arrayBuffer: async () => {
        await held;
        return bytes.buffer;
      },
    }),
  };
  return { file: file as unknown as File, release };
}

/**
 * Give a released read every chance to write before asserting it did not.
 *
 * **Measured rather than chosen, and the short window lied.** A single
 * `setTimeout(0)` reported an empty card for both arms of the `confirm`
 * mutation below, which reads as the guard being redundant; instrumenting the
 * read showed it had not resumed inside that window at all. So a negative
 * assertion taken on the short window is a test that cannot fail.
 */
async function settle() {
  for (let turn = 0; turn < 40; turn += 1) {
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

describe("a read the member has moved on from", () => {
  it("writes a held read once it is released, which is what settle is for", async () => {
    // **The positive control for `settle`, and the only arm here that fails
    // when its window is too short.** Every other arm asserts that a released
    // read did *not* write, and a window the read cannot resume inside
    // satisfies all of them while testing nothing: measured, cutting `settle`
    // to one turn left all of them green. This one asserts the write happens,
    // through the same helper and the same held file, so a settle that stops
    // being long enough is a failure here rather than silence everywhere.
    const { result } = storeHook();
    const held = heldFile("held.zip");

    await act(async () => result.current.choose("playBooks", held.file));
    expect(result.current.sources.playBooks?.status).toBe("reading");

    await act(async () => {
      held.release();
      await settle();
    });

    expect(result.current.sources.playBooks).toMatchObject({
      status: "failed",
      fileName: "held.zip",
    });
  });

  it("keeps the pick that replaced it, whichever read finishes last", async () => {
    // The scenario the guard is named for. Without it the first read writes
    // its answer whenever it finishes, so the file the member replaced comes
    // back on screen after the one they chose.
    const { result } = storeHook();
    const first = heldFile("first.zip");

    await act(async () => result.current.choose("playBooks", first.file));
    await act(async () =>
      result.current.choose("playBooks", new File(["nonsense"], "second.zip")),
    );
    await waitFor(() =>
      expect(result.current.sources.playBooks).toMatchObject({
        status: "failed",
        fileName: "second.zip",
      }),
    );

    await act(async () => {
      first.release();
      await settle();
    });

    expect(result.current.sources.playBooks).toMatchObject({
      fileName: "second.zip",
    });
  });

  it("never lands on a card an import has just cleared", async () => {
    // The other half of what the guard is for, and the half `reset` does not
    // reach: a source still reading when the write finishes would otherwise
    // put a preview and an Import button back under a result the member has
    // just been shown.
    const { result } = storeHook();
    const late = heldFile("late.zip");

    await act(async () => result.current.choose("playBooks", late.file));
    await act(async () => result.current.choose("kobo", await deviceFile(2)));
    await waitFor(() => expect(result.current.preview?.total).toBe(2));

    await act(async () => result.current.confirm());
    await waitFor(() => expect(result.current.result).not.toBeNull());
    expect(result.current.sources).toEqual({});

    await act(async () => {
      late.release();
      await settle();
    });

    expect(result.current.sources).toEqual({});
    expect(result.current.preview).toBeNull();
  });

  it("never lands on a card that has been cleared under it", async () => {
    // **The control and the case, same file and same settle.** Without the
    // guard the second read lands exactly as the first one does, and puts a
    // preview back on a card that had just been cleared. A Takeout that is not
    // a zip is used because it fails without touching the engine, so what is
    // being asserted is the write and not a compile finishing in time.
    const { result } = storeHook();
    const file = new File(["nonsense"], "takeout.zip");

    // **The control takes the same `settle()` as the case, and that is what
    // makes the window self checking.** Taken with a `waitFor` it would wait
    // only as long as it had to, so a settle that had become too short for the
    // read would leave the case passing quietly instead of the control failing
    // loudly, which is the failure `settle` itself is written about.
    await act(async () => {
      result.current.choose("playBooks", file);
      await settle();
    });
    expect(result.current.sources.playBooks?.status).toBe("failed");

    await act(async () => {
      result.current.reset();
      result.current.choose("playBooks", file);
      result.current.reset();
    });
    await act(async () => {
      await settle();
    });

    expect(result.current.sources).toEqual({});
    expect(result.current.preview).toBeNull();
  });
});

describe("an unreadable store is one skipped source", () => {
  it("keeps the source that read and names the one that did not", async () => {
    // The rule, at the only place a member can watch it happen. The Play Books
    // pick is not an archive at all; the Kobo pick is a device.
    const { result } = storeHook();

    await act(async () => {
      result.current.choose("kobo", await deviceFile(2));
      result.current.choose("playBooks", new File(["nonsense"], "takeout.zip"));
    });
    await waitFor(() =>
      expect(result.current.sources.playBooks?.status).toBe("failed"),
    );
    await waitFor(() =>
      expect(result.current.sources.kobo?.status).toBe("read"),
    );

    expect(result.current.sources.playBooks).toEqual({
      status: "failed",
      fileName: "takeout.zip",
      failure: "not-an-archive",
    });
    expect(result.current.preview?.total).toBe(2);
  });

  it("writes the source that read and nothing from the one that did not", async () => {
    const { result } = storeHook();
    await act(async () => {
      result.current.choose("kobo", await deviceFile(2));
      result.current.choose("playBooks", new File(["nonsense"], "takeout.zip"));
    });
    await waitFor(() => expect(result.current.preview?.total).toBe(2));

    await act(async () => result.current.confirm());
    await waitFor(() => expect(result.current.result).not.toBeNull());

    expect(posted.map((one) => one.body["title"])).toEqual([
      "Book 1",
      "Book 2",
    ]);
  });
});
