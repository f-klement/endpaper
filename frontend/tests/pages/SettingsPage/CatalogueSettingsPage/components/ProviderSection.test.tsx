/**
 * Tests for src/pages/SettingsPage/CatalogueSettingsPage/components/ProviderSection.tsx.
 *
 * The provider list: which catalogues are asked, and in what order.
 *
 * **Two properties carry the weight here.** A press must reach the server as a
 * whole roster rather than a patch, because a partial list would be read as an
 * instruction about the sources it omits; and a burst of presses must be one
 * request, because reordering is done by pressing a button four times.
 *
 * Fake timers with `fireEvent`, never `user-event`: it schedules its own async
 * work and deadlocks against them, which is the house rule for every debounce
 * test here.
 */

import { fireEvent, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CatalogueSourceOut,
  SettingsOut,
} from "../../../../../src/api/generated/model";
import ProviderSection from "../../../../../src/pages/SettingsPage/CatalogueSettingsPage/components/ProviderSection";
import { renderLocalised } from "../../../../utils";

/** The seeded roster, in the order a new install asks it. */
const ROSTER: CatalogueSourceOut[] = [
  row("dnb", { asked_first: true }),
  row("k10plus", { asked_first: true }),
  row("oenb"),
  row("open_library"),
  row("google_books", {
    needs_a_key: true,
    has_key: false,
    ready: false,
  }),
  row("bnf", { answers_lookup: false }),
  row("loc", { answers_lookup: false }),
];

function row(
  source: string,
  over: Partial<CatalogueSourceOut> = {},
): CatalogueSourceOut {
  return {
    source: source as CatalogueSourceOut["source"],
    enabled: true,
    answers_lookup: true,
    answers_search: true,
    asked_first: false,
    needs_a_key: false,
    has_key: true,
    ready: true,
    ...over,
  };
}

function draw(sources: CatalogueSourceOut[] = ROSTER) {
  const onSave = vi.fn();
  renderLocalised(
    <ProviderSection
      settings={{ catalogue_sources: sources } as SettingsOut}
      onSave={onSave}
    />,
  );
  return onSave;
}

/** Run out the debounce the component collects a burst of presses with. */
function settle() {
  act(() => {
    vi.advanceTimersByTime(1000);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ProviderSection", () => {
  it("lists every catalogue in the order the server sent", () => {
    draw();
    const listed = screen
      .getAllByRole("listitem")
      .map((item) => item.textContent ?? "");
    expect(listed).toHaveLength(ROSTER.length);
    expect(listed[0]).toContain("German National Library");
    expect(listed[1]).toContain("K10plus");
    expect(listed[6]).toContain("Library of Congress");
  });

  it("names every catalogue on screen", () => {
    draw();
    for (const name of [
      "German National Library",
      "K10plus",
      "Austrian National Library",
      "Open Library",
      "Google Books",
      "National Library of France",
      "Library of Congress",
    ]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("sends the whole roster when one source moves up", () => {
    const onSave = draw();
    fireEvent.click(screen.getByLabelText("Move Austrian National Library up"));
    settle();

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(
      onSave.mock.calls[0]?.[0].catalogue_sources.map(
        (entry: { source: string }) => entry.source,
      ),
    ).toEqual([
      "dnb",
      "oenb",
      "k10plus",
      "open_library",
      "google_books",
      "bnf",
      "loc",
    ]);
  });

  it("sends every source rather than only the one that moved", () => {
    const onSave = draw();
    fireEvent.click(screen.getByLabelText("Move Austrian National Library up"));
    settle();
    expect(onSave.mock.calls[0]?.[0].catalogue_sources).toHaveLength(
      ROSTER.length,
    );
  });

  it("collects a burst of presses into one save", () => {
    const onSave = draw();
    const up = () =>
      fireEvent.click(screen.getByLabelText("Move Library of Congress up"));
    up();
    up();
    up();
    settle();
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("moves a source as many places as it was pressed", () => {
    const onSave = draw();
    const up = () =>
      fireEvent.click(screen.getByLabelText("Move Library of Congress up"));
    up();
    up();
    settle();
    const order = onSave.mock.calls[0]?.[0].catalogue_sources.map(
      (entry: { source: string }) => entry.source,
    );
    expect(order.indexOf("loc")).toBe(4);
  });

  it("cannot move the first source up", () => {
    draw();
    expect(
      screen.getByLabelText("Move German National Library up"),
    ).toBeDisabled();
  });

  it("cannot move the last source down", () => {
    draw();
    expect(
      screen.getByLabelText("Move Library of Congress down"),
    ).toBeDisabled();
  });

  it("announces where a source landed", () => {
    draw();
    fireEvent.click(screen.getByLabelText("Move Austrian National Library up"));
    expect(
      screen.getByText("Austrian National Library moved to position 2 of 7."),
    ).toBeInTheDocument();
  });

  it("keeps the saved banner unambiguous by not being a second status", () => {
    draw();
    fireEvent.click(screen.getByLabelText("Move Austrian National Library up"));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("switches a source off without reordering anything", () => {
    const onSave = draw();
    fireEvent.click(screen.getByLabelText("Google Books"));
    settle();
    const sent = onSave.mock.calls[0]?.[0].catalogue_sources;
    expect(sent.map((entry: { source: string }) => entry.source)).toEqual(
      ROSTER.map((entry) => entry.source),
    );
    expect(
      sent.find((entry: { source: string }) => entry.source === "google_books")
        .enabled,
    ).toBe(false);
  });

  it("names the card below when the key is there and the source is off", () => {
    // The symptom this section exists to remove, produced by its own first fix:
    // a library holding a Google Books key was told to add one.
    // Replaced in place rather than prepended: prepending left the original
    // google_books row further down the list, so both messages rendered and the
    // test would have passed on the wrong one.
    draw(
      ROSTER.map((entry) =>
        entry.source === "google_books" ? { ...entry, has_key: true } : entry,
      ),
    );
    expect(
      screen.getByText(
        "A key is stored, but this catalogue is switched off in its own card below.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Needs an API key. Add one below, or it cannot answer.",
      ),
    ).not.toBeInTheDocument();
  });

  it("keeps focus on the row when a move disables the button just pressed", () => {
    // A disabled element drops focus to the body, so without this the press
    // that lands a row at an end silently ends the run.
    draw();
    const up = screen.getByLabelText("Move K10plus up");
    up.focus();
    fireEvent.click(up);
    expect(document.activeElement).toBe(
      screen.getByLabelText("Move K10plus down"),
    );
  });

  it("keeps focus on the row at the other end too", () => {
    draw();
    const down = screen.getByLabelText("Move National Library of France down");
    down.focus();
    fireEvent.click(down);
    expect(document.activeElement).toBe(
      screen.getByLabelText("Move National Library of France up"),
    );
  });

  it("leaves focus alone for a move that lands in the middle", () => {
    draw();
    const up = screen.getByLabelText("Move Open Library up");
    up.focus();
    fireEvent.click(up);
    expect(document.activeElement).toBe(up);
  });

  it("says when a source cannot answer for want of a key", () => {
    draw();
    expect(
      screen.getByText("Needs an API key. Add one below, or it cannot answer."),
    ).toBeInTheDocument();
  });

  it("says when a source has no say in scanning a barcode", () => {
    draw();
    expect(
      screen.getAllByText(
        "Answers title searches only, so its position does not affect scanning.",
      ),
    ).toHaveLength(2);
  });

  it("says which sources are asked on every scan", () => {
    draw();
    expect(
      screen.getAllByText(
        "Asked on every scan, with the others at the top of this list.",
      ),
    ).toHaveLength(2);
  });

  it("renders nothing rather than looping when the list is absent", () => {
    // `catalogue_sources` is optional on the generated type. A fresh `[]`
    // fallback would be a new array on every render, and the effect that
    // re-seeds from the server depends on its identity, so the pair would
    // render forever. This test times out rather than failing if that returns.
    const onSave = vi.fn();
    renderLocalised(
      <ProviderSection settings={{} as SettingsOut} onSave={onSave} />,
    );
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });

  it("says plainly that a switched off source is never asked", () => {
    draw([row("dnb", { enabled: false }), ...ROSTER.slice(1)]);
    expect(
      screen.getByText("Off. This catalogue is never asked."),
    ).toBeInTheDocument();
  });
});
