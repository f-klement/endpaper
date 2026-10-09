/** Tests for src/pages/Home/components/UnconfirmedBanner.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Locale } from "../../../../src/api/generated/model";
import UnconfirmedBanner from "../../../../src/pages/Home/components/UnconfirmedBanner";
import { renderLocalised } from "../../../utils";

describe("UnconfirmedBanner", () => {
  it("says how many books are unconfirmed", () => {
    renderLocalised(<UnconfirmedBanner count={12} onReview={vi.fn()} />);
    expect(screen.getByText(/12 books/)).toBeInTheDocument();
  });

  it("renders nothing when there are none", () => {
    // Nothing to dismiss: it disappears on its own once the count reaches
    // zero, which is what makes it a nudge rather than a notification.
    const { container } = renderLocalised(
      <UnconfirmedBanner count={0} onReview={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("offers a way to review them", async () => {
    const onReview = vi.fn();
    renderLocalised(<UnconfirmedBanner count={3} onReview={onReview} />);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Review them" }));

    expect(onReview).toHaveBeenCalledOnce();
  });

  it("translates", () => {
    renderLocalised(<UnconfirmedBanner count={3} onReview={vi.fn()} />, {
      locale: Locale.de,
    });
    expect(
      screen.getByRole("button", { name: "Jetzt prüfen" }),
    ).toBeInTheDocument();
  });
});
