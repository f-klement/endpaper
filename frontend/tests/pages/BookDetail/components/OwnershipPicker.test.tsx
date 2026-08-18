/** Tests for src/pages/BookDetail/components/OwnershipPicker.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { OwnershipStatus } from "../../../../src/api/generated/model";
import OwnershipPicker from "../../../../src/pages/BookDetail/components/OwnershipPicker";
import { renderLocalised } from "../../../utils";

describe("OwnershipPicker", () => {
  it("offers all three states", () => {
    // Including "not confirmed": a Goodreads import cannot answer the
    // question, so it has to be expressible rather than guessed at.
    renderLocalised(
      <OwnershipPicker value={OwnershipStatus.owned} onChange={vi.fn()} />,
    );

    expect(
      screen.getByRole("button", { name: "On the shelf" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Not owned" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Not confirmed" }),
    ).toBeInTheDocument();
  });

  it("marks the current state as pressed", () => {
    renderLocalised(
      <OwnershipPicker value={OwnershipStatus.unknown} onChange={vi.fn()} />,
    );

    expect(
      screen.getByRole("button", { name: "Not confirmed" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "On the shelf" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("reports a change", async () => {
    const onChange = vi.fn();
    renderLocalised(
      <OwnershipPicker value={OwnershipStatus.unknown} onChange={onChange} />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "On the shelf" }));

    expect(onChange).toHaveBeenCalledWith(OwnershipStatus.owned);
  });

  it("explains that this is not the reading status", () => {
    renderLocalised(
      <OwnershipPicker value={OwnershipStatus.owned} onChange={vi.fn()} />,
    );
    expect(
      screen.getByText(/Separate from whether you have read it/),
    ).toBeInTheDocument();
  });

  it("goes quiet while disabled", async () => {
    const onChange = vi.fn();
    renderLocalised(
      <OwnershipPicker
        value={OwnershipStatus.owned}
        disabled
        onChange={onChange}
      />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Not owned" }));

    expect(onChange).not.toHaveBeenCalled();
  });
});
