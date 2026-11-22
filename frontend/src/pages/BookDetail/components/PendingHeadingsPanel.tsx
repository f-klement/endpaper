import type { ClassificationOut } from "../../../api/generated/model";
import { Button } from "../../../components";
import { useTranslation } from "../../../i18n";
import {
  KIND_LABEL,
  headingKind,
  headingText,
  schemeLabel,
} from "../../../lib/classificationLabels";

interface PendingHeadingsPanelProps {
  headings: ClassificationOut[];
  isBusy: boolean;
  onConfirm: () => void;
  /** Drop the whole set. The caller asks first. */
  onDiscard: () => void;
}

/**
 * The headings a harvest suggested for this book, waiting for an admin.
 *
 * **Under the classification and apart from it**, because these are not the
 * book's yet: a harvest confirms no record, so it suggests rather than writes
 * (`models.PendingHeading`). So the chips are plain text and not the filter
 * links the classification panel draws, since no book carries them to filter by.
 *
 * **One confirm and one discard for the whole set**, which is all the server
 * takes: the set is one record's, as a picker row is (ADR 0006). Draws nothing
 * when there are none, which is every book for anybody but an admin.
 */
export default function PendingHeadingsPanel({
  headings,
  isBusy,
  onConfirm,
  onDiscard,
}: PendingHeadingsPanelProps) {
  const { t } = useTranslation();
  if (headings.length === 0) return null;

  return (
    <div className="mt-4">
      <h3 className="text-sm font-medium text-paper-800 dark:text-paper-200">
        {t("pendingHeadings.section")}
      </h3>
      <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
        {t("pendingHeadings.explain")}
      </p>
      <ul className="flex flex-wrap gap-1.5 mt-2">
        {headings.map((heading) => (
          <li
            key={`${heading.scheme}-${heading.number}`}
            className="inline-flex items-baseline gap-1.5 text-xs px-2 py-1 rounded border border-dashed border-paper-300 text-paper-700 dark:border-paper-700 dark:text-paper-300"
          >
            <PendingChip heading={heading} />
          </li>
        ))}
      </ul>
      <div className="flex gap-2 mt-2">
        <Button size="sm" disabled={isBusy} onClick={onConfirm}>
          {headings.length === 1
            ? t("pendingHeadings.confirmOne")
            : t("pendingHeadings.confirm", { count: headings.length })}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={isBusy}
          onClick={onDiscard}
        >
          {t("pendingHeadings.discard")}
        </Button>
      </div>
    </div>
  );
}

/** One suggestion: its scheme, its words, and its kind where that is not a subject. */
function PendingChip({ heading }: { heading: ClassificationOut }) {
  const { t } = useTranslation();
  const kind = KIND_LABEL[headingKind(heading.kind)];
  return (
    <>
      <span className="text-paper-600 dark:text-paper-400">
        {schemeLabel(heading.scheme, t)}
      </span>
      <span className="font-medium">{headingText(heading)}</span>
      {kind && (
        <span className="text-paper-600 dark:text-paper-400">{t(kind)}</span>
      )}
    </>
  );
}
