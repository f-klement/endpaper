/**
 * Tests for src/components/CollapsibleSection.tsx.
 *
 * One framing since 2026-08-27. The `card` variant and its two tests went with
 * the settings fold: settings is a route tree now, nothing there folds, and the
 * book page is the only caller left. `SettingsSection` is the settings card,
 * and `SectionIcon.test.tsx` covers the badge both of them used to share.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import CollapsibleSection from "../../src/components/CollapsibleSection";
import { renderLocalised } from "../utils";

function render(isOpen: boolean, onToggle = vi.fn()) {
  renderLocalised(
    <CollapsibleSection
      id="lending"
      title="Lending this copy"
      isOpen={isOpen}
      onToggle={onToggle}
    >
      <p>who has it</p>
    </CollapsibleSection>,
  );
  return onToggle;
}

describe("CollapsibleSection", () => {
  it("is a button that says whether it is expanded", () => {
    // Not a div with an onClick: that is neither reachable by Tab nor
    // announced as something that opens.
    render(false);

    expect(
      screen.getByRole("button", { name: "Lending this copy" }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("says so when it is open", () => {
    render(true);

    expect(
      screen.getByRole("button", { name: "Lending this copy" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("names the panel it controls, and that panel exists while closed", () => {
    // aria-controls pointing at nothing is a dangling id, which is why the
    // panel is hidden rather than unmounted.
    render(false);

    const handle = screen.getByRole("button", { name: "Lending this copy" });
    const panelId = handle.getAttribute("aria-controls");
    expect(panelId).toBe("lending-panel");
    expect(document.getElementById(panelId!)).toBeInTheDocument();
  });

  it("hides its contents when closed", () => {
    render(false);

    expect(screen.getByText("who has it")).not.toBeVisible();
  });

  it("shows its contents when open", () => {
    render(true);

    expect(screen.getByText("who has it")).toBeVisible();
  });

  it("keeps a half typed form when it closes", () => {
    // Unmounting the children would throw away a note somebody was writing,
    // which is why the panel is hidden instead.
    const { rerender } = renderLocalised(
      <CollapsibleSection
        id="writing"
        title="Notes and quotes"
        isOpen={true}
        onToggle={vi.fn()}
      >
        <input aria-label="note" defaultValue="half a thought" />
      </CollapsibleSection>,
    );

    rerender(
      <CollapsibleSection
        id="writing"
        title="Notes and quotes"
        isOpen={false}
        onToggle={vi.fn()}
      >
        <input aria-label="note" defaultValue="half a thought" />
      </CollapsibleSection>,
    );

    expect(screen.getByDisplayValue("half a thought")).toBeInTheDocument();
  });

  it("reports a click", async () => {
    const onToggle = render(false);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Lending this copy" }));

    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("opens from the keyboard", async () => {
    const onToggle = render(false);
    const user = userEvent.setup();

    await user.tab();
    await user.keyboard("{Enter}");

    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("is a heading, so the page has an outline to skim", () => {
    render(false);

    expect(
      screen.getByRole("heading", { name: "Lending this copy" }),
    ).toBeInTheDocument();
  });
});
