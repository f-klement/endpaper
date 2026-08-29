/**
 * Tests for AccountSettingsPage/components/AddressField.tsx.
 *
 * The same control for the member's own address and for a row of the admin
 * list. Its one interesting state is read only, which is drawn as text rather
 * than as a disabled input: a disabled input reads as temporarily unavailable,
 * and this one never becomes available.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AddressField from "../../../../../src/pages/SettingsPage/AccountSettingsPage/components/AddressField";
import { renderLocalised } from "../../../../utils";

function member(
  overrides: Partial<Parameters<typeof AddressField>[0]["member"]> = {},
) {
  return { id: 1, username: "kim", email: null, editable: true, ...overrides };
}

describe("AddressField", () => {
  it("starts from the saved address", () => {
    renderLocalised(
      <AddressField
        member={member({ email: "kim@example.org" })}
        label="Your address"
        disabled={false}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Your address")).toHaveValue(
      "kim@example.org",
    );
  });

  it("trims what was typed before handing it over", async () => {
    const onSave = vi.fn();
    renderLocalised(
      <AddressField
        member={member()}
        label="Your address"
        disabled={false}
        onSave={onSave}
      />,
    );

    await userEvent.type(
      screen.getByLabelText("Your address"),
      "  kim@example.org  ",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith("kim@example.org");
  });

  it("hands over null for a field with nothing in it", async () => {
    const onSave = vi.fn();
    renderLocalised(
      <AddressField
        member={member({ email: "kim@example.org" })}
        label="Your address"
        disabled={false}
        onSave={onSave}
      />,
    );

    await userEvent.clear(screen.getByLabelText("Your address"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith(null);
  });

  it("draws no input at all when the directory owns the address", () => {
    renderLocalised(
      <AddressField
        member={member({ email: "kim@directory.example", editable: false })}
        label="Your address"
        disabled={false}
        onSave={vi.fn()}
      />,
    );

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("kim@directory.example")).toBeInTheDocument();
  });

  it("says so when a directory owned row has no address either", () => {
    renderLocalised(
      <AddressField
        member={member({ editable: false })}
        label="Your address"
        disabled={false}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByText("None set.")).toBeInTheDocument();
  });

  it("takes the saved value when it changes underneath", () => {
    const { rerender } = renderLocalised(
      <AddressField
        member={member()}
        label="Your address"
        disabled={false}
        onSave={vi.fn()}
      />,
    );

    rerender(
      <AddressField
        member={member({ email: "kim@example.org" })}
        label="Your address"
        disabled={false}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Your address")).toHaveValue(
      "kim@example.org",
    );
  });
});
