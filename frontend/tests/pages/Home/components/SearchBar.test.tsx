/**
 * Tests for src/pages/Home/components/SearchBar.tsx: the debounce is the point.
 *
 * Driven with fireEvent rather than user-event: user-event schedules its own
 * async work, which deadlocks against fake timers unless the two are carefully
 * bridged. A change event is exactly what a keystroke produces here, so
 * nothing is lost.
 */

import { act, fireEvent, screen } from "@testing-library/react";
import { renderLocalised } from "../../../utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SearchBar, {
  DEBOUNCE_MS,
  MIN_QUERY_LENGTH,
} from "../../../../src/pages/Home/components/SearchBar";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

function type(value: string) {
  fireEvent.change(screen.getByRole("searchbox"), { target: { value } });
}

describe("SearchBar", () => {
  it("renders the default placeholder", () => {
    renderLocalised(<SearchBar onSearch={vi.fn()} />);
    expect(screen.getByPlaceholderText("Search books...")).toBeInTheDocument();
  });

  it("accepts a custom placeholder", () => {
    renderLocalised(
      <SearchBar onSearch={vi.fn()} placeholder="Find a title" />,
    );
    expect(screen.getByPlaceholderText("Find a title")).toBeInTheDocument();
  });

  it("is labelled for assistive tech", () => {
    renderLocalised(<SearchBar onSearch={vi.fn()} />);
    expect(screen.getByLabelText("Search books")).toBeInTheDocument();
  });

  it("does not fire on mount", () => {
    // Home has already loaded the unfiltered grid by the time this renders, so
    // firing here re-requests a list nobody asked to change.
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);
    advance(DEBOUNCE_MS);
    expect(onSearch).not.toHaveBeenCalled();
  });

  it("ignores a query too short to mean anything", () => {
    // One letter matches most of a library: an expensive request for a useless
    // answer.
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);

    type("d".repeat(MIN_QUERY_LENGTH - 1));
    advance(DEBOUNCE_MS);

    expect(onSearch).not.toHaveBeenCalled();
  });

  it("fires when the box is emptied again", () => {
    // Clearing is a real instruction: show me the whole shelf.
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);

    type("dune");
    advance(DEBOUNCE_MS);
    onSearch.mockClear();

    type("");
    advance(DEBOUNCE_MS);

    expect(onSearch).toHaveBeenCalledExactlyOnceWith("");
  });

  it("trims what it sends", () => {
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);

    type("  dune  ");
    advance(DEBOUNCE_MS);

    expect(onSearch).toHaveBeenCalledExactlyOnceWith("dune");
  });

  it("waits long enough to catch an unhurried typist", () => {
    // A debounce only collapses keystrokes closer together than its window.
    // At 300ms this was firing once per character for anyone typing on a
    // phone, which is the whole thing it exists to prevent.
    expect(DEBOUNCE_MS).toBeGreaterThanOrEqual(500);
  });

  it("does not fire before the window elapses", () => {
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);

    type("dune");
    advance(DEBOUNCE_MS - 1);

    expect(onSearch).not.toHaveBeenCalled();
  });

  it("fires with the typed value once the window elapses", () => {
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);

    type("dune");
    advance(DEBOUNCE_MS);

    expect(onSearch).toHaveBeenCalledExactlyOnceWith("dune");
  });

  it("collapses a burst of keystrokes into one call", () => {
    // Four characters must not become four requests.
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);

    for (const value of ["d", "du", "dun", "dune"]) {
      type(value);
      advance(50);
    }
    advance(DEBOUNCE_MS);

    expect(onSearch).toHaveBeenCalledExactlyOnceWith("dune");
  });

  it("cancels a pending call when unmounted", () => {
    const onSearch = vi.fn();
    const { unmount } = renderLocalised(<SearchBar onSearch={onSearch} />);

    type("du");
    unmount();
    advance(1000);

    expect(onSearch).not.toHaveBeenCalled();
  });
});
