import { useTranslation } from "../i18n";
import Icon from "./Icon";

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
  // A drawn star takes a width, not a font size. `text-sm`/`text-2xl` sized
  // the emoji this replaced and would leave every star the same size here.
  const starSize = size === "sm" ? "w-3.5 h-3.5" : "w-6 h-6";

  if (readOnly) {
    return (
      <span
        className="inline-flex items-center gap-0.5"
        aria-label={t("rating.label")}
      >
        {STARS.map((star) => (
          <Icon
            key={star}
            name="star"
            filled={star <= current}
            className={`${starSize} ${
              star <= current
                ? "text-amber-400"
                : "text-paper-300 dark:text-paper-700"
            }`}
          />
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
          className={`leading-none rounded transition-colors ${
            star <= current
              ? "text-amber-400 hover:text-amber-500"
              : "text-paper-300 hover:text-amber-300 dark:text-paper-700"
          }`}
        >
          {/* Outlined until it is earned, filled once it is. An unfilled star
              that is merely a paler solid reads as a rating you already gave. */}
          <Icon name="star" filled={star <= current} className={starSize} />
        </button>
      ))}
      {current > 0 && (
        <button
          type="button"
          onClick={() => onChange(null)}
          className="ml-2 text-xs text-paper-600 hover:text-paper-800 underline dark:text-paper-400 dark:hover:text-paper-300"
        >
          {t("rating.clear")}
        </button>
      )}
    </div>
  );
}
