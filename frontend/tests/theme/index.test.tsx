/** Tests for src/theme/index.tsx. */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ThemeProvider,
  applyWallpaper,
  currentPattern,
  patternFor,
  prefersMoreContrast,
  resolveTheme,
  systemTheme,
  useTheme,
  type Appearance,
} from "../../src/theme";
import { PATTERNS } from "../../src/theme/patterns";

const LIGHT: Appearance = { palette: "endpaper", mode: "light", wallpaper: null };

interface Listeners {
  dark: (() => void) | null;
  contrast: (() => void) | null;
}

/**
 * Pretend the operating system asks for these.
 *
 * Answers per query rather than the same for every one. A stub that returned
 * `matches` for anything would have a dark-mode test also claim the reader had
 * asked for more contrast, which turns the wallpaper off underneath it.
 */
function setSystem(
  { dark = false, contrast = false }: { dark?: boolean; contrast?: boolean },
  listeners: Listeners,
) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => {
      const isContrast = query.includes("prefers-contrast");
      return {
        matches: isContrast ? contrast : dark,
        addEventListener: (_: string, fn: () => void) => {
          if (isContrast) listeners.contrast = fn;
          else listeners.dark = fn;
        },
        removeEventListener: () => {
          if (isContrast) listeners.contrast = null;
          else listeners.dark = null;
        },
      };
    }),
  );
}

let listeners: Listeners;

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  delete document.documentElement.dataset.theme;
  listeners = { dark: null, contrast: null };
  setSystem({}, listeners);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function Probe() {
  const { theme, appearance, setAppearance, adopt, pattern, wallpaperOff } =
    useTheme();
  return (
    <div>
      <p data-testid="theme">{theme}</p>
      <p data-testid="mode">{appearance.mode}</p>
      <p data-testid="palette">{appearance.palette}</p>
      <p data-testid="pattern">{pattern.id}</p>
      <p data-testid="wallpaper-off">{String(wallpaperOff)}</p>
      <button onClick={() => setAppearance({ mode: "dark" })}>go dark</button>
      <button onClick={() => setAppearance({ mode: "system" })}>
        follow system
      </button>
      <button onClick={() => setAppearance({ palette: "nord" })}>go nord</button>
      <button onClick={() => adopt({ ...LIGHT, palette: "gruvbox" }, 7)}>
        adopt
      </button>
    </div>
  );
}

function renderTheme(appearance: Appearance = LIGHT) {
  return render(
    <ThemeProvider initialAppearance={appearance} initialPattern={PATTERNS[0]}>
      <Probe />
    </ThemeProvider>,
  );
}

describe("resolveTheme", () => {
  it("follows the system when nothing is chosen", () => {
    setSystem({ dark: true }, listeners);
    expect(resolveTheme("system")).toBe("dark");
  });

  it("takes an explicit choice over the system", () => {
    setSystem({ dark: true }, listeners);
    expect(resolveTheme("light")).toBe("light");
  });

  it("defaults to light when the browser cannot say", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(systemTheme()).toBe("light");
  });
});

describe("ThemeProvider", () => {
  it("starts on the system setting", () => {
    setSystem({ dark: true }, listeners);
    renderTheme({ ...LIGHT, mode: "system" });

    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
    expect(screen.getByTestId("mode")).toHaveTextContent("system");
  });

  it("puts the class on the document, which is what the CSS keys off", () => {
    setSystem({ dark: true }, listeners);
    renderTheme({ ...LIGHT, mode: "system" });

    expect(document.documentElement).toHaveClass("dark");
  });

  it("puts the palette on the document, which is what selects its block", () => {
    renderTheme({ ...LIGHT, palette: "nord" });

    expect(document.documentElement.dataset.theme).toBe("nord");
  });

  it("switches the palette on request", async () => {
    renderTheme();

    await userEvent.setup().click(screen.getByRole("button", { name: "go nord" }));

    expect(screen.getByTestId("palette")).toHaveTextContent("nord");
    expect(document.documentElement.dataset.theme).toBe("nord");
  });

  it("switches the mode on request", async () => {
    renderTheme();

    await userEvent.setup().click(screen.getByRole("button", { name: "go dark" }));

    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
    expect(document.documentElement).toHaveClass("dark");
  });

  it("caches an adopted appearance under the account it belongs to", async () => {
    // The write-through half. Nothing is cached until an account is named,
    // because a preference with no owner is what this replaced.
    renderTheme();
    await userEvent.setup().click(screen.getByRole("button", { name: "adopt" }));

    expect(JSON.parse(localStorage.getItem("appearance") ?? "{}")).toEqual({
      last: "7",
      accounts: { "7": { palette: "gruvbox", mode: "light", wallpaper: null } },
    });
  });

  it("caches a later choice under the same account", async () => {
    renderTheme();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "adopt" }));
    await user.click(screen.getByRole("button", { name: "go dark" }));

    const cache = JSON.parse(localStorage.getItem("appearance") ?? "{}");
    expect(cache.accounts["7"].mode).toBe("dark");
  });

  it("follows the system changing, while nobody has chosen", () => {
    // Someone whose laptop flips at sunset should flip with it.
    renderTheme({ ...LIGHT, mode: "system" });
    expect(screen.getByTestId("theme")).toHaveTextContent("light");

    setSystem({ dark: true }, listeners);
    act(() => listeners.dark?.());

    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  });

  it("stops following once a choice is made", async () => {
    // The opposite failure: being flipped back at sunrise having asked for dark.
    renderTheme({ ...LIGHT, mode: "system" });
    await userEvent.setup().click(screen.getByRole("button", { name: "go dark" }));

    expect(listeners.dark).toBeNull();
    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  });

  it("goes back to following when system is chosen again", async () => {
    setSystem({ dark: true }, listeners);
    renderTheme();
    expect(screen.getByTestId("theme")).toHaveTextContent("light");

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "follow system" }));

    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  });

  it("paints a background pattern", () => {
    renderTheme();
    expect(document.body.style.backgroundImage).toContain("data:image/svg+xml");
  });

  it("repaints the wallpaper when the mode changes", async () => {
    // The ink comes from the palette, so a mode change that moved the class and
    // not the pattern would leave the dark page wearing the light tile.
    renderTheme();
    const light = document.body.style.backgroundImage;

    await userEvent.setup().click(screen.getByRole("button", { name: "go dark" }));

    expect(document.body.style.backgroundImage).not.toBe(light);
  });

  it("refuses to render outside a provider", () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/ThemeProvider/);
    quiet.mockRestore();
  });
});

describe("more contrast, asked for at the operating system", () => {
  it("paints no wallpaper", () => {
    setSystem({ contrast: true }, listeners);
    renderTheme();

    expect(document.body.style.backgroundImage).toBe("");
  });

  it("says so, rather than leaving it to be noticed", () => {
    setSystem({ contrast: true }, listeners);
    renderTheme();

    expect(screen.getByTestId("wallpaper-off")).toHaveTextContent("true");
  });

  it("clears a wallpaper already on the page when it is turned on", () => {
    renderTheme();
    expect(document.body.style.backgroundImage).not.toBe("");

    setSystem({ contrast: true }, listeners);
    act(() => listeners.contrast?.());

    expect(document.body.style.backgroundImage).toBe("");
    expect(screen.getByTestId("wallpaper-off")).toHaveTextContent("true");
  });

  it("is false when the browser cannot say", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(prefersMoreContrast()).toBe(false);
  });
});

describe("applyWallpaper", () => {
  it("paints without React", () => {
    // The point of the whole exercise. `main.tsx` calls this before anything
    // mounts, because painted from an effect the wallpaper arrives a frame
    // after the page. Rendering a provider here would let that regress and the
    // test would still pass.
    applyWallpaper(PATTERNS[0]!, "light");

    expect(document.body.style.backgroundImage).toContain("data:image/svg+xml");
  });

  it("paints nothing when a token is not a colour", () => {
    // These two are interpolated into `stroke="{ink}"` inside the tile, and
    // encoding the data URI does not protect that: the browser decodes it and
    // parses the result as SVG, so a quote would still close the attribute.
    // Nothing can currently put anything but a hex there, which is why the
    // check is here rather than left as an inference across two files.
    document.body.style.backgroundImage = "";
    document.documentElement.style.setProperty(
      "--color-accent-700",
      '#000" onload="alert(1)',
    );
    applyWallpaper(PATTERNS[0]!, "light");

    expect(document.body.style.backgroundImage).toBe("");
  });

  it("paints nothing when the palette is not on the document", () => {
    // An SVG shape with no fill is black, so a missing stylesheet would dirty
    // the page rather than leave it plain. It leaves what is there rather than
    // clearing it: a failed read is not a reason to strip a good wallpaper.
    document.body.style.backgroundImage = "";
    document.documentElement.style.cssText = "";
    applyWallpaper(PATTERNS[0]!, "light");

    expect(document.body.style.backgroundImage).toBe("");
  });
});

describe("currentPattern", () => {
  it("chooses one wallpaper for the visit and keeps it", () => {
    // `main.tsx` paints before React exists and the provider then has to render
    // the pattern already on the page. Two rolls of the dice would put one
    // wallpaper on the body and name a different one in the picker.
    expect(currentPattern()).toBe(currentPattern());
  });
});

describe("patternFor", () => {
  it("uses the one a preference names", () => {
    expect(patternFor(PATTERNS[1]!.id)).toBe(PATTERNS[1]);
  });

  it("falls back to the visit's own for a name it does not have", () => {
    // Patterns come and go between versions. One this build never heard of is
    // the same answer as no preference at all, not a blank page.
    expect(patternFor("hollyhock")).toBe(currentPattern());
  });

  it("falls back for no preference at all", () => {
    expect(patternFor(null)).toBe(currentPattern());
  });
});
