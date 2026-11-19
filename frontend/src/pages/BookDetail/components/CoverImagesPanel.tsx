import { useRef, type ChangeEvent } from "react";

import type { CoverImageOut } from "../../../api/generated/model";
import { Button, ErrorState } from "../../../components";
import { useTranslation } from "../../../i18n";
import { CoverImage } from "../../components";

interface CoverImagesPanelProps {
  title: string;
  images: CoverImageOut[];
  isUploading: boolean;
  /** Ids of the images being removed or shelved right now. */
  busy: ReadonlySet<number>;
  listError: unknown;
  error: unknown;
  onUpload: (file: File) => void;
  onRemove: (image: CoverImageOut) => void;
  onShelve: (image: CoverImageOut) => void;
}

/** Each image, with its two actions; nothing while there is none. */
function ImageList({
  title,
  images,
  busy,
  onRemove,
  onShelve,
}: Pick<
  CoverImagesPanelProps,
  "title" | "images" | "busy" | "onRemove" | "onShelve"
>) {
  const { t } = useTranslation();
  if (images.length === 0) return null;
  return (
    <ul className="grid grid-cols-3 sm:grid-cols-4 gap-2 mb-2">
      {images.map((image, index) => {
        const number = index + 1;
        return (
          <li key={image.id} className="flex flex-col gap-1">
            <CoverImage
              src={image.url}
              alt={t("coverImages.alt", { number, title })}
              loading="lazy"
              className="w-full aspect-[2/3] object-cover rounded bg-paper-100 dark:bg-paper-800"
            />
            <button
              type="button"
              onClick={() => onShelve(image)}
              disabled={busy.has(image.id)}
              // The visible word is the same on every image and the
              // accessible name is not, so a screen reader can tell them
              // apart.
              aria-label={t("coverImages.shelveFor", { number })}
              className="text-xs font-medium text-accent-700 hover:text-accent-900 disabled:opacity-50 dark:text-accent-300 dark:hover:text-accent-200"
            >
              {t("coverImages.shelve")}
            </button>
            <button
              type="button"
              onClick={() => onRemove(image)}
              disabled={busy.has(image.id)}
              aria-label={t("coverImages.removeFor", { number })}
              className="text-xs font-medium text-paper-600 hover:text-danger-500 disabled:opacity-50 dark:text-paper-300 dark:hover:text-danger-300"
            >
              {t("coverImages.remove")}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** The add button and the hidden file input it opens. */
function ImageAdder({
  isUploading,
  onUpload,
}: Pick<CoverImagesPanelProps, "isUploading" | "onUpload">) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);

  function handlePick(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onUpload(file);
    event.target.value = "";
  }

  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => input.current?.click()}
        disabled={isUploading}
      >
        {isUploading ? t("coverImages.adding") : t("coverImages.add")}
      </Button>
      <input
        ref={input}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="hidden"
        aria-label={t("coverImages.add")}
        onChange={handlePick}
      />
    </>
  );
}

/** One failure under the panel, or nothing. */
function PanelError({ error, fallback }: { error: unknown; fallback: string }) {
  if (error == null) return null;
  return (
    <div className="mt-2">
      <ErrorState error={error} fallback={fallback} />
    </div>
  );
}

/**
 * Images of this copy kept beside the shelf cover: the back, the spine, a
 * dust jacket variant, as evidence of which edition this is.
 *
 * **In the copy's group**, beside its files, because an image is a fact about
 * this object: the hardback's jacket is not the paperback's. Choosing one for
 * the shelf swaps it with the cover shown now, so nothing kept is lost.
 */
export default function CoverImagesPanel({
  title,
  images,
  isUploading,
  busy,
  listError,
  error,
  onUpload,
  onRemove,
  onShelve,
}: CoverImagesPanelProps) {
  const { t } = useTranslation();
  return (
    <div>
      <p className="text-sm font-semibold text-paper-700 mb-1 dark:text-paper-200">
        {t("coverImages.title")}
      </p>
      <p className="text-xs text-paper-600 mb-2 dark:text-paper-300">
        {t("coverImages.hint")}
      </p>
      <ImageList
        title={title}
        images={images}
        busy={busy}
        onRemove={onRemove}
        onShelve={onShelve}
      />
      <ImageAdder isUploading={isUploading} onUpload={onUpload} />
      <PanelError error={listError} fallback={t("coverImages.loadFailed")} />
      <PanelError error={error} fallback={t("coverImages.failed")} />
    </div>
  );
}
