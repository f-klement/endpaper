/**
 * Tests for
 * src/pages/SettingsPage/LibrarySettingsPage/components/CalibreImport.tsx.
 *
 * Two things this card must do that no other import card does: say the one
 * writer rule where the member is standing, and report the identifier count,
 * which is the number that says whether the expensive route paid on this
 * library.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import CalibreImport from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/CalibreImport";
import type {
  CalibrePreview,
  CalibreResult,
} from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/hooks";
import { renderLocalised } from "../../../../utils";

function preview(overrides: Partial<CalibrePreview> = {}): CalibrePreview {
  return {
    total: 897,
    importable: 890,
    withIsbn: 568,
    withSeries: 120,
    withFile: 880,
    crossChecked: 0,
    filled: 0,
    disagreed: 0,
    rows: [{ title: "Dune", author: "Frank Herbert", isbn: "9780441013593" }],
    ...overrides,
  };
}

function outcome(overrides: Partial<CalibreResult> = {}): CalibreResult {
  return { added: 890, failures: [], stopped: false, ...overrides };
}

function renderCard(
  overrides: Partial<React.ComponentProps<typeof CalibreImport>> = {},
) {
  const props = {
    isReading: false,
    isImporting: false,
    preview: null,
    progress: null,
    result: null,
    failure: null,
    error: null,
    onChoose: vi.fn(),
    onCrossCheck: vi.fn(),
    onConfirm: vi.fn(),
    onStop: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
  renderLocalised(<CalibreImport {...props} />);
  return props;
}

const INDEX = new File(["SQLite format 3"], "metadata.db");

describe("CalibreImport", () => {
  it("says the one writer rule before anything else", () => {
    // The member is the only one who can keep it: nothing in a browser can stop
    // somebody pointing this at a library calibre-web is writing to.
    renderCard();

    expect(
      screen.getByText(/Copy metadata.db somewhere else first/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Do not start the Calibre desktop/),
    ).toBeInTheDocument();
  });

  it("reads rather than importing when a file is chosen", async () => {
    const props = renderCard();

    await userEvent
      .setup()
      .upload(screen.getByLabelText("Choose a copy of metadata.db"), INDEX);

    expect(props.onChoose).toHaveBeenCalledWith(INDEX);
    expect(props.onConfirm).not.toHaveBeenCalled();
  });

  it("reports how many books carry an identifier, which is why this route exists", () => {
    renderCard({ preview: preview({ withIsbn: 568 }) });

    expect(screen.getByText("568 carry an ISBN.")).toBeInTheDocument();
  });

  it("reports the identifier count at zero too", () => {
    // A count shown only above zero cannot be told apart from a screen that
    // never counted, and zero is the answer that says this library should have
    // arrived through the feed instead.
    renderCard({ preview: preview({ withIsbn: 0 }) });

    expect(screen.getByText("0 carry an ISBN.")).toBeInTheDocument();
  });

  it("says nothing about a cross check that has not been run", () => {
    renderCard({ preview: preview({ crossChecked: 0 }) });

    expect(
      screen.queryByText(/had a file beside them/),
    ).not.toBeInTheDocument();
  });

  it("reports what the cross check filled in and where the two disagreed", () => {
    renderCard({
      preview: preview({ crossChecked: 244, filled: 57, disagreed: 3 }),
    });

    expect(
      screen.getByText(/244 books had a file beside them: 57 fields filled in/),
    ).toBeInTheDocument();
  });

  it("offers the cross check only once there is a library to check", () => {
    // Before a file is read there is nothing to check against, and the second
    // pick would hand nine hundred files to a hook holding no books.
    renderCard({ preview: null });
    expect(
      screen.queryByRole("button", {
        name: "Check against the files beside the books",
      }),
    ).not.toBeInTheDocument();
  });

  it("offers the cross check once a library has been read", () => {
    renderCard({ preview: preview() });
    expect(
      screen.getByRole("button", {
        name: "Check against the files beside the books",
      }),
    ).toBeInTheDocument();
  });

  it("counts the books it would write, not the rows it read", () => {
    // 897 read and 890 with a title. Naming 897 on the button promises seven
    // books the import will not make.
    renderCard({ preview: preview({ total: 897, importable: 890 }) });

    expect(
      screen.getByRole("button", { name: "Import 890 books" }),
    ).toBeInTheDocument();
  });

  it("will not start an import that would write nothing", () => {
    renderCard({ preview: preview({ importable: 0 }) });

    expect(
      screen.getByRole("button", { name: "Import 0 books" }),
    ).toBeDisabled();
  });

  it("offers a stop while it is running, and not a cancel", () => {
    renderCard({ preview: preview(), isImporting: true });

    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel" }),
    ).not.toBeInTheDocument();
  });

  it("says how far through it is", () => {
    renderCard({
      preview: preview(),
      isImporting: true,
      progress: { done: 431, total: 890 },
    });

    expect(screen.getByText("431 of 890")).toBeInTheDocument();
  });

  it("names each refusal in its own sentence", () => {
    renderCard({
      result: outcome({
        added: 2,
        failures: [
          { title: "Dune", status: 409 },
          { title: "Solaris", status: 500 },
        ],
      }),
    });

    expect(
      screen.getByText(/Dune · already in the catalogue/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Solaris · not added/)).toBeInTheDocument();
  });

  it("says it was stopped rather than reporting a short count as the whole", () => {
    renderCard({ result: outcome({ added: 12, stopped: true }) });

    expect(
      screen.getByText("Stopped. 12 books were added before that."),
    ).toBeInTheDocument();
  });

  it("has one sentence for every way the file can fail", () => {
    // A `Record` in the component makes a new failure a type error; this is the
    // other half, that each key reaches a string rather than the key itself.
    for (const [failure, expected] of [
      ["not-a-database", /not a SQLite database/],
      ["damaged", /copy is damaged/],
      ["too-large", /too large to read/],
      ["no-engine", /could not load the reader/],
      ["not-a-calibre-library", /not a Calibre library/],
      ["empty", /no books in it/],
    ] as const) {
      const { unmount } = renderLocalised(
        <CalibreImport
          isReading={false}
          isImporting={false}
          preview={null}
          progress={null}
          result={null}
          failure={failure}
          error={null}
          onChoose={vi.fn()}
          onCrossCheck={vi.fn()}
          onConfirm={vi.fn()}
          onStop={vi.fn()}
          onCancel={vi.fn()}
        />,
      );
      expect(screen.getByRole("alert")).toHaveTextContent(expected);
      unmount();
    }
  });
});
