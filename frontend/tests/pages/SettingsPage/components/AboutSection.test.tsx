/**
 * Tests for src/pages/SettingsPage/components/AboutSection.tsx.
 *
 * Two things are worth pinning. The Ko-fi button is served from here rather
 * than from Ko-fi, because a remote one would need a CSP entry and would tell
 * them the address of a private server on every visit to Settings. And the card
 * stays short: it is one of three open cards on a member's page, where its own
 * height is the only thing keeping it from dominating.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AboutSection from "../../../../src/pages/SettingsPage/components/AboutSection";
import { renderLocalised } from "../../../utils";

function render(isOpen = true) {
  renderLocalised(<AboutSection isOpen={isOpen} onToggle={vi.fn()} />);
}

describe("AboutSection", () => {
  it("names the build that is running", () => {
    render();

    expect(screen.getByText(/^Version \S+$/)).toBeInTheDocument();
  });

  // Not a tautology, though it reads like one. __APP_VERSION__ is substituted by
  // vite.config.ts at build time, and vitest applies the same define, so this
  // fails if the card ever goes back to a hardcoded string or a second source.
  it("shows the version the build was stamped with, not a copy of it", () => {
    render();

    expect(screen.getByText(`Version ${__APP_VERSION__}`)).toBeInTheDocument();
    expect(__APP_VERSION__).not.toBe("");
  });

  // A release must never ship the development marker, and a development build
  // must never look like a clean release. Both directions have a failure mode.
  it("distinguishes a tagged build from a working one", () => {
    const tagged = /^\d+\.\d+\.\d+$/.test(__APP_VERSION__);
    const working =
      __APP_VERSION__ === "unknown" ||
      /-\d+-g[0-9a-f]+/.test(__APP_VERSION__) ||
      __APP_VERSION__.endsWith("-dirty");

    expect(tagged || working).toBe(true);
  });

  it("links to the source", () => {
    render();

    expect(screen.getByRole("link", { name: "Source code" })).toHaveAttribute(
      "href",
      "https://github.com/f-klement/endpaper",
    );
  });

  it("keeps the version and the source on one line", () => {
    // One thought, what am I running and where does it live, and on a member's
    // page every line this card does not need is a line it should not have.
    render();

    expect(screen.getByText(`Version ${__APP_VERSION__}`)).toContainElement(
      screen.getByRole("link", { name: "Source code" }),
    );
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

  it("asks in one sentence, without explaining itself", () => {
    // The README argues the case at length, to somebody deciding whether to
    // install this. The card talks to somebody who already did.
    render();

    expect(
      screen.getByText(
        "If you like Endpaper and want to support my work, buy me a coffee.",
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
