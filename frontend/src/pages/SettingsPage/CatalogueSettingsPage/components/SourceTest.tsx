import type { Disposition } from "../../../../api/generated/model";
import { Button, ErrorState } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import type { MessageKey } from "../../../../i18n/en";
import { useSourceTest } from "../hooks";

/** The sentence for each disposition, one key per member so `de.ts` cannot miss one. */
export const DISPOSITION_TEXT: Record<Disposition, MessageKey> = {
  answered: "providers.disposition.answered",
  answered_nothing: "providers.disposition.answered_nothing",
  refused: "providers.disposition.refused",
  unreachable: "providers.disposition.unreachable",
};

/**
 * The **test this source** action for one catalogue, and its answer.
 *
 * **What is shown is how the catalogue answered, never what it said**: the
 * server returns a disposition and the ISBN asked, and nothing else, so this
 * cannot become a way to read whatever an address serves.
 */
export default function SourceTest({
  source,
  name,
}: {
  source: string;
  name: string;
}) {
  const { t } = useTranslation();
  const test = useSourceTest(source);
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <Button
        variant="secondary"
        size="sm"
        disabled={test.isRunning}
        aria-label={t("providers.testLabel", { name })}
        onClick={test.run}
      >
        {test.isRunning ? t("providers.testing") : t("providers.test")}
      </Button>
      {test.result && (
        <p role="status" className="text-xs text-paper-600 dark:text-paper-400">
          {t(DISPOSITION_TEXT[test.result.disposition], {
            isbn: test.result.isbn,
          })}
        </p>
      )}
      {test.error != null && (
        <ErrorState error={test.error} fallback={t("providers.testFailed")} />
      )}
    </div>
  );
}
