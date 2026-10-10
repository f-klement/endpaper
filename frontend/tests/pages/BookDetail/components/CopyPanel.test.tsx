/**
 * Tests for src/pages/BookDetail/components/CopyPanel.tsx.
 *
 * Facts about the object rather than the work. The case worth pinning hardest
 * is the price: it is stored as an integer count of cents, so a typo that
 * became zero would be silent and permanent.
 */

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CopyPanel from "../../../../src/pages/BookDetail/components/CopyPanel";
import { makeBook, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";
import type {
  BookDetailsUpdate,
  BookOut,
} from "../../../../src/api/generated/model";

beforeEach(resetIds);

function renderPanel(book = {}) {
  const onSave = vi.fn<(fields: BookDetailsUpdate) => void>();
  renderLocalised(
    <CopyPanel book={makeBook(book)} isSaving={false} onSave={onSave} />,
  );
  return onSave;
}

/** The panel over one book, for a test that rerenders it with another. */
function panel(book: BookOut) {
  return (
    <CopyPanel
      book={book}
      isSaving={false}
      onSave={vi.fn<(fields: BookDetailsUpdate) => void>()}
    />
  );
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

    fireEvent.change(screen.getByLabelText("Price paid"), {
      target: { value: "12.99" },
    });
    await user.click(screen.getByRole("button", { name: "Save copy details" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ purchase_price_minor: 1299 }),
    );
  });

  it("refuses a price it cannot read rather than storing zero", async () => {
    const onSave = renderPanel();
    const user = userEvent.setup();

    fireEvent.change(screen.getByLabelText("Price paid"), {
      target: { value: "twelve quid" },
    });
    await user.click(screen.getByRole("button", { name: "Save copy details" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("upper-cases the currency, so eur and EUR do not sort apart", async () => {
    const onSave = renderPanel();
    const user = userEvent.setup();

    fireEvent.change(screen.getByLabelText("Currency"), {
      target: { value: "eur" },
    });
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

  it("shows the stored values again when the book changes underneath", () => {
    const book = makeBook({ purchase_currency: "EUR" });
    const { rerender } = renderLocalised(panel(book));
    fireEvent.change(screen.getByLabelText("Currency"), {
      target: { value: "GBP" },
    });

    rerender(panel({ ...book, purchase_currency: "USD" }));

    expect(screen.getByLabelText("Currency")).toHaveValue("USD");
  });

  it("shows a stored price back as a decimal", () => {
    renderPanel({ purchase_price_minor: 1299 });
    expect(screen.getByLabelText("Price paid")).toHaveValue("12.99");
  });

  it("names itself with a heading, since it lost the summary that announced it", () => {
    // The <summary> it used to have was focusable and announced. A bold <p>
    // is announced as nothing, which would leave "Your copies" the one
    // section with no heading inside it at all.
    renderLocalised(
      <CopyPanel
        book={makeBook()}
        isSaving={false}
        onSave={vi.fn<(fields: BookDetailsUpdate) => void>()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "This copy" }),
    ).toBeInTheDocument();
  });

  it("carries no disclosure of its own", () => {
    // It had a <details> that opened itself on a copy with something already
    // recorded. The "Your copies" section folds this panel away now, and two
    // disclosures nested inside each other put these fields two clicks deep.
    // Whether the panel is worth showing at all is now the section's default,
    // which is tested in pages/BookDetail/hooks.test.tsx.
    const { container } = renderLocalised(
      <CopyPanel
        book={makeBook({ format: "hardcover" })}
        isSaving={false}
        onSave={vi.fn<(fields: BookDetailsUpdate) => void>()}
      />,
    );

    expect(container.querySelector("details")).toBeNull();
    expect(screen.getByLabelText("Format")).toBeVisible();
  });
});
