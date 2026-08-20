/** Tests for src/pages/AppearancePage/AppearancePage.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getListBooksInfiniteQueryKey } from "../../../src/api/generated/endpoints/books/books";
import AppearancePage from "../../../src/pages/AppearancePage";
import { PATTERNS } from "../../../src/theme/patterns";
import { makeBook, makeBookPage, resetIds } from "../../factories";
import {
  LIGHT_APPEARANCE,
  createTestQueryClient,
  mockApi,
  renderWithProviders,
} from "../../utils";

beforeEach(() => {
  resetIds();
  mockApi();
});

/** The picker, with an optional library already in the cache. */
function renderPicker({ books = 0 }: { books?: number } = {}) {
  const queryClient = createTestQueryClient();
  if (books > 0) {
    queryClient.setQueryData(getListBooksInfiniteQueryKey({ page_size: 24 }), {
      pages: [
        makeBookPage(
          Array.from({ length: books }, (_, index) =>
            makeBook({ title: `Book ${index}` }),
          ),
        ),
      ],
      pageParams: [1],
    });
  }
  return renderWithProviders(<AppearancePage />, { queryClient });
}

function group(name: string) {
  return within(screen.getByRole("group", { name }));
}

describe("the appearance picker", () => {
  it("offers the three modes", () => {
    renderPicker();

    for (const label of ["Light", "Dark", "Follow system"]) {
      expect(
        group("Light and dark").getByRole("button", { name: label }),
      ).toBeInTheDocument();
    }
  });

  it("applies a mode on a click, with no Save button", async () => {
    renderPicker();

    await userEvent
      .setup()
      .click(group("Light and dark").getByRole("button", { name: "Dark" }));

    expect(document.documentElement).toHaveClass("dark");
  });

  it("offers every palette by name", () => {
    renderPicker();
    const palettes = group("Palette");

    for (const label of [
      "Endpaper",
      "Catppuccin",
      "Rose Pine",
      "Gruvbox",
      "Solarized",
      "Everforest",
      "Nord",
    ]) {
      expect(palettes.getByRole("button", { name: new RegExp(label) }))
        .toBeInTheDocument();
    }
  });

  it("names the member of a palette that has one of its own", () => {
    // A reader who knows Catppuccin knows "Latte" better than "light", and the
    // catalogue has carried the name since the palettes shipped with nothing
    // reading it.
    renderPicker();

    expect(
      group("Palette").getByRole("button", { name: /Catppuccin.*Latte/ }),
    ).toBeInTheDocument();
  });

  it("says which member of a palette was built here", () => {
    // Nord publishes no light theme. Somebody choosing it in light is choosing
    // something this project assembled, and the catalogue says so in
    // `constructed`, which nothing read until this screen existed.
    renderPicker();

    expect(
      group("Palette").getByRole("button", {
        name: /Nord publishes no light theme/,
      }),
    ).toBeInTheDocument();
  });

  it("credits every palette it did not write", () => {
    renderPicker();

    expect(
      group("Palette").getByRole("button", {
        name: /Colours from Arctic Ice Studio and Sven Greb, MIT/,
      }),
    ).toBeInTheDocument();
    expect(
      group("Palette").getByRole("button", {
        name: /Endpaper.*This project's own colours/,
      }),
    ).toBeInTheDocument();
  });

  it("applies a palette on a click", async () => {
    renderPicker();

    await userEvent
      .setup()
      .click(group("Palette").getByRole("button", { name: /Gruvbox/ }));

    expect(document.documentElement.dataset.theme).toBe("gruvbox");
  });

  it("offers every wallpaper, plus off and surprise me", () => {
    renderPicker();
    const wallpapers = group("Wallpaper");

    for (const pattern of PATTERNS) {
      expect(
        wallpapers.getByRole("button", { name: new RegExp(pattern.name) }),
      ).toBeInTheDocument();
    }
    expect(wallpapers.getByRole("button", { name: /None/ })).toBeInTheDocument();
    expect(
      wallpapers.getByRole("button", { name: /Surprise me/ }),
    ).toBeInTheDocument();
  });

  it("groups the wallpapers under their two families", () => {
    renderPicker();

    expect(
      screen.getByRole("heading", { name: "William Morris" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Decorated papers" }),
    ).toBeInTheDocument();
  });

  it("turns the wallpaper off as a choice, not a switch", async () => {
    renderPicker();
    expect(document.body.style.backgroundImage).not.toBe("");

    await userEvent
      .setup()
      .click(group("Wallpaper").getByRole("button", { name: /None/ }));

    expect(document.body.style.backgroundImage).toBe("");
    expect(
      group("Wallpaper").getByRole("button", { name: /None/ }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("marks Surprise me for an account that has not chosen", () => {
    // The default a new account starts at. Keeping it as a tile is what keeps
    // the behaviour the app was built around instead of retiring it quietly.
    renderPicker();

    expect(
      group("Wallpaper").getByRole("button", { name: /Surprise me/ }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("applies a wallpaper on a click", async () => {
    renderPicker();

    await userEvent
      .setup()
      .click(group("Wallpaper").getByRole("button", { name: /Seigaiha/ }));

    expect(
      group("Wallpaper").getByRole("button", { name: /Seigaiha/ }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("previews on the reader's own books", () => {
    renderPicker({ books: 4 });

    expect(screen.getByText("Book 0")).toBeInTheDocument();
    expect(screen.getByText("Book 1")).toBeInTheDocument();
    expect(screen.queryByText("Book 2")).not.toBeInTheDocument();
  });

  it("says why the preview is empty rather than inventing a book", () => {
    renderPicker();

    expect(screen.getByText(/nothing real to preview/)).toBeInTheDocument();
  });

  it("shows the licences on the screen that offers the palettes", () => {
    // Six MIT notices and the Morris sentence, where a reader can find them.
    renderPicker();

    expect(screen.getByText("Catppuccin, MIT")).toBeInTheDocument();
    expect(screen.getByText("sainnhe, MIT")).toBeInTheDocument();
    expect(
      screen.getByText(/not affiliated with, or endorsed by, Morris & Co/),
    ).toBeInTheDocument();
  });

  it("says nothing about contrast while the wallpaper is on", () => {
    renderPicker();

    expect(screen.queryByText(/wallpaper is off/)).not.toBeInTheDocument();
  });

  it("says the system turned the wallpaper off, rather than showing it off", () => {
    // A decoration that vanishes with no explanation reads as a fault in this
    // app rather than as the preference being honoured.
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: query.includes("prefers-contrast"),
        addEventListener: () => {},
        removeEventListener: () => {},
      })),
    );
    renderPicker();

    expect(screen.getByText(/wallpaper is off/)).toBeInTheDocument();
    // The choice is still recorded and still shown, because it is what comes
    // back when the system stops asking.
    expect(
      group("Wallpaper").getByRole("button", { name: /Surprise me/ }),
    ).toHaveAttribute("aria-pressed", "true");
    vi.unstubAllGlobals();
  });

  it("keeps the wallpaper the reader already had", () => {
    renderWithProviders(<AppearancePage />, {
      appearance: { ...LIGHT_APPEARANCE, wallpaper: "khatam" },
    });

    expect(
      group("Wallpaper").getByRole("button", { name: /Khatam/ }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
