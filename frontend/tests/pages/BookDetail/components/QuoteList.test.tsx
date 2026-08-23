/** Tests for src/pages/BookDetail/components/QuoteList.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { QuoteOut, UserOut } from "../../../../src/api/generated/model";
import QuoteList from "../../../../src/pages/BookDetail/components/QuoteList";
import { makeQuote, makeUser } from "../../../factories";
import { renderLocalised } from "../../../utils";

function renderList(quotes: QuoteOut[] = [], user: Partial<UserOut> = {}) {
  const onAdd = vi.fn();
  const onEdit = vi.fn();
  const onRemove = vi.fn();
  renderLocalised(
    <QuoteList
      quotes={quotes}
      currentUser={makeUser({ id: 1, ...user })}
      isAdding={false}
      onAdd={onAdd}
      onEdit={onEdit}
      onRemove={onRemove}
    />,
  );
  return { onAdd, onEdit, onRemove };
}

describe("QuoteList", () => {
  it("says when there are none", () => {
    renderList();
    expect(screen.getByText("No quotes yet")).toBeInTheDocument();
  });

  it("renders the passage as a quotation rather than as body text", () => {
    // A blockquote, because these are the book's words and not the member's.
    renderList([makeQuote({ text: "Call me Ishmael" })]);
    expect(screen.getByText("Call me Ishmael").tagName).toBe("BLOCKQUOTE");
  });

  it("shows the page when there is one", () => {
    renderList([makeQuote({ page: 214 })]);
    expect(screen.getByText(/p\. 214/)).toBeInTheDocument();
  });

  it("shows no page marker when there is none", () => {
    renderList([makeQuote({ page: null })]);
    expect(screen.queryByText(/p\. /)).not.toBeInTheDocument();
  });

  it("shows the remark beside the passage", () => {
    renderList([makeQuote({ text: "Passage", note: "Why this one" })]);
    expect(screen.getByText("Why this one")).toBeInTheDocument();
  });

  it("sends the passage, the page and the remark together", async () => {
    const { onAdd } = renderList();

    await userEvent.type(screen.getByLabelText("The passage"), "A passage");
    await userEvent.type(screen.getByLabelText("Page the quote is on"), "42");
    await userEvent.type(
      screen.getByLabelText("What you want to say about it"),
      "A remark",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add quote" }));

    expect(onAdd).toHaveBeenCalledWith({
      text: "A passage",
      page: 42,
      note: "A remark",
    });
  });

  it("sends no page when the field is left empty", async () => {
    // Null rather than 0 or NaN: "I did not note it" is a real answer, and the
    // API refuses a page of zero.
    const { onAdd } = renderList();

    await userEvent.type(screen.getByLabelText("The passage"), "A passage");
    await userEvent.click(screen.getByRole("button", { name: "Add quote" }));

    expect(onAdd).toHaveBeenCalledWith({
      text: "A passage",
      page: null,
      note: null,
    });
  });

  it("refuses to send a passage of only spaces", async () => {
    const { onAdd } = renderList();

    await userEvent.type(screen.getByLabelText("The passage"), "   ");
    await userEvent.click(screen.getByRole("button", { name: "Add quote" }));

    expect(onAdd).not.toHaveBeenCalled();
  });

  it("lets the author correct their own quote", async () => {
    const { onEdit } = renderList([
      makeQuote({ id: 7, user_id: 1, text: "Typo", page: 3 }),
    ]);

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const field = screen.getByLabelText("Edit quote");
    await userEvent.clear(field);
    await userEvent.type(field, "Fixed");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onEdit).toHaveBeenCalledWith(7, {
      text: "Fixed",
      page: 3,
      note: null,
    });
  });

  it("does not save when the edit is cancelled", async () => {
    // Cancel sits inside the edit `<form>` now, so without `type="button"` it
    // defaults to submit and cancelling would save.
    const { onEdit } = renderList([makeQuote({ id: 7, user_id: 1, text: "Typo" })]);

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onEdit).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Edit quote")).not.toBeInTheDocument();
  });

  it("saves an edit from a form, not from a click handler", async () => {
    // The page field's min, max and implicit step are only enforced by a
    // submit. As a bare div they were inert, and an out-of-range page 422d
    // after the editor had already closed and thrown the edit away.
    renderList([makeQuote({ id: 7, user_id: 1 })]);

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));

    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toHaveAttribute("type", "submit");
    expect(save.closest("form")).not.toBeNull();
  });

  it("takes the remark in a textarea, so it can hold a line break", () => {
    // `<input type="text">` cannot hold a newline at all, and `note` renders
    // as a paragraph. It was an input when adding and a textarea when editing.
    renderList();
    expect(
      screen.getByLabelText("What you want to say about it").tagName,
    ).toBe("TEXTAREA");
  });

  it("offers no edit on somebody else's quote", () => {
    renderList([makeQuote({ user_id: 99 })], { id: 1, is_admin: true });
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("lets an admin delete somebody else's quote", () => {
    renderList([makeQuote({ user_id: 99 })], { id: 1, is_admin: true });
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("offers a member no delete on somebody else's quote", () => {
    renderList([makeQuote({ user_id: 99 })], { id: 1, is_admin: false });
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
  });
});
