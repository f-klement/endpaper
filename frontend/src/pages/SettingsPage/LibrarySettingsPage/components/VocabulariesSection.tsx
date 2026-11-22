import type {
  VocabularyLoadPhase,
  VocabularyOut,
  VocabularyProgressOut,
} from "../../../../api/generated/model";
import { Button, ErrorState } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import type { MessageKey } from "../../../../i18n/en";
import { numericDate } from "../../../../lib/date";
import { SettingsSection } from "../../../components";

const PHASE_LABEL: Record<VocabularyLoadPhase, MessageKey> = {
  queued: "vocabularies.phaseQueued",
  fetching: "vocabularies.phaseFetching",
  converting: "vocabularies.phaseConverting",
  loading: "vocabularies.phaseLoading",
  failed: "vocabularies.phaseFailed",
};

interface VocabulariesSectionProps {
  vocabularies: VocabularyOut[];
  isStarting: boolean;
  error: unknown;
  onDownload: (scheme: string) => void;
}

/**
 * The subject vocabularies a heading may come from, and the local copy of each.
 *
 * **Nothing waits on a copy.** Until one is loaded, and while one loads, a
 * lookup asks the source live, so the section offers the download and never
 * asks for it (owner, 2026-11-20). A refresh is by hand from here, which is why
 * each row shows both the day it was fetched and the day the source released it.
 *
 * **A licence that permits no copy leaves the button drawn but disabled**, with
 * the reason under it: the server refuses the start with a 409 in any case, and
 * a missing button would read as a vocabulary the app forgot.
 */
export default function VocabulariesSection({
  vocabularies,
  isStarting,
  error,
  onDownload,
}: VocabulariesSectionProps) {
  const { t } = useTranslation();
  return (
    <SettingsSection title={t("vocabularies.title")} icon="book">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("vocabularies.explain")}
      </p>
      {error != null && <ErrorState error={error} />}
      <ul className="space-y-3">
        {vocabularies.map((vocabulary) => (
          <VocabularyRow
            key={vocabulary.scheme}
            vocabulary={vocabulary}
            isStarting={isStarting}
            onDownload={onDownload}
          />
        ))}
      </ul>
    </SettingsSection>
  );
}

interface VocabularyRowProps {
  vocabulary: VocabularyOut;
  isStarting: boolean;
  onDownload: (scheme: string) => void;
}

/** One vocabulary: what is loaded of it, its licence, and its one control. */
function VocabularyRow({
  vocabulary,
  isStarting,
  onDownload,
}: VocabularyRowProps) {
  const { t } = useTranslation();
  const { progress } = vocabulary;
  const running = progress != null && progress.phase !== "failed";
  const loaded = vocabulary.fetched_at != null;
  return (
    <li className="text-sm space-y-1">
      <div className="flex items-center gap-2">
        <span className="flex-1 text-paper-700 dark:text-paper-200">
          {vocabulary.name}{" "}
          <span className="text-xs text-paper-600 dark:text-paper-400">
            {vocabulary.scheme}
          </span>
        </span>
        <Button
          size="sm"
          variant="secondary"
          disabled={!vocabulary.copyable || running || isStarting}
          onClick={() => onDownload(vocabulary.scheme)}
        >
          {t(loaded ? "vocabularies.refresh" : "vocabularies.download")}
        </Button>
      </div>
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {vocabulary.licence == null
          ? t("vocabularies.licenceNone")
          : t("vocabularies.licence", { licence: vocabulary.licence })}
      </p>
      {!vocabulary.copyable && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("vocabularies.notCopyable")}
        </p>
      )}
      <LoadState vocabulary={vocabulary} />
      {progress != null && <Progress progress={progress} />}
    </li>
  );
}

/**
 * What is loaded of a vocabulary: when, how many entries and which release;
 * or that nothing is, said only of one that may be copied.
 */
function LoadState({ vocabulary }: { vocabulary: VocabularyOut }) {
  const { t, locale } = useTranslation();
  if (vocabulary.fetched_at == null) {
    if (!vocabulary.copyable) return null;
    return (
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("vocabularies.notLoaded")}
      </p>
    );
  }
  return (
    <p className="text-xs text-paper-600 dark:text-paper-400">
      {t("vocabularies.fetched", {
        date: numericDate(vocabulary.fetched_at, locale),
        count: vocabulary.entries ?? 0,
      })}{" "}
      {vocabulary.released == null
        ? t("vocabularies.releasedUnknown")
        : t("vocabularies.released", {
            date: numericDate(vocabulary.released, locale),
          })}
    </p>
  );
}

/**
 * A load under way, as its phase and a bar, or the last load's failure.
 *
 * `done` and `total` count bytes while fetching and entries while loading, so
 * only the percentage is shown: a raw count would name no unit. **Where the
 * server knows no total the bar is indeterminate**, never 0%: converting
 * reports none, and it is the longest step for LCSH, so a bar standing at
 * nothing would read as a load that had stalled.
 */
function Progress({ progress }: { progress: VocabularyProgressOut }) {
  const { t } = useTranslation();
  if (progress.phase === "failed") {
    return (
      <ErrorState
        error={
          new Error(
            progress.error == null
              ? t("vocabularies.phaseFailed")
              : t("vocabularies.failedBecause", { error: progress.error }),
          )
        }
      />
    );
  }
  const percent =
    progress.total != null && progress.total > 0
      ? Math.min(100, Math.floor((progress.done * 100) / progress.total))
      : null;
  return (
    <div className="space-y-1">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {percent == null
          ? t(PHASE_LABEL[progress.phase])
          : t("vocabularies.phasePercent", {
              phase: t(PHASE_LABEL[progress.phase]),
              percent,
            })}
      </p>
      <div
        role="progressbar"
        aria-valuenow={percent ?? undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={t(PHASE_LABEL[progress.phase])}
        className="h-2 rounded-full bg-paper-100 overflow-hidden dark:bg-paper-800"
      >
        <div
          className={`h-full rounded-full bg-accent-400${percent == null ? " animate-pulse" : ""}`}
          style={{ width: `${percent ?? 100}%` }}
        />
      </div>
    </div>
  );
}
