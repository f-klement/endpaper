/**
 * Tests for src/pages/ScanPage/components/BarcodeScanner.tsx.
 *
 * @zxing/library is mocked wholesale: there is no camera in jsdom, and what is
 * worth testing is the ISBN filter, what the camera is asked for, and the
 * lifecycle, not ZXing's decoding.
 *
 * The constraints are asserted on rather than taken on trust because they are
 * the fix for the scanner reading nothing on a phone: the default stream is
 * around 640x480, and an EAN-13 is 95 modules wide, so at that resolution the
 * bars fall below a pixel each and no amount of decoding effort recovers them.
 */

import { screen, waitFor } from "@testing-library/react";
import { renderLocalised } from "../../../utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The library is replaced for the whole suite by an alias in `vite.config.ts`,
// so these are the spies the component under test really calls, and importing
// `@zxing/library` below reaches the same double. There is no `vi.mock` here on
// purpose: see `tests/doubles/README.md`.
import {
  fakeStream,
  getUserMedia,
  installCamera,
  stopTrack,
} from "../../../doubles/camera";
import {
  decodeFromStream,
  emitBarcode,
  emitScannerError,
  readerArgs,
  reset,
} from "../../../doubles/zxing";

import { NotFoundException } from "@zxing/library";

import BarcodeScanner, {
  readIsbnBarcode,
} from "../../../../src/pages/ScanPage/components/BarcodeScanner";

beforeEach(() => {
  // The ZXing double is reset by tests/setup.ts, for every file.
  installCamera();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("readIsbnBarcode", () => {
  it.each(["9780441013593", "9791234567896", "0441013597"])(
    "accepts %s",
    (code) => {
      expect(readIsbnBarcode(code)).not.toBeNull();
    },
  );

  it("accepts an ISBN-10 ending in X", () => {
    // Roughly one ISBN-10 in eleven ends this way, and the previous regex
    // rejected every one of them.
    expect(readIsbnBarcode("043942089X")).not.toBeNull();
  });

  it("returns the canonical ISBN-13 for an ISBN-10 barcode", () => {
    // So a paperback's ISBN-10 barcode and its ISBN-13 reprint resolve to one
    // book rather than two catalogue entries.
    expect(readIsbnBarcode("0441013597")).toBe("9780441013593");
  });

  it.each([
    ["1234567890123", "an EAN-13 that is not Bookland"],
    ["5012345678900", "a real product barcode"],
    ["9780441013594", "a book ISBN with one digit misread"],
    ["12345", "too short"],
    ["97804410135931", "too long"],
    ["", "empty"],
  ])("rejects %s (%s)", (code) => {
    expect(readIsbnBarcode(code)).toBeNull();
  });
});

describe("what the camera is asked for", () => {
  it("asks for a resolution that can actually resolve a barcode", async () => {
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());

    const video = getUserMedia.mock.calls[0]![0].video as MediaTrackConstraints;
    expect((video.width as ConstrainULongRange).ideal).toBeGreaterThanOrEqual(
      1280,
    );
  });

  it("prefers the rear camera without demanding one", async () => {
    // `exact` fails outright on a laptop with only a front camera, and a front
    // camera that works beats a rear camera that does not exist.
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());

    const video = getUserMedia.mock.calls[0]![0].video as MediaTrackConstraints;
    expect(video.facingMode).toEqual({ ideal: "environment" });
  });

  it("looks for book symbologies only", async () => {
    // Otherwise every frame is also tried against QR, Data Matrix and PDF417,
    // which no book carries: wasted budget and more chances to misread.
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);
    await waitFor(() => expect(readerArgs).toHaveBeenCalled());

    const hints = readerArgs.mock.calls[0]![0] as Map<string, string[]>;
    expect(hints.get("POSSIBLE_FORMATS")).toContain("EAN_13");
    expect(hints.get("POSSIBLE_FORMATS")).not.toContain("QR_CODE");
  });

  it("works harder per frame, because book barcodes are creased and curved", async () => {
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);
    await waitFor(() => expect(readerArgs).toHaveBeenCalled());

    const hints = readerArgs.mock.calls[0]![0] as Map<string, boolean>;
    expect(hints.get("TRY_HARDER")).toBe(true);
  });

  it("checks frames more often than the library's default", async () => {
    // 500ms skips most of the frames where a hand-held phone happened to be
    // steady and in focus.
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);
    await waitFor(() => expect(readerArgs).toHaveBeenCalled());

    expect(readerArgs.mock.calls[0]![1]).toBeLessThan(500);
  });
});

describe("BarcodeScanner", () => {
  it("starts the camera when active", async () => {
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());
  });

  it("does not start the camera when inactive", () => {
    renderLocalised(<BarcodeScanner active={false} onDetected={vi.fn()} />);
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("reports an ISBN barcode", async () => {
    const onDetected = vi.fn();
    renderLocalised(<BarcodeScanner active onDetected={onDetected} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitBarcode("9780441013593");

    expect(onDetected).toHaveBeenCalledWith("9780441013593");
  });

  it("reports a misread frame to nobody", async () => {
    // A single wrong digit still looks like an ISBN. Without a checksum this
    // fired a lookup for a book that cannot exist.
    const onDetected = vi.fn();
    renderLocalised(<BarcodeScanner active onDetected={onDetected} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitBarcode("9780441013594");

    expect(onDetected).not.toHaveBeenCalled();
  });

  it("ignores a barcode that is not a book", async () => {
    // Otherwise pointing the camera at a cereal box fires a lookup.
    const onDetected = vi.fn();
    renderLocalised(<BarcodeScanner active onDetected={onDetected} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitBarcode("5012345678900");

    expect(onDetected).not.toHaveBeenCalled();
  });

  it("says so when it read a barcode that is not a book", async () => {
    // Discarding it in silence is why the scanner looked broken at exactly the
    // moment it was working: the price code beside the ISBN decodes perfectly.
    const onRejected = vi.fn();
    renderLocalised(
      <BarcodeScanner active onDetected={vi.fn()} onRejected={onRejected} />,
    );
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitBarcode("5012345678900");

    expect(onRejected).toHaveBeenCalledWith("5012345678900");
  });

  it("does not report a book as rejected", async () => {
    const onRejected = vi.fn();
    renderLocalised(
      <BarcodeScanner active onDetected={vi.fn()} onRejected={onRejected} />,
    );
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitBarcode("9780441013593");

    expect(onRejected).not.toHaveBeenCalled();
  });

  it("stays quiet on NotFoundException, which fires constantly", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitScannerError(new NotFoundException("no barcode in frame"));

    expect(warn).not.toHaveBeenCalled();
  });

  it("logs a genuine scanner error", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitScannerError(new Error("device lost"));

    expect(warn).toHaveBeenCalled();
  });

  it("shows the viewfinder prompt while scanning", async () => {
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);
    expect(await screen.findByText("Point at barcode")).toBeInTheDocument();
  });

  it("explains a denied camera permission", async () => {
    getUserMedia.mockRejectedValue(new Error("Permission denied"));
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);

    expect(await screen.findByText("Camera unavailable")).toBeInTheDocument();
    expect(screen.getByText("Permission denied")).toBeInTheDocument();
  });

  it("hides the viewfinder once the camera has failed", async () => {
    getUserMedia.mockRejectedValue(new Error("Permission denied"));
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);

    await screen.findByText("Camera unavailable");
    expect(screen.queryByText("Point at barcode")).not.toBeInTheDocument();
  });

  it("releases the camera on unmount", async () => {
    // Otherwise the phone's camera light stays on after navigating away.
    const { unmount } = renderLocalised(
      <BarcodeScanner active onDetected={vi.fn()} />,
    );
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    unmount();

    expect(reset).toHaveBeenCalled();
  });

  it("stops the track it opened, not only the reader", async () => {
    // reset() releases the track ZXing opened. This component opens its own,
    // so without stopping it the indicator stays lit.
    const { unmount } = renderLocalised(
      <BarcodeScanner active onDetected={vi.fn()} />,
    );
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    unmount();

    expect(stopTrack).toHaveBeenCalled();
  });

  it("releases the camera when it goes inactive", async () => {
    const { rerender } = renderLocalised(
      <BarcodeScanner active onDetected={vi.fn()} />,
    );
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    rerender(<BarcodeScanner active={false} onDetected={vi.fn()} />);

    expect(stopTrack).toHaveBeenCalled();
  });
});

describe("the camera light", () => {
  it("is offered when the camera has one", async () => {
    getUserMedia.mockResolvedValue(fakeStream({ torch: true }));
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);

    expect(await screen.findByText("Camera light")).toBeInTheDocument();
  });

  it("is not offered when the camera has none", async () => {
    renderLocalised(<BarcodeScanner active onDetected={vi.fn()} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    expect(screen.queryByText("Camera light")).not.toBeInTheDocument();
  });
});
