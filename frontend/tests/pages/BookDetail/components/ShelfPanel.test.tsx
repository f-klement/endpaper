/** Tests for src/pages/BookDetail/components/ShelfPanel.tsx. */

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { BookOut } from "../../../../src/api/generated/model";
import ShelfPanel from "../../../../src/pages/BookDetail/components/ShelfPanel";
import { makeBook } from "../../../factories";
import { renderLocalised } from "../../../utils";

function renderPanel(book: Partial<BookOut> = {}) {
  const onSave = vi.fn();
  renderLocalised(
    <ShelfPanel
      book={makeBook(book)}
      knownLocations={[{ name: "Living room", book_count: 4 }]}
      isSaving={false}
      onSave={onSave}
    />,
  );
  return onSave;
}

describe("ShelfPanel", () => {
  it("shows the current values", () => {
    renderPanel({ series_name: "Dune", series_index: 2, location: "Loft" });

    expect(screen.getByLabelText("Series")).toHaveValue("Dune");
    expect(screen.getByLabelText("No.")).toHaveValue(2);
    expect(screen.getByLabelText("Where it is")).toHaveValue("Loft");
  });

  it("offers no save button until something changes", () => {
    renderPanel({ location: "Loft" });
    expect(
      screen.queryByRole("button", { name: "Save" }),
    ).not.toBeInTheDocument();
  });

  it("saves an edited location", async () => {
    const onSave = renderPanel({ location: null });
    const user = userEvent.setup();

    fireEvent.change(screen.getByLabelText("Where it is"), { target: { value: "Kitchen" } });
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ location: "Kitchen" }),
    );
  });

  it("sends null rather than an empty string when a field is cleared", async () => {
    // The API distinguishes absent from null; an empty string is neither.
    const onSave = renderPanel({ series_name: "Dune", series_index: 1 });
    const user = userEvent.setup();

    await user.clear(screen.getByLabelText("Series"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ series_name: null }),
    );
  });

  it("keeps a half number, which omnibus editions really have", async () => {
    const onSave = renderPanel({ series_name: "Discworld" });
    const user = userEvent.setup();

    fireEvent.change(screen.getByLabelText("No."), { target: { value: "2.5" } });
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ series_index: 2.5 }),
    );
  });

  it("offers the known locations as suggestions", () => {
    // Free text with no suggestions turns into six spellings of "living room".
    renderPanel();
    expect(screen.getByLabelText("Where it is")).toHaveAttribute(
      "list",
      "known-locations",
    );
  });
});
