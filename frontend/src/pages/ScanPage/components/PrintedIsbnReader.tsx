import { useEffect, useRef, useState, type RefObject } from "react";

import { Button, Icon } from "../../../components";
import { useTranslation, type MessageKey } from "../../../i18n";
import type { FrameRegion } from "../../../lib/textRecognition";
import {
  usePrintedIsbnReader,
  type PrintedReaderState,
  type UsePrintedIsbnReaderResult,
} from "../hooks";
import { CAMERA_CONSTRAINTS } from "./BarcodeScanner";

/**
 * The part of the frame that is read: the guide box drawn over the picture.
 *
 * Fractions of the frame, and the box is drawn with the same fractions over a
 * picture shown at its own aspect ratio (no `aspect-*` class on the frame), so
 * what is inside the box on screen is what the engine reads. A box rather than
 * the whole frame because a copyright page holds a dozen lines of numbers and
 * every line read costs time; a strip this shape holds one line comfortably.
 */
const GUIDE: FrameRegion = { left: 0.1, top: 0.35, width: 0.8, height: 0.3 };

/**
 * Stop every track of `stream`. Stopped explicitly, or the phone's camera
 * indicator stays lit after the reader closes.
 */
function release(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop());
}

/** Show the opened camera in the reader's picture, while it is on the page. */
function show(video: HTMLVideoElement | null, opened: MediaStream) {
  if (!video) return;
  video.srcObject = opened;
  // A refused autoplay leaves a still picture, which reads as well.
  Promise.resolve()
    .then(() => video.play())
    .catch(() => undefined);
}

/** What the member is told when the camera will not open. */
function refusal(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

/** The camera, opened on mount and released on unmount. */
function useCameraStream(videoRef: RefObject<HTMLVideoElement | null>) {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let closed = false;
    navigator.mediaDevices.getUserMedia(CAMERA_CONSTRAINTS).then(
      (opened) => {
        if (closed) {
          release(opened);
          return;
        }
        stream = opened;
        show(videoRef.current, opened);
        setStreaming(true);
      },
      (err: unknown) => {
        if (!closed) setError(refusal(err, t("scan.cameraUnavailable")));
      },
    );
    return () => {
      closed = true;
      release(stream);
    };
  }, [videoRef, t]);

  return { error, streaming };
}

/** The guide box and the line under it. */
function Guide() {
  const { t } = useTranslation();
  return (
    <div className="absolute inset-0 pointer-events-none">
      <div
        className="absolute border-2 border-accent-400 rounded-lg"
        style={{
          left: `${GUIDE.left * 100}%`,
          top: `${GUIDE.top * 100}%`,
          width: `${GUIDE.width * 100}%`,
          height: `${GUIDE.height * 100}%`,
        }}
      />
      <p className="absolute bottom-3 inset-x-0 px-4 text-center text-white text-sm font-medium">
        {t("scan.printed.aim")}
      </p>
    </div>
  );
}

/** One ISBN the read found, offered for the member to confirm. */
function Offer({
  isbn,
  onConfirm,
}: {
  isbn: string;
  onConfirm: (isbn: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg bg-paper-100 px-3 py-2 dark:bg-paper-800">
      <p className="text-sm text-paper-800 dark:text-paper-200">
        {t("scan.printed.found", { isbn })}
      </p>
      <Button size="sm" onClick={() => onConfirm(isbn)}>
        {t("scan.printed.lookUp")}
      </Button>
    </div>
  );
}

/** What the last read came to, and the way on from it. */
function ReadOutcome({
  state,
  onConfirm,
  onAgain,
}: {
  state: Extract<PrintedReaderState, { kind: "read" }>;
  onConfirm: (isbn: string) => void;
  onAgain: () => void;
}) {
  const { t } = useTranslation();
  const { isbns, misread } = state.found;
  return (
    <div className="space-y-2" role="status">
      {isbns.length > 0 ? (
        <>
          <p className="text-sm text-paper-600 dark:text-paper-400">
            {t("scan.printed.confirm")}
          </p>
          {isbns.map((isbn) => (
            <Offer key={isbn} isbn={isbn} onConfirm={onConfirm} />
          ))}
        </>
      ) : (
        <p className="text-sm text-amber-700 bg-amber-50 rounded-lg px-3 py-2 dark:text-amber-300 dark:bg-amber-950/40">
          {misread.length > 0
            ? t("scan.printed.misread", { code: misread[0]! })
            : t("scan.printed.nothing")}
        </p>
      )}
      <Button variant="secondary" size="sm" onClick={onAgain}>
        {t("scan.printed.again")}
      </Button>
    </div>
  );
}

/** What the read button says while the engine loads, waits and reads. */
const BUTTON_LABEL: Record<"loading" | "ready" | "reading", MessageKey> = {
  loading: "scan.printed.loading",
  ready: "scan.printed.read",
  reading: "scan.printed.reading",
};

/** The control under the picture, by where the reader is. */
function ReaderControls({
  reader,
  canRead,
  onRead,
  onConfirm,
}: {
  reader: UsePrintedIsbnReaderResult;
  canRead: boolean;
  onRead: () => void;
  onConfirm: (isbn: string) => void;
}) {
  const { t } = useTranslation();
  const { state } = reader;
  if (state.kind === "read") {
    return (
      <ReadOutcome state={state} onConfirm={onConfirm} onAgain={reader.again} />
    );
  }
  if (state.kind === "unavailable") {
    return (
      <p role="status" className="text-sm text-amber-700 dark:text-amber-300">
        {t("scan.printed.unavailable")}
      </p>
    );
  }
  return (
    <Button
      fullWidth
      disabled={!canRead || state.kind !== "ready"}
      onClick={onRead}
    >
      {t(BUTTON_LABEL[state.kind])}
    </Button>
  );
}

/**
 * The camera reading the printed ISBN, for a barcode that will not scan. Used
 * only by ScanPage.
 *
 * Nothing is looked up from here without the member's tap on the ISBN read:
 * `onConfirm` is the only way out to a lookup.
 */
export default function PrintedIsbnReader({
  onConfirm,
}: {
  onConfirm: (isbn: string) => void;
}) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const { error, streaming } = useCameraStream(videoRef);
  const reader = usePrintedIsbnReader();

  return (
    <>
      <div className="relative w-full bg-black rounded-xl overflow-hidden">
        <video
          ref={videoRef}
          className="block w-full h-auto"
          muted
          playsInline
        />
        {streaming && <Guide />}
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
      <div className="mt-3">
        <ReaderControls
          reader={reader}
          canRead={streaming}
          onRead={() => {
            if (videoRef.current) reader.read(videoRef.current, GUIDE);
          }}
          onConfirm={onConfirm}
        />
      </div>
    </>
  );
}
