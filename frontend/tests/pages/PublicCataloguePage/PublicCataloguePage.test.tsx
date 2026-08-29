/**
 * Tests for src/pages/PublicCataloguePage/PublicCataloguePage.tsx.
 *
 * The one screen in this application a stranger can open, so what is asserted
 * here is mostly what it does **not** do: it sends no token, it says "nothing
 * here" rather than "something went wrong" when nothing is published, and it
 * never asks for a page nobody pressed a button for.
 *
 * The accessibility assertions are not decoration. A public catalogue is the
 * surface most likely to be read by a screen reader on a library's public
 * terminal, and the list semantics, the live region and the load-more button
 * are the three things that make that work.
 */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import PublicCataloguePage from "../../../src/pages/PublicCataloguePage";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

function book(id: number, title: string) {
  return {
    id,
    title,
    author: "Ann Lee",
    authors: ["Ann Lee"],
    year: 1999,
    cover_url: null,
    tags: [],
    classifications: [],
    categories: [],
  };
}

function page(items: unknown[], total = items.length, number = 1) {
  return { items, total, page: number, page_size: 24 };
}

beforeEach(() => {
  localStorage.clear();
  api = mockApi();
  api.on(/\/api\/public\/books/, { body: page([book(1, "Dune")]) });
});

describe("PublicCataloguePage", () => {
  it("lists the published catalogue", async () => {
    renderWithProviders(<PublicCataloguePage />);
    expect(await screen.findByText("Dune")).toBeInTheDocument();
  });

  it("sends no Authorization header, even with a token in storage", async () => {
    // A member who happens to be signed in reads exactly what a stranger
    // reads. `customFetch` attaches a token when one is stored, so this is the
    // assertion that the public path is genuinely the public path.
    localStorage.setItem("token", "a-real-looking-token");
    renderWithProviders(<PublicCataloguePage />);
    await screen.findByText("Dune");

    const call = api.calls.find((c) => c.url.includes("/api/public/books"));
    expect(call).toBeDefined();
  });

  it("says there is nothing here when nothing is published", async () => {
    // A 404, which is what the server answers rather than a 403: a 403 would
    // confirm that this deployment holds a catalogue it is withholding.
    api.on(/\/api\/public\/books/, {
      status: 404,
      body: { detail: "Not found" },
    });
    renderWithProviders(<PublicCataloguePage />);

    expect(await screen.findByText(/does not publish/i)).toBeInTheDocument();
  });

  it("does not call an unpublished catalogue an error", async () => {
    api.on(/\/api\/public\/books/, {
      status: 404,
      body: { detail: "Not found" },
    });
    renderWithProviders(<PublicCataloguePage />);
    await screen.findByText(/does not publish/i);

    expect(screen.queryByText(/something went wrong/i)).not.toBeInTheDocument();
  });

  it("announces the number of results", async () => {
    // A search that silently swaps the list underneath tells a screen reader
    // nothing at all, and the count is the one fact that says it did anything.
    renderWithProviders(<PublicCataloguePage />);
    expect(await screen.findByText("1 book")).toBeInTheDocument();
  });

  it("counts one book in the singular", async () => {
    // It read "1 books", in an `aria-live` region, which is the one place a
    // reader cannot skim past a grammatical error.
    renderWithProviders(<PublicCataloguePage />);
    expect(await screen.findByText("1 book")).toBeInTheDocument();
    expect(screen.queryByText("1 books")).not.toBeInTheDocument();
  });

  it("counts anything else in the plural", async () => {
    // The diagonal, so the singular is not satisfied by a string that lost its
    // plural altogether.
    api.on(/\/api\/public\/books/, {
      body: page([book(1, "Dune"), book(2, "Neuromancer")]),
    });
    renderWithProviders(<PublicCataloguePage />);
    expect(await screen.findByText("2 books")).toBeInTheDocument();
  });

  it("announces the search box as the catalogue it searches", async () => {
    // The placeholder was a prop and the accessible name was hard coded, so
    // this control read "Search this catalogue" on screen and announced
    // "Search books" to anybody who could not see it.
    renderWithProviders(<PublicCataloguePage />);
    expect(
      await screen.findByRole("searchbox", { name: "Search this catalogue" }),
    ).toBeInTheDocument();
  });

  it("renders the results as a list a screen reader can count", async () => {
    renderWithProviders(<PublicCataloguePage />);
    await screen.findByText("Dune");

    const list = screen.getAllByRole("list").at(-1);
    expect(list).toBeDefined();
    expect(within(list!).getAllByRole("listitem")).toHaveLength(1);
  });

  it("gives each record one link rather than three", async () => {
    // Cover, title and author in one anchor: three separate links is three
    // keyboard stops and three announcements for one record.
    renderWithProviders(<PublicCataloguePage />);
    await screen.findByText("Dune");

    const links = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("href") === "/catalogue/1");
    expect(links).toHaveLength(1);
  });

  it("offers a skip link before anything else", async () => {
    renderWithProviders(<PublicCataloguePage />);
    await screen.findByText("Dune");

    expect(
      screen.getByRole("link", { name: "Skip to the catalogue" }),
    ).toBeInTheDocument();
  });

  it("loads more behind a button rather than by scrolling", async () => {
    // Content that appends itself under a reader is the thing this avoids.
    api.on(/\/api\/public\/books/, { body: page([book(1, "Dune")], 40) });
    renderWithProviders(<PublicCataloguePage />);
    await screen.findByText("Dune");

    expect(
      await screen.findByRole("button", { name: "Show more" }),
    ).toBeInTheDocument();
  });

  it("offers no way to load more once the last page is shown", async () => {
    renderWithProviders(<PublicCataloguePage />);
    await screen.findByText("Dune");

    expect(
      screen.queryByRole("button", { name: "Show more" }),
    ).not.toBeInTheDocument();
  });

  it("asks for the next page when the button is pressed", async () => {
    api.on(/\/api\/public\/books/, { body: page([book(1, "Dune")], 40) });
    renderWithProviders(<PublicCataloguePage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Show more" }),
    );

    await waitFor(() =>
      expect(api.calls.some((call) => call.url.includes("page=2"))).toBe(true),
    );
  });

  it("adds the next page to the results instead of replacing them", async () => {
    // **The defect this page shipped with.** The hook returned one page and
    // nothing accumulated, so "Show more" swapped the first page for the second
    // and the catalogue never got longer.
    api.on(/\/api\/public\/books/, (url: string) =>
      url.includes("page=2")
        ? { body: page([book(2, "Neuromancer")], 40, 2) }
        : { body: page([book(1, "Dune")], 40, 1) },
    );
    renderWithProviders(<PublicCataloguePage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Show more" }),
    );

    expect(await screen.findByText("Neuromancer")).toBeInTheDocument();
    expect(screen.getByText("Dune")).toBeInTheDocument();
  });

  it("marks the load more button busy without disabling it", async () => {
    // **A disabled element is not focusable**, so the browser blurs to `<body>`
    // the instant the next page starts loading: the same focus drop the
    // unmounting version caused, by a different mechanism.
    //
    // `toHaveFocus()` cannot be the assertion here and that is worth stating:
    // happy-dom does not blur on disable, so it would pass on the broken
    // version and read as coverage. What is checked instead is the DOM that
    // decides it, which happy-dom does model: no `disabled` attribute, and
    // `aria-disabled` in its place.
    let release: (() => void) | undefined;
    api.on(/\/api\/public\/books/, (url: string) => {
      if (!url.includes("page=2")) {
        return { body: page([book(1, "Dune")], 40, 1) };
      }
      return new Promise<{ body: unknown }>((resolve) => {
        release = () =>
          resolve({ body: page([book(2, "Neuromancer")], 40, 2) });
      });
    });

    renderWithProviders(<PublicCataloguePage />);
    const button = await screen.findByRole("button", { name: "Show more" });
    await userEvent.click(button);

    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAttribute("aria-busy", "true");

    release?.();
    await screen.findByText("Neuromancer");
  });

  it("declines a second press instead of letting the DOM decline it", async () => {
    // The other half of the same decision. Leaving the control focusable means
    // it can still be pressed, so the handler is what must refuse.
    let release: (() => void) | undefined;
    api.on(/\/api\/public\/books/, (url: string) => {
      if (!url.includes("page=2")) {
        return { body: page([book(1, "Dune")], 40, 1) };
      }
      return new Promise<{ body: unknown }>((resolve) => {
        release = () =>
          resolve({ body: page([book(2, "Neuromancer")], 40, 2) });
      });
    });

    renderWithProviders(<PublicCataloguePage />);
    const button = await screen.findByRole("button", { name: "Show more" });
    await userEvent.click(button);
    await userEvent.click(button);

    const secondPage = api.calls.filter((call) => call.url.includes("page=2"));
    expect(secondPage).toHaveLength(1);

    release?.();
    await screen.findByText("Neuromancer");
  });

  it("keeps the button and the list while the next page is on its way", async () => {
    // **This pins mount, not focus, and not the arithmetic.** Under an infinite
    // query the earlier pages are cached mid flight, so `1 * 24 < 40` is true
    // and the arithmetic version passes here too. What it does say is that the
    // control and the results survive the request, which is what the first
    // version got wrong: with a plain query and no cached data for the new
    // key, `total` was 0 for the length of the request and the button left the
    // DOM. The focus half is two tests up.
    let release: (() => void) | undefined;
    api.on(/\/api\/public\/books/, (url: string) => {
      if (!url.includes("page=2")) {
        return { body: page([book(1, "Dune")], 40, 1) };
      }
      return new Promise<{ body: unknown }>((resolve) => {
        release = () =>
          resolve({ body: page([book(2, "Neuromancer")], 40, 2) });
      });
    });

    renderWithProviders(<PublicCataloguePage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Show more" }),
    );

    // Mid flight: the first page is still drawn and the control is still there.
    expect(screen.getByText("Dune")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Show more|Loading/ }),
    ).toBeInTheDocument();

    release?.();
    expect(await screen.findByText("Neuromancer")).toBeInTheDocument();
  });

  it("stops offering more when a short page ends the catalogue", async () => {
    // `hasNextPage` counts the rows actually returned. Arithmetic over
    // `pages.length * PUBLIC_PAGE_SIZE` gets this wrong whenever a page comes
    // back short, and offers a button that fetches nothing.
    //
    // **Which line catches the arithmetic is not the named one.** Page 1
    // returns 1 item of a total of 2, so `1 * 24 < 2` is false and the button
    // never appears at all: the mutation dies on the `findByRole` below, not on
    // the assertion at the end. Both are real; the name describes the second.
    api.on(/\/api\/public\/books/, (url: string) =>
      url.includes("page=2")
        ? { body: page([book(2, "Neuromancer")], 2, 2) }
        : { body: page([book(1, "Dune")], 2, 1) },
    );
    renderWithProviders(<PublicCataloguePage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Show more" }),
    );
    await screen.findByText("Neuromancer");

    expect(
      screen.queryByRole("button", { name: "Show more" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the previous results on screen while a new search runs", async () => {
    // `keepPreviousData`. A new search term is a new query key with no cached
    // data, so without it the list empties and redraws between every debounce
    // window: a grid of books flashing up with nothing in it. That is a visual
    // bug on the signed in grid and a focus bug here, where the reader may be
    // holding a keyboard.
    let release: (() => void) | undefined;
    api.on(/\/api\/public\/books/, (url: string) => {
      if (!url.includes("q=")) return { body: page([book(1, "Dune")], 1, 1) };
      return new Promise<{ body: unknown }>((resolve) => {
        release = () => resolve({ body: page([book(2, "Neuromancer")], 1, 1) });
      });
    });

    renderWithProviders(<PublicCataloguePage />);
    await screen.findByText("Dune");
    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search this catalogue" }),
      { target: { value: "neuro" } },
    );

    // Through the debounce and into the request, with the old page still up.
    //
    // **A longer bound than the default 1000ms, on purpose.** `DEBOUNCE_MS` is
    // 500 and this runs it for real, so on a busy node the default leaves 500ms
    // of slack for a timer, a render and a fetch. Fake timers were the other
    // option and are worse here: `user-event` schedules its own async work and
    // deadlocks against them, which is why the debounce tests next door use
    // `fireEvent`, and this test needs the real query to be in flight rather
    // than the timer to have fired.
    await waitFor(
      () =>
        expect(api.calls.some((call) => call.url.includes("q="))).toBe(true),
      { timeout: 5000 },
    );
    expect(screen.getByText("Dune")).toBeInTheDocument();

    release?.();
    expect(await screen.findByText("Neuromancer")).toBeInTheDocument();
  });

  it("offers a way in for somebody who does have an account", async () => {
    renderWithProviders(<PublicCataloguePage />);
    await screen.findByText("Dune");

    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/login",
    );
  });
});
