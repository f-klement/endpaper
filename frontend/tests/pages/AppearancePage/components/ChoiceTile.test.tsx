/** Tests for src/pages/AppearancePage/components/ChoiceTile.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ChoiceTile from "../../../../src/pages/AppearancePage/components/ChoiceTile";
import { renderLocalised } from "../../../utils";

describe("ChoiceTile", () => {
  it("names the thing being chosen", () => {
    renderLocalised(
      <ChoiceTile name="Willow Bough" selected={false} onSelect={() => {}}>
        <span data-testid="preview" />
      </ChoiceTile>,
    );

    expect(
      screen.getByRole("button", { name: /Willow Bough/ }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("preview")).toBeInTheDocument();
  });

  it("says whether it is the one in force", () => {
    renderLocalised(
      <ChoiceTile name="Nord" selected onSelect={() => {}}>
        <span />
      </ChoiceTile>,
    );

    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  });

  it("chooses on a click", async () => {
    const onSelect = vi.fn();
    renderLocalised(
      <ChoiceTile name="Nord" selected={false} onSelect={onSelect}>
        <span />
      </ChoiceTile>,
    );

    await userEvent.setup().click(screen.getByRole("button"));

    expect(onSelect).toHaveBeenCalledOnce();
  });

  it("shows every note rather than the last one", () => {
    // Nord's light member carries an attribution and a constructed note, and an
    // attribution that disappeared whenever a note appeared would vanish
    // exactly where it is most needed.
    renderLocalised(
      <ChoiceTile
        name="Nord"
        notes={["Colours from somebody, MIT", "Light was built here."]}
        selected={false}
        onSelect={() => {}}
      >
        <span />
      </ChoiceTile>,
    );

    expect(screen.getByText("Colours from somebody, MIT")).toBeInTheDocument();
    expect(screen.getByText("Light was built here.")).toBeInTheDocument();
  });
});
