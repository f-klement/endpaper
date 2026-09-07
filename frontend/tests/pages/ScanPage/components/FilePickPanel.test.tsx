/** Tests for src/pages/ScanPage/components/FilePickPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import FilePickPanel from "../../../../src/pages/ScanPage/components/FilePickPanel";
import { renderLocalised } from "../../../utils";

function renderPanel(
  overrides: Partial<Parameters<typeof FilePickPanel>[0]> = {},
) {
  // The spy is held separately from the props it is spread into, so its type
  // survives the spread: a `Partial` override widens `onPick` to the prop's own
  // type and takes `.mock` with it.
  const onPick = vi.fn<(files: File[]) => void>();
  renderLocalised(
    <FilePickPanel onPick={onPick} isReading={false} {...overrides} />,
  );
  return { onPick };
}

function input(): HTMLInputElement {
  return screen.getByLabelText("EPUB files") as HTMLInputElement;
}

describe("FilePickPanel", () => {
  it("offers a file input and nothing that opens by itself", () => {
    // The page next to this one says why for the camera, and a file dialog is
    // the same class of thing: it may not open because somebody looked at the
    // tab. An input cannot, which is the whole reason the intake is one.
    renderPanel();
    expect(input().type).toBe("file");
  });

  it("says the files are not uploaded, because that is the decision", () => {
    renderPanel();
    expect(screen.getByText(/never uploaded/)).toBeInTheDocument();
  });

  it("reports what was picked", async () => {
    const { onPick } = renderPanel();
    const file = new File(["bytes"], "dune.epub");

    await userEvent.upload(input(), file);

    expect(onPick).toHaveBeenCalledWith([file]);
  });

  it("reports several files as one batch", async () => {
    const { onPick } = renderPanel();
    const files = [new File(["a"], "one.epub"), new File(["b"], "two.epub")];

    await userEvent.upload(input(), files);

    expect(onPick.mock.calls[0]?.[0]).toHaveLength(2);
  });

  it("clears itself so the same file can be picked again", async () => {
    // Without this a file removed from the queue by hand could never be picked
    // back: the input holds the same value and fires no change.
    const { onPick } = renderPanel();
    const file = new File(["bytes"], "dune.epub");

    await userEvent.upload(input(), file);
    await userEvent.upload(input(), file);

    expect(onPick).toHaveBeenCalledTimes(2);
  });

  it("says nothing about reading when nothing is being read", () => {
    renderPanel();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("says so while a pick is being read", () => {
    renderPanel({ isReading: true });
    expect(screen.getByRole("status")).toHaveTextContent("Reading the files");
  });
});
