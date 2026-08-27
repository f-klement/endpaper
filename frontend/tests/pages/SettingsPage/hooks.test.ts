/**
 * Tests for the section state in src/pages/SettingsPage/hooks.ts.
 *
 * The API hooks on this page are covered through the page itself, in
 * SettingsPage.test.tsx. What is only testable here is the defaults table and
 * the three states behind it, since a test that checks a default alone cannot
 * tell "closed" from "nobody has said".
 */

import { act } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  SETTINGS_SECTIONS,
  SETTINGS_SECTION_DEFAULTS,
  useSettingsSections,
} from "../../../src/pages/SettingsPage/hooks";
import { readSectionChoices } from "../../../src/lib/sectionState";
import { renderHookWithProviders } from "../../utils";

beforeEach(() => localStorage.clear());

/** What a member who is not an admin is shown, in draw order. */
const MEMBER_SECTIONS = [
  "language",
  "appearance",
  "import",
  "covers",
  "customFields",
  "about",
] as const;

describe("SETTINGS_SECTION_DEFAULTS", () => {
  it("opens what answers a question and closes what starts a job", () => {
    // Asserted whole rather than one entry at a time, so moving a section
    // across the line is a deliberate edit to this list.
    expect(SETTINGS_SECTION_DEFAULTS).toEqual({
      language: true,
      appearance: true,
      import: false,
      covers: false,
      customFields: false,
      googleBooks: true,
      goodreads: true,
      defaultLanguage: true,
      overdue: false,
      reminderSenders: false,
      testAccounts: false,
      backup: false,
      about: true,
    });
  });

  it("does not leave About as the only card open", () => {
    // A settings page whose one expanded card asks for money is a donation
    // prompt wearing a settings page.
    const open = SETTINGS_SECTIONS.filter(
      (section) => SETTINGS_SECTION_DEFAULTS[section],
    );

    expect(SETTINGS_SECTION_DEFAULTS.about).toBe(true);
    expect(open.length).toBeGreaterThan(1);
  });

  it("leaves a member who is not an admin something to read", () => {
    // Six cards reach a member, and folding the language switch as well would
    // leave five closed handles and nothing else.
    const open = MEMBER_SECTIONS.filter(
      (section) => SETTINGS_SECTION_DEFAULTS[section],
    );

    expect(open).toEqual(["language", "appearance", "about"]);
  });

  it("decides every section it draws", () => {
    // A `Record` over the ids, so a new section cannot arrive silently closed.
    expect(Object.keys(SETTINGS_SECTION_DEFAULTS).sort()).toEqual(
      [...SETTINGS_SECTIONS].sort(),
    );
  });
});

describe("useSettingsSections", () => {
  it("follows the table when nobody has said anything", () => {
    const { result } = renderHookWithProviders(() => useSettingsSections());

    expect(result.current.isOpen("language")).toBe(true);
    expect(result.current.isOpen("backup")).toBe(false);
  });

  it("keeps a card closed on the next visit, even though the table opens it", () => {
    const first = renderHookWithProviders(() => useSettingsSections());
    act(() => first.result.current.toggle("about"));
    first.unmount();

    const second = renderHookWithProviders(() => useSettingsSections());

    expect(second.result.current.isOpen("about")).toBe(false);
  });

  it("keeps a card open on the next visit, even though the table closes it", () => {
    const first = renderHookWithProviders(() => useSettingsSections());
    act(() => first.result.current.toggle("backup"));
    first.unmount();

    const second = renderHookWithProviders(() => useSettingsSections());

    expect(second.result.current.isOpen("backup")).toBe(true);
  });

  it("remembers each card on its own", () => {
    const { result } = renderHookWithProviders(() => useSettingsSections());

    act(() => result.current.toggle("backup"));

    expect(result.current.isOpen("backup")).toBe(true);
    expect(result.current.isOpen("overdue")).toBe(false);
  });

  it("writes to this page's store and not the book page's", () => {
    // Both pages have an `about` section, so a shared key would let closing
    // one close the other.
    const { result } = renderHookWithProviders(() => useSettingsSections());

    act(() => result.current.toggle("about"));

    expect(readSectionChoices("settingsSections")).toEqual({
      about: "closed",
    });
    expect(readSectionChoices("bookDetailSections")).toEqual({});
  });
});
