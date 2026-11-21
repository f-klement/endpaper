/** Tests for src/pages/BookDetail/components/PendingHeadingsPanel. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ClassificationScheme,
  HeadingKind,
  Locale,
  type ClassificationOut,
} from "../../../../src/api/generated/model";
import PendingHeadingsPanel from "../../../../src/pages/BookDetail/components/PendingHeadingsPanel";
import { renderLocalised } from "../../../utils";

const DEWEY: ClassificationOut = {
  scheme: ClassificationScheme.ddc,
  number: "155.9042",
  label: null,
};
const CARRIER: ClassificationOut = {
  scheme: ClassificationScheme.gnd,
  number: "4123623-3",
  label: "Online-Ressource",
  kind: HeadingKind.carrier,
};

function renderPanel(
  headings: ClassificationOut[],
  {
    isBusy = false,
    locale = Locale.en,
  }: { isBusy?: boolean; locale?: Locale } = {},
) {
  const onConfirm = vi.fn<() => void>();
  const onDiscard = vi.fn<() => void>();
  renderLocalised(
    <PendingHeadingsPanel
      headings={headings}
      isBusy={isBusy}
      onConfirm={onConfirm}
      onDiscard={onDiscard}
    />,
    { locale },
  );
  return { onConfirm, onDiscard };
}

describe("what the panel shows", () => {
  it("draws nothing for a book with no suggestions", () => {
    renderPanel([]);

    expect(screen.queryByText("Suggested by a harvest")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("names each suggestion's scheme and words, and a carrier as a carrier", () => {
    renderPanel([DEWEY, CARRIER]);

    expect(screen.getByText("Suggested by a harvest")).toBeInTheDocument();
    expect(screen.getByText("Dewey")).toBeInTheDocument();
    expect(screen.getByText("155.9042")).toBeInTheDocument();
    expect(screen.getByText("Online-Ressource")).toBeInTheDocument();
    expect(screen.getByText("Carrier type")).toBeInTheDocument();
  });

  it("links no suggestion, since no book carries it yet", () => {
    renderPanel([DEWEY]);

    expect(screen.queryByRole("link")).toBeNull();
  });

  it("speaks German to a German reader", () => {
    renderPanel([DEWEY, CARRIER], { locale: Locale.de });

    expect(
      screen.getByText("Von einer Übernahme vorgeschlagen"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Alle 2 bestätigen" }),
    ).toBeInTheDocument();
  });
});

describe("what the buttons do", () => {
  it("confirms the whole set, counted on its button", async () => {
    const { onConfirm } = renderPanel([DEWEY, CARRIER]);

    await userEvent.click(
      screen.getByRole("button", { name: "Confirm all 2" }),
    );

    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("confirms a single suggestion without counting it", async () => {
    const { onConfirm } = renderPanel([DEWEY]);

    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(onConfirm).toHaveBeenCalledOnce();
    expect(screen.queryByText(/all 1/)).toBeNull();
  });

  it("discards the whole set", async () => {
    const { onDiscard } = renderPanel([DEWEY]);

    await userEvent.click(screen.getByRole("button", { name: "Discard" }));

    expect(onDiscard).toHaveBeenCalledOnce();
  });

  it("holds both buttons while a write is out", () => {
    renderPanel([DEWEY], { isBusy: true });

    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Discard" })).toBeDisabled();
  });
});
