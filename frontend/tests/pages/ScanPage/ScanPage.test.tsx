/**
 * Tests for src/pages/ScanPage.
 *
 * **The real scanner is rendered, with the camera and the decoder replaced by
 * the shared doubles** rather than the component replaced by a stub. The stub
 * was a `vi.mock` of `BarcodeScanner`, which under `isolate: false` is dropped
 * whenever another file has already evaluated that module, and two do. Driving
 * the real one costs a `waitFor` on the camera opening and nothing else: the
 * scanner's own file runs thirty-three tests this way in 93ms to 159ms across
 * runs on the builder worker. The scanner still has its own tests; this file
 * covers scan, lookup and confirm.
 */

import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fc from "fast-check";
import { beforeEach, describe, expect, it } from "vitest";

import { installCamera } from "../../doubles/camera";
import { decodeFromStream, emitBarcode } from "../../doubles/zxing";

import { en } from "../../../src/i18n/en";
import ScanPage from "../../../src/pages/ScanPage";
import { makeBook, makeTagSet, resetIds } from "../../factories";
import { rememberCarried } from "../../../src/lib/carryOver";
import { answersOf, DISTINCT } from "../../lib/schemaArbitrary";
import { holds, PROFILE, PROPERTY, witness } from "../../property";
import { forget, overSchema, type OverSchema } from "../../schemaPage";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";
import { epubFile, packageDocument } from "../../zipFixtures";

const LOOKUP = {
  isbn: "9780441013593",
  title: "Dune",
  subtitle: null,
  author: "Frank Herbert",
  publisher: "Chilton",
  year: 1965,
  description: null,
  cover_url: "https://covers.openlibrary.org/b/isbn/9780441013593-L.jpg",
  classifications: [{ scheme: "ddc", number: "004", label: "Informatik" }],
  suggested_tag_ids: [] as number[],
};

/** The signed in member every render here is for. */
const ME = 1;
/** Another member, who used this browser before. */
const SOMEBODY_ELSE = 2;

let api: MockApi;

const ALREADY_HELD = "/api/books/already-held";

beforeEach(() => {
  resetIds();
  installCamera();
  api = mockApi();
  api.on("/api/books/tags", { body: [] });
  api.on(ALREADY_HELD, { body: { match: null, book_ids: [] } });
  api.on("/api/collections", { body: [] });
});

/**
 * Open the camera, then emit a barcode from the stubbed scanner.
 *
 * The camera is behind an explicit button now: the page used to open it on
 * arrival and hold it until the tab was left.
 */
async function openCamera() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Start scanning" }));
  // The stream is opened asynchronously, and a barcode delivered before the
  // decoder has been handed its callback goes nowhere.
  await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());
  return user;
}

async function scan(code = "9780441013593") {
  const user = await openCamera();
  // ZXing calls back outside React, so the state this sets has no act() of its
  // own the way a click does.
  await act(async () => {
    emitBarcode(code);
  });
  return user;
}

describe("ScanPage", () => {
  it("checks the files saved from a folder when the folder is picked again", async () => {
    // The sweep is the page's, beside the queue, so the hook's own tests
    // cannot see whether this door calls it.
    api.on(
      "/api/books/digital-references",
      { body: { items: [], total: 0, page: 1, page_size: 200 } },
      "GET",
    );
    const user = userEvent.setup();
    const file = new File(["text"], "notes.txt");
    Object.defineProperty(file, "webkitRelativePath", {
      value: "Books/notes.txt",
    });
    renderWithProviders(<ScanPage accountId={ME} />);

    await user.upload(screen.getByLabelText("A whole folder of books"), file);

    await waitFor(() =>
      expect(api.lastCall("root_label=Books", "GET")).toBeDefined(),
    );
  });

  it("offers manual ISBN entry alongside the camera", () => {
    renderWithProviders(<ScanPage accountId={ME} />);
    expect(screen.getByLabelText("ISBN")).toBeInTheDocument();
  });

  describe("a file is the fourth way of choosing which book", () => {
    it("offers the picker beside the camera and the search box", () => {
      renderWithProviders(<ScanPage accountId={ME} />);
      expect(screen.getByLabelText("Book files")).toBeInTheDocument();
    });

    it("shows no queue until something is in it", () => {
      renderWithProviders(<ScanPage accountId={ME} />);
      expect(screen.queryByText("Nothing scanned yet")).not.toBeInTheDocument();
    });

    it("puts a picked EPUB into the same queue rapid scanning fills", async () => {
      // A folder is a third way of answering *which* book, so it gets the same
      // review and the same one commit at the end rather than a second bulk
      // path beside it.
      const user = userEvent.setup();
      const file = await epubFile("dune.epub");
      renderWithProviders(<ScanPage accountId={ME} />);

      await user.upload(screen.getByLabelText("Book files"), file);

      await waitFor(() => expect(screen.getByText("Dune")).toBeInTheDocument());
      expect(screen.getByText("1 in the queue")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Add all" }),
      ).toBeInTheDocument();
    });

    it("puts the file's own subjects in front of the member, removably", async () => {
      // **The whole wiring, end to end, because the middle of it is where a
      // design round put the control on a surface a file never reaches.** A
      // picked file settles into this queue and never into the confirm card,
      // so this is the one screen where a subject is visible while it is
      // still one press to undo: no page sends `BookDetailsUpdate`'s
      // `categories`, so the remedy after "Add all" is the API by hand.
      const user = userEvent.setup();
      const file = await epubFile("dune.epub", {
        opf: packageDocument(
          `<dc:identifier id="pub-id">urn:uuid:1</dc:identifier>` +
            `<dc:title>Dune</dc:title>` +
            `<dc:subject>Fiction</dc:subject>` +
            `<dc:subject>Science Fiction</dc:subject>`,
        ),
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      await user.upload(screen.getByLabelText("Book files"), file);

      await waitFor(() =>
        expect(
          screen.getByText("Subject words from the file: 2. Show them."),
        ).toBeInTheDocument(),
      );

      await user.click(
        screen.getByRole("button", {
          name: "Remove the subject Fiction from dune.epub",
        }),
      );

      // The count is what says the row's own draft changed rather than the
      // chip merely disappearing from a list the component keeps.
      await waitFor(() =>
        expect(
          screen.getByText("Subject words from the file: 1. Show them."),
        ).toBeInTheDocument(),
      );
    });

    it("keeps a file it could not read, under the name it had", async () => {
      // A dead end until the filename fallback shipped: the file is still a
      // book and the name is what is left to go on.
      const user = userEvent.setup();
      renderWithProviders(<ScanPage accountId={ME} />);

      await user.upload(
        screen.getByLabelText("Book files"),
        new File(["not an epub"], "broken.epub"),
      );

      await waitFor(() =>
        expect(screen.getByText(/From the file name/)).toBeInTheDocument(),
      );
      expect(screen.getByText(/Not an EPUB file/)).toBeInTheDocument();
    });

    it("offers a whole folder as well as single files", async () => {
      // Only a folder pick carries the path, and the folder above a file is
      // often the one thing that names its author.
      renderWithProviders(<ScanPage accountId={ME} />);
      expect(
        screen.getByLabelText("A whole folder of books"),
      ).toBeInTheDocument();
    });

    it("offers the catalogue lookup rather than running it", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ScanPage accountId={ME} />);

      await user.upload(
        screen.getByLabelText("Book files"),
        new File(["%PDF-1.4"], "The Dispossessed.pdf"),
      );

      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Look up 1 in the catalogues" }),
        ).toBeInTheDocument(),
      );
      expect(api.lastCall("/api/books/search")).toBeUndefined();
    });

    it("says what it passed over rather than showing an empty queue", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ScanPage accountId={ME} />);

      // Through the folder input, which is where a format the picker filters
      // out actually arrives: a browser applies `accept` to a file dialog and
      // to no directory pick anywhere.
      await user.upload(
        screen.getByLabelText("A whole folder of books"),
        new File(["a"], "watchmen.cbr"),
      );

      await waitFor(() =>
        expect(
          screen.getByText(
            "1 passed over, because Endpaper reads no format of theirs.",
          ),
        ).toBeInTheDocument(),
      );
    });
  });

  describe("the camera is opened on request", () => {
    // It used to start the moment this tab was rendered and run until the tab
    // was left, so opening the Scan tab lit the phone's camera indicator and
    // held it there through everything that followed.

    it("does not open the camera on arrival", () => {
      renderWithProviders(<ScanPage accountId={ME} />);
      expect(
        screen.queryByRole("button", { name: "Stop scanning" }),
      ).not.toBeInTheDocument();
    });

    it("says the camera is off rather than showing a black rectangle", () => {
      renderWithProviders(<ScanPage accountId={ME} />);
      expect(screen.getByText("The camera is off")).toBeInTheDocument();
    });

    it("opens it when asked", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ScanPage accountId={ME} />);

      await user.click(screen.getByRole("button", { name: "Start scanning" }));

      expect(
        screen.getByRole("button", { name: "Stop scanning" }),
      ).toBeInTheDocument();
    });

    it("closes it again when asked", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ScanPage accountId={ME} />);

      await user.click(screen.getByRole("button", { name: "Start scanning" }));
      await user.click(screen.getByRole("button", { name: "Stop scanning" }));

      expect(
        screen.queryByRole("button", { name: "Stop scanning" }),
      ).not.toBeInTheDocument();
    });

    it("closes it once a barcode has been read", async () => {
      // The next step is confirming a draft. Holding the stream open behind
      // that form keeps the indicator lit for as long as somebody takes to
      // check a title.
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      await waitFor(() =>
        expect(
          screen.queryByRole("button", { name: "Stop scanning" }),
        ).not.toBeInTheDocument(),
      );
    });

    it("opens it for rapid scanning, and closes it when that is finished", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ScanPage accountId={ME} />);

      await user.click(screen.getByRole("button", { name: "Scan several" }));
      await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());
      expect(screen.getByText(en["rapid.explain"])).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Finish scanning" }));
      expect(screen.queryByText(en["rapid.explain"])).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Scan several" }),
      ).toBeInTheDocument();
    });

    it.each([
      [
        "after Cancel on the book it read",
        async (user: ReturnType<typeof userEvent.setup>) => {
          api.on("/api/books/lookup", { body: LOOKUP });
          await act(async () => {
            emitBarcode("9780441013593");
          });
          await user.click(
            await screen.findByRole("button", { name: "Cancel" }),
          );
        },
      ],
      [
        "after rapid scanning is finished",
        async (user: ReturnType<typeof userEvent.setup>) => {
          await user.click(
            screen.getByRole("button", { name: "Scan several" }),
          );
          await user.click(
            screen.getByRole("button", { name: "Finish scanning" }),
          );
        },
      ],
    ])("stays off %s", async (_, leave) => {
      // The entry panel unmounts the scanner on both routes, so a camera left
      // switched on underneath comes back with no tap once the panel returns.
      renderWithProviders(<ScanPage accountId={ME} />);
      const user = await openCamera();

      await leave(user);

      expect(await screen.findByText("The camera is off")).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Stop scanning" }),
      ).not.toBeInTheDocument();
    });
  });

  it("keeps the queue on screen to say what the run added once it is empty", async () => {
    // The banner is where "1 added" is said, and it sits in the queue: hiding
    // the queue with its last row would hide the verdict with it.
    api.on("/api/books/lookup", { body: LOOKUP });
    api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
    const user = userEvent.setup();
    renderWithProviders(<ScanPage accountId={ME} />);
    await user.click(screen.getByRole("button", { name: "Scan several" }));
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());
    await act(async () => {
      emitBarcode("9780441013593");
    });
    await screen.findByText("Dune");
    await user.click(screen.getByRole("button", { name: "Finish scanning" }));

    await user.click(screen.getByRole("button", { name: "Add all" }));

    expect(await screen.findByText(/^1 added\./)).toBeInTheDocument();
  });

  describe("a barcode that is not a book", () => {
    it("says what it read instead of going quiet", async () => {
      // Silence here reads as a broken scanner, when what happened is that the
      // price code beside the ISBN was read.
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan("4001234567890");

      expect(screen.getByRole("status")).toHaveTextContent("4001234567890");
    });

    it("clears the notice when scanning starts again", async () => {
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan("4001234567890");
      await user.click(screen.getByRole("button", { name: "Stop scanning" }));

      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });
  });

  describe("lookup", () => {
    it("looks up a scanned barcode", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      expect(await screen.findByText("Dune")).toBeInTheDocument();
      expect(screen.getByText("by Frank Herbert")).toBeInTheDocument();
    });

    it("sends the ISBN as a query parameter", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      await waitFor(() =>
        expect(api.lastCall("/api/books/lookup")?.url).toContain(
          "isbn=9780441013593",
        ),
      );
    });

    it("looks up a manually typed ISBN", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = userEvent.setup();
      fireEvent.change(screen.getByLabelText("ISBN"), {
        target: { value: "9780441013593" },
      });
      await user.click(screen.getByRole("button", { name: "Look up" }));

      expect(await screen.findByText("Dune")).toBeInTheDocument();
    });

    it("refuses a mistyped ISBN without asking the server, until it is corrected", async () => {
      // A typo is told to the member at once rather than sent as a lookup for
      // a book that cannot exist. The corrected lookup reaches no catalogue,
      // which is the answer that puts the form back on screen to read.
      api.on("/api/books/lookup", {
        status: 503,
        body: { detail: "Could not reach the book catalogues." },
      });
      renderWithProviders(<ScanPage accountId={ME} />);
      const user = userEvent.setup();
      const isbn = screen.getByLabelText("ISBN");

      fireEvent.change(isbn, { target: { value: "9780441013594" } });
      await user.click(screen.getByRole("button", { name: "Look up" }));

      expect(screen.getByText(en["scan.invalidIsbn"])).toBeInTheDocument();
      expect(api.lastCall("/api/books/lookup")).toBeUndefined();

      fireEvent.change(isbn, { target: { value: "9780441013593" } });
      await user.click(screen.getByRole("button", { name: "Look up" }));
      await screen.findByRole("button", { name: "Try again" });

      expect(
        screen.queryByText(en["scan.invalidIsbn"]),
      ).not.toBeInTheDocument();
    });

    it("ignores an empty manual submission", async () => {
      renderWithProviders(<ScanPage accountId={ME} />);

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Look up" }));

      expect(api.lastCall("/api/books/lookup")).toBeUndefined();
    });

    it("falls back to manual entry when the ISBN is unknown", async () => {
      // Both metadata sources 404. The member should still be able to add it.
      api.on("/api/books/lookup", {
        status: 404,
        body: { detail: "Book not found" },
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      expect(await screen.findByLabelText("Title *")).toBeInTheDocument();
      expect(screen.getByLabelText("Author")).toBeInTheDocument();
      expect(screen.getByText(/No details found for ISBN/)).toBeInTheDocument();
    });

    it("offers to ask again when the catalogues could not be reached", async () => {
      // A 503 is no catalogue having answered. A blank form here reported a
      // fact about the book that nobody established, and offered no retry.
      api.on("/api/books/lookup", {
        status: 503,
        body: { detail: "Could not reach the book catalogues." },
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      const retry = await screen.findByRole("button", { name: "Try again" });
      api.on("/api/books/lookup", { body: LOOKUP });
      await user.click(retry);

      expect(await screen.findByText("Dune")).toBeInTheDocument();
    });

    it("still lets that book be added by hand, as the server's words offer", async () => {
      api.on("/api/books/lookup", {
        status: 503,
        body: { detail: "Could not reach the book catalogues." },
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add it by hand" }),
      );

      expect(await screen.findByLabelText("Title *")).toBeInTheDocument();
      // No catalogue answered, so the card may not say none of them knew it.
      expect(screen.queryByText(/No details found/)).not.toBeInTheDocument();
      expect(screen.getByText(/No catalogue answered/)).toBeInTheDocument();
    });

    it("preselects the tags the backend suggested", async () => {
      const tags = makeTagSet();
      api.on("/api/books/tags", { body: tags });
      api.on("/api/books/lookup", {
        body: { ...LOOKUP, suggested_tag_ids: [tags[1]!.id] },
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Fantasy" })).toHaveAttribute(
          "aria-pressed",
          "true",
        ),
      );
    });
  });

  describe("the warning before the save", () => {
    beforeEach(() => {
      api.on("/api/books/lookup", { body: LOOKUP });
    });

    it("says the same ISBN is already held and links to it", async () => {
      api.on(ALREADY_HELD, { body: { match: "isbn", book_ids: [42] } });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      const sentence = await screen.findByText(en["scan.alreadyHeldIsbn"]);
      const warning = sentence.closest<HTMLElement>('[role="status"]');
      expect(warning).not.toBeNull();
      expect(
        within(warning as HTMLElement).getByRole("link", {
          name: en["scan.openTheOneWeHave"],
        }),
      ).toHaveAttribute("href", "/book/42");
    });

    it("says a title and author match is only possibly the same book", async () => {
      api.on(ALREADY_HELD, { body: { match: "title_author", book_ids: [7] } });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      expect(
        await screen.findByText(en["scan.alreadyHeldTitleAuthor"]),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(en["scan.alreadyHeldIsbn"]),
      ).not.toBeInTheDocument();
    });

    it("leaves a missing author out of the question rather than sending null", async () => {
      // The generated client spells a null as the string "null", which the
      // server would compare as an author called that.
      api.on("/api/books/lookup", { status: 404, body: { detail: "nope" } });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();
      fireEvent.change(await screen.findByLabelText("Title *"), {
        target: { value: "Dune" },
      });

      await waitFor(() =>
        expect(api.lastCall("title=Dune", "GET")).toBeDefined(),
      );
      expect(api.lastCall("title=Dune", "GET")?.url).not.toContain("author");
    });
  });

  describe("adding the book", () => {
    beforeEach(() => {
      api.on("/api/books/lookup", { body: LOOKUP });
    });

    it("posts the looked-up fields", async () => {
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      await waitFor(() =>
        expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
          isbn: "9780441013593",
          title: "Dune",
          is_private: false,
        }),
      );
    });

    it("strips the client-only fields from the payload", async () => {
      // suggested_tag_ids and notFound are UI state, not columns.
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      await waitFor(() =>
        expect(api.lastCall("/api/books/scan", "POST")).toBeDefined(),
      );
      const body = api.lastCall("/api/books/scan", "POST")!.body as Record<
        string,
        unknown
      >;
      expect(body).not.toHaveProperty("suggested_tag_ids");
      expect(body).not.toHaveProperty("notFound");
    });

    it("posts the catalogue headings back so the server stores them", async () => {
      // These are not UI state: the lookup is the only place they exist, and a
      // payload that dropped them would leave the scan flow storing none.
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      await waitFor(() =>
        expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
          classifications: [
            { scheme: "ddc", number: "004", label: "Informatik" },
          ],
        }),
      );
    });

    it("navigates to the new book", async () => {
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      const { path } = renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      // Where the router ended up, not that `useNavigate` was called: see
      // `PathProbe` in tests/utils.tsx for why this suite owns no router mock.
      await waitFor(() => expect(path()).toBe("/book/12"));
    });

    it("marks the book private when the box is ticked", async () => {
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(await screen.findByRole("checkbox"));
      await user.click(screen.getByRole("button", { name: "Add to Library" }));

      await waitFor(() =>
        expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
          is_private: true,
        }),
      );
    });

    it("applies the selected tags after creating the book", async () => {
      const tags = makeTagSet();
      api.on("/api/books/tags", { body: tags });
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      api.on(/\/api\/books\/12\/tags\//, { body: makeBook({ id: 12 }) });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      // The tag categories start closed: the curated vocabulary is 105 tags.
      await user.click(await screen.findByRole("button", { name: /Genre/ }));
      await user.click(await screen.findByRole("button", { name: "Fantasy" }));
      await user.click(screen.getByRole("button", { name: "Add to Library" }));

      await waitFor(() =>
        expect(
          api.lastCall(`/api/books/12/tags/${tags[1]!.id}`, "POST"),
        ).toBeDefined(),
      );
    });

    it("holds a typed tag name until the book exists, and posts it by name", async () => {
      const tags = makeTagSet();
      api.on("/api/books/tags", { body: tags });
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      api.on("/api/books/12/tags", { body: makeBook({ id: 12 }) });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.type(await screen.findByLabelText("New tag"), "Loft finds");
      await user.click(screen.getByRole("button", { name: "Create" }));

      // **Nothing has been asked of the server yet**, which is the whole
      // change: this form used to invent the tag on this keystroke and leave
      // the row behind if the scan was then cancelled.
      expect(api.lastCall("/api/books/tags", "POST")).toBeUndefined();

      await user.click(screen.getByRole("button", { name: "Add to Library" }));

      await waitFor(() =>
        expect(api.lastCall("/api/books/12/tags", "POST")?.body).toEqual({
          name: "Loft finds",
        }),
      );
    });

    it("and cancelling the scan asks the server for nothing at all", async () => {
      const tags = makeTagSet();
      api.on("/api/books/tags", { body: tags });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.type(await screen.findByLabelText("New tag"), "Loft finds");
      await user.click(screen.getByRole("button", { name: "Create" }));
      await user.click(screen.getByRole("button", { name: "Cancel" }));

      // The reset clears the name with the rest of the draft, and there was
      // never a row to leave behind: `blankPending` is the whole cleanup.
      expect(api.lastCall("/api/books/tags", "POST")).toBeUndefined();
    });

    it("still navigates when tagging fails", async () => {
      // The book exists by then; a failed tag is not worth stranding the member.
      const tags = makeTagSet();
      api.on("/api/books/tags", { body: tags });
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      api.on(/\/api\/books\/12\/tags\//, {
        status: 404,
        body: { detail: "Tag not found" },
      });
      const { path } = renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      // The tag categories start closed: the curated vocabulary is 105 tags.
      await user.click(await screen.findByRole("button", { name: /Genre/ }));
      await user.click(await screen.findByRole("button", { name: "Fantasy" }));
      await user.click(screen.getByRole("button", { name: "Add to Library" }));

      await waitFor(() => expect(path()).toBe("/book/12"));
    });

    it("reports a duplicate ISBN and stays put", async () => {
      api.on("/api/books/scan", {
        status: 409,
        body: { detail: "Book with this ISBN already in catalog" },
      });
      const { path } = renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Book with this ISBN already in catalog",
      );
      expect(path()).toBe("/");
    });

    it("offers to open the copy already on the shelf", async () => {
      // The second pass through a bookcase is mostly books already in the
      // library, so a bare sentence here is a dead end on a common path: the
      // reader is holding the book with nothing to press.
      api.on("/api/books/scan", {
        status: 409,
        body: {
          detail: {
            message: "Book with this ISBN already in catalog",
            book_id: 42,
          },
        },
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      expect(
        await screen.findByRole("link", {
          name: "Open the copy already in the library",
        }),
      ).toHaveAttribute("href", "/book/42");
    });

    it("offers no link when the server named no book", async () => {
      // It withholds the id when the holder is another member's private book,
      // because returning it would confirm they own it.
      api.on("/api/books/scan", {
        status: 409,
        body: { detail: "Book with this ISBN already in catalog" },
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      await screen.findByRole("alert");
      expect(
        screen.queryByRole("link", {
          name: "Open the copy already in the library",
        }),
      ).not.toBeInTheDocument();
    });

    it("says a book refused as in the trash is there, and links to the trash", async () => {
      // The refusal names no Book, so the server's own English was all the
      // member read, with nothing to press.
      api.on("/api/books/scan", {
        status: 409,
        body: {
          detail: { message: "The server's sentence", code: "in_trash" },
        },
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      expect(
        await screen.findByRole("link", { name: "Open trash" }),
      ).toHaveAttribute("href", "/trash");
      expect(screen.getByRole("alert")).toHaveTextContent(en["scan.inTrash"]);
      expect(screen.getByRole("alert")).not.toHaveTextContent(
        "The server's sentence",
      );
    });

    it("refuses to add an untitled manual entry", async () => {
      api.on("/api/books/lookup", {
        status: 404,
        body: { detail: "not found" },
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      await screen.findByLabelText("Title *");
      expect(
        screen.getByRole("button", { name: "Add to Library" }),
      ).toBeDisabled();
    });

    it("enables the button once a manual title is typed", async () => {
      api.on("/api/books/lookup", {
        status: 404,
        body: { detail: "not found" },
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();
      fireEvent.change(await screen.findByLabelText("Title *"), {
        target: { value: "Untracked Book" },
      });

      expect(
        screen.getByRole("button", { name: "Add to Library" }),
      ).toBeEnabled();
    });
  });

  describe("the card a lookup draws", () => {
    // Each arm pins one part of the card a split moved into its own helper:
    // a render reaching those lines counts them covered whether or not
    // anything reads them.

    it("prints the publisher and the year on one line", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      expect(
        await screen.findByText("Chilton \u00b7 1965"),
      ).toBeInTheDocument();
    });

    it("prints the ISBN that was looked up", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      expect(
        await screen.findByText("ISBN: 9780441013593"),
      ).toBeInTheDocument();
    });

    it("prints the subtitle under the title", async () => {
      api.on("/api/books/lookup", {
        body: { ...LOOKUP, subtitle: "The First Book" },
      });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      expect(await screen.findByText("The First Book")).toBeInTheDocument();
    });

    it("leaves the tag heading out while the library has no tags", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      await screen.findByText("by Frank Herbert");
      expect(screen.queryByText(en["library.tags"])).not.toBeInTheDocument();
    });

    it("shows no count while no tag is chosen", async () => {
      api.on("/api/books/tags", { body: makeTagSet() });
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      await screen.findByLabelText("New tag");
      expect(screen.queryByText(/\(\d+ selected\)/)).not.toBeInTheDocument();
    });

    it("counts a typed tag name as chosen", async () => {
      // A typed name is held as a name until the book exists, not as an id,
      // and a count of the ids alone read as the typing having been lost.
      api.on("/api/books/tags", { body: makeTagSet() });
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.type(await screen.findByLabelText("New tag"), "Loft finds");
      await user.click(screen.getByRole("button", { name: "Create" }));

      expect(screen.getByText("(1 selected)")).toBeInTheDocument();
    });

    it("offers to replace the catalogue's cover", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      await scan();

      expect(
        await screen.findByLabelText("Replace cover photo (optional)"),
      ).toBeInTheDocument();
    });

    it("names the cover file once one is chosen", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.upload(
        await screen.findByLabelText("Replace cover photo (optional)"),
        new File(["cover"], "my-cover.jpg", { type: "image/jpeg" }),
      );

      expect(screen.getByText("my-cover.jpg")).toBeInTheDocument();
    });

    it("says what went wrong in its own words when the server gave none", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      api.on("/api/books/scan", { status: 500, statusText: "", body: {} });
      renderWithProviders(<ScanPage accountId={ME} />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      expect(await screen.findByRole("alert")).toHaveTextContent(
        en["scan.couldNotAdd"],
      );
    });

    describe("a 409 naming a book already here", () => {
      beforeEach(() => {
        api.on("/api/books/lookup", { body: LOOKUP });
        api.on("/api/books/scan", {
          status: 409,
          body: {
            detail: {
              message: "Book with this ISBN already in catalog",
              book_id: 42,
            },
          },
        });
      });

      it("files the scan as another copy of it on the press", async () => {
        api.on("/api/books/42/copies", { body: makeBook({ id: 99 }) }, "POST");
        renderWithProviders(<ScanPage accountId={ME} />);

        const user = await scan();
        await user.click(
          await screen.findByRole("button", { name: "Add to Library" }),
        );
        await user.click(
          await screen.findByRole("button", { name: "Add another copy" }),
        );

        await waitFor(() =>
          expect(api.lastCall("/api/books/42/copies", "POST")).toBeDefined(),
        );
      });

      it("says before the press what a copy takes from that book", async () => {
        renderWithProviders(<ScanPage accountId={ME} />);

        const user = await scan();
        await user.click(
          await screen.findByRole("button", { name: "Add to Library" }),
        );

        expect(
          await screen.findByText(en["copies.fromScanHint"]),
        ).toBeInTheDocument();
      });
    });
  });

  it("Cancel returns to the scanner", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    renderWithProviders(<ScanPage accountId={ME} />);

    const user = await scan();
    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(await screen.findByLabelText("ISBN")).toBeInTheDocument();
    expect(screen.queryByText("by Frank Herbert")).not.toBeInTheDocument();
  });

  it("sends a cleared manual author as null rather than an empty string", async () => {
    // The column holds "no author" as null, and so does every other field the
    // frontend clears; `""` was the one second spelling of it.
    api.on("/api/books/lookup", {
      status: 404,
      body: { detail: "Book not found" },
    });
    api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
    renderWithProviders(<ScanPage accountId={ME} />);

    const user = await scan();
    fireEvent.change(await screen.findByLabelText("Title *"), {
      target: { value: "Dune" },
    });
    const author = screen.getByLabelText("Author");
    fireEvent.change(author, { target: { value: "Frank Herbert" } });
    fireEvent.change(author, { target: { value: "" } });
    await user.click(screen.getByRole("button", { name: "Add to Library" }));

    await waitFor(() =>
      expect(api.lastCall("/api/books/scan", "POST")).toBeDefined(),
    );
    expect(api.lastCall("/api/books/scan", "POST")!.body).toMatchObject({
      title: "Dune",
      author: null,
    });
  });
});

/**
 * The title the lookup answered, where it answered one a reach can look for:
 * a `DISTINCT` marker, as `echoed` counts, so the page's own words cannot
 * pass the reach by spelling a short title.
 */
const lookedUpTitle = (rendered: OverSchema) => {
  const found = rendered.answered.find(
    ([operationId, answer]) =>
      operationId === "lookup_isbn" && answer.status === 200,
  );
  const title = (found?.[1].body as { title?: unknown } | undefined)?.title;
  return typeof title === "string" && DISTINCT.test(title) ? title : undefined;
};

describe("ScanPage and a book that starts private", () => {
  it("says on the form that the book is private because the last one was", async () => {
    rememberCarried(ME, { isPrivate: true });
    api.on("/api/books/lookup", { body: LOOKUP });
    renderWithProviders(<ScanPage accountId={ME} />);

    await scan();

    // By its words: the lookup's spinner is a status too.
    expect(
      await screen.findByText(
        "This book starts private because the last one you added was.",
        { exact: false },
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeChecked();
  });

  it("says nothing of another member's last book", async () => {
    rememberCarried(SOMEBODY_ELSE, { isPrivate: true });
    api.on("/api/books/lookup", { body: LOOKUP });
    renderWithProviders(<ScanPage accountId={ME} />);

    await scan();

    await screen.findByRole("button", { name: "Add to Library" });
    expect(
      screen.queryByText("the last one you added was", { exact: false }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("adds it public once the notice is answered", async () => {
    rememberCarried(ME, { isPrivate: true });
    api.on("/api/books/lookup", { body: LOOKUP });
    api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
    renderWithProviders(<ScanPage accountId={ME} />);

    const user = await scan();
    await user.click(
      await screen.findByRole("button", {
        name: "Make it visible to everyone",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Add to Library" }));

    await waitFor(() =>
      expect(api.lastCall("/api/books/scan", "POST")?.body).toMatchObject({
        is_private: false,
      }),
    );
  });
});

describe("ScanPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do. The page
  // asks for nothing about a book until a reader names one, so each example
  // types an ISBN and looks it up, and the lookup's answer is drawn too. A
  // failed lookup opens a blank draft rather than an alert, by design
  // (`useScanFlow`), so no reach asks for an alert.
  it("is drawn an error body and a lookup", async () => {
    await witness(answersOf("lookup_isbn"), {
      "is an error body": (answer) => answer.status === 422,
      "is a lookup": (answer) => answer.status === 200,
    });
  });

  it("neither throws nor shows a value nobody can name", PROPERTY, async () => {
    expect(
      await holds(
        fc.gen(),
        async (answers) => {
          try {
            const rendered = await overSchema(
              <ScanPage accountId={ME} />,
              answers,
              {
                uses: [
                  (page) =>
                    fireEvent.change(within(page).getByLabelText("ISBN"), {
                      target: { value: LOOKUP.isbn },
                    }),
                  (page) =>
                    fireEvent.click(
                      within(page).getByRole("button", { name: "Look up" }),
                    ),
                ],
              },
            );
            expect(rendered.problems).toEqual([]);
            return rendered;
          } finally {
            forget();
          }
        },
        {
          "looked the book up": (_, rendered) =>
            rendered.asked.includes("lookup_isbn"),
          // The lookup's own title, rather than any drawn string: the tags and
          // locations the draft offers are drawn too, and shown whatever the
          // lookup answered.
          "showed the title the lookup answered": (_, rendered) => {
            const title = lookedUpTitle(rendered);
            return (
              title !== undefined &&
              rendered.shown.some((text) => text.includes(title))
            );
          },
        },
      ),
    ).toBe(PROFILE.runs);
  });
});
