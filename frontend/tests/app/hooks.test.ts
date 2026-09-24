/** Tests for src/app/hooks.ts: the library export and the feature flags. */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExportFormat } from "../../src/api/generated/model";
import {
  useExportLibrary,
  useFeatureFlagsState,
  useScopedPreference,
} from "../../src/app/hooks";
import { declareScopedPreference } from "../../src/lib/preference";
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
 * `isResolved`, which is the half `useFeatureFlagsState`'s readers cannot express.
 *
 * `flags === undefined` is the same value before the request has answered and
 * after it has failed, and the two want opposite treatment: one is not an
 * answer, the other is the documented answer. Anything writing something keyed
 * on a flag has to tell them apart. See `pages/Home/hooks.ts`.
 */
describe("useFeatureFlagsState", () => {
  const BODY = {
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

/**
 * The scoped preference binding: the gate, and the one property a plain setter
 * cannot have.
 *
 * Driven against a preference declared here rather than one of the five, so
 * these arms are about the binding and not about what any real key means.
 */
describe("useScopedPreference", () => {
  const shelf = declareScopedPreference<"near" | "far", string>(
    { near: "test.binding.near", far: "test.binding.far" },
    "near",
    {
      decode: (raw) => raw,
      encode: (value) => value,
      fallback: (scope) => `default ${scope}`,
    },
  );

  it("reads under the unknown scope before one arrives", () => {
    const { result } = renderHook(() => useScopedPreference(shelf, undefined));
    expect(result.current.value).toBe("default near");
    expect(result.current.canSet).toBe(false);
  });

  it("refuses a write while no scope has arrived", () => {
    const { result } = renderHook(() => useScopedPreference(shelf, undefined));

    act(() => result.current.set("attic"));

    expect(localStorage.getItem("test.binding.near")).toBeNull();
    expect(result.current.value).toBe("default near");
  });

  it("writes under the scope it was given", () => {
    const { result } = renderHook(() => useScopedPreference(shelf, "far"));

    act(() => result.current.set("attic"));

    expect(localStorage.getItem("test.binding.far")).toBe("attic");
    expect(localStorage.getItem("test.binding.near")).toBeNull();
  });

  /**
   * **The property the wrapper this replaced had, which a plain setter does
   * not.** `writeForMode` handed the mode to its caller, so a value could not be
   * computed under one scope and stored under another. `set(value)` takes a
   * value computed elsewhere, so a caller deriving its value from the scope,
   * which is every caller resetting to a default, asks for the scope instead.
   */
  it("computes the value from the scope it is writing under", () => {
    const { result } = renderHook(() => useScopedPreference(shelf, "far"));

    act(() => result.current.setFromScope((known) => `shelf ${known}`));

    expect(localStorage.getItem("test.binding.far")).toBe("shelf far");
  });

  it("refuses that too, and calls nothing, while no scope has arrived", () => {
    // Calls nothing, rather than calling it with the reading scope: a value
    // computed under the unknown scope is exactly the wrong write this refuses.
    const compute = vi.fn((known: "near" | "far") => `shelf ${known}`);
    const { result } = renderHook(() => useScopedPreference(shelf, undefined));

    act(() => result.current.setFromScope(compute));

    expect(compute).not.toHaveBeenCalled();
    expect(localStorage.getItem("test.binding.near")).toBeNull();
  });
});
