import {
  BarcodeFormat,
  BrowserMultiFormatReader,
  DecodeHintType,
  NotFoundException,
  type Exception,
  type Result,
} from "@zxing/library";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";

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

/**
 * Whether this camera is known to face away from the member.
 *
 * Only a rear camera says so, by reporting `environment`; a front camera
 * reports `user`, and a browser may report nothing (how many do is
 * unmeasured). Everything that is not known to be rear, a track without
 * `getSettings` included, gets the front camera treatment,
 * a mirrored preview and the focus hint, neither of which touches decoding.
 *
 * There is deliberately no flipped decode for a camera that delivers mirrored
 * frames: ZXing's one dimensional readers already retry every row reversed,
 * which for a barcode is a horizontal flip. See docs/decisions.md.
 */
function facesAway(track: MediaStreamTrack | undefined): boolean {
  if (!track || typeof track.getSettings !== "function") return false;
  return track.getSettings().facingMode === "environment";
}

/**
 * How long a camera that may face the member goes without a read before the
 * scanner suggests holding the book further back.
 *
 * A fixed focus webcam, which many laptops are assumed to have (unmeasured
 * here), blurs a barcode held close enough to fill the frame beyond what any
 * decoder recovers, and nothing on screen says so.
 */
const HOLD_FURTHER_BACK_AFTER_MS = 6000;

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

type ScanHandlers = Pick<BarcodeScannerProps, "onDetected" | "onRejected">;

/** Stop every track of a stream, which is what puts the camera indicator out. */
function stopTracks(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop());
}

/** Hand one decoded barcode to the page: a book, or a code that is not one. */
function reportRead(text: string, handlers: ScanHandlers) {
  // Report the canonical form, not the raw scan, so an ISBN-10 barcode and its
  // ISBN-13 reprint resolve to the same book.
  const canonical = readIsbnBarcode(text);
  if (canonical) {
    handlers.onDetected(canonical);
  } else {
    handlers.onRejected?.(text);
  }
}

/** The hold further back hint, which `useHoldFurtherBackHint` owns. */
interface HoldFurtherBackHint {
  showing: boolean;
  /** Start, or restart, the wait before the hint. */
  arm: () => void;
  /** A barcode read: take the hint down and start the wait again. */
  withdraw: () => void;
  /** The scanner closed: no hint, and no wait left to show one. */
  clear: () => void;
}

/** One frame from the reader: a read, a decode error, or both. */
function handleFrame(
  result: Result | undefined,
  err: Exception | undefined,
  facingMember: boolean,
  handlers: ScanHandlers,
  withdrawHint: () => void,
) {
  if (result && facingMember) withdrawHint();
  if (result) reportRead(result.getText(), handlers);
  // NotFoundException fires continuously while no barcode is in frame.
  if (err && !(err instanceof NotFoundException)) {
    console.warn("Scanner error:", err);
  }
}

/** What one opening of the camera reports back to the component. */
interface CameraSession {
  /** Whether the scanner has closed since this opening began. */
  isClosed: () => boolean;
  opened: (stream: MediaStream) => void;
  read: (result: Result | undefined, err: Exception | undefined) => void;
  started: () => void;
  failed: (err: unknown) => void;
}

/** Open the camera and start decoding from it, unless the scanner closes first. */
async function openCamera(
  video: HTMLVideoElement,
  reader: BrowserMultiFormatReader,
  session: CameraSession,
) {
  try {
    const stream =
      await navigator.mediaDevices.getUserMedia(CAMERA_CONSTRAINTS);
    if (session.isClosed()) {
      stopTracks(stream);
      return;
    }
    session.opened(stream);
    void reader.decodeFromStream(stream, video, (result, err) => {
      // The library can deliver a frame after stop(). A closed scanner reports
      // nothing from it: no book to the page, and no hint timer, which would
      // outlive the scanner and show its hint on the next camera, even a rear
      // one, which never clears it.
      if (!session.isClosed()) session.read(result, err);
    });
    session.started();
  } catch (err: unknown) {
    if (!session.isClosed()) session.failed(err);
  }
}

function useHoldFurtherBackHint(): HoldFurtherBackHint {
  const [showing, setShowing] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const arm = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(
      () => setShowing(true),
      HOLD_FURTHER_BACK_AFTER_MS,
    );
  }, []);
  const withdraw = useCallback(() => {
    setShowing(false);
    arm();
  }, [arm]);
  const clear = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    setShowing(false);
  }, []);

  return { showing, arm, withdraw, clear };
}

/** The camera's light: whether there is one, whether it is on, and the switch. */
function useTorch(streamRef: RefObject<MediaStream | null>) {
  const [available, setAvailable] = useState(false);
  const [on, setOn] = useState(false);

  const offer = useCallback(
    (track: MediaStreamTrack | undefined) => setAvailable(supportsTorch(track)),
    [],
  );
  const reset = useCallback(() => {
    setOn(false);
    setAvailable(false);
  }, []);

  async function toggle() {
    const [track] = streamRef.current?.getVideoTracks() ?? [];
    if (!track) return;
    const next = !on;
    try {
      // Not in the standard MediaTrackConstraintSet, but implemented on the
      // browsers that have a torch to offer.
      await track.applyConstraints({
        advanced: [{ torch: next } as MediaTrackConstraintSet],
      });
      setOn(next);
    } catch {
      // A camera that reported the capability and then refused it is not worth
      // an error message: the scan works without light.
      setAvailable(false);
    }
  }

  return { available, on, offer, reset, toggle };
}

/** The camera for as long as `active` holds, and everything it reports. */
function useCamera(active: boolean, handlers: ScanHandlers) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const readerRef = useRef<BrowserMultiFormatReader | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [mirrored, setMirrored] = useState(false);
  const hint = useHoldFurtherBackHint();
  const torch = useTorch(streamRef);

  // Held in a ref so the effect below does not list them as dependencies.
  // ScanPage passes inline callbacks, and depending on them would tear the
  // camera down and bring it back up on every render.
  const latest = useRef(handlers);
  latest.current = handlers;

  // Every one is stable, and must be: a change of identity in any of them
  // would rerun the effect below and restart the camera.
  const { arm: armHint, withdraw: withdrawHint, clear: clearHint } = hint;
  const { offer: offerTorch, reset: resetTorch } = torch;
  const stop = useCallback(() => {
    readerRef.current?.reset();
    readerRef.current = null;
    // reset() releases the track it opened, but the stream here was opened by
    // this component, so it has to be stopped explicitly or the phone's camera
    // indicator stays lit after leaving the page.
    stopTracks(streamRef.current);
    streamRef.current = null;
    clearHint();
    setScanning(false);
    resetTorch();
    setMirrored(false);
  }, [clearHint, resetTorch]);

  useEffect(() => {
    if (!active) {
      stop();
      return;
    }

    let cancelled = false;
    let facingMember = false;
    const reader = new BrowserMultiFormatReader(
      bookReaderHints(),
      SCAN_INTERVAL_MS,
    );
    readerRef.current = reader;
    setError(null);

    const video = videoRef.current;
    if (video) {
      void openCamera(video, reader, {
        isClosed: () => cancelled,
        opened(stream) {
          streamRef.current = stream;
          const [track] = stream.getVideoTracks();
          offerTorch(track);
          // A camera that reports itself rear facing gets no hint timer and
          // no mirrored preview.
          facingMember = !facesAway(track);
          if (facingMember) {
            setMirrored(true);
            armHint();
          }
        },
        read: (result, err) =>
          handleFrame(result, err, facingMember, latest.current, withdrawHint),
        started: () => setScanning(true),
        failed(err) {
          // The camera also needs a secure context: on a plain-HTTP LAN
          // address this fails no matter what the member taps.
          setError(
            err instanceof Error ? err.message : t("scan.cameraUnavailable"),
          );
          setScanning(false);
        },
      });
    }

    return () => {
      cancelled = true;
      stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, stop, armHint, withdrawHint, offerTorch]);

  return { videoRef, error, scanning, mirrored, hint, torch };
}

/** The guide box and the line under it, shown while the camera reads. */
function Viewfinder({ holdFurtherBack }: { holdFurtherBack: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
      <div className="w-64 h-32 border-2 border-accent-400 rounded-lg relative">
        <div className="absolute top-0 left-0 w-5 h-5 border-t-4 border-l-4 border-accent-400 rounded-tl" />
        <div className="absolute top-0 right-0 w-5 h-5 border-t-4 border-r-4 border-accent-400 rounded-tr" />
        <div className="absolute bottom-0 left-0 w-5 h-5 border-b-4 border-l-4 border-accent-400 rounded-bl" />
        <div className="absolute bottom-0 right-0 w-5 h-5 border-b-4 border-r-4 border-accent-400 rounded-br" />
        <div className="absolute inset-x-0 top-1/2 h-px bg-accent-400 opacity-60 animate-pulse" />
      </div>
      <p
        aria-live="polite"
        className="absolute bottom-4 inset-x-0 px-4 text-center text-white text-sm font-medium"
      >
        {holdFurtherBack ? t("scan.holdFurtherBack") : t("scan.pointAtBarcode")}
      </p>
    </div>
  );
}

/** What is drawn over the picture while the camera reads: the guide and the light. */
function ScanningOverlay({
  hint,
  torch,
}: {
  hint: HoldFurtherBackHint;
  torch: ReturnType<typeof useTorch>;
}) {
  const { t } = useTranslation();
  return (
    <>
      <Viewfinder holdFurtherBack={hint.showing} />
      {torch.available && (
        <button
          type="button"
          onClick={() => void torch.toggle()}
          aria-pressed={torch.on}
          className="absolute top-3 right-3 w-10 h-10 rounded-full bg-black/50 text-white text-lg backdrop-blur-sm hover:bg-black/70 transition-colors"
        >
          <Icon name="lamp" className="w-4 h-4" filled={torch.on} />
          <span className="sr-only">{t("scan.torch")}</span>
        </button>
      )}
    </>
  );
}

/** The camera viewfinder. Used only by ScanPage. */
export default function BarcodeScanner({
  onDetected,
  active,
  onRejected,
}: BarcodeScannerProps) {
  const { t } = useTranslation();
  // Destructured rather than read off one object: the React compiler takes
  // every field of an object that holds a ref for a ref, and `react/refs` then
  // reports reading `mirrored` during render.
  const { videoRef, mirrored, scanning, error, hint, torch } = useCamera(
    active,
    { onDetected, onRejected },
  );

  return (
    <div className="relative w-full aspect-[4/3] bg-black rounded-xl overflow-hidden">
      {/* object-contain, not object-cover. Cover crops the frame, so the guide
          box below sits over a picture that is narrower than what is actually
          being decoded, and a barcode lined up inside the box can be outside
          the part of the image the reader ever sees. The mirror is for display
          only, the way a member expects to see a camera that faces them: the
          decoder reads the stream, never this element's transform. */}
      <video
        ref={videoRef}
        className={`w-full h-full object-contain${mirrored ? " -scale-x-100" : ""}`}
        muted
        playsInline
      />

      {scanning && <ScanningOverlay hint={hint} torch={torch} />}

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
