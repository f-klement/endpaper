/**
 * Tests for src/pages/BookDetail/components/CopyPanel.tsx.
 *
 * Facts about the object rather than the work. The case worth pinning hardest
 * is the price: it is stored as an integer count of cents, so a typo that
 * became zero would be silent and permanent.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CopyPanel from "../../../../src/pages/BookDetail/components/CopyPanel";
import { makeBook, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

function renderPanel(book = {}) {
  const onSave = vi.fn();
  renderLocalised(
    <CopyPanel book={makeBook(book)} isSaving={false} onSave={onSave} />,
  );
  return onSave;
}

describe("CopyPanel", () => {
  it("sends the format and the condition", async () => {
    const onSave = renderPanel();
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText("Format"), "paperback");
    await user.selectOptions(screen.getByLabelText("Condition"), "good");
    await user.click(screen.getByRole("button", { name: "Save copy details" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ format: "paperback", condition: "good" }),
    );
  });

  it("sends a typed price as whole cents", async () => {
    const onSave = renderPanel();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Price paid"), "12.99");
    await user.click(screen.getByRole("button", { name: "Save copy details" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ purchase_price_minor: 1299 }),
    );
  });

  it("refuses a price it cannot read rather than storing zero", async () => {
    const onSave = renderPanel();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Price paid"), "twelve quid");
    await user.click(screen.getByRole("button", { name: "Save copy details" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("upper-cases the currency, so eur and EUR do not sort apart", async () => {
    const onSave = renderPanel();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Currency"), "eur");
    await user.click(screen.getByRole("button", { name: "Save copy details" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ purchase_currency: "EUR" }),
    );
  });

  it("clears a field rather than leaving the old value", async () => {
    const onSave = renderPanel({ purchase_source: "Oxfam" });
    const user = userEvent.setup();

    await user.clear(screen.getByLabelText("Bought from"));
    await user.click(screen.getByRole("button", { name: "Save copy details" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ purchase_source: null }),
    );
  });

  it("cannot be saved until something changes", () => {
    renderPanel();
    expect(
      screen.getByRole("button", { name: "Save copy details" }),
    ).toBeDisabled();
  });

  it("shows a stored price back as a decimal", () => {
    renderPanel({ purchase_price_minor: 1299 });
    expect(screen.getByLabelText("Price paid")).toHaveValue("12.99");
  });

  it("opens itself when the book already has details to show", () => {
    const { container } = renderLocalised(
      <CopyPanel
        book={makeBook({ format: "hardcover" })}
        isSaving={false}
        onSave={vi.fn()}
      />,
    );
    expect(container.querySelector("details")).toHaveAttribute("open");
  });

  it("stays closed on a book with none, so the page is not longer for nothing", () => {
    const { container } = renderLocalised(
      <CopyPanel book={makeBook()} isSaving={false} onSave={vi.fn()} />,
    );
    expect(container.querySelector("details")).not.toHaveAttribute("open");
  });
});
