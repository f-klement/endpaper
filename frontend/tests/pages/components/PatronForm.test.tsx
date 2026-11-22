/** Tests for src/pages/components/PatronForm: the register form two pages hold. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { PatronCreate } from "../../../src/api/generated/model";
import { ApiError } from "../../../src/api/mutator";
import { PatronForm } from "../../../src/pages/components";
import { BLANK_DRAFT } from "../../../src/pages/types";
import { renderLocalised } from "../../utils";

function renderForm(error: unknown = null) {
  const onSubmit = vi.fn<(body: PatronCreate) => void>();
  renderLocalised(
    <PatronForm
      title="Register a patron"
      initial={BLANK_DRAFT}
      submitLabel="Register"
      busyLabel="Registering..."
      isSaving={false}
      error={error}
      onSubmit={onSubmit}
      onClose={() => {}}
    />,
  );
  return onSubmit;
}

describe("PatronForm", () => {
  it("sends every value trimmed and every empty box as nothing", async () => {
    const onSubmit = renderForm();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Name"), "  Ada Lovelace ");
    await user.type(screen.getByLabelText(/^Card number/), "A-1001");
    await user.type(screen.getByLabelText("Phone"), "   ");
    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(onSubmit).toHaveBeenCalledWith({
      name: "Ada Lovelace",
      card_number: "A-1001",
      email: null,
      phone: null,
      street: null,
      house_number: null,
      postcode: null,
      city: null,
      expires_on: null,
    });
  });

  it("holds the submit button while the name is only spaces", async () => {
    renderForm();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Name"), "   ");
    await user.type(screen.getByLabelText(/^Card number/), "A-1001");

    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });

  it("shows the server's refusal inside the form", () => {
    renderForm(
      new ApiError("Another patron already carries this card number.", 409),
    );

    expect(
      screen.getByText("Another patron already carries this card number."),
    ).toBeInTheDocument();
  });
});
