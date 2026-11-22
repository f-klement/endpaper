import type {
  ClassificationOut,
  SuggestingVocabularyOut,
} from "../../../api/generated/model";
import { ErrorState } from "../../../components";
import { useTranslation } from "../../../i18n";
import { headingText } from "../../../lib/classificationLabels";

interface HeadingFieldProps {
  /** The vocabularies with a loaded copy. Empty draws nothing. */
  vocabularies: SuggestingVocabularyOut[];
  scheme: string;
  onChooseScheme: (scheme: string) => void;
  typed: string;
  onType: (text: string) => void;
  suggestions: ClassificationOut[];
  onPick: (heading: ClassificationOut) => void;
  isPicking: boolean;
  error: unknown;
}

/**
 * Add a heading to the book from a local vocabulary copy, offered as the
 * cataloguer types.
 *
 * **Draws nothing while no vocabulary is offered**: the setting is off, the
 * library is a household, or no copy is loaded. A field that can offer
 * nothing would read as a vocabulary with no match for anything.
 *
 * **Each suggestion is a button and nothing typed is ever saved**, so the
 * field writes only a heading the copy holds; the server refuses nothing on
 * save, so this is the only place the filter lives.
 */
export default function HeadingField({
  vocabularies,
  scheme,
  onChooseScheme,
  typed,
  onType,
  suggestions,
  onPick,
  isPicking,
  error,
}: HeadingFieldProps) {
  const { t } = useTranslation();
  if (vocabularies.length === 0) return null;

  return (
    <div className="mt-4">
      <h3 className="text-sm font-medium text-paper-800 dark:text-paper-200">
        {t("headingField.section")}
      </h3>
      <div className="flex gap-2 mt-2">
        {/* A choice only where there is one to make: with one copy loaded the
            select would offer a single option. */}
        {vocabularies.length > 1 && (
          <select
            value={scheme}
            onChange={(event) => onChooseScheme(event.target.value)}
            aria-label={t("headingField.vocabulary")}
            className="px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
          >
            {vocabularies.map((vocabulary) => (
              <option key={vocabulary.scheme} value={vocabulary.scheme}>
                {vocabulary.name}
              </option>
            ))}
          </select>
        )}
        <input
          type="search"
          value={typed}
          onChange={(event) => onType(event.target.value)}
          placeholder={t("headingField.placeholder")}
          aria-label={t("headingField.label")}
          className="flex-1 px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
        />
      </div>
      {error != null && <ErrorState error={error} />}
      {suggestions.length > 0 && (
        <ul className="mt-2 space-y-1">
          {suggestions.map((heading) => (
            <li key={`${heading.scheme}-${heading.number}`}>
              <button
                type="button"
                disabled={isPicking}
                onClick={() => onPick(heading)}
                className="w-full text-left text-sm px-3 py-1.5 rounded-lg hover:bg-paper-100 disabled:opacity-50 dark:hover:bg-paper-800"
              >
                <span className="font-medium">{headingText(heading)}</span>{" "}
                {/* An LCSH heading is its own number and carries no label,
                    so the number would only repeat the heading. */}
                {heading.label != null && (
                  <span className="text-xs text-paper-600 dark:text-paper-400">
                    {heading.number}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
