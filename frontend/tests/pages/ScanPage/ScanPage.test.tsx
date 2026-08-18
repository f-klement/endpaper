/**
 * Tests for src/pages/ScanPage.
 *
 * BarcodeScanner is replaced with a button that emits a fixed ISBN, so the
 * scan → lookup → confirm flow is covered without a camera. The scanner has
 * its own tests.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigate };
});

vi.mock("../../../src/pages/ScanPage/components/BarcodeScanner", () => ({
  default: ({ onDetected }: { onDetected: (isbn: string) => void }) => (
    <button onClick={() => onDetected("9780441013593")}>simulate scan</button>
  ),
}));

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
  suggested_tag_ids: [] as number[],
};

let api: MockApi;

beforeEach(() => {
  resetIds();
  navigate.mockReset();
  api = mockApi();
  api.on("/api/books/tags", { body: [] });
});

async function scan() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "simulate scan" }));
  return user;
}

describe("ScanPage", () => {
  it("offers manual ISBN entry alongside the camera", () => {
    renderWithProviders(<ScanPage />);
    expect(screen.getByLabelText("ISBN")).toBeInTheDocument();
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
      await user.type(screen.getByLabelText("ISBN"), "9780441013593");
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

    it("navigates to the new book", async () => {
      api.on("/api/books/scan", { body: makeBook({ id: 12 }) });
      renderWithProviders(<ScanPage />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      await waitFor(() => expect(navigate).toHaveBeenCalledWith("/book/12"));
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
      renderWithProviders(<ScanPage />);

      const user = await scan();
      await user.click(await screen.findByRole("button", { name: "Fantasy" }));
      await user.click(screen.getByRole("button", { name: "Add to Library" }));

      await waitFor(() => expect(navigate).toHaveBeenCalledWith("/book/12"));
    });

    it("reports a duplicate ISBN and stays put", async () => {
      api.on("/api/books/scan", {
        status: 409,
        body: { detail: "Book with this ISBN already in catalog" },
      });
      renderWithProviders(<ScanPage />);

      const user = await scan();
      await user.click(
        await screen.findByRole("button", { name: "Add to Library" }),
      );

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Book with this ISBN already in catalog",
      );
      expect(navigate).not.toHaveBeenCalled();
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

      const user = await scan();
      await user.type(
        await screen.findByLabelText("Title *"),
        "Untracked Book",
      );

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
