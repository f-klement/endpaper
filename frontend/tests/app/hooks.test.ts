/** Tests for src/app/hooks.ts: the library export and the feature flags. */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExportFormat } from "../../src/api/generated/model";
import { useExportLibrary, useFeatureFlagsState } from "../../src/app/hooks";
import {
  mockApi,
  renderHookWithProviders,
  type MockApi,
  type StubResponse,
} from "../utils";

let api: MockApi;

beforeEach(() => {
  api = mockApi();
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

describe("useExportLibrary", () => {
  it("requests the chosen format", async () => {
    api.on("/api/books/export", {
      body: "csv",
      headers: { "content-type": "text/csv" },
    });
    const { result } = renderHook(() => useExportLibrary());

    act(() => result.current.exportLibrary(ExportFormat.txt));

    await waitFor(() =>
      expect(api.lastCall("/api/books/export")?.url).toContain("format=txt"),
    );
  });

  it("reports a failed export rather than failing silently", async () => {
    api.on("/api/books/export", {
      status: 401,
      body: { detail: "Not authenticated" },
    });
    const { result } = renderHook(() => useExportLibrary());

    act(() => result.current.exportLibrary(ExportFormat.csv));

    await waitFor(() => expect(result.current.error).toBeTruthy());
  });

  it("clears the busy flag when the download finishes", async () => {
    api.on("/api/books/export", {
      body: "csv",
      headers: { "content-type": "text/csv" },
    });
    const { result } = renderHook(() => useExportLibrary());

    act(() => result.current.exportLibrary(ExportFormat.csv));

    await waitFor(() => expect(result.current.isExporting).toBe(false));
  });

  it("clears the busy flag even when the download fails", async () => {
    api.on("/api/books/export", { status: 500, body: { detail: "boom" } });
    const { result } = renderHook(() => useExportLibrary());

    act(() => result.current.exportLibrary(ExportFormat.csv));

    await waitFor(() => expect(result.current.isExporting).toBe(false));
  });
});

/**
 * `isResolved`, which is the half `useFeatureFlags` cannot express.
 *
 * `flags === undefined` is the same value before the request has answered and
 * after it has failed, and the two want opposite treatment: one is not an
 * answer, the other is the documented answer. Anything writing something keyed
 * on a flag has to tell them apart. See `pages/Home/hooks.ts`.
 */
describe("useFeatureFlagsState", () => {
  const BODY = {
    google_books_enabled: false,
    google_books_ready: false,
    goodreads_lookup_enabled: false,
    default_locale: "en",
    library_mode: true,
  };

  it("is unresolved while the request is in flight", async () => {
    let release!: () => void;
    const held = new Promise<StubResponse>((resolve) => {
      release = () => resolve({ body: BODY });
    });
    api.on("/api/settings/features", () => held);

    const { result } = renderHookWithProviders(() => useFeatureFlagsState());
    expect(result.current.isResolved).toBe(false);
    expect(result.current.flags).toBeUndefined();

    release();
    await waitFor(() => expect(result.current.isResolved).toBe(true));
    expect(result.current.flags?.library_mode).toBe(true);
  });

  it("is resolved once the request fails, because that is an answer", async () => {
    api.on("/api/settings/features", { status: 500, body: {} });

    const { result } = renderHookWithProviders(() => useFeatureFlagsState());

    await waitFor(() => expect(result.current.isResolved).toBe(true));
    // Resolved and empty, which is the pair the flag exists to distinguish
    // from unresolved and empty.
    expect(result.current.flags).toBeUndefined();
  });
});
