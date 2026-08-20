/**
 * Tests for src/i18n/index.tsx.
 *
 * The catalogue's completeness is a compile-time property (`de` is typed as
 * `Messages`), so it is not re-tested here. What is tested is everything the
 * type system cannot see: which language gets chosen, and what happens to a
 * string on its way to the screen.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Locale } from "../../src/api/generated/model";
import {
  LocaleProvider,
  de,
  detectBrowserLocale,
  en,
  interpolate,
  readStoredLocale,
  resolveLocale,
  useTranslation,
} from "../../src/i18n";

/** Pretend the browser is configured for these languages, in order. */
function setBrowserLanguages(...languages: string[]) {
  vi.stubGlobal("navigator", {
    ...navigator,
    language: languages[0] ?? "",
    languages,
  });
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── Choosing a language ───────────────────────────────────────────────────────

describe("detectBrowserLocale", () => {
  it("recognises a language we speak", () => {
    setBrowserLanguages("de-DE");
    expect(detectBrowserLocale()).toBe(Locale.de);
  });

  it("matches on the primary subtag, so de-AT counts as German", () => {
    setBrowserLanguages("de-AT");
    expect(detectBrowserLocale()).toBe(Locale.de);
  });

  it("is case-insensitive about the tag", () => {
    setBrowserLanguages("DE");
    expect(detectBrowserLocale()).toBe(Locale.de);
  });

  it("returns null for a language we do not speak", () => {
    setBrowserLanguages("fr-FR");
    expect(detectBrowserLocale()).toBeNull();
  });

  it("walks the preference list rather than stopping at the first entry", () => {
    // Someone whose first choice is French but who also reads German should
    // get German, not English.
    setBrowserLanguages("fr-FR", "de-DE", "en-GB");
    expect(detectBrowserLocale()).toBe(Locale.de);
  });

  it("falls back to navigator.language when there is no list", () => {
    vi.stubGlobal("navigator", { language: "de-DE", languages: [] });
    expect(detectBrowserLocale()).toBe(Locale.de);
  });
});

describe("readStoredLocale", () => {
  it("reads a previous choice", () => {
    localStorage.setItem("locale", "de");
    expect(readStoredLocale()).toBe(Locale.de);
  });

  it("ignores a value that is not a language we have", () => {
    // Anything could be in storage: an old build, another app on the same
    // origin, or somebody in the console.
    localStorage.setItem("locale", "klingon");
    expect(readStoredLocale()).toBeNull();
  });

  it("returns null when nothing is stored", () => {
    expect(readStoredLocale()).toBeNull();
  });
});

describe("resolveLocale", () => {
  it("prefers an explicit choice over the browser", () => {
    localStorage.setItem("locale", "en");
    setBrowserLanguages("de-DE");
    expect(resolveLocale()).toBe(Locale.en);
  });

  it("prefers an explicit choice over the server default", () => {
    localStorage.setItem("locale", "en");
    setBrowserLanguages("fr-FR");
    expect(resolveLocale(Locale.de)).toBe(Locale.en);
  });

  it("follows the browser when nothing was chosen", () => {
    setBrowserLanguages("de-DE");
    expect(resolveLocale()).toBe(Locale.de);
  });

  it("prefers the browser over the server default", () => {
    // The admin's default answers "what should a stranger see", not "override
    // what this person's own device says".
    setBrowserLanguages("de-DE");
    expect(resolveLocale(Locale.en)).toBe(Locale.de);
  });

  it("uses the server default when the browser speaks something else", () => {
    setBrowserLanguages("fr-FR");
    expect(resolveLocale(Locale.de)).toBe(Locale.de);
  });

  it("ends at English", () => {
    setBrowserLanguages("fr-FR");
    expect(resolveLocale()).toBe(Locale.en);
  });

  it("treats a null server default as absent", () => {
    setBrowserLanguages("fr-FR");
    expect(resolveLocale(null)).toBe(Locale.en);
  });
});

// ── Substitution ──────────────────────────────────────────────────────────────

describe("interpolate", () => {
  it("replaces a named placeholder", () => {
    expect(interpolate("by {author}", { author: "Le Guin" }, Locale.en)).toBe(
      "by Le Guin",
    );
  });

  it("replaces every placeholder in the template", () => {
    expect(
      interpolate("{a} then {b}", { a: "first", b: "second" }, Locale.en),
    ).toBe("first then second");
  });

  it("leaves an unsupplied placeholder visible", () => {
    // A literal {count} on screen is obviously a bug. "undefined" reads like
    // a value, and blank text reads like nothing is wrong at all.
    expect(interpolate("{count} books", {}, Locale.en)).toBe("{count} books");
  });

  it("formats numbers for the locale", () => {
    // German groups with a full stop where English uses a comma.
    expect(interpolate("{n}", { n: 1234 }, Locale.de)).toBe("1.234");
    expect(interpolate("{n}", { n: 1234 }, Locale.en)).toBe("1,234");
  });

  it("leaves a template with no placeholders alone", () => {
    expect(interpolate("Library", {}, Locale.en)).toBe("Library");
  });

  it("does not treat text in braces as a placeholder unless it is a word", () => {
    expect(interpolate("{ not a key }", { x: "y" }, Locale.en)).toBe(
      "{ not a key }",
    );
  });
});

// ── The hook ──────────────────────────────────────────────────────────────────

function Probe() {
  const { t, locale, setLocale } = useTranslation();
  return (
    <div>
      <p data-testid="locale">{locale}</p>
      <p data-testid="text">{t("library.title")}</p>
      <p data-testid="interpolated">{t("book.by", { author: "Le Guin" })}</p>
      <button onClick={() => setLocale(Locale.de)}>switch</button>
    </div>
  );
}

describe("LocaleProvider and useTranslation", () => {
  it("translates through the catalogue", () => {
    render(
      <LocaleProvider initialLocale={Locale.en}>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("text")).toHaveTextContent("Library");
  });

  it("translates into German", () => {
    render(
      <LocaleProvider initialLocale={Locale.de}>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("text")).toHaveTextContent(de["library.title"]);
  });

  it("interpolates through t()", () => {
    render(
      <LocaleProvider initialLocale={Locale.en}>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("interpolated")).toHaveTextContent("by Le Guin");
  });

  it("switches language and persists the choice", async () => {
    setBrowserLanguages("en-GB");
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("locale")).toHaveTextContent("en");

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "switch" }));

    expect(screen.getByTestId("locale")).toHaveTextContent("de");
    expect(localStorage.getItem("locale")).toBe("de");
  });

  it("starts in the stored language on a later visit", () => {
    localStorage.setItem("locale", "de");
    setBrowserLanguages("en-GB");
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("locale")).toHaveTextContent("de");
  });

  it("uses the server default only when the browser is no help", () => {
    setBrowserLanguages("fr-FR");
    render(
      <LocaleProvider serverDefault={Locale.de}>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByTestId("locale")).toHaveTextContent("de");
  });

  it("refuses to render outside a provider", () => {
    // A component reaching for translation with no provider above it would
    // otherwise render an empty string and look merely unfinished.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/LocaleProvider/);
    quiet.mockRestore();
  });
});

// ── The catalogues themselves ────────────────────────────────────────────────

describe("catalogues", () => {
  it("decide on their own which locales are selectable", () => {
    // isSupported used to list the two locales by hand, so adding a third
    // meant editing it too. Forgetting that fails quietly: the language is
    // translated and still never selected, because both the stored choice and
    // the browser's language are read through it.
    for (const locale of Object.values(Locale)) {
      localStorage.setItem("locale", locale);
      expect(readStoredLocale()).toBe(locale);
    }
  });

  it("cover exactly the same keys", () => {
    // Enforced by the type system too, but this states the rule in the suite
    // rather than leaving it to a build step nobody watches.
    expect(Object.keys(de).sort()).toEqual(Object.keys(en).sort());
  });

  it("have no empty translations", () => {
    const blank = Object.entries(de).filter(([, value]) => !value.trim());
    expect(blank).toEqual([]);
  });

  it("use no dash as punctuation, in either language", () => {
    // House style, asserted rather than trusted: a dash is easy to paste in
    // and invisible when skimming a diff. Covers em and en dashes both.
    const DASHES = /[\u2013\u2014]/;
    const offenders = [...Object.entries(en), ...Object.entries(de)]
      .filter(([, value]) => DASHES.test(value))
      .map(([key]) => key);
    expect(offenders).toEqual([]);
  });

  it("keep every placeholder that the English text declares", () => {
    // A dropped {count} is silent: the German sentence just reads oddly.
    const placeholders = (value: string) =>
      (value.match(/\{(\w+)\}/g) ?? []).sort();

    const mismatched = Object.keys(en).filter((key) => {
      const source = en[key as keyof typeof en];
      const target = de[key as keyof typeof de];
      return (
        JSON.stringify(placeholders(source)) !==
        JSON.stringify(placeholders(target))
      );
    });

    expect(mismatched).toEqual([]);
  });
});
