import { useEffect, useRef, type ReactNode } from "react";

import { useTranslation } from "../i18n";

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
}

/**
 * A dialog, hand-rolled on `<dialog>`.
 *
 * The native element is used rather than a positioned div because it brings the
 * three things a hand-rolled overlay always gets wrong: focus is trapped inside
 * it, the rest of the page is inert, and Escape closes it. None of that is
 * behaviour worth reimplementing.
 *
 * `showModal()` rather than the `open` attribute: only the former gives the
 * top layer and the backdrop, and an element opened with `open` is an ordinary
 * inline box that the page can scroll past.
 */
export default function Modal({ title, onClose, children }: ModalProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    // jsdom implements the element but not showModal, so this stays optional
    // rather than assuming the method exists.
    dialog?.showModal?.();
    return () => dialog?.close?.();
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby="modal-title"
      // The native close fires on Escape and on the backdrop, so the parent
      // hears about both without a keydown listener of its own.
      onClose={onClose}
      onClick={(event) => {
        // A click on the dialog's own box lands on the backdrop, because the
        // content sits in a child. Clicking outside the content closes.
        if (event.target === ref.current) onClose();
      }}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl border border-gray-200 p-0 backdrop:bg-black/40 dark:border-gray-700"
    >
      <div className="p-5">
        <div className="flex items-start justify-between gap-4 mb-3">
          <h2
            id="modal-title"
            className="text-base font-semibold text-gray-900 dark:text-gray-100"
          >
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("common.close")}
            className="shrink-0 text-gray-400 hover:text-gray-700 text-lg leading-none dark:text-gray-500 dark:hover:text-gray-200"
          >
            ✕
          </button>
        </div>

        <div className="text-sm text-gray-600 leading-relaxed space-y-3 dark:text-gray-300">
          {children}
        </div>
      </div>
    </dialog>
  );
}
