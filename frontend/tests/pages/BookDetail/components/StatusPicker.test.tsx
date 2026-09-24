/** Tests for src/pages/BookDetail/components/StatusPicker.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReadStatus } from "../../../../src/api/generated/model";
import StatusPicker from "../../../../src/pages/BookDetail/components/StatusPicker";
import { STATUS_ORDER } from "../../../../src/pages/types";
import { renderLocalised } from "../../../utils";

describe("StatusPicker", () => {
  it("offers every status the shelf can hold, in the shared order", () => {
    // The picker used to carry its own list of five, which is why this file
    // exists: the type could not see a status left out of that list, so a sixth
    // would have been unreachable here while the card and the table printed it.
    renderLocalised(
      <StatusPicker current={ReadStatus.unread} onChange={vi.fn()} />,
    );

    const offered = screen
      .getAllByRole("button")
      .map((button) => button.textContent?.trim());

    expect(offered).toEqual([
      "Unread",
      "Want to Read",
      "Reading",
      "Read",
      "Did not finish",
    ]);
  });

  it("marks the reader's current status as pressed, and only that one", () => {
    renderLocalised(
      <StatusPicker current={ReadStatus.reading} onChange={vi.fn()} />,
    );

    const pressed = screen
      .getAllByRole("button")
      .filter((button) => button.getAttribute("aria-pressed") === "true")
      .map((button) => button.textContent?.trim());

    expect(pressed).toEqual(["Reading"]);
  });

  it("reports the status behind the button that was pressed", async () => {
    // No button carries a value of its own any more: each is built from the
    // status, so this is what says the right one is still wired to the right
    // word.
    const onChange = vi.fn();
    renderLocalised(
      <StatusPicker current={ReadStatus.unread} onChange={onChange} />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Did not finish" }));

    expect(onChange).toHaveBeenCalledWith(ReadStatus.did_not_finish);
  });

  it("gives every button one glyph, hidden from a reader that has the word", () => {
    // `STATUS_ICONS` being total says every status has a glyph. It does not
    // say the glyph reaches the DOM, or that it stays decorative: announced,
    // it makes a screen reader say each status twice.
    renderLocalised(
      <StatusPicker current={ReadStatus.unread} onChange={vi.fn()} />,
    );

    for (const button of screen.getAllByRole("button")) {
      const glyphs = button.querySelectorAll("svg");

      expect(glyphs).toHaveLength(1);
      expect(glyphs[0]?.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("names one wide column per status it offers", () => {
    // Tailwind reads class names out of the source, so the column count cannot
    // be computed and is written into the markup. Recomputed here from
    // `STATUS_ORDER` rather than asserted as a literal five: a sixth status is
    // already a compile error at the three tables, and this is what stops it
    // rendering as a row of five with an orphan underneath, which the picker's
    // own comment records paying for once.
    const { container } = renderLocalised(
      <StatusPicker current={ReadStatus.unread} onChange={vi.fn()} />,
    );

    expect(container.querySelector("div.grid")?.className).toContain(
      `sm:grid-cols-${STATUS_ORDER.length}`,
    );
  });
});
