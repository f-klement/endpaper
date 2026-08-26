/**
 * Tests for src/pages/SettingsPage/components/AboutBadges.tsx.
 *
 * The constraint the whole component exists under is that a badge here is
 * markup, never an image. shields.io would need `img-src` widened for
 * decoration, which this card already refused once over the Ko-fi button, and
 * it would report a private server to a third party on every visit to
 * Settings. That is asserted rather than commented, because an `<img>` is what
 * somebody reaches for first.
 *
 * The measured token pairings are asserted too. `tests/theme/palettes.test.ts`
 * holds the ratios and the lightness separations those tokens produce on all
 * seven palettes; nothing else holds that this component is the thing using
 * them.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Locale } from "../../../../src/api/generated/model";
import AboutBadges from "../../../../src/pages/SettingsPage/components/AboutBadges";
import { renderLocalised } from "../../../utils";

const REPOSITORY = "https://github.com/f-klement/endpaper";

describe("AboutBadges", () => {
  it("names the build that is running", () => {
    renderLocalised(<AboutBadges />);

    expect(screen.getByText("Version")).toBeInTheDocument();
    expect(screen.getByText(__APP_VERSION__)).toBeInTheDocument();
  });

  // Not a tautology, though it reads like one. `__APP_VERSION__` is substituted
  // by vite.config.ts at build time and vitest applies the same define, so this
  // fails if the badge ever goes back to a hardcoded string or a second source.
  it("shows the version the build was stamped with, not a copy of it", () => {
    renderLocalised(<AboutBadges />);

    expect(screen.getByText(__APP_VERSION__)).toBeInTheDocument();
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

  it("draws every badge as markup, never as an image", () => {
    const { container } = renderLocalised(<AboutBadges />);

    expect(container.querySelectorAll("img, svg, picture, object")).toHaveLength(
      0,
    );
    expect(container.querySelectorAll("[src], [srcset]")).toHaveLength(0);
  });

  it("asks no other host for anything", () => {
    // The other half of the same rule: a badge service reached through a
    // stylesheet, a background image or a preload would not be an `<img>` and
    // would still be an outbound request from a private server.
    const { container } = renderLocalised(<AboutBadges />);

    expect(container.innerHTML).not.toMatch(
      /shields\.io|url\(|https?:\/\/(?!github\.com)/,
    );
  });

  it("states the licence and links the file that says it", () => {
    renderLocalised(<AboutBadges />);

    expect(screen.getByText("Apache 2.0")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Licence Apache 2.0" }),
    ).toHaveAttribute("href", `${REPOSITORY}/blob/main/LICENSE`);
  });

  it("links the source", () => {
    renderLocalised(<AboutBadges />);

    expect(screen.getByRole("link", { name: "Source GitHub" })).toHaveAttribute(
      "href",
      REPOSITORY,
    );
  });

  it("names a link from its own two cells, not from a label beside them", () => {
    // Measured with dom-accessibility-api: two adjacent spans with no
    // whitespace between them name the link "SourceGitHub", and the `{" "}`
    // between them is what makes it "Source GitHub". It costs no layout,
    // because a whitespace only anonymous flex item is not rendered.
    renderLocalised(<AboutBadges />);

    const link = screen.getByRole("link", { name: "Source GitHub" });
    expect(link).not.toHaveAttribute("aria-label");
    expect(
      screen.queryByRole("link", { name: "SourceGitHub" }),
    ).not.toBeInTheDocument();
  });

  it("tells GitHub nothing about where the link was followed from", () => {
    renderLocalised(<AboutBadges />);

    for (const link of screen.getAllByRole("link")) {
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
  });

  it("carries only facts that need no network call", () => {
    // Docker pulls and a latest release both need a request to a host the CSP
    // does not carry, and a hardcoded number is wrong within a week and silent
    // about it.
    renderLocalised(<AboutBadges />);

    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(screen.queryByText(/pulls|downloads/i)).not.toBeInTheDocument();
  });

  it("leaves the languages to the language card", () => {
    // It answered "what does this project support" for a stranger reading the
    // README, to a reader already inside the app who has a language switch on
    // this same page. It was also a fourth hardcoded copy of the locale list.
    renderLocalised(<AboutBadges />);

    expect(screen.queryByText("Languages")).not.toBeInTheDocument();
    expect(screen.queryByText("DE, EN")).not.toBeInTheDocument();
  });

  it("translates the labels and leaves the names alone", () => {
    renderLocalised(<AboutBadges />, { locale: Locale.de });

    expect(screen.getByText("Lizenz")).toBeInTheDocument();
    expect(screen.getByText("Quelltext")).toBeInTheDocument();
    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.getByText("Apache 2.0")).toBeInTheDocument();
  });

  it("keeps its ink off the rung the status pill fails on", () => {
    // The `unread` pill draws `paper-600` on `paper-200` and measures 3.55:1 on
    // solarized, 3.56 on nord and 3.87 on catppuccin, under the 4.5 floor on
    // three of seven palettes. The badge takes `paper-800`, the rung of that
    // pairing that clears it everywhere: 4.57:1 at worst, on catppuccin.
    const { container } = renderLocalised(<AboutBadges />);

    const label = screen.getByText("Version");
    expect(label.className).toContain("bg-paper-200");
    expect(label.className).toContain("text-paper-800");
    expect(label.className).toContain("dark:bg-paper-800");
    expect(label.className).toContain("dark:text-paper-200");
    expect(container.innerHTML).not.toContain("text-paper-600");
  });

  it("paints a value cell in the pairings that were measured", () => {
    // The half a pin on the label cell alone would miss, which is most of the
    // component: the value cell's own surface, and the accent ink a link's
    // value cell carries. `palettes.test.ts` measures these token pairs; only
    // this holds that they are the ones on screen.
    renderLocalised(<AboutBadges />);

    const fact = screen.getByText(__APP_VERSION__);
    expect(fact.className).toContain("bg-paper-100");
    expect(fact.className).toContain("dark:bg-paper-700");
    expect(fact.className).toContain("text-paper-800");
    expect(fact.className).toContain("dark:text-paper-200");

    const link = screen.getByText("GitHub");
    expect(link.className).toContain("bg-paper-100");
    expect(link.className).toContain("dark:bg-paper-700");
    expect(link.className).toContain("text-accent-800");
    expect(link.className).toContain("dark:text-accent-200");
    expect(link.className).toContain("dark:hover:text-accent-100");
  });

  it("separates the two cells with a hairline rather than with their own tones", () => {
    // `paper-100` against `paper-200` is 1.32 CIE L* apart on Rose Pine light,
    // where the other six run 3.14 to 8.89: on that palette the badge read as
    // one flat chip. `palettes.test.ts` holds the separation the border buys.
    renderLocalised(<AboutBadges />);

    const fact = screen.getByText(__APP_VERSION__);
    expect(fact.className).toContain("border-l");
    expect(fact.className).toContain("border-paper-300");
    expect(fact.className).toContain("dark:border-paper-600");
  });

  it("tells a link from a fact by more than its colour", () => {
    // WCAG 1.4.1. The accent ink is 7.21:1 at worst in light and 4.58:1 at
    // worst in dark, but hue alone is not a distinction, so the value cell of a
    // link is underlined at rest.
    renderLocalised(<AboutBadges />);

    expect(screen.getByText("GitHub").className).toContain("underline");
    expect(screen.getByText(__APP_VERSION__).className).not.toContain(
      "underline",
    );
  });
});
