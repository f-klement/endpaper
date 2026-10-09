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
      canChange={true}
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
    // The rule about opacity on this chip is not here: it is not a fact about
    // the title, and stating it here is what let it cover one element. See
    // "no chosen chip carries an opacity class" below.

    await userEvent.setup().click(title);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("no chosen chip carries an opacity class", async () => {
    // **`opacity` on a button composites its fill and its text together**, and
    // a chosen chip's pair is `on-accent` on `accent-fill`, which
    // `palettes.test.ts` floors at 4.5:1 and which halves to 2.83:1 light and
    // 3.52:1 dark under a 50% dim. The unchosen arm is `text-paper-600` on
    // `paper-0` and is exempt: `index.css` records that a disabled control does
    // not owe the 3:1 floor, and every `disabled:opacity-50` control in this
    // app already sits there.
    //
    // **Every pressed button rather than the title**, which is what this
    // replaced. The title was one element read by name, so a dim applied to
    // every other chosen chip passed clean, measured: the whole suite green at
    // 141 files. `aria-pressed` is what the rule is actually about, so the
    // assertion now covers the chips this picker draws today and the ones a
    // later version adds.
    renderPicker({ visible: ["title", "author", "callNumber"] });
    await open();

    const pressed = screen.getAllByRole("button", { pressed: true });
    expect(pressed.length).toBeGreaterThan(1);
    for (const chip of pressed) {
      expect(chip.className).not.toMatch(/\bopacity-/);
    }
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

describe("ColumnPicker before the mode is known", () => {
  it("disables every chip", async () => {
    // A toggle in that window writes the household's key whatever mode the
    // flags turn out to name, and nothing says so afterwards.
    const onToggle = vi.fn();
    renderPicker({ canChange: false, onToggle });
    await open();

    const author = screen.getByRole("button", { name: "Author" });
    expect(author).toBeDisabled();
    await userEvent.setup().click(author);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("disables the reset rather than hiding it", async () => {
    // Hiding it would read as "there is nothing to reset", which is the
    // opposite of what `canReset` true means.
    const onReset = vi.fn();
    renderPicker({ canChange: false, canReset: true, onReset });
    await open();

    const reset = screen.getByRole("button", {
      name: "Back to the usual columns",
    });
    expect(reset).toBeDisabled();
    await userEvent.setup().click(reset);
    expect(onReset).not.toHaveBeenCalled();
  });

  it("hands every chip back once the mode arrives", async () => {
    // The gate is a window, not a mode of its own: nothing stays disabled.
    renderPicker({ canChange: true });
    await open();

    expect(screen.getByRole("button", { name: "Author" })).toBeEnabled();
  });
});
