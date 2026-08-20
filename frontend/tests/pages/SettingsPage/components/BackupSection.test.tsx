/**
 * Tests for src/pages/SettingsPage/components/BackupSection.tsx.
 *
 * Restoring is the one action in the app that destroys data it was not given
 * the id of, so what is pinned here is the friction in front of it.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import BackupSection from "../../../../src/pages/SettingsPage/components/BackupSection";
import { renderLocalised } from "../../../utils";

function renderSection(
  overrides: Partial<React.ComponentProps<typeof BackupSection>> = {},
) {
  const props = {
    isDownloading: false,
    downloadError: null,
    onDownload: vi.fn(),
    isRestoring: false,
    restoreError: null,
    restored: null,
    onRestore: vi.fn(),
    ...overrides,
  };
  renderLocalised(<BackupSection {...props} />);
  return props;
}

const ARCHIVE = new File([new Uint8Array([80, 75, 3, 4])], "backup.zip", {
  type: "application/zip",
});

describe("BackupSection", () => {
  it("downloads when asked", async () => {
    const props = renderSection();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Download a backup" }));

    expect(props.onDownload).toHaveBeenCalledOnce();
  });

  it("says the CSV export is not a backup", () => {
    // Somebody who believes it is has no copy of their notes, loans or covers.
    renderSection();
    expect(screen.getByText(/The CSV export is not this/)).toBeInTheDocument();
  });

  it("warns that restoring replaces everything", () => {
    renderSection();
    expect(
      screen.getByText(/Restoring replaces everything/),
    ).toBeInTheDocument();
  });

  it("offers no restore button until a file is chosen", () => {
    renderSection();
    expect(
      screen.queryByRole("button", { name: /Restore from/ }),
    ).not.toBeInTheDocument();
  });

  it("asks before restoring", async () => {
    const props = renderSection();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();

    await user.upload(screen.getByLabelText("Backup file"), ARCHIVE);
    await user.click(screen.getByRole("button", { name: /Restore from/ }));

    expect(confirmSpy).toHaveBeenCalled();
    expect(props.onRestore).not.toHaveBeenCalled();
  });

  it("restores once confirmed", async () => {
    const props = renderSection();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();

    await user.upload(screen.getByLabelText("Backup file"), ARCHIVE);
    await user.click(screen.getByRole("button", { name: /Restore from/ }));

    expect(props.onRestore).toHaveBeenCalledWith(ARCHIVE);
  });

  it("names the file on the button, so the wrong one is visible first", async () => {
    renderSection();
    await userEvent
      .setup()
      .upload(screen.getByLabelText("Backup file"), ARCHIVE);

    expect(
      screen.getByRole("button", { name: "Restore from backup.zip" }),
    ).toBeInTheDocument();
  });

  it("reports what a restore put back", () => {
    renderSection({ restored: { books: 42, covers: 7 } });
    expect(
      screen.getByText("Restored 42 books and 7 covers."),
    ).toBeInTheDocument();
  });

  it("surfaces a refused archive", () => {
    renderSection({ restoreError: new Error("That file is not a backup.") });
    expect(screen.getByRole("alert")).toHaveTextContent("not a backup");
  });
});
