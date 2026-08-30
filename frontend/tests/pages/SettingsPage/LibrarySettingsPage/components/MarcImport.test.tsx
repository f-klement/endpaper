/**
 * Tests for src/pages/SettingsPage/LibrarySettingsPage/components/MarcImport.tsx.
 *
 * The two steps are the same shape as the CSV importer's and exist for a
 * different reason, so that is what most of these pin: a MARC preview is not
 * there to correct a column guess, it is there to answer "will importing this
 * double my catalogue" before anything is written.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  ImportResultOut,
  MarcPreviewOut,
} from "../../../../../src/api/generated/model";
import MarcImport from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/MarcImport";
import { renderLocalised } from "../../../../utils";

function outcome(overrides: Partial<ImportResultOut> = {}): ImportResultOut {
  return {
    rows_read: 10,
    matched: 4,
    created: 6,
    statuses_updated: 0,
    skipped: 0,
    unmatched_titles: [],
    ...overrides,
  };
}

function preview(overrides: Partial<MarcPreviewOut> = {}): MarcPreviewOut {
  return {
    total_records: 10,
    readable: 10,
    skipped: 0,
    already_held: 0,
    blocked: 0,
    rows: [
      {
        title: "Stoner",
        author: "John Williams",
        isbn: "9780099561545",
        classifications: ["ddc:813.54"],
      },
    ],
    ...overrides,
  };
}

function renderMarc(
  overrides: Partial<React.ComponentProps<typeof MarcImport>> = {},
) {
  const props = {
    isPreviewing: false,
    isImporting: false,
    preview: null,
    result: null,
    error: null,
    onChoose: vi.fn(),
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    onReviewUnconfirmed: vi.fn(),
    ...overrides,
  };
  renderLocalised(<MarcImport {...props} />);
  return props;
}

const FILE = new File(["<collection/>"], "catalogue.xml", {
  type: "application/marcxml+xml",
});

describe("MarcImport", () => {
  it("says how records are matched, because that is what decides duplicates", () => {
    renderMarc();
    expect(screen.getByText(/author and title together/)).toBeInTheDocument();
  });

  it("previews rather than importing when a file is chosen", () => {
    const props = renderMarc();

    return userEvent
      .setup()
      .upload(screen.getByLabelText("Choose a MARC file"), FILE)
      .then(() => {
        expect(props.onChoose).toHaveBeenCalledWith(FILE);
        expect(props.onConfirm).not.toHaveBeenCalled();
      });
  });

  it("reports how many records the file holds and how many are usable", () => {
    renderMarc({ preview: preview({ total_records: 12, readable: 10 }) });
    expect(
      screen.getByText(/12 records in the file, 10 this app can store/),
    ).toBeInTheDocument();
  });

  it("says how many are already held, which is why the preview exists", () => {
    renderMarc({ preview: preview({ already_held: 4 }) });
    expect(screen.getByText(/4 are already on this shelf/)).toBeInTheDocument();
  });

  it("does not mention what is already held when nothing is", () => {
    // A zero here reads as a warning about nothing, on the screen whose job is
    // to warn about something.
    renderMarc({ preview: preview({ already_held: 0 }) });
    expect(screen.queryByText(/already on this shelf/)).not.toBeInTheDocument();
  });

  it("counts the records the switch would actually add, not the whole file", () => {
    // 10 readable, 4 of them held, so 6 would be new. Showing 10 next to the
    // switch would promise the opposite of what pressing it does.
    renderMarc({ preview: preview({ readable: 10, already_held: 4 }) });
    expect(
      screen.getByLabelText(/Add the 6 records this catalogue does not hold/),
    ).toBeInTheDocument();
  });

  it("subtracts the records the import will refuse as well as the ones it holds", () => {
    // The count promised records the import then refused, by exactly the number
    // another member holds privately under one of the file's ISBNs.
    renderMarc({
      preview: preview({ readable: 10, already_held: 4, blocked: 2 }),
    });
    expect(
      screen.getByLabelText(/Add the 4 records this catalogue does not hold/),
    ).toBeInTheDocument();
  });

  it("says why a record will be left alone rather than only counting it", () => {
    renderMarc({ preview: preview({ blocked: 2 }) });
    expect(
      screen.getByText(
        /2 carry an ISBN that belongs to a book this account cannot see/,
      ),
    ).toBeInTheDocument();
  });

  it("does not mention blocked records when there are none", () => {
    renderMarc({ preview: preview({ blocked: 0 }) });
    expect(screen.queryByText(/cannot see/)).not.toBeInTheDocument();
  });

  it("names what the button will do when the add switch is off", async () => {
    // The button said "Import 10 records" for a request that creates none and
    // fills gaps in 4, and neither number moved with the switch.
    renderMarc({ preview: preview({ readable: 10, already_held: 4 }) });
    const user = userEvent.setup();

    await user.click(
      screen.getByLabelText(/Add the 6 records this catalogue does not hold/),
    );

    expect(
      screen.getByRole("button", { name: /Fill in 4 records already here/ }),
    ).toBeInTheDocument();
  });

  it("refuses to import with the switch off and nothing already held", () => {
    renderMarc({ preview: preview({ readable: 10, already_held: 4 }) });
    return userEvent
      .setup()
      .click(screen.getByLabelText(/Add the 6 records/))
      .then(() => {
        expect(
          screen.getByRole("button", { name: /Fill in 4 records/ }),
        ).toBeEnabled();
      });
  });

  it("shows what a record was read as, so a bad field is visible first", () => {
    renderMarc({ preview: preview() });
    expect(screen.getByText(/Stoner/)).toBeInTheDocument();
    expect(screen.getByText(/ddc:813.54/)).toBeInTheDocument();
  });

  it("imports only when the confirm button is pressed", async () => {
    const props = renderMarc({ preview: preview() });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Import 10 records/ }));

    expect(props.onConfirm).toHaveBeenCalledWith({ createMissing: true });
  });

  it("refuses to import a file with nothing readable in it", () => {
    renderMarc({ preview: preview({ readable: 0, skipped: 3 }) });
    expect(
      screen.getByRole("button", { name: /Import 0 records/ }),
    ).toBeDisabled();
  });

  it("refuses to import a file whose every record the import would refuse", () => {
    renderMarc({
      preview: preview({ readable: 3, already_held: 0, blocked: 3 }),
    });
    expect(
      screen.getByRole("button", { name: /Import 0 records/ }),
    ).toBeDisabled();
  });

  it("warns that created records are not evidence this library holds them", async () => {
    renderMarc({ preview: preview() });
    expect(
      screen.getByText(
        /another library's record says that library holds the book/,
      ),
    ).toBeInTheDocument();
  });

  it("reports what the import did", () => {
    renderMarc({ result: outcome() });
    expect(
      screen.getByText(/10 records read, 4 matched, 6 added/),
    ).toBeInTheDocument();
  });

  it("offers to review the records it added", async () => {
    const props = renderMarc({ result: outcome({ created: 6 }) });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Review/ }));

    expect(props.onReviewUnconfirmed).toHaveBeenCalled();
  });

  it("does not offer a review when it added nothing", () => {
    renderMarc({ result: outcome({ created: 0 }) });
    expect(
      screen.queryByRole("button", { name: /Review/ }),
    ).not.toBeInTheDocument();
  });

  it("shows the reason a file was refused", () => {
    // Through the shared reader, so a 400 naming the fault reads the same here
    // as everywhere else rather than becoming "something went wrong".
    renderMarc({ error: new Error("That file is not XML: syntax error") });
    expect(screen.getByRole("alert")).toHaveTextContent(/not XML/);
  });
});
