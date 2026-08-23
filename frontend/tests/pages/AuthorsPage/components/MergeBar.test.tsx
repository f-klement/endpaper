/** Tests for src/pages/AuthorsPage/components/MergeBar. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MergeBar from "../../../../src/pages/AuthorsPage/components/MergeBar";
import { renderLocalised } from "../../../utils";

function author(key: string, name: string) {
  return { key, name, book_count: 1, spellings: [name], merged: [] };
}

const TWO = [author("tolkein", "Tolkein"), author("tolkien", "Tolkien")];

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

function renderBar(selected = TWO, onMerge = vi.fn()) {
  renderLocalised(
    <MergeBar
      selected={selected}
      isMerging={false}
      onMerge={onMerge}
      onClear={vi.fn()}
    />,
  );
  return onMerge;
}

describe("MergeBar", () => {
  it("folds a misspelling into the right name, which no rule proposes", () => {
    // `Tolkein` and `Tolkien` share no word, no initial pattern and no
    // squashed key, so the suggestion pass offers nothing and this bar is the
    // only way to say they are one person.
    const onMerge = renderBar();

    return userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Keep Tolkien" }))
      .then(() => {
        expect(onMerge).toHaveBeenCalledWith(["tolkein", "tolkien"], "Tolkien");
      });
  });

  it("renames one name on its own, and says rename rather than fold", async () => {
    // Every string here used to describe a fold: a field labelled "Or a name
    // none of them has" when there is one of them, and a confirmation reading
    // `Fold 1 spellings into "X"?`. It is the same write; the words were for
    // the two-name case.
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(true);
    const onMerge = renderBar([author("tolkein", "Tolkein")]);

    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("A name to use instead"),
      "J. R. R. Tolkien",
    );
    await user.click(screen.getByRole("button", { name: "Rename" }));

    expect(onMerge).toHaveBeenCalledWith(["tolkein"], "J. R. R. Tolkien");
    expect(confirmed).toHaveBeenLastCalledWith(
      'Rename "Tolkein" to "J. R. R. Tolkien"?',
    );
  });

  it("offers no name to keep when only one is selected", () => {
    // Keeping the only selected name would fold it into itself.
    renderBar([author("tolkein", "Tolkein")]);

    expect(
      screen.queryByRole("button", { name: /^Keep / }),
    ).not.toBeInTheDocument();
  });

  it("says how many spellings move, which is the last checkable fact", async () => {
    // A native confirm covers the page, and the selection survives the search
    // box, so the names being folded can be off screen when it opens.
    const confirmed = vi.spyOn(window, "confirm").mockReturnValue(true);
    const three = [...TWO, author("tolkien j r r", "Tolkien, J. R. R.")];
    renderBar(three);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Keep Tolkien" }));
    expect(confirmed).toHaveBeenLastCalledWith(
      'Fold 2 spellings into "Tolkien"?',
    );

    await user.type(
      screen.getByLabelText("Or a name none of them has"),
      "J. R. R. Tolkien",
    );
    await user.click(
      screen.getByRole("button", { name: "Fold into this name" }),
    );
    expect(confirmed).toHaveBeenLastCalledWith(
      'Fold 3 spellings into "J. R. R. Tolkien"?',
    );
  });

  it("says how many are selected", () => {
    renderBar();

    expect(screen.getByText("2 selected")).toBeInTheDocument();
  });

  it("sends nothing when the reader cancels", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const onMerge = renderBar();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Keep Tolkien" }));

    expect(onMerge).not.toHaveBeenCalled();
  });
});
