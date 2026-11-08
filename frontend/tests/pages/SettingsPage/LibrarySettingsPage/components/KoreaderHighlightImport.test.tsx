/**
 * Tests for
 * src/pages/SettingsPage/LibrarySettingsPage/components/KoreaderHighlightImport.tsx.
 *
 * The card hands over every picked file and gives each one a line of its own,
 * so an unmatched sidecar is never folded into a total.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import KoreaderHighlightImport from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/KoreaderHighlightImport";
import type {
  SidecarOutcome,
  SidecarRow,
} from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/hooks";
import { renderLocalised } from "../../../../utils";

type Props = React.ComponentProps<typeof KoreaderHighlightImport>;

function renderCard(overrides: Partial<Props> = {}) {
  const props = {
    rows: null,
    isRunning: false,
    onChoose: vi.fn<Props["onChoose"]>(),
    ...overrides,
  };
  renderLocalised(<KoreaderHighlightImport {...props} />);
  return props;
}

function row(
  outcome: SidecarOutcome,
  title: string | null = "Dune",
): SidecarRow {
  return {
    key: `0:metadata.epub.lua:${title}`,
    name: "metadata.epub.lua",
    title,
    outcome,
  };
}

function imported(
  counts: Partial<Extract<SidecarOutcome, { kind: "imported" }>> = {},
): SidecarOutcome {
  return {
    kind: "imported",
    created: 3,
    updated: 1,
    unchanged: 2,
    left_deleted: 0,
    oversized: 0,
    ...counts,
  };
}

const SIDECAR = new File(["return {}"], "metadata.epub.lua");
const OTHER = new File(["return {}"], "metadata.pdf.lua");

describe("KoreaderHighlightImport", () => {
  it("hands over every file picked at once", async () => {
    const props = renderCard();

    await userEvent
      .setup()
      .upload(screen.getByLabelText("Choose metadata files"), [SIDECAR, OTHER]);

    expect(props.onChoose).toHaveBeenCalledWith([SIDECAR, OTHER]);
  });

  it("hands over the same file when it is picked a second time", async () => {
    // The input is emptied after each pick; without that, the browser fires
    // no change for a pick identical to the last one.
    const props = renderCard();
    const user = userEvent.setup();
    const input = screen.getByLabelText("Choose metadata files");

    await user.upload(input, SIDECAR);
    await user.upload(input, SIDECAR);

    expect(props.onChoose).toHaveBeenCalledTimes(2);
  });

  it("opens the file picker from the button", async () => {
    renderCard();
    const input = screen.getByLabelText<HTMLInputElement>(
      "Choose metadata files",
    );
    const opened = vi.fn<() => void>();
    input.addEventListener("click", opened);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Choose metadata files" }));

    expect(opened).toHaveBeenCalledOnce();
  });

  it("refuses a second pick while one is running", () => {
    renderCard({ isRunning: true });

    expect(
      screen.getByRole("button", { name: "Reading and importing..." }),
    ).toBeDisabled();
    expect(screen.getByLabelText("Choose metadata files")).toBeDisabled();
  });

  it("lists nothing before a pick", () => {
    renderCard();

    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("gives an imported file its counts and nothing about marks left out when none were", () => {
    renderCard({ rows: [row(imported())] });

    expect(
      screen.getByText("New: 3. Updated: 1. Unchanged: 2."),
    ).toBeInTheDocument();
  });

  it("says how many marks were left out as deleted and as unstorable", () => {
    renderCard({ rows: [row(imported({ left_deleted: 4, oversized: 5 }))] });

    expect(
      screen.getByText(
        "New: 3. Updated: 1. Unchanged: 2. Left out as deleted here: 4. Left out as too long, or as holding a character that cannot be stored: 5.",
      ),
    ).toBeInTheDocument();
  });

  it("gives every refused file its own reason, beside the imported ones", () => {
    renderCard({
      rows: [
        row(imported(), "Dune"),
        row({ kind: "unmatched" }, "Emma"),
        row({ kind: "empty" }, "Ulysses"),
      ],
    });

    const lines = screen
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(lines).toEqual([
      "DuneNew: 3. Updated: 1. Unchanged: 2.",
      "EmmaNo book you can see holds this file. Add the file from the scan page, then import again.",
      "UlyssesIt holds no highlights.",
    ]);
  });

  it("names a file whose sidecar records no title by its file name", () => {
    renderCard({ rows: [row({ kind: "unreadable" }, null)] });

    expect(screen.getByText("metadata.epub.lua")).toBeInTheDocument();
  });
});
