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

import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { installCamera } from "../../doubles/camera";
import { decodeFromStream, emitBarcode } from "../../doubles/zxing";

import ScanPage from "../../../src/pages/ScanPage";
import { makeBook, makeTagSet, resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

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

let api: MockApi;

beforeEach(() => {
  resetIds();
  installCamera();
  api = mockApi();
  api.on("/api/books/tags", { body: [] });
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
  it("offers manual ISBN entry alongside the camera", () => {
    renderWithProviders(<ScanPage />);
    expect(screen.getByLabelText("ISBN")).toBeInTheDocument();
  });

  describe("the camera is opened on request", () => {
    // It used to start the moment this tab was rendered and run until the tab
    // was left, so opening the Scan tab lit the phone's camera indicator and
    // held it there through everything that followed.

    it("does not open the camera on arrival", () => {
      renderWithProviders(<ScanPage />);
      expect(
        screen.queryByRole("button", { name: "Stop scanning" }),
      ).not.toBeInTheDocument();
    });

    it("says the camera is off rather than showing a black rectangle", () => {
      renderWithProviders(<ScanPage />);
      expect(screen.getByText("The camera is off")).toBeInTheDocument();
    });

    it("opens it when asked", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ScanPage />);

      await user.click(screen.getByRole("button", { name: "Start scanning" }));

      expect(
        screen.getByRole("button", { name: "Stop scanning" }),
      ).toBeInTheDocument();
    });

    it("closes it again when asked", async () => {
      const user = userEvent.setup();
      renderWithProviders(<ScanPage />);

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
      renderWithProviders(<ScanPage />);

      await scan();

      await waitFor(() =>
        expect(
          screen.queryByRole("button", { name: "Stop scanning" }),
        ).not.toBeInTheDocument(),
      );
    });
  });

  describe("a barcode that is not a book", () => {
    it("says what it read instead of going quiet", async () => {
      // Silence here reads as a broken scanner, when what happened is that the
      // price code beside the ISBN was read.
      renderWithProviders(<ScanPage />);

      await scan("4001234567890");

      expect(screen.getByRole("status")).toHaveTextContent("4001234567890");
    });

    it("clears the notice when scanning starts again", async () => {
      renderWithProviders(<ScanPage />);

      const user = await scan("4001234567890");
      await user.click(screen.getByRole("button", { name: "Stop scanning" }));

      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });
  });

  describe("lookup", () => {
    it("looks up a scanned barcode", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage />);

      await scan();

      expect(await screen.findByText("Dune")).toBeInTheDocument();
      expect(screen.getByText("by Frank Herbert")).toBeInTheDocument();
    });

    it("sends the ISBN as a query parameter", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage />);

      await scan();

      await waitFor(() =>
        expect(api.lastCall("/api/books/lookup")?.url).toContain(
          "isbn=9780441013593",
        ),
      );
    });

    it("looks up a manually typed ISBN", async () => {
      api.on("/api/books/lookup", { body: LOOKUP });
      renderWithProviders(<ScanPage />);

      const user = userEvent.setup();
      fireEvent.change(screen.getByLabelText("ISBN"), {
        target: { value: "9780441013593" },
      });
      await user.click(screen.getByRole("button", { name: "Look up" }));

      expect(await screen.findByText("Dune")).toBeInTheDocument();
    });

    it("ignores an empty manual submission", async () => {
      renderWithProviders(<ScanPage />);

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
      renderWithProviders(<ScanPage />);

      await scan();

      expect(await screen.findByLabelText("Title *")).toBeInTheDocument();
      expect(screen.getByLabelText("Author")).toBeInTheDocument();
    });

    it("preselects the tags the backend suggested", async () => {
      const tags = makeTagSet();
      api.on("/api/books/tags", { body: tags });
      api.on("/api/books/lookup", {
        body: { ...LOOKUP, suggested_tag_ids: [tags[1]!.id] },
      });
      renderWithProviders(<ScanPage />);

      await scan();

      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Fantasy" })).toHaveAttribute(
          "aria-pressed",
          "true",
        ),
      );
    });
  });

  describe("adding the book", () => {
    beforeEach(() => {
      api.on("/api/books/lookup", { body: LOOKUP });
    });

    it("posts the looked-up fields", async () => {
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      renderWithProviders(<ScanPage />);

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
      renderWithProviders(<ScanPage />);

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
      renderWithProviders(<ScanPage />);

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
      const { path } = renderWithProviders(<ScanPage />);

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
      renderWithProviders(<ScanPage />);

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
      renderWithProviders(<ScanPage />);

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

    it("still navigates when tagging fails", async () => {
      // The book exists by then; a failed tag is not worth stranding the member.
      const tags = makeTagSet();
      api.on("/api/books/tags", { body: tags });
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      api.on(/\/api\/books\/12\/tags\//, {
        status: 404,
        body: { detail: "Tag not found" },
      });
      const { path } = renderWithProviders(<ScanPage />);

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
      const { path } = renderWithProviders(<ScanPage />);

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
      renderWithProviders(<ScanPage />);

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
      renderWithProviders(<ScanPage />);

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

    it("refuses to add an untitled manual entry", async () => {
      api.on("/api/books/lookup", {
        status: 404,
        body: { detail: "not found" },
      });
      renderWithProviders(<ScanPage />);

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
      renderWithProviders(<ScanPage />);

      await scan();
      fireEvent.change(await screen.findByLabelText("Title *"), {
        target: { value: "Untracked Book" },
      });

      expect(
        screen.getByRole("button", { name: "Add to Library" }),
      ).toBeEnabled();
    });
  });

  it("Cancel returns to the scanner", async () => {
    api.on("/api/books/lookup", { body: LOOKUP });
    renderWithProviders(<ScanPage />);

    const user = await scan();
    await user.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(await screen.findByLabelText("ISBN")).toBeInTheDocument();
    expect(screen.queryByText("by Frank Herbert")).not.toBeInTheDocument();
  });
});
