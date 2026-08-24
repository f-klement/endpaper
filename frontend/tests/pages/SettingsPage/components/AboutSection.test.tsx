/**
 * Tests for src/pages/SettingsPage/components/AboutSection.tsx.
 *
 * Three things are worth pinning. The Ko-fi button is served from here rather
 * than from Ko-fi, because a remote one would need a CSP entry and would tell
 * them the address of a private server on every visit to Settings. The card
 * stays short: it is one of three open cards on a member's page, where its own
 * height is the only thing keeping it from dominating. And the version and the
 * source are stated once, in the badge row, not there and in a line above it.
 *
 * What a badge is made of belongs to `AboutBadges.test.tsx`. This file asserts
 * that the card carries the row and no longer carries the paragraph it
 * replaced.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AboutSection from "../../../../src/pages/SettingsPage/components/AboutSection";
import { renderLocalised } from "../../../utils";

function render(isOpen = true) {
  renderLocalised(<AboutSection isOpen={isOpen} onToggle={vi.fn()} />);
}

describe("AboutSection", () => {
  it("carries the badge row", () => {
    render();

    expect(screen.getByText("Version")).toBeInTheDocument();
    expect(screen.getByText(__APP_VERSION__)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Source GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/f-klement/endpaper",
    );
  });

  it("states the version and the source once, not twice", () => {
    // The row replaced a line reading "Version 0.6.0 · Source code". Keeping
    // both would put each fact on the card twice, which is what adding the row
    // was meant to remove. Three links: the licence, the source, and Ko-fi.
    render();

    expect(screen.getAllByText(__APP_VERSION__)).toHaveLength(1);
    expect(
      screen.queryByText(`Version ${__APP_VERSION__}`),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(3);
  });

  it("serves the Ko-fi button from this deployment", () => {
    // A hotlinked button would need `storage.ko-fi.com` in the CSP's img-src,
    // which is derived from the cover hosts, and it would report every visit
    // to Settings to Ko-fi.
    render();

    expect(
      screen.getByRole("img", { name: "Support Endpaper on Ko-fi" }),
    ).toHaveAttribute("src", "/kofi-button.png");
  });

  it("tells Ko-fi nothing about where the link was followed from", () => {
    render();

    const link = screen.getByRole("link", {
      name: "Support Endpaper on Ko-fi",
    });
    expect(link).toHaveAttribute("href", "https://ko-fi.com/fklement");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("asks, says what the money is for, and that nothing is gated", () => {
    // Three sentences since 2026-08-24. The card used to add nothing to the ask,
    // on the grounds that its reader is already inside the app; the owner
    // reversed that and it now carries both facts the README carries. See
    // docs/decisions.md for why the older rule reads as sound and was still
    // wrong: a donate button provokes two questions, what it funds and what it
    // withholds, and leaving both unanswered is quieter rather than clearer.
    render();

    expect(
      screen.getByText(
        "If you like Endpaper and want to support my work, buy me a coffee. " +
          "It helps pay for the public server that can mediate between households. " +
          "All features are free either way.",
      ),
    ).toBeInTheDocument();
  });

  it("does not explain what this app is to somebody already inside it", () => {
    render();

    expect(
      screen.queryByText(/self hosted catalogue/i),
    ).not.toBeInTheDocument();
  });

  it("folds like every other card", () => {
    render(false);

    expect(screen.getByText(/buy me a coffee/)).not.toBeVisible();
  });
});
