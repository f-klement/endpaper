/** Tests for src/pages/Home/components/ChannelAlertBanner.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OverdueSender } from "../../../../src/api/generated/model";
import ChannelAlertBanner from "../../../../src/pages/Home/components/ChannelAlertBanner";
import { renderLocalised } from "../../../utils";

describe("ChannelAlertBanner", () => {
  it("names the channel that has stopped getting through", () => {
    // Naming it is the point: "a reminder channel is broken" sends somebody to
    // a settings screen with four of them on it.
    renderLocalised(<ChannelAlertBanner senders={[OverdueSender.telegram]} />);

    expect(
      screen.getByText(/reminders are not getting through on Telegram/i),
    ).toBeInTheDocument();
  });

  it("names all of them when more than one has", () => {
    renderLocalised(
      <ChannelAlertBanner
        senders={[OverdueSender.email, OverdueSender.webhook]}
      />,
    );

    expect(screen.getByText(/Email, Webhook/)).toBeInTheDocument();
  });

  it("renders nothing when every channel is working", () => {
    // Which is almost always, and is why this surface can be used at all. The
    // server decides what counts as broken: a refusal at once, a transport
    // failure only after a day and at least two consecutive failures.
    const { container } = renderLocalised(<ChannelAlertBanner senders={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("sends the reader to the screen that fixes it", () => {
    renderLocalised(<ChannelAlertBanner senders={[OverdueSender.email]} />);

    expect(
      screen.getByRole("link", { name: "Check the settings" }),
    ).toHaveAttribute("href", "/settings/lending");
  });
});
