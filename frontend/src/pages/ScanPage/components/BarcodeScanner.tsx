import {
  BarcodeFormat,
  BrowserMultiFormatReader,
  DecodeHintType,
  NotFoundException,
} from "@zxing/library";
import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "../../../components";
import { useTranslation } from "../../../i18n";
import { parseIsbn } from "../../../lib/isbn";

/**
 * Is this barcode a book, and if so which one?
 *
 * Returns the canonical ISBN-13 or null. Delegating to the shared parser means
 * the check digit is verified, so a misread frame is discarded instead of
 * firing a lookup for a book that cannot exist, and an ISBN-10 ending in X is
 * accepted rather than silently ignored.
 */
export function readIsbnBarcode(text: string): string | null {
  return parseIsbn(text);
}

/**
 * The only symbologies a book is printed in.
 *
 * Without this the reader tries every format it knows on every frame, QR, Data
 * Matrix, PDF417, Codabar and the rest included. That is most of the per-frame
 * budget spent on formats no book has ever carried, and each one is another
 * chance to lock onto a false positive. Restricting it is the single cheapest
 * thing that makes scanning feel responsive.
 */
const BOOK_FORMATS = [
  BarcodeFormat.EAN_13,
  BarcodeFormat.EAN_8,
  BarcodeFormat.UPC_A,
  BarcodeFormat.UPC_E,
];

function bookReaderHints(): Map<DecodeHintType, unknown> {
  const hints = new Map<DecodeHintType, unknown>();
  hints.set(DecodeHintType.POSSIBLE_FORMATS, BOOK_FORMATS);
  // Worth the extra work per frame here: a book barcode is often creased,
  // curved over a spine, or printed small on a paperback.
  hints.set(DecodeHintType.TRY_HARDER, true);
  return hints;
}

/**
 * How long the reader idles between decode attempts.
 *
 * The library's default is 500ms, which on a hand-held phone means most of the
 * frames where the barcode happened to be steady and in focus are skipped. Low
 * enough to catch those, high enough to leave the main thread usable.
 */
const SCAN_INTERVAL_MS = 150;

/**
 * What to ask the camera for.
 *
 * The resolution is the other half of why scanning was unreliable. Asking for
 * nothing gets whatever the browser defaults to, typically 640x480, and an
 * EAN-13 has 95 modules across it: at that width, held at a comfortable
 * distance, the bars land on well under a pixel each and no amount of decoding
 * effort recovers them. Asking for 1080p costs nothing when the camera cannot
 * do it, because `ideal` degrades instead of failing.
 *
 * `facingMode` is `ideal` rather than `exact` on purpose: `exact` fails outright
 * on a laptop with only a front camera, and a front camera that works beats a
 * rear camera that does not exist.
 */
const CAMERA_CONSTRAINTS: MediaStreamConstraints = {
  video: {
    facingMode: { ideal: "environment" },
    width: { ideal: 1920 },
    height: { ideal: 1080 },
  },
};

/**
 * Whether this camera has a light, which the DOM types do not describe.
 *
 * `torch` is real and widely implemented but is not in the standard
 * `MediaTrackCapabilities`, so it is read through a narrow cast rather than by
 * widening the interface, which TypeScript rejects because `getCapabilities`
 * is not optional on the real type.
 */
function supportsTorch(track: MediaStreamTrack | undefined): boolean {
  if (!track || typeof track.getCapabilities !== "function") return false;
  const capabilities = track.getCapabilities() as MediaTrackCapabilities & {
    torch?: boolean;
  };
  return capabilities.torch === true;
}

interface BarcodeScannerProps {
  onDetected: (isbn: string) => void;
  active: boolean;
  /**
   * Called when a barcode decoded cleanly but is not a book.
   *
   * Silence was its own bug. A shelf label, a library sticker or the price
   * barcode next to the ISBN all decode perfectly and are then discarded with
   * no trace, so the scanner looks broken at exactly the moment it is working.
   */
  onRejected?: (code: string) => void;
}

/** The camera viewfinder. Used only by ScanPage. */
export default function BarcodeScanner({
  onDetected,
  active,
  onRejected,
}: BarcodeScannerProps) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const readerRef = useRef<BrowserMultiFormatReader | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [hasTorch, setHasTorch] = useState(false);
  const [torchOn, setTorchOn] = useState(false);

  // Held in a ref so the effect below does not list them as dependencies.
  // ScanPage passes inline callbacks, and depending on them would tear the
  // camera down and bring it back up on every render.
  const handlers = useRef({ onDetected, onRejected });
  handlers.current = { onDetected, onRejected };

  const stop = useCallback(() => {
    readerRef.current?.reset();
    readerRef.current = null;
    // reset() releases the track it opened, but the stream here was opened by
    // this component, so it has to be stopped explicitly or the phone's camera
    // indicator stays lit after leaving the page.
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setScanning(false);
    setTorchOn(false);
    setHasTorch(false);
  }, []);

  useEffect(() => {
    if (!active) {
      stop();
      return;
    }

    let cancelled = false;
    const reader = new BrowserMultiFormatReader(
      bookReaderHints(),
      SCAN_INTERVAL_MS,
    );
    readerRef.current = reader;
    setError(null);

    async function start() {
      const video = videoRef.current;
      if (!video) return;

      try {
        const stream =
          await navigator.mediaDevices.getUserMedia(CAMERA_CONSTRAINTS);
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;

        setHasTorch(supportsTorch(stream.getVideoTracks()[0]));

        void reader.decodeFromStream(stream, video, (result, err) => {
          if (result) {
            const text = result.getText();
            // Report the canonical form, not the raw scan, so an ISBN-10
            // barcode and its ISBN-13 reprint resolve to the same book.
            const canonical = readIsbnBarcode(text);
            if (canonical) {
              handlers.current.onDetected(canonical);
            } else {
              handlers.current.onRejected?.(text);
            }
          }
          // NotFoundException fires continuously while no barcode is in frame.
          if (err && !(err instanceof NotFoundException)) {
            console.warn("Scanner error:", err);
          }
        });
        setScanning(true);
      } catch (err: unknown) {
        if (cancelled) return;
        // The camera also needs a secure context: on a plain-HTTP LAN address
        // this fails no matter what the member taps.
        setError(
          err instanceof Error ? err.message : t("scan.cameraUnavailable"),
        );
        setScanning(false);
      }
    }

    void start();

    return () => {
      cancelled = true;
      stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, stop]);

  async function toggleTorch() {
    const [track] = streamRef.current?.getVideoTracks() ?? [];
    if (!track) return;
    const next = !torchOn;
    try {
      // Not in the standard MediaTrackConstraintSet, but implemented on the
      // browsers that have a torch to offer.
      await track.applyConstraints({
        advanced: [{ torch: next } as MediaTrackConstraintSet],
      });
      setTorchOn(next);
    } catch {
      // A camera that reported the capability and then refused it is not worth
      // an error message: the scan works without light.
      setHasTorch(false);
    }
  }

  return (
    <div className="relative w-full aspect-[4/3] bg-black rounded-xl overflow-hidden">
      {/* object-contain, not object-cover. Cover crops the frame, so the guide
          box below sits over a picture that is narrower than what is actually
          being decoded, and a barcode lined up inside the box can be outside
          the part of the image the reader ever sees. */}
      <video
        ref={videoRef}
        className="w-full h-full object-contain"
        muted
        playsInline
      />

      {scanning && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-64 h-32 border-2 border-accent-400 rounded-lg relative">
            <div className="absolute top-0 left-0 w-5 h-5 border-t-4 border-l-4 border-accent-400 rounded-tl" />
            <div className="absolute top-0 right-0 w-5 h-5 border-t-4 border-r-4 border-accent-400 rounded-tr" />
            <div className="absolute bottom-0 left-0 w-5 h-5 border-b-4 border-l-4 border-accent-400 rounded-bl" />
            <div className="absolute bottom-0 right-0 w-5 h-5 border-b-4 border-r-4 border-accent-400 rounded-br" />
            <div className="absolute inset-x-0 top-1/2 h-px bg-accent-400 opacity-60 animate-pulse" />
          </div>
          <p className="absolute bottom-4 text-white text-sm font-medium">
            {t("scan.pointAtBarcode")}
          </p>
        </div>
      )}

      {scanning && hasTorch && (
        <button
          type="button"
          onClick={() => void toggleTorch()}
          aria-pressed={torchOn}
          className="absolute top-3 right-3 w-10 h-10 rounded-full bg-black/50 text-white text-lg backdrop-blur-sm hover:bg-black/70 transition-colors"
        >
          <Icon name="lamp" className="w-4 h-4" filled={torchOn} />
          <span className="sr-only">{t("scan.torch")}</span>
        </button>
      )}

      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/70">
          <div className="text-center text-white p-4">
            <Icon name="camera" className="w-7 h-7 mx-auto mb-2 opacity-80" />
            <p className="font-medium">{t("scan.cameraUnavailable")}</p>
            <p className="text-sm text-paper-300 mt-1">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}
