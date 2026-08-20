import { useState } from "react";

import { Icon } from "../../components";

interface CoverImageProps {
  /** The cover URL, or null when the book has none. */
  src: string | null | undefined;
  /** The book's title, or "" where the cover is decorative beside its title. */
  alt: string;
  /**
   * Classes for the box. Applied to the image *and* to the placeholder, so the
   * two occupy exactly the same space. Give it the size, the rounding and the
   * background; a background behind a cover that loads is invisible anyway.
   */
  className?: string;
  /** Size of the placeholder glyph. Defaults to a third of the box. */
  iconClassName?: string;
  loading?: "eager" | "lazy";
}

/**
 * A book cover, or the placeholder that stands in for one.
 *
 * **A failed cover must not collapse the layout.** Every cover in this app used
 * to hide itself with `style.display = "none"` on error, which removes the
 * element from the flow: on the book page that left the header container at
 * zero height, and the absolutely positioned back button landed on top of the
 * title. The image is swapped for the same placeholder the no-cover branch
 * renders instead, so the box is the same size either way.
 *
 * A cover fails more often than it looks: Open Library 404s plenty of ISBNs,
 * and until this release the CSP blocked every German cover outright.
 *
 * The failure is remembered by URL rather than as a boolean, so a re-cover or a
 * metadata refresh gets a fresh attempt without an effect to reset it.
 */
export default function CoverImage({
  src,
  alt,
  className = "",
  iconClassName = "w-1/3 h-1/3 opacity-40",
  loading,
}: CoverImageProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  if (!src || src === failedSrc) {
    return (
      <div
        aria-hidden="true"
        className={`${className} flex items-center justify-center`}
      >
        <Icon name="book" className={iconClassName} />
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      loading={loading}
      onError={() => setFailedSrc(src)}
    />
  );
}
