/** Tests for src/components/HelpButton.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import HelpButton from "../../src/components/HelpButton";
import { renderLocalised } from "../utils";

describe("HelpButton", () => {
  it("is named by what it explains, not by its glyph", () => {
    // "?" read aloud tells nobody anything.
    renderLocalised(
      <HelpButton label="About searching Google Books" onClick={vi.fn()} />,
    );

    expect(
      screen.getByRole("button", { name: "About searching Google Books" }),
    ).toBeInTheDocument();
  });

  it("reports a click", async () => {
    const onClick = vi.fn();
    renderLocalised(<HelpButton label="Help" onClick={onClick} />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Help" }));

    expect(onClick).toHaveBeenCalledOnce();
  });
});
