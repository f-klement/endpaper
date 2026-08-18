import type { ChangeEvent } from "react";

import { useTranslation } from "../../../i18n";

interface BackgroundUploaderProps {
  hasBackground: boolean;
  isUploading: boolean;
  onUpload: (file: File) => void;
}

/**
 * Admin-only control for the login page's background image.
 *
 * The input is visually hidden inside its label rather than removed from the
 * tree, so it stays reachable by keyboard and by assistive tech.
 */
export default function BackgroundUploader({
  hasBackground,
  isUploading,
  onUpload,
}: BackgroundUploaderProps) {
  const { t } = useTranslation();

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onUpload(file);
    // Reset so choosing the same file twice fires change again.
    event.target.value = "";
  }

  return (
    <div className="mt-4 text-center">
      <label className="inline-block cursor-pointer text-xs text-white/70 hover:text-white bg-black/20 hover:bg-black/30 px-3 py-1.5 rounded-lg transition-colors">
        {isUploading
          ? t("login.uploading")
          : hasBackground
            ? t("login.changeBackground")
            : t("login.setBackground")}
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="sr-only"
          disabled={isUploading}
          onChange={handleChange}
        />
      </label>
    </div>
  );
}
