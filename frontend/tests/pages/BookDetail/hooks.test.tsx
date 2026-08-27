/**
 * Tests for the section state in src/pages/BookDetail/hooks.ts.
 *
 * The API hooks on this page are covered through the page itself, in
 * BookDetail.test.tsx. What is only testable here is the interaction between
 * a book's own defaults and what a reader has said, which is three states and
 * is invisible to any test that checks the default alone.
 */

import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  hasAbout,
  sectionDefaults,
  useBookSections,
  type BookSection,
} from "../../../src/pages/BookDetail/hooks";
import { makeBook, makeLoan, resetIds } from "../../factories";
import { renderHookWithProviders } from "../../utils";

beforeEach(() => {
  resetIds();
  localStorage.clear();
});

afterEach(() => vi.restoreAllMocks());

describe("sectionDefaults", () => {
  it("opens what a reader came for", () => {
    const defaults = sectionDefaults(makeBook());

    expect(defaults.reading).toBe(true);
    expect(defaults.filing).toBe(true);
  });

  it("hides the loan on a book nobody has", () => {
    expect(sectionDefaults(makeBook({ active_loan: null })).lending).toBe(
      false,
    );
  });

  it("shows the loan on a book somebody has", () => {
    const book = makeBook();
    expect(
      sectionDefaults({ ...book, active_loan: makeLoan({ book_id: book.id }) })
        .lending,
    ).toBe(true);
  });

  it("hides the copies of a book there is only one of", () => {
    expect(sectionDefaults(makeBook({ copy_count: 1 })).copies).toBe(false);
  });

  it("shows them when there are two", () => {
    expect(sectionDefaults(makeBook({ copy_count: 2 })).copies).toBe(true);
  });

  it("treats a book with no copy count as a single copy", () => {
    expect(
      sectionDefaults({ ...makeBook(), copy_count: undefined }).copies,
    ).toBe(false);
  });

  it("opens the about section, which is drawn only when it has content", () => {
    expect(sectionDefaults(makeBook({ description: null })).about).toBe(true);
  });

  it("closes notes and quotes whatever the book says", () => {
    // Fixed, not conditional: the counts are not on BookOut, so a conditional
    // default could only open this after a second request landed.
    expect(sectionDefaults(makeBook()).writing).toBe(false);
  });
});

describe("hasAbout", () => {
  it("is true for a blurb", () => {
    expect(hasAbout(makeBook({ description: "Spice." }))).toBe(true);
  });

  it("is true for categories with no blurb", () => {
    expect(
      hasAbout(makeBook({ description: null, categories: ["Fiction"] })),
    ).toBe(true);
  });

  it("is false on a hand typed book, which is then given no handle at all", () => {
    // A section that offers no action and holds nothing is not a section.
    expect(hasAbout(makeBook({ description: null, categories: [] }))).toBe(
      false,
    );
  });
});

describe("useBookSections", () => {
  const defaults = (overrides: Partial<Record<BookSection, boolean>> = {}) => ({
    reading: true,
    filing: true,
    copies: false,
    lending: false,
    writing: false,
    about: false,
    ...overrides,
  });

  it("follows the book when nobody has said anything", () => {
    const { result } = renderHookWithProviders(() =>
      useBookSections(1, defaults({ lending: true })),
    );

    expect(result.current.isOpen("lending")).toBe(true);
    expect(result.current.isOpen("writing")).toBe(false);
  });

  it("keeps a section closed on the next visit, even though the book opens it", () => {
    // The failure this design exists to prevent. Two renders, because the
    // stored value has to survive the first one going away.
    const first = renderHookWithProviders(() =>
      useBookSections(1, defaults({ lending: true })),
    );
    act(() => first.result.current.toggle("lending"));
    first.unmount();

    const second = renderHookWithProviders(() =>
      useBookSections(1, defaults({ lending: true })),
    );

    expect(second.result.current.isOpen("lending")).toBe(false);
  });

  it("keeps a section open on the next visit, even though the book closes it", () => {
    const first = renderHookWithProviders(() => useBookSections(1, defaults()));
    act(() => first.result.current.toggle("writing"));
    first.unmount();

    const second = renderHookWithProviders(() =>
      useBookSections(1, defaults()),
    );

    expect(second.result.current.isOpen("writing")).toBe(true);
  });

  it("remembers each section on its own", () => {
    const { result } = renderHookWithProviders(() =>
      useBookSections(1, defaults()),
    );

    act(() => result.current.toggle("writing"));

    expect(result.current.isOpen("writing")).toBe(true);
    expect(result.current.isOpen("reading")).toBe(true);
    expect(result.current.isOpen("about")).toBe(false);
  });

  it("closes everything while the book is still loading", () => {
    // Null means no book yet. The page renders a spinner then, so nothing is
    // drawn against a default computed from a book that was not there.
    const { result } = renderHookWithProviders(() => useBookSections(1, null));

    expect(result.current.isOpen("reading")).toBe(false);
  });

  it("holds the defaults the book arrived with", () => {
    // Marking a loan returned changes active_loan, which would flip the
    // lending default to closed and fold the section away under the hand that
    // just used it.
    let borrowed = true;
    const { result, rerender } = renderHookWithProviders(() =>
      useBookSections(1, defaults({ lending: borrowed })),
    );
    expect(result.current.isOpen("lending")).toBe(true);

    borrowed = false;
    rerender();

    expect(result.current.isOpen("lending")).toBe(true);
  });

  it("re-arms for the next book, because the route reuses the component", () => {
    // `routes.tsx` renders /book/:id with no key, and the copies section links
    // straight to a sibling copy. A freeze that armed once would hand the
    // second book the first one's loan.
    let bookId = 1;
    let borrowed = true;
    const { result, rerender } = renderHookWithProviders(() =>
      useBookSections(bookId, defaults({ lending: borrowed })),
    );
    expect(result.current.isOpen("lending")).toBe(true);

    bookId = 2;
    borrowed = false;
    rerender();

    expect(result.current.isOpen("lending")).toBe(false);
  });

  it("still lets a reader's own choice cross from one book to the next", () => {
    // Storage is per section and not per book, so an explicit choice outlives
    // the book it was made on. That is the point: it is a preference about the
    // section, not about this title.
    let bookId = 1;
    const { result, rerender } = renderHookWithProviders(() =>
      useBookSections(bookId, defaults({ lending: true })),
    );
    act(() => result.current.toggle("lending"));

    bookId = 2;
    rerender();

    expect(result.current.isOpen("lending")).toBe(false);
  });

  it("renders with no memory at all when storage refuses", () => {
    // A private window. The book still has to draw, on the book's defaults.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });

    const { result } = renderHookWithProviders(() =>
      useBookSections(1, defaults({ about: true })),
    );

    expect(result.current.isOpen("about")).toBe(true);
  });
});
