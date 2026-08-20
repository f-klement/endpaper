/** Tests for src/pages/BookDetail/components/EnrichPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { BookEnrichmentOut } from "../../../../src/api/generated/model";
import EnrichPanel from "../../../../src/pages/BookDetail/components/EnrichPanel";
import { makeBook } from "../../../factories";
import { renderLocalised } from "../../../utils";

function result(overrides: Partial<BookEnrichmentOut>): BookEnrichmentOut {
  return { book: makeBook(), found: true, updated_fields: [], ...overrides };
}

function renderPanel(
  overrides: Partial<Parameters<typeof EnrichPanel>[0]> = {},
) {
  const props = {
    isConfigured: true,
    onOpenHelp: vi.fn(),
    isWorking: false,
    result: null,
    error: null,
    onBrowse: vi.fn(),
    onDismiss: vi.fn(),
    ...overrides,
  };
  renderLocalised(<EnrichPanel {...props} />);
  return props;
}

describe("EnrichPanel", () => {
  it("offers the lookup", async () => {
    const props = renderPanel();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Find more details" }));

    expect(props.onBrowse).toHaveBeenCalledOnce();
  });

  it("disables the button while it works", () => {
    renderPanel({ isWorking: true });
    expect(screen.getByRole("button", { name: "Searching..." })).toBeDisabled();
  });

  describe("reporting the outcome", () => {
    it("names the fields it filled in", () => {
      renderPanel({
        result: result({ updated_fields: ["page_count", "language"] }),
      });
      expect(screen.getByRole("status")).toHaveTextContent(
        "Added: page count, language.",
      );
    });

    it("says so when it found the book but had nothing to add", () => {
      // The common case. Reporting plain success here would be
      // indistinguishable from a button that does nothing.
      renderPanel({ result: result({ found: true, updated_fields: [] }) });
      expect(screen.getByRole("status")).toHaveTextContent("Nothing new found");
    });

    it("distinguishes not finding the book at all", () => {
      renderPanel({ result: result({ found: false }) });
      expect(screen.getByRole("status")).toHaveTextContent(
        "does not have a record",
      );
    });

    it("shows a field name it has no translation for, rather than a key", () => {
      // The list comes from the server, so a field added there before the
      // catalogue catches up must still read as English words.
      renderPanel({ result: result({ updated_fields: ["some_new_field"] }) });
      expect(screen.getByRole("status")).toHaveTextContent("some_new_field");
      expect(screen.getByRole("status")).not.toHaveTextContent("enrich.field");
    });

    it("can be dismissed", async () => {
      const props = renderPanel({ result: result({}) });

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Close" }));

      expect(props.onDismiss).toHaveBeenCalledOnce();
    });
  });

  it("shows a failure next to the button", () => {
    renderPanel({ error: new Error("No Google Books API key is set.") });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No Google Books API key is set.",
    );
  });

  it("says nothing before the first run", () => {
    renderPanel();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("EnrichPanel without a Google Books key", () => {
  it("stays usable, because the other catalogues need no key", () => {
    // It used to grey itself out here, which left a household unable to fill
    // in exactly the books the national catalogues cover best.
    renderPanel({ isConfigured: false });
    expect(
      screen.getByRole("button", { name: "Find more details" }),
    ).not.toBeDisabled();
  });

  it("says what a key would add rather than what is broken", () => {
    renderPanel({ isConfigured: false });
    expect(
      screen.getByText(/A key adds descriptions and genres/),
    ).toBeInTheDocument();
  });

  it("offers the explanation", async () => {
    const props = renderPanel({ isConfigured: false });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "About extra book details" }));

    expect(props.onOpenHelp).toHaveBeenCalledOnce();
  });

  it("says nothing about configuration once a key is set", () => {
    renderPanel({ isConfigured: true });
    expect(screen.queryByText(/Extra details are off/)).not.toBeInTheDocument();
  });
});
