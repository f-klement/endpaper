/** Tests for
 * src/pages/SettingsPage/LibrarySettingsPage/components/VocabulariesSection.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { VocabularyOut } from "../../../../../src/api/generated/model";
import VocabulariesSection from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/VocabulariesSection";
import { renderLocalised } from "../../../../utils";

const GND: VocabularyOut = {
  scheme: "gnd",
  name: "GND subjects",
  licence: "CC0-1.0",
  copyable: true,
  entries: null,
  fetched_at: null,
  released: null,
  progress: null,
};
const LCSH: VocabularyOut = {
  scheme: "lcsh",
  name: "Library of Congress Subject Headings",
  licence: null,
  copyable: false,
  entries: null,
  fetched_at: null,
  released: null,
  progress: null,
};

type SectionProps = React.ComponentProps<typeof VocabulariesSection>;

function renderSection(over: Partial<SectionProps> = {}) {
  const props: SectionProps = {
    vocabularies: [GND, LCSH],
    isStarting: false,
    error: null,
    onDownload: vi.fn<SectionProps["onDownload"]>(),
    ...over,
  };
  renderLocalised(<VocabulariesSection {...props} />);
  return props;
}

function row(name: string): HTMLElement {
  return screen.getByText(name).closest("li")!;
}

describe("VocabulariesSection", () => {
  it("downloads a vocabulary not yet copied by its scheme", async () => {
    const props = renderSection();

    await userEvent.click(
      within(row("GND subjects")).getByRole("button", { name: "Download" }),
    );

    expect(props.onDownload).toHaveBeenCalledWith("gnd");
  });

  it("disables the download where the licence permits no copy, and says why", () => {
    renderSection();

    const lcsh = within(row("Library of Congress Subject Headings"));
    expect(lcsh.getByRole("button", { name: "Download" })).toBeDisabled();
    expect(
      lcsh.getByText(
        "Its licence does not permit a local copy, so lookups always ask the source live.",
      ),
    ).toBeInTheDocument();
  });

  it("offers a refresh on a loaded copy and shows when it was fetched and released", () => {
    renderSection({
      vocabularies: [
        {
          ...GND,
          entries: 1200,
          fetched_at: "2026-11-20T10:00:00",
          released: "2026-11-01T00:00:00",
        },
      ],
    });

    const gnd = within(row("GND subjects"));
    expect(gnd.getByRole("button", { name: "Refresh" })).toBeEnabled();
    expect(
      gnd.getByText(/Fetched 11\/20\/2026, 1,200 entries\./),
    ).toBeInTheDocument();
    expect(
      gnd.getByText(/Released by the source 11\/1\/2026\./),
    ).toBeInTheDocument();
  });

  it("shows a running load's share and holds the button until it ends", () => {
    renderSection({
      vocabularies: [
        {
          ...GND,
          progress: { phase: "fetching", done: 1, total: 4, error: null },
        },
      ],
    });

    const gnd = within(row("GND subjects"));
    expect(gnd.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
    expect(gnd.getByText("Downloading: 25%")).toBeInTheDocument();
    expect(gnd.getByRole("button", { name: "Download" })).toBeDisabled();
  });

  it("draws an indeterminate bar, not 0%, where the server knows no total", () => {
    renderSection({
      vocabularies: [
        {
          ...GND,
          progress: { phase: "converting", done: 7, total: null, error: null },
        },
      ],
    });

    expect(screen.getByText("Converting")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).not.toHaveAttribute(
      "aria-valuenow",
    );
  });

  it("reports the last load's failure and offers the download again", () => {
    renderSection({
      vocabularies: [
        {
          ...GND,
          progress: {
            phase: "failed",
            done: 0,
            total: null,
            error: "HTTP 503",
          },
        },
      ],
    });

    const gnd = within(row("GND subjects"));
    expect(gnd.getByRole("alert")).toHaveTextContent(
      "The last download failed: HTTP 503",
    );
    expect(gnd.getByRole("button", { name: "Download" })).toBeEnabled();
  });
});
