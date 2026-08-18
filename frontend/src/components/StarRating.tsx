import { useTranslation } from "../i18n";

const STARS = [1, 2, 3, 4, 5] as const;

interface StarRatingProps {
  value: number | null | undefined;
  /** Omit to render a read-only display rather than a control. */
  onChange?: (rating: number | null) => void;
  size?: "sm" | "md";
}

/**
 * Five stars, personal to whoever is signed in.
 *
 * Read-only without `onChange`, which is how the grid uses it. Interactive it
 * is a radio group rather than five buttons: the values are mutually exclusive
 * and a screen reader should hear one control with five options, not five
 * unrelated ones.
 */
export default function StarRating({
  value,
  onChange,
  size = "md",
}: StarRatingProps) {
  const { t } = useTranslation();
  const current = value ?? 0;
  const readOnly = onChange === undefined;
  const starClass = size === "sm" ? "text-sm" : "text-2xl";

  if (readOnly) {
    return (
      <span
        className={`${starClass} tracking-tight`}
        aria-label={t("rating.label")}
      >
        {STARS.map((star) => (
          <span
            key={star}
            className={star <= current ? "text-amber-400" : "text-gray-200"}
          >
            ★
          </span>
        ))}
      </span>
    );
  }

  return (
    <div
      className="flex items-center gap-1"
      role="radiogroup"
      aria-label={t("rating.label")}
    >
      {STARS.map((star) => (
        <button
          key={star}
          type="button"
          role="radio"
          aria-checked={star === current}
          aria-label={t("rating.setTo", { stars: star })}
          // Clicking the current rating clears it. Without this there is no way
          // back from a rating except through a separate control, and a
          // mis-tapped star would be permanent.
          onClick={() => onChange(star === current ? null : star)}
          className={`${starClass} leading-none transition-colors ${
            star <= current
              ? "text-amber-400 hover:text-amber-500"
              : "text-gray-300 hover:text-amber-300"
          }`}
        >
          ★
        </button>
      ))}
      {current > 0 && (
        <button
          type="button"
          onClick={() => onChange(null)}
          className="ml-2 text-xs text-gray-400 hover:text-gray-600 underline dark:text-gray-500 dark:hover:text-gray-300"
        >
          {t("rating.clear")}
        </button>
      )}
    </div>
  );
}
