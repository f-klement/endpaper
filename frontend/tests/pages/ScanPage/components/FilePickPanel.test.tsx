/** Tests for src/pages/ScanPage/components/FilePickPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import FilePickPanel from "../../../../src/pages/ScanPage/components/FilePickPanel";
import { SUPPORTED_EXTENSIONS } from "../../../../src/lib/fileName";
import { renderLocalised } from "../../../utils";

function renderPanel(
  overrides: Partial<Parameters<typeof FilePickPanel>[0]> = {},
) {
  // The spy is held separately from the props it is spread into, so its type
  // survives the spread: a `Partial` override widens `onPick` to the prop's own
  // type and takes `.mock` with it.
  const onPick = vi.fn<(files: File[]) => void>();
  renderLocalised(
    <FilePickPanel
      onPick={onPick}
      isReading={false}
      skipped={0}
      {...overrides}
    />,
  );
  return { onPick };
}

function input(): HTMLInputElement {
  return screen.getByLabelText("Book files") as HTMLInputElement;
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

  it("offers a whole folder, which is the only thing that carries a path", () => {
    // The folder above a file is often the one thing that names its author, and
    // a single file pick carries no path at all.
    renderPanel();
    // Told apart by something a sighted member can read, not only by a name a
    // screen reader gets: no browser draws a different button for a directory
    // input, so two bare file inputs look like the same control twice.
    expect(screen.getByText("A whole folder of books").tagName).toBe("LABEL");
    expect(screen.getByText("Book files").tagName).toBe("LABEL");
    const folder = screen.getByLabelText(
      "A whole folder of books",
    ) as HTMLInputElement;
    expect(folder.type).toBe("file");
    expect(folder.getAttribute("webkitdirectory")).toBe("");
  });

  it("offers every format the walk considers, not only EPUB", () => {
    // A filter on the dialog and never a check, but a filter that greys out a
    // format the walk would have read is a picker that lies about itself.
    renderPanel();
    const accepted = input().accept.split(",");
    for (const extension of SUPPORTED_EXTENSIONS) {
      expect(accepted).toContain(extension);
    }
  });

  it("says what it passed over, where a queue would not exist to say it", () => {
    // A folder of CBR files produces no queue at all, so a message beside the
    // queue would be absent in exactly the case it is for.
    renderPanel({ skipped: 3 });
    expect(
      screen.getByText(
        "3 passed over, because Endpaper reads no format of theirs.",
      ),
    ).toBeInTheDocument();
  });

  it("says nothing about passing anything over when it passed nothing", () => {
    renderPanel();
    expect(screen.queryByText(/passed over/)).not.toBeInTheDocument();
  });
});
