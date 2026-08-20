/**
 * Tests for src/components/Button.tsx.
 *
 * What is worth pinning is not the styling, which will keep moving, but the
 * three behaviours that were inconsistent across the forty hand-rolled buttons
 * this replaced: the default type, whether a loading control can still be
 * clicked, and whether the state reaches assistive tech.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Button from "../../src/components/Button";
import { renderLocalised } from "../utils";

describe("Button", () => {
  it("renders its label", () => {
    renderLocalised(<Button>Add book</Button>);
    expect(screen.getByRole("button", { name: "Add book" })).toBeInTheDocument();
  });

  it("defaults to type=button", () => {
    // An un-typed button inside a form submits it. That has caused a stray
    // submit in this codebase before, so the default is the safe one and a
    // form's real submit has to ask for it.
    renderLocalised(<Button>Cancel</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });

  it("still allows an explicit submit", () => {
    renderLocalised(<Button type="submit">Look up</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "submit");
  });

  it("calls its handler", async () => {
    const onClick = vi.fn();
    renderLocalised(<Button onClick={onClick}>Go</Button>);
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  describe("while loading", () => {
    it("cannot be clicked again", async () => {
      // The whole point: a second click on a button that is already working is
      // a duplicate request, and several of the buttons this replaced allowed
      // exactly that.
      const onClick = vi.fn();
      renderLocalised(
        <Button isLoading onClick={onClick}>
          Save
        </Button>,
      );
      await userEvent.click(screen.getByRole("button"));
      expect(onClick).not.toHaveBeenCalled();
    });

    it("keeps its label", () => {
      // Swapping the text to "Saving..." changes the button's width mid-click,
      // which moves whatever sits beside it.
      renderLocalised(<Button isLoading>Save</Button>);
      expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
    });

    it("announces itself as busy", () => {
      // A spinner is invisible to a screen reader. This is what actually
      // carries the state.
      renderLocalised(<Button isLoading>Save</Button>);
      expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
    });
  });

  it("is not busy when it is merely disabled", () => {
    renderLocalised(<Button disabled>Save</Button>);
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).not.toHaveAttribute("aria-busy");
  });

  it("hides its icon from assistive tech", () => {
    // Otherwise the accessible name becomes "📷 Start scanning".
    renderLocalised(<Button icon="📷">Start scanning</Button>);
    expect(
      screen.getByRole("button", { name: "Start scanning" }),
    ).toBeInTheDocument();
  });

  it("keeps caller classes alongside its own", () => {
    renderLocalised(<Button className="mt-3">Go</Button>);
    const button = screen.getByRole("button");
    expect(button.className).toContain("mt-3");
    expect(button.className).toContain("rounded-lg");
  });
});
