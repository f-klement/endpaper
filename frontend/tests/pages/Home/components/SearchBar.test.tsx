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

  it("fires once with the empty string on mount", () => {
    // Home relies on this to load the unfiltered grid.
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);
    advance(DEBOUNCE_MS);
    expect(onSearch).toHaveBeenCalledWith("");
  });

  it("does not fire before the window elapses", () => {
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);
    advance(DEBOUNCE_MS);
    onSearch.mockClear();

    type("dune");
    advance(DEBOUNCE_MS - 1);

    expect(onSearch).not.toHaveBeenCalled();
  });

  it("fires with the typed value once the window elapses", () => {
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);
    advance(DEBOUNCE_MS);
    onSearch.mockClear();

    type("dune");
    advance(DEBOUNCE_MS);

    expect(onSearch).toHaveBeenCalledExactlyOnceWith("dune");
  });

  it("collapses a burst of keystrokes into one call", () => {
    // Four characters must not become four requests.
    const onSearch = vi.fn();
    renderLocalised(<SearchBar onSearch={onSearch} />);
    advance(DEBOUNCE_MS);
    onSearch.mockClear();

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
    advance(DEBOUNCE_MS);
    onSearch.mockClear();

    type("d");
    unmount();
    advance(1000);

    expect(onSearch).not.toHaveBeenCalled();
  });
});
