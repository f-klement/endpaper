/** Tests for src/pages/AuthorsPage/components/BatchBar. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthorMergeGroup } from "../../../../src/api/generated/model";
import BatchBar from "../../../../src/pages/AuthorsPage/components/BatchBar";
import { renderLocalised } from "../../../utils";

// The request the button would send, which is what the counts describe.
const TOLKIEN: AuthorMergeGroup = {
  keys: ["jrr tolkien", "j r r tolkien"],
  keep_name: "J. R. R. Tolkien",
};

const LE_GUIN: AuthorMergeGroup = {
  keys: ["le guin", "ursula k", "ursula k le guin"],
  keep_name: "Ursula K. Le Guin",
};

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("BatchBar", () => {
  it("counts the spellings and not only the groups", () => {
    // Two groups can be four rows or five, and the group count hides which.
    renderLocalised(
      <BatchBar
        payload={[TOLKIEN, LE_GUIN]}
        heldBack={0}
        withdrawn={0}
        isMerging={false}
        onFold={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/2 groups ticked, 5 spellings in all/),
    ).toBeInTheDocument();
  });

  it("says how many the server held back", () => {
    renderLocalised(
      <BatchBar
        payload={[TOLKIEN]}
        heldBack={2}
        withdrawn={0}
        isMerging={false}
        onFold={vi.fn()}
      />,
    );

    expect(screen.getByText(/2 more are left out/)).toBeInTheDocument();
  });

  it("says nothing about held back groups when there are none", () => {
    renderLocalised(
      <BatchBar
        payload={[TOLKIEN]}
        heldBack={0}
        withdrawn={0}
        isMerging={false}
        onFold={vi.fn()}
      />,
    );

    expect(screen.queryByText(/left out/)).not.toBeInTheDocument();
  });

  it("asks before folding, with both counts in the question", async () => {
    const onFold = vi.fn();
    renderLocalised(
      <BatchBar
        payload={[TOLKIEN, LE_GUIN]}
        heldBack={0}
        withdrawn={0}
        isMerging={false}
        onFold={onFold}
      />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Fold the ticked groups" }));

    expect(window.confirm).toHaveBeenCalledWith(
      "Fold 2 groups, 5 spellings in all?",
    );
    expect(onFold).toHaveBeenCalled();
  });

  it("folds nothing when the question is refused", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const onFold = vi.fn();
    renderLocalised(
      <BatchBar
        payload={[TOLKIEN]}
        heldBack={0}
        withdrawn={0}
        isMerging={false}
        onFold={onFold}
      />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Fold the ticked groups" }));

    expect(onFold).not.toHaveBeenCalled();
  });

  it("counts a group the reader narrowed apart from one the server held back", () => {
    // One number covering both would blame the reader's own edit on somebody
    // else's merge, which is the opposite of what happened.
    renderLocalised(
      <BatchBar
        payload={[TOLKIEN]}
        heldBack={1}
        withdrawn={2}
        isMerging={false}
        onFold={vi.fn()}
      />,
    );

    expect(screen.getByText(/1 more are left out/)).toBeInTheDocument();
    expect(
      screen.getByText(
        /2 more are out until the name they would be folded into/,
      ),
    ).toBeInTheDocument();
  });

  it("cannot be pressed with nothing ticked", () => {
    renderLocalised(
      <BatchBar
        payload={[]}
        heldBack={3}
        withdrawn={0}
        isMerging={false}
        onFold={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Fold the ticked groups" }),
    ).toBeDisabled();
  });
});
