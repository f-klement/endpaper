/** Tests for src/pages/AppearancePage/hooks.ts. */

import { describe, expect, it } from "vitest";

import {
  getListBooksInfiniteQueryKey,
  getListBooksQueryKey,
} from "../../../src/api/generated/endpoints/books/books";
import { usePreviewBooks } from "../../../src/pages/AppearancePage";
import { makeBook, makeBookPage } from "../../factories";
import { createTestQueryClient, renderHookWithProviders } from "../../utils";

function page(count: number) {
  return makeBookPage(Array.from({ length: count }, () => makeBook()));
}

describe("usePreviewBooks", () => {
  it("finds nothing before the library has been opened", () => {
    // The picker draws no cards at all in that case. An invented book in a
    // preview is exactly what previewing on real content exists to avoid.
    const { result } = renderHookWithProviders(() => usePreviewBooks(2));

    expect(result.current).toEqual([]);
  });

  it("takes the first books off Home's paged listing", () => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(getListBooksInfiniteQueryKey({ page_size: 24 }), {
      pages: [page(5)],
      pageParams: [1],
    });

    const { result } = renderHookWithProviders(() => usePreviewBooks(2), {
      queryClient,
    });

    expect(result.current).toHaveLength(2);
  });

  it("takes them off an unpaged listing too", () => {
    // Two hooks write to this cache and the picker reads whichever is there,
    // rather than naming one and drawing nothing when the other filled it.
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(getListBooksQueryKey({ page_size: 24 }), page(3));

    const { result } = renderHookWithProviders(() => usePreviewBooks(2), {
      queryClient,
    });

    expect(result.current).toHaveLength(2);
  });

  it("asks for nothing over the network", () => {
    // `setup.ts` installs a fetch that rejects, so a request here would fail
    // the test rather than pass quietly.
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(getListBooksInfiniteQueryKey({ page_size: 24 }), {
      pages: [page(2)],
      pageParams: [1],
    });

    renderHookWithProviders(() => usePreviewBooks(2), { queryClient });

    expect(fetch).not.toHaveBeenCalled();
  });

  it("returns fewer than asked for rather than padding", () => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(getListBooksInfiniteQueryKey(), {
      pages: [page(1)],
      pageParams: [1],
    });

    const { result } = renderHookWithProviders(() => usePreviewBooks(2), {
      queryClient,
    });

    expect(result.current).toHaveLength(1);
  });

  it("skips an empty listing to find one with books in it", () => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(getListBooksInfiniteQueryKey({ q: "nothing" }), {
      pages: [page(0)],
      pageParams: [1],
    });
    queryClient.setQueryData(getListBooksInfiniteQueryKey({ page_size: 24 }), {
      pages: [page(4)],
      pageParams: [1],
    });

    const { result } = renderHookWithProviders(() => usePreviewBooks(2), {
      queryClient,
    });

    expect(result.current).toHaveLength(2);
  });
});
