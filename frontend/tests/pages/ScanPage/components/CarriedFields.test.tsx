/** Tests for src/pages/ScanPage/components/CarriedFields.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import CarriedFields from "../../../../src/pages/ScanPage/components/CarriedFields";
import { blankPending } from "../../../../src/pages/ScanPage/types";
import { renderLocalised } from "../../../utils";

type FieldsProps = Parameters<typeof CarriedFields>[0];

function renderFields(overrides: Partial<FieldsProps> = {}) {
  const props = {
    pending: blankPending({
      collectionId: 4,
      condition: "fair",
      purchaseSource: "Oxfam",
      purchasedAt: "2026-11-07",
    }),
    onChange: vi.fn<FieldsProps["onChange"]>(),
    collections: [{ id: 4, name: "Paperbacks" }],
    privacyCarried: false,
    ...overrides,
  } satisfies FieldsProps;
  renderLocalised(<CarriedFields {...props} />);
  return props;
}

describe("CarriedFields", () => {
  it("shows each carried value prefilled", () => {
    renderFields();
    expect(screen.getByLabelText("Collection")).toHaveValue("4");
    expect(screen.getByLabelText("Condition")).toHaveValue("fair");
    expect(screen.getByLabelText("Ownership")).toHaveValue("owned");
    expect(screen.getByLabelText("Bought from")).toHaveValue("Oxfam");
    expect(screen.getByLabelText("Bought on")).toHaveValue("2026-11-07");
  });

  it("clears the collection to none", async () => {
    const { onChange } = renderFields();
    await userEvent.selectOptions(
      screen.getByLabelText("Collection"),
      "Not in a collection",
    );
    expect(onChange).toHaveBeenCalledWith({ collectionId: null });
  });

  it("clears the purchase date with its own button", async () => {
    const { onChange } = renderFields();
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(onChange).toHaveBeenCalledWith({ purchasedAt: "" });
  });

  it("offers no date clear when there is no date", () => {
    renderFields({ pending: blankPending() });
    expect(screen.queryByRole("button", { name: "Clear" })).toBeNull();
  });

  it("says in words that a carried private book starts private", () => {
    renderFields({
      pending: blankPending({ isPrivate: true }),
      privacyCarried: true,
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "This book starts private because the last one you added was.",
    );
  });

  it("makes a carried private book public from the notice", async () => {
    const { onChange } = renderFields({
      pending: blankPending({ isPrivate: true }),
      privacyCarried: true,
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Make it visible to everyone" }),
    );
    expect(onChange).toHaveBeenCalledWith({ isPrivate: false });
  });

  it("shows no privacy notice when privacy was not carried", () => {
    renderFields({ pending: blankPending({ isPrivate: true }) });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("says the privacy notice in German", () => {
    renderLocalised(
      <CarriedFields
        pending={blankPending({ isPrivate: true })}
        onChange={vi.fn<FieldsProps["onChange"]>()}
        collections={[]}
        privacyCarried
      />,
      { locale: "de" },
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Dieses Buch ist zunächst privat",
    );
  });
});
