/** Tests for src/pages/Home/components/VocabularyOfferBanner.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import VocabularyOfferBanner from "../../../../src/pages/Home/components/VocabularyOfferBanner";
import type { VocabularyOfferState } from "../../../../src/pages/Home/hooks";
import { renderLocalised } from "../../../utils";

function renderOffer({
  offer = "download",
  onDismiss = () => {},
  isDismissing = false,
}: {
  offer?: VocabularyOfferState;
  onDismiss?: () => void;
  isDismissing?: boolean;
} = {}) {
  return renderLocalised(
    <VocabularyOfferBanner
      offer={offer}
      onDismiss={onDismiss}
      isDismissing={isDismissing}
    />,
  );
}

describe("VocabularyOfferBanner", () => {
  it("sends an admin to the settings page that holds the download", () => {
    renderOffer();

    expect(
      screen.getByRole("link", { name: "Open the settings" }),
    ).toHaveAttribute("href", "/settings/library");
  });

  it("names the section the download is in", () => {
    renderOffer();

    expect(screen.getByText(/under Subject vocabularies/)).toBeInTheDocument();
  });

  it("points at the progress rather than the download while a load runs", () => {
    renderOffer({ offer: "loading" });

    expect(screen.getByText(/is being copied/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Show the progress" }),
    ).toHaveAttribute("href", "/settings/library");
    expect(screen.queryByText(/can be downloaded/)).not.toBeInTheDocument();
  });

  it("renders nothing once there is nothing to offer", () => {
    const { container } = renderOffer({ offer: null });

    expect(container).toBeEmptyDOMElement();
  });

  it("dismisses the offer when asked", async () => {
    const onDismiss = vi.fn<() => void>();
    renderOffer({ onDismiss });

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("holds the dismiss button while the dismissal is written", () => {
    renderOffer({ isDismissing: true });

    expect(screen.getByRole("button", { name: "Dismiss" })).toBeDisabled();
  });
});
