/** Tests for src/pages/Home/components/ColumnPicker.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ColumnPicker from "../../../../src/pages/Home/components/ColumnPicker";
import { renderLocalised } from "../../../utils";

function renderPicker(props: Partial<Parameters<typeof ColumnPicker>[0]> = {}) {
  return renderLocalised(
    <ColumnPicker
      available={["title", "author", "callNumber", "classification"]}
      visible={["title", "author"]}
      onToggle={() => {}}
      onReset={() => {}}
      canReset={false}
      {...props}
    />,
  );
}

/** Open the panel, which is closed on arrival. */
async function open() {
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: /Columns/ }));
}

describe("ColumnPicker", () => {
  it("stays out of the way until it is asked for", () => {
    renderPicker();

    expect(screen.getByRole("button", { name: /Columns/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    // Out of the accessibility tree, so no chip is reachable.
    expect(screen.queryByRole("group")).toBeNull();
    expect(screen.queryByRole("button", { name: "Author" })).toBeNull();
  });

  it("keeps the panel in the document so aria-controls points at it", () => {
    // A dangling id is worse than none, which is the rule `CollapsibleSection`
    // states. Unmounting the panel would leave the button describing an
    // element that is not there.
    const { container } = renderPicker();

    const trigger = screen.getByRole("button", { name: /Columns/ });
    const id = trigger.getAttribute("aria-controls")!;
    expect(id).toBeTruthy();

    const panel = container.querySelector(`#${CSS.escape(id)}`);
    expect(panel).not.toBeNull();
    expect(panel).toHaveAttribute("hidden");
  });

  it("says how many of how many are drawn", () => {
    renderPicker();

    expect(
      screen.getByRole("button", { name: /Columns\s*2 of 4/ }),
    ).toBeInTheDocument();
  });

  it("offers every column this mode has, drawn or not", async () => {
    renderPicker();
    await open();

    const chips = screen.getAllByRole("button", { pressed: true });
    expect(chips.map((chip) => chip.textContent)).toEqual(["Title", "Author"]);
    expect(
      screen
        .getAllByRole("button", { pressed: false })
        .map((chip) => chip.textContent),
    ).toEqual(["Call number", "Subjects"]);
  });

  it("asks the caller to turn one on", async () => {
    const onToggle = vi.fn();
    renderPicker({ onToggle });
    await open();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Call number" }));

    expect(onToggle).toHaveBeenCalledWith("callNumber");
  });

  it("draws the title and refuses to turn it off", async () => {
    // Drawn rather than left out: a picker whose list disagrees with the
    // table's headers gives the reader no way to learn that the missing
    // control is not their mistake.
    const onToggle = vi.fn();
    renderPicker({ onToggle });
    await open();

    const title = screen.getByRole("button", { name: "Title" });
    expect(title).toHaveAttribute("aria-disabled", "true");
    // And no opacity on it: `opacity` on the button composites the accent fill
    // and its text together and takes the pair below the 4.5 contrast floor.
    expect(title.className).not.toMatch(/\bopacity-/);

    await userEvent.setup().click(title);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("says the title is always shown", async () => {
    renderPicker();
    await open();

    expect(screen.getByText(/title is always shown/i)).toBeInTheDocument();
  });

  it("offers no way back while there is nothing to go back from", async () => {
    renderPicker({ canReset: false });
    await open();

    expect(screen.queryByRole("button", { name: /usual columns/ })).toBeNull();
  });

  it("offers the way back once the set has been changed", async () => {
    const onReset = vi.fn();
    renderPicker({ canReset: true, onReset });
    await open();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /usual columns/ }));

    expect(onReset).toHaveBeenCalledOnce();
  });
});
