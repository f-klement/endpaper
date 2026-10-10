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

import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

type OnDetected = NonNullable<
  React.ComponentProps<typeof BarcodeScanner>["onDetected"]
>;

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

/** The video constraints the first camera request carried, refused by name when there were none. */
function askedVideo(): MediaTrackConstraints {
  const video = getUserMedia.mock.calls[0]?.[0]?.video;
  if (typeof video !== "object") {
    throw new Error("the camera was not asked for video constraints");
  }
  return video;
}

describe("what the camera is asked for", () => {
  it("asks for a resolution that can actually resolve a barcode", async () => {
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());

    const video = askedVideo();
    expect((video.width as ConstrainULongRange).ideal).toBeGreaterThanOrEqual(
      1280,
    );
  });

  it("prefers the rear camera without demanding one", async () => {
    // `exact` fails outright on a laptop with only a front camera, and a front
    // camera that works beats a rear camera that does not exist.
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());

    const video = askedVideo();
    expect(video.facingMode).toEqual({ ideal: "environment" });
  });

  it("looks for book symbologies only", async () => {
    // Otherwise every frame is also tried against QR, Data Matrix and PDF417,
    // which no book carries: wasted budget and more chances to misread.
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    await waitFor(() => expect(readerArgs).toHaveBeenCalled());

    const hints = readerArgs.mock.calls[0]![0] as Map<string, string[]>;
    expect(hints.get("POSSIBLE_FORMATS")).toContain("EAN_13");
    expect(hints.get("POSSIBLE_FORMATS")).not.toContain("QR_CODE");
  });

  it("works harder per frame, because book barcodes are creased and curved", async () => {
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    await waitFor(() => expect(readerArgs).toHaveBeenCalled());

    const hints = readerArgs.mock.calls[0]![0] as Map<string, boolean>;
    expect(hints.get("TRY_HARDER")).toBe(true);
  });

  it("checks frames more often than the library's default", async () => {
    // 500ms skips most of the frames where a hand-held phone happened to be
    // steady and in focus.
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    await waitFor(() => expect(readerArgs).toHaveBeenCalled());

    expect(readerArgs.mock.calls[0]![1]).toBeLessThan(500);
  });
});

describe("BarcodeScanner", () => {
  it("starts the camera when active", async () => {
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());
  });

  it("does not start the camera when inactive", () => {
    renderLocalised(
      <BarcodeScanner active={false} onDetected={vi.fn<OnDetected>()} />,
    );
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("reports an ISBN barcode", async () => {
    const onDetected = vi.fn<OnDetected>();
    renderLocalised(<BarcodeScanner active onDetected={onDetected} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitBarcode("9780441013593");

    expect(onDetected).toHaveBeenCalledWith("9780441013593");
  });

  it("reports a misread frame to nobody", async () => {
    // A single wrong digit still looks like an ISBN. Without a checksum this
    // fired a lookup for a book that cannot exist.
    const onDetected = vi.fn<OnDetected>();
    renderLocalised(<BarcodeScanner active onDetected={onDetected} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitBarcode("9780441013594");

    expect(onDetected).not.toHaveBeenCalled();
  });

  it("ignores a barcode that is not a book", async () => {
    // Otherwise pointing the camera at a cereal box fires a lookup.
    const onDetected = vi.fn<OnDetected>();
    renderLocalised(<BarcodeScanner active onDetected={onDetected} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitBarcode("5012345678900");

    expect(onDetected).not.toHaveBeenCalled();
  });

  it("says so when it read a barcode that is not a book", async () => {
    // Discarding it in silence is why the scanner looked broken at exactly the
    // moment it was working: the price code beside the ISBN decodes perfectly.
    const onRejected = vi.fn<(code: string) => void>();
    renderLocalised(
      <BarcodeScanner
        active
        onDetected={vi.fn<OnDetected>()}
        onRejected={onRejected}
      />,
    );
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitBarcode("5012345678900");

    expect(onRejected).toHaveBeenCalledWith("5012345678900");
  });

  it("does not report a book as rejected", async () => {
    const onRejected = vi.fn<(code: string) => void>();
    renderLocalised(
      <BarcodeScanner
        active
        onDetected={vi.fn<OnDetected>()}
        onRejected={onRejected}
      />,
    );
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitBarcode("9780441013593");

    expect(onRejected).not.toHaveBeenCalled();
  });

  it("stays quiet on NotFoundException, which fires constantly", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitScannerError(new NotFoundException("no barcode in frame"));

    expect(warn).not.toHaveBeenCalled();
  });

  it("logs a genuine scanner error", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    emitScannerError(new Error("device lost"));

    expect(warn).toHaveBeenCalled();
  });

  it("shows the viewfinder prompt while scanning", async () => {
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    expect(await screen.findByText("Point at barcode")).toBeInTheDocument();
  });

  it("explains a denied camera permission", async () => {
    getUserMedia.mockRejectedValue(new Error("Permission denied"));
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);

    expect(await screen.findByText("Camera unavailable")).toBeInTheDocument();
    expect(screen.getByText("Permission denied")).toBeInTheDocument();
  });

  it("hides the viewfinder once the camera has failed", async () => {
    getUserMedia.mockRejectedValue(new Error("Permission denied"));
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);

    await screen.findByText("Camera unavailable");
    expect(screen.queryByText("Point at barcode")).not.toBeInTheDocument();
  });

  it("releases the camera on unmount", async () => {
    // Otherwise the phone's camera light stays on after navigating away.
    const { unmount } = renderLocalised(
      <BarcodeScanner active onDetected={vi.fn<OnDetected>()} />,
    );
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    unmount();

    expect(reset).toHaveBeenCalled();
  });

  it("stops the track it opened, not only the reader", async () => {
    // reset() releases the track ZXing opened. This component opens its own,
    // so without stopping it the indicator stays lit.
    const { unmount } = renderLocalised(
      <BarcodeScanner active onDetected={vi.fn<OnDetected>()} />,
    );
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    unmount();

    expect(stopTrack).toHaveBeenCalled();
  });

  it("releases the camera when it goes inactive", async () => {
    const { rerender } = renderLocalised(
      <BarcodeScanner active onDetected={vi.fn<OnDetected>()} />,
    );
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    rerender(
      <BarcodeScanner active={false} onDetected={vi.fn<OnDetected>()} />,
    );

    expect(stopTrack).toHaveBeenCalled();
  });

  it("names the camera unavailable when the refusal carries no message", async () => {
    // A browser may reject with something that is not an Error, which has no
    // message to show: the translated line stands in for it.
    getUserMedia.mockRejectedValue("NotAllowed");
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);

    // Two: the heading always reads it, and the detail line reads it only
    // when it stands in for the missing message.
    expect(await screen.findAllByText("Camera unavailable")).toHaveLength(2);
  });
});

/**
 * A camera request held open until the test answers it.
 *
 * The permission prompt can sit open while the member leaves the page, so the
 * answer arrives at a scanner that has already been closed.
 */
function heldCamera() {
  let answer!: (stream: MediaStream) => void;
  let refuse!: (reason: unknown) => void;
  getUserMedia.mockReturnValue(
    new Promise<MediaStream>((resolve, reject) => {
      answer = resolve;
      refuse = reject;
    }),
  );
  return { answer: (stream: MediaStream) => answer(stream), refuse };
}

/** Run `deliver` and let every promise it settles be handled. */
async function settle(deliver: () => void): Promise<void> {
  await act(async () => {
    deliver();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("a camera that answers after the scanner was closed", () => {
  it("is released at once rather than left running", async () => {
    const camera = heldCamera();
    const { unmount } = renderLocalised(
      <BarcodeScanner active onDetected={vi.fn<OnDetected>()} />,
    );
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    unmount();

    await settle(() => camera.answer(fakeStream()));

    expect(stopTrack).toHaveBeenCalled();
    expect(decodeFromStream).not.toHaveBeenCalled();
  });

  it("leaves no error behind for a refusal that arrives after it", async () => {
    const camera = heldCamera();
    const { rerender } = renderLocalised(
      <BarcodeScanner active onDetected={vi.fn<OnDetected>()} />,
    );
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    rerender(
      <BarcodeScanner active={false} onDetected={vi.fn<OnDetected>()} />,
    );

    await settle(() => camera.refuse(new Error("Permission denied")));

    expect(screen.queryByText("Camera unavailable")).not.toBeInTheDocument();
  });
});

describe("the camera light", () => {
  it("is offered when the camera has one", async () => {
    getUserMedia.mockResolvedValue(fakeStream({ torch: true }));
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);

    expect(await screen.findByText("Camera light")).toBeInTheDocument();
  });

  it("is not offered when the camera has none", async () => {
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    await waitFor(() => expect(decodeFromStream).toHaveBeenCalled());

    expect(screen.queryByText("Camera light")).not.toBeInTheDocument();
  });

  it("asks the camera for its light when pressed", async () => {
    const stream = fakeStream({ torch: true });
    getUserMedia.mockResolvedValue(stream);
    const user = userEvent.setup();
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);

    await user.click(
      await screen.findByRole("button", { name: "Camera light" }),
    );

    expect(stream.getVideoTracks()[0]!.applyConstraints).toHaveBeenCalledWith({
      advanced: [{ torch: true }],
    });
  });

  it("shows the light as on once the camera has accepted it", async () => {
    getUserMedia.mockResolvedValue(fakeStream({ torch: true }));
    const user = userEvent.setup();
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    const button = await screen.findByRole("button", { name: "Camera light" });

    await user.click(button);

    await waitFor(() => expect(button).toHaveAttribute("aria-pressed", "true"));
  });

  it("turns the light off again on a second press", async () => {
    const stream = fakeStream({ torch: true });
    getUserMedia.mockResolvedValue(stream);
    const user = userEvent.setup();
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);
    const button = await screen.findByRole("button", { name: "Camera light" });

    await user.click(button);
    await waitFor(() => expect(button).toHaveAttribute("aria-pressed", "true"));
    await user.click(button);

    await waitFor(() =>
      expect(button).toHaveAttribute("aria-pressed", "false"),
    );
    expect(
      stream.getVideoTracks()[0]!.applyConstraints,
    ).toHaveBeenLastCalledWith({ advanced: [{ torch: false }] });
  });

  it("withdraws the control when the camera refuses the light", async () => {
    // A camera that reported the capability and then refused it: the scan
    // works without light, so the control goes rather than an error appearing.
    const stream = fakeStream({ torch: true });
    vi.mocked(stream.getVideoTracks()[0]!.applyConstraints).mockRejectedValue(
      new Error("OverconstrainedError"),
    );
    getUserMedia.mockResolvedValue(stream);
    const user = userEvent.setup();
    renderLocalised(<BarcodeScanner active onDetected={vi.fn<OnDetected>()} />);

    await user.click(
      await screen.findByRole("button", { name: "Camera light" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Camera light" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.queryByText("Camera unavailable")).not.toBeInTheDocument();
  });
});
