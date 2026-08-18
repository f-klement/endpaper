/** Tests for src/app/hooks.ts: the library export. */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExportFormat } from "../../src/api/generated/model";
import { useExportLibrary } from "../../src/app/hooks";
import { mockApi, type MockApi } from "../utils";

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
