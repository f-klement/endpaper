/**
 * Tests for src/pages/SettingsPage/LibrarySettingsPage/components/HarvestImport.tsx.
 *
 * The MARC card's two steps over a repository. What is pinned is what a
 * repository adds to a file: a set to narrow by, a run that may stop short,
 * headings counted and not written, and the refusals said in words.
 */

import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  type HarvestPreviewOut,
  type HarvestResultOut,
  Locale,
} from "../../../../../src/api/generated/model";
import { ApiError } from "../../../../../src/api/mutator";
import HarvestImport from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/HarvestImport";
import { renderLocalised } from "../../../../utils";

function preview(
  overrides: Partial<HarvestPreviewOut> = {},
): HarvestPreviewOut {
  return {
    already_held: 0,
    deleted: 0,
    metadata_prefix: "marc21",
    pages_read: 1,
    readable: 10,
    records_seen: 10,
    repository_name: null,
    skipped: 0,
    total_records: 10,
    truncated: false,
    ...overrides,
  };
}

function outcome(overrides: Partial<HarvestResultOut> = {}): HarvestResultOut {
  return {
    created: 6,
    deleted: 0,
    harvest_id: 1,
    headings_unconfirmed: 0,
    matched: 4,
    metadata_prefix: "marc21",
    pages_read: 1,
    records_seen: 10,
    rows_read: 10,
    skipped: 0,
    statuses_updated: 0,
    truncated: false,
    ...overrides,
  };
}

type HarvestProps = React.ComponentProps<typeof HarvestImport>;

function renderHarvest(
  overrides: Partial<HarvestProps> = {},
  locale: Locale = Locale.en,
) {
  const props = {
    isPreviewing: false,
    isImporting: false,
    preview: null,
    result: null,
    readError: null,
    harvestError: null,
    onRead: vi.fn<HarvestProps["onRead"]>(),
    onConfirm: vi.fn<HarvestProps["onConfirm"]>(),
    onCancel: vi.fn<HarvestProps["onCancel"]>(),
    ...overrides,
  };
  renderLocalised(<HarvestImport {...props} />, { locale });
  return props;
}

describe("HarvestImport", () => {
  it("reads the repository with the typed set rather than harvesting it", () => {
    const props = renderHarvest();

    fireEvent.change(screen.getByLabelText("Set (optional)"), {
      target: { value: "theses" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Read the repository" }),
    );

    expect(props.onRead).toHaveBeenCalledWith("theses");
    expect(props.onConfirm).not.toHaveBeenCalled();
  });

  it("offers no second read while the first is running", () => {
    renderHarvest({ isPreviewing: true });

    expect(
      screen.getByRole("button", { name: "Reading the repository..." }),
    ).toBeDisabled();
  });

  it("names the repository when it gives a name", () => {
    renderHarvest({ preview: preview({ repository_name: "Stadtbibliothek" }) });

    expect(screen.getByText("Repository: Stadtbibliothek")).toBeInTheDocument();
  });

  it("counts the new records apart from the ones already here", () => {
    renderHarvest({
      preview: preview({ readable: 10, already_held: 4, in_trash: 1 }),
    });

    expect(
      screen.getByText("5 are new here and will be added."),
    ).toBeInTheDocument();
    expect(screen.getByText(/4 are already on this shelf/)).toBeInTheDocument();
  });

  it("counts the records the repository marks deleted", () => {
    renderHarvest({ preview: preview({ deleted: 3 }) });

    expect(
      screen.getByText(/3 records are marked deleted by the repository/),
    ).toBeInTheDocument();
  });

  it("counts the records with no title as left out", () => {
    renderHarvest({ preview: preview({ skipped: 2 }) });

    expect(
      screen.getByText("2 records have no title and will be left out."),
    ).toBeInTheDocument();
  });

  it("counts the headings the listed records carry before the write", () => {
    renderHarvest({
      preview: preview({
        rows: [
          { title: "Faust", classifications: ["ddc:830", "gnd:4017745-6"] },
          { title: "Werther", classifications: ["ddc:833"] },
        ],
      }),
    });

    expect(
      screen.getByText(/shelf notations in the records listed below: 3\./),
    ).toBeInTheDocument();
  });

  it("lists each previewed record with its headings", () => {
    renderHarvest({
      preview: preview({
        rows: [
          { title: "Faust", author: "Goethe", classifications: ["ddc:830"] },
        ],
      }),
    });

    expect(screen.getByText("Faust · Goethe · ddc:830")).toBeInTheDocument();
  });

  it("refuses a set wider than the server keeps", () => {
    renderHarvest();

    expect(screen.getByLabelText("Set (optional)")).toHaveAttribute(
      "maxLength",
      "255",
    );
  });

  it("says a preview cut short covers part of the repository and how to narrow it", () => {
    renderHarvest({ preview: preview({ truncated: true }) });

    expect(
      screen.getByText(/cover only part of it.*starts over.*naming a set/),
    ).toBeInTheDocument();
  });

  it("confirms the new and the matched records together", () => {
    const props = renderHarvest({
      preview: preview({ readable: 10, already_held: 4 }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Harvest 10 records" }));

    expect(props.onConfirm).toHaveBeenCalledOnce();
  });

  it("withholds the confirm when there is nothing to harvest", () => {
    renderHarvest({ preview: preview({ readable: 0 }) });

    expect(
      screen.getByRole("button", { name: "Harvest 0 records" }),
    ).toBeDisabled();
  });

  it("reports what the harvest did in counts", () => {
    renderHarvest({ result: outcome() });

    expect(
      screen.getByText("10 records read, 4 matched, 6 added."),
    ).toBeInTheDocument();
  });

  it("counts the headings the harvest did not write", () => {
    renderHarvest({ result: outcome({ headings_unconfirmed: 7 }) });

    expect(
      screen.getByText(
        "Headings and shelf notations counted and not yet written: 7.",
      ),
    ).toBeInTheDocument();
  });

  it("says a harvest cut short kept what it read and starts over next time", () => {
    renderHarvest({ result: outcome({ truncated: true }) });

    expect(
      screen.getByText(/What was read is kept\. A re-run starts over/),
    ).toBeInTheDocument();
  });

  it("says the harvester is off on a 404", () => {
    renderHarvest({ readError: new ApiError("Not Found", 404) });

    expect(screen.getByRole("alert")).toHaveTextContent(/The harvester is off/);
  });

  it("says a harvest is already running on a 409 coded so, at the read", () => {
    renderHarvest({
      readError: new ApiError("running", 409, undefined, "harvest_running"),
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "A harvest is already running.",
    );
  });

  it("says a harvest is already running on a 409 coded so, at the apply", () => {
    renderHarvest({
      harvestError: new ApiError("running", 409, undefined, "harvest_running"),
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "A harvest is already running.",
    );
  });

  it("asks for a new read when the stored repository is not the one this page read", () => {
    renderHarvest({
      harvestError: new ApiError(
        "changed",
        409,
        undefined,
        "repository_changed",
      ),
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The stored repository is not the one this page read, and nothing was harvested.",
    );
  });

  it("words a code naming an object's own method as a lost race", () => {
    renderHarvest({
      harvestError: new ApiError("odd", 409, undefined, "toString"),
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Another change to the same books met this harvest, and nothing was harvested.",
    );
  });

  it("words a 409 with no code as a lost race with another change", () => {
    renderHarvest({
      harvestError: new ApiError("Another change met this import", 409),
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Another change to the same books met this harvest, and nothing was harvested.",
    );
  });

  it("says a 502 in the server's own words, which name the fault", () => {
    renderHarvest({
      readError: new ApiError(
        "The repository offers no MARCXML format, and Dublin Core alone is not read by this library yet.",
        502,
      ),
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The repository offers no MARCXML format",
    );
  });

  it("shows any other refusal in the server's own words", () => {
    renderHarvest({ harvestError: new ApiError("Too many imports", 429) });

    expect(screen.getByRole("alert")).toHaveTextContent("Too many imports");
  });

  it("says a running harvest in German", () => {
    renderHarvest(
      { readError: new ApiError("running", 409, undefined, "harvest_running") },
      Locale.de,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Es läuft bereits eine Übernahme.",
    );
  });
});
