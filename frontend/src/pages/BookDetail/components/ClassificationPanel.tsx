import { Link } from "react-router-dom";

import type { ClassificationOut } from "../../../api/generated/model";
import { useTranslation } from "../../../i18n";
import { SCHEME_LABEL } from "../../../lib/classificationLabels";

interface ClassificationPanelProps {
  classifications: ClassificationOut[];
}

/**
 * What published schemes say this book is about.
 *
 * **Beside the tags and deliberately not among them.** A tag is this library's
 * own word, invented or curated here. A row here is somebody at a national
 * library placing the book in a published schedule, and only the second means
 * anything to another institution. Showing them as one list of chips would
 * make a curated opinion look like a standard, which is the confusion the
 * store was built to avoid: see `docs/legend.md`.
 *
 * So every chip names its scheme. The scheme is not decoration: `004` is
 * computing in Dewey and is not a Library of Congress call number at all, so a
 * number shown without its scheme cannot be read.
 */

/**
 * The filter link one heading leads to.
 *
 * `URLSearchParams` rather than a template, because an LCSH number is the
 * authorised heading string: it carries spaces, commas and the occasional
 * colon, and hand-built query strings are where those get lost.
 */
export function headingHref(classification: ClassificationOut): string {
  const params = new URLSearchParams();
  params.set(
    "classification",
    `${classification.scheme}:${classification.number}`,
  );
  return `/?${params.toString()}`;
}

export default function ClassificationPanel({
  classifications,
}: ClassificationPanelProps) {
  const { t } = useTranslation();

  return (
    <div className="mt-4">
      <h3 className="text-sm font-medium text-paper-800 dark:text-paper-200">
        {t("classification.section")}
      </h3>

      {classifications.length === 0 ? (
        <p className="text-xs text-paper-600 mt-1 dark:text-paper-400">
          {t("classification.noneOnBook")}
        </p>
      ) : (
        <ul className="flex flex-wrap gap-1.5 mt-2">
          {classifications.map((classification) => (
            <li key={`${classification.scheme}-${classification.number}`}>
              <Link
                to={headingHref(classification)}
                title={t("classification.filterBy", {
                  heading: classification.number,
                })}
                className="inline-flex items-baseline gap-1.5 text-xs px-2 py-1 rounded border border-paper-200 bg-paper-0 text-paper-700 transition-colors hover:border-accent-300 hover:text-accent-700 dark:border-paper-800 dark:bg-paper-900 dark:text-paper-300 dark:hover:border-accent-700 dark:hover:text-accent-400"
              >
                {/* The scheme, in the muted tier, because it qualifies the
                    number rather than competing with it. */}
                <span className="text-paper-600 dark:text-paper-400">
                  {t(SCHEME_LABEL[classification.scheme])}
                </span>
                <span className="font-medium">{classification.number}</span>
                {/* A caption where the record carried one, which for Dewey is
                    never: MARC 082 holds the notation and the printed schedule
                    holds the words. Rendered as "a number that may or may not
                    be followed by words, never a template with a hole in it". */}
                {classification.label && (
                  <span className="text-paper-600 dark:text-paper-400">
                    {classification.label}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
