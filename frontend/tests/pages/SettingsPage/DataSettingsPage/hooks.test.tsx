/**
 * Tests for src/pages/SettingsPage/DataSettingsPage/hooks.ts: the backup
 * download, the one call there that goes around the generated client.
 *
 * The rest of the module is generated queries and mutations passed through,
 * which `DataSettingsPage.test.tsx` drives through the page. The download is a
 * hand written promise with its own busy flag and its own error, so it is
 * pinned here.
 */

import { act, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useBackup } from "../../../../src/pages/SettingsPage/DataSettingsPage/hooks";
import { mockApi, renderHookWithProviders, type MockApi } from "../../../utils";

let api: MockApi;
/** The file name each saved download was given, in order. */
let saved: string[];

beforeEach(() => {
  api = mockApi();
  saved = [];
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:backup");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    saved.push(this.download);
  });
  // Only the clock the file name reads; promises and timers stay real.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-09T12:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("downloading a backup", () => {
  it("saves the archive named for today when the server names none", async () => {
    api.on("/api/backup", { body: "archive" });
    const { result } = renderHookWithProviders(() => useBackup());

    act(() => result.current.download());

    await waitFor(() =>
      expect(saved).toEqual(["endpaper-backup-2026-10-09.zip"]),
    );
  });

  it("reports a refused download and stops being busy", async () => {
    api.on("/api/backup", { status: 500, body: { detail: "disk full" } });
    const { result } = renderHookWithProviders(() => useBackup());

    act(() => result.current.download());

    await waitFor(() =>
      expect(result.current.downloadError).toBeInstanceOf(Error),
    );
    expect((result.current.downloadError as Error).message).toBe("disk full");
    await waitFor(() => expect(result.current.isDownloading).toBe(false));
    expect(saved).toEqual([]);
  });
});
