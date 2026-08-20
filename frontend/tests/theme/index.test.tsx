/** Tests for src/theme/index.tsx. */

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ThemeProvider,
  applyWallpaper,
  currentPattern,
  readStoredPreference,
  resolveTheme,
  systemTheme,
  useTheme,
} from "../../src/theme";
import { PATTERNS } from "../../src/theme/patterns";

/** Pretend the operating system asks for this. */
function setSystem(dark: boolean, listeners: { current: (() => void) | null }) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: dark,
      addEventListener: (_: string, fn: () => void) => {
        listeners.current = fn;
      },
      removeEventListener: () => {
        listeners.current = null;
      },
    })),
  );
}

let listeners: { current: (() => void) | null };

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  listeners = { current: null };
  setSystem(false, listeners);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function Probe() {
  const { theme, preference, setPreference, pattern } = useTheme();
  return (
    <div>
      <p data-testid="theme">{theme}</p>
      <p data-testid="preference">{preference}</p>
      <p data-testid="pattern">{pattern.id}</p>
      <button onClick={() => setPreference("dark")}>go dark</button>
      <button onClick={() => setPreference("system")}>follow system</button>
    </div>
  );
}

function renderTheme() {
  return render(
    <ThemeProvider initialPattern={PATTERNS[0]}>
      <Probe />
    </ThemeProvider>,
  );
}

describe("resolveTheme", () => {
  it("follows the system when nothing is chosen", () => {
    setSystem(true, listeners);
    expect(resolveTheme("system")).toBe("dark");
  });

  it("takes an explicit choice over the system", () => {
    setSystem(true, listeners);
    expect(resolveTheme("light")).toBe("light");
  });

  it("defaults to light when the browser cannot say", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(systemTheme()).toBe("light");
  });
});

describe("readStoredPreference", () => {
  it("defaults to following the system", () => {
    expect(readStoredPreference()).toBe("system");
  });

  it("reads a previous choice", () => {
    localStorage.setItem("theme", "dark");
    expect(readStoredPreference()).toBe("dark");
  });

  it("ignores a value that is not a preference", () => {
    localStorage.setItem("theme", "aubergine");
    expect(readStoredPreference()).toBe("system");
  });
});

describe("ThemeProvider", () => {
  it("starts on the system setting", () => {
    setSystem(true, listeners);
    renderTheme();

    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
    expect(screen.getByTestId("preference")).toHaveTextContent("system");
  });

  it("puts the class on the document, which is what the CSS keys off", () => {
    setSystem(true, listeners);
    renderTheme();

    expect(document.documentElement).toHaveClass("dark");
  });

  it("switches on request and remembers it", async () => {
    renderTheme();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "go dark" }));

    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(document.documentElement).toHaveClass("dark");
  });

  it("follows the system changing, while nobody has chosen", () => {
    // Someone whose laptop flips at sunset should flip with it.
    renderTheme();
    expect(screen.getByTestId("theme")).toHaveTextContent("light");

    setSystem(true, listeners);
    act(() => listeners.current?.());

    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  });

  it("stops following once a choice is made", async () => {
    // The opposite failure: being flipped back at sunrise having asked for dark.
    renderTheme();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "go dark" }));

    expect(listeners.current).toBeNull();
    expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  });

  it("goes back to following when system is chosen again", async () => {
    setSystem(true, listeners);
    render(
      <ThemeProvider initialPreference="light" initialPattern={PATTERNS[0]}>
        <Probe />
      </ThemeProvider>,
    );
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

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "go dark" }));

    expect(document.body.style.backgroundImage).not.toBe(light);
  });

  it("refuses to render outside a provider", () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/ThemeProvider/);
    quiet.mockRestore();
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
