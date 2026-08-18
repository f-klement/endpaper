import { BrowserMultiFormatReader, NotFoundException } from "@zxing/library";
import { useEffect, useRef, useState } from "react";

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

interface BarcodeScannerProps {
  onDetected: (isbn: string) => void;
  active: boolean;
}

/** The camera viewfinder. Used only by ScanPage. */
export default function BarcodeScanner({
  onDetected,
  active,
}: BarcodeScannerProps) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const readerRef = useRef<BrowserMultiFormatReader | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    if (!active) {
      readerRef.current?.reset();
      setScanning(false);
      return;
    }

    const reader = new BrowserMultiFormatReader();
    readerRef.current = reader;
    setScanning(true);
    setError(null);

    reader
      .decodeFromVideoDevice(null, videoRef.current, (result, err) => {
        // Report the canonical form, not the raw scan, so an ISBN-10 barcode
        // and its ISBN-13 reprint resolve to the same book.
        const canonical = result && readIsbnBarcode(result.getText());
        if (canonical) {
          onDetected(canonical);
        }
        // NotFoundException fires continuously while no barcode is in frame.
        if (err && !(err instanceof NotFoundException)) {
          console.warn("Scanner error:", err);
        }
      })
      .catch((err: unknown) => {
        // The camera also needs a secure context: on a plain-HTTP LAN address
        // this fails no matter what the member taps.
        setError(
          err instanceof Error ? err.message : t("scan.cameraUnavailable"),
        );
        setScanning(false);
      });

    // Release the camera, or the phone's indicator light stays on after
    // navigating away.
    return () => {
      reader.reset();
    };
    // onDetected is omitted deliberately: ScanPage passes an inline callback,
    // and including it would restart the camera on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  return (
    <div className="relative w-full aspect-[4/3] bg-black rounded-xl overflow-hidden">
      <video
        ref={videoRef}
        className="w-full h-full object-cover"
        muted
        playsInline
      />

      {scanning && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-64 h-32 border-2 border-sky-400 rounded-lg relative">
            <div className="absolute top-0 left-0 w-5 h-5 border-t-4 border-l-4 border-sky-400 rounded-tl" />
            <div className="absolute top-0 right-0 w-5 h-5 border-t-4 border-r-4 border-sky-400 rounded-tr" />
            <div className="absolute bottom-0 left-0 w-5 h-5 border-b-4 border-l-4 border-sky-400 rounded-bl" />
            <div className="absolute bottom-0 right-0 w-5 h-5 border-b-4 border-r-4 border-sky-400 rounded-br" />
            <div className="absolute inset-x-0 top-1/2 h-px bg-sky-400 opacity-60 animate-pulse" />
          </div>
          <p className="absolute bottom-4 text-white text-sm font-medium">
            {t("scan.pointAtBarcode")}
          </p>
        </div>
      )}

      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/70">
          <div className="text-center text-white p-4">
            <p className="text-2xl mb-2">📷</p>
            <p className="font-medium">{t("scan.cameraUnavailable")}</p>
            <p className="text-sm text-gray-300 mt-1">{error}</p>
          </div>
        </div>
      )}
    </div>
  );
}
