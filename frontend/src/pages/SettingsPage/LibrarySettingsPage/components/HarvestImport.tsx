import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../../../api/mutator";
import {
  HarvestFormat,
  type HarvestPreviewOut,
  type HarvestResultOut,
  type MarcPreviewRow,
  type ResumableHarvestOut,
} from "../../../../api/generated/model";
import { Button } from "../../../../components";
import { type MessageKey, useTranslation } from "../../../../i18n";
import { shortMonthDate } from "../../../../lib/date";
import {
  ConfirmRow,
  ImportAlert,
  ImportError,
  RecordRows,
  ResultPanel,
  TitleList,
} from "./ImportChrome";
import { wouldBeAddedBy } from "./MarcImport";

interface HarvestImportProps {
  isPreviewing: boolean;
  isImporting: boolean;
  /** What a run over the repository read. Shown before anything is written. */
  preview: HarvestPreviewOut | null;
  result: HarvestResultOut | null;
  /** The last run, while it was cut short and may be carried on from. */
  resumable: ResumableHarvestOut | null;
  /** Whatever the read was refused with. */
  readError: unknown;
  /** Whatever the harvest was refused with. */
  harvestError: unknown;
  /** Read the repository, or only the typed set of it. */
  onRead: (setSpec: string) => void;
  /** Read on from where `resumable` stopped. */
  onCarryOn: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Running the harvester: the MARC card's preview then apply, over the
 * repository the section above stores.
 *
 * Dumb: it owns the set field and draws the rest from `./ImportChrome`. The
 * mutations live in the page's `useHarvestImport`.
 *
 * **The result links to the Books this run added**, at the Home page's
 * `harvest` key, and to no others: `books.harvest_id` keeps the first run that
 * created a Book, so a Book a later run matched lists under that first run. No
 * count stands beside the link, since a Book trashed or merged away since has
 * left the list and `created` would no longer be its size.
 */
export default function HarvestImport({
  isPreviewing,
  isImporting,
  preview,
  result,
  resumable,
  readError,
  harvestError,
  onRead,
  onCarryOn,
  onConfirm,
  onCancel,
}: HarvestImportProps) {
  const { t } = useTranslation();
  const [setSpec, setSetSpec] = useState("");

  return (
    <div className="space-y-3">
      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("harvestRun.explain")}
      </p>

      {!preview && resumable && (
        <CarryOn run={resumable} busy={isPreviewing} onCarryOn={onCarryOn} />
      )}

      {!preview && (
        <SetField
          value={setSpec}
          busy={isPreviewing}
          onChange={setSetSpec}
          onRead={() => onRead(setSpec)}
        />
      )}

      {preview && (
        <PreviewStep
          preview={preview}
          isImporting={isImporting}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      )}

      <HarvestRefusal readError={readError} harvestError={harvestError} />

      {result && <HarvestResult result={result} />}
    </div>
  );
}

/**
 * The offer to carry on from a run cut short, beside the read from the start
 * rather than instead of it: an admin whose repository forgot where the run
 * stopped starts over, and that is the other button.
 */
function CarryOn({
  run,
  busy,
  onCarryOn,
}: {
  run: ResumableHarvestOut;
  busy: boolean;
  onCarryOn: () => void;
}) {
  const { t, locale } = useTranslation();
  return (
    <div className="space-y-1.5 text-sm text-paper-700 bg-paper-50 border border-paper-200 rounded-xl p-3 dark:text-paper-200 dark:bg-paper-900 dark:border-paper-700">
      <p>
        {t("harvestRun.resumable", {
          date: shortMonthDate(run.started_at, locale),
          count: run.records_seen,
        })}
      </p>
      {run.set_spec && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("harvestRun.resumableSet", { set: run.set_spec })}
        </p>
      )}
      <Button size="sm" disabled={busy} onClick={onCarryOn}>
        {busy ? t("harvestRun.reading") : t("harvestRun.carryOn")}
      </Button>
    </div>
  );
}

/** The optional set, and the button that reads the repository. */
function SetField({
  value,
  busy,
  onChange,
  onRead,
}: {
  value: string;
  busy: boolean;
  onChange: (value: string) => void;
  onRead: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-1.5">
      <label
        htmlFor="oai-harvest-set-spec"
        className="block text-xs font-medium text-paper-600 dark:text-paper-300"
      >
        {t("harvestRun.setLabel")}
      </label>
      <input
        id="oai-harvest-set-spec"
        type="text"
        autoComplete="off"
        value={value}
        // `HARVEST_SET_SPEC_MAX` in `backend/models.py`, the width
        // of `harvests.set_spec`: a longer set is refused there with a 422.
        maxLength={255}
        disabled={busy}
        onChange={(event) => onChange(event.target.value)}
        className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
      />
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("harvestRun.setHint")}
      </p>
      <Button size="sm" disabled={busy} onClick={onRead}>
        {busy ? t("harvestRun.reading") : t("harvestRun.read")}
      </Button>
    </div>
  );
}

/** The counts and the confirm row, once the repository is read. */
function PreviewStep({
  preview,
  isImporting,
  onConfirm,
  onCancel,
}: {
  preview: HarvestPreviewOut;
  isImporting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  // A harvest always adds what it does not hold: there is no switch to turn
  // that off, unlike the MARC card's, so the confirm counts both.
  const toHarvest = wouldBeAddedBy(preview) + preview.already_held;

  return (
    <>
      <PreviewCounts preview={preview} />
      <ConfirmRow
        isImporting={isImporting}
        withheld={toHarvest === 0}
        confirmLabel={t("harvestRun.confirm", { count: toHarvest })}
        importingLabel={t("harvestRun.importing")}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    </>
  );
}

/** What the run read, before anything is written. */
function PreviewCounts({ preview }: { preview: HarvestPreviewOut }) {
  const { t } = useTranslation();
  const rows = preview.rows ?? [];
  const counts: [MessageKey, number][] = [
    ["harvestRun.wouldAdd", wouldBeAddedBy(preview)],
    ["marc.alreadyHeld", preview.already_held],
    ["marc.blocked", preview.blocked ?? 0],
    ["marc.inTrash", preview.in_trash ?? 0],
    ["marc.ambiguous", preview.ambiguous ?? 0],
    ["marc.skipped", preview.skipped],
    ["harvestRun.deleted", preview.deleted],
  ];

  return (
    <div className="text-sm text-paper-700 bg-paper-50 border border-paper-200 rounded-xl p-3 space-y-1 dark:text-paper-200 dark:bg-paper-900 dark:border-paper-700">
      {preview.repository_name && (
        <p className="font-medium">
          {t("harvestRun.repository", { name: preview.repository_name })}
        </p>
      )}
      <p>
        {t("harvestRun.previewTitle", {
          seen: preview.records_seen,
          readable: preview.readable,
        })}
      </p>
      <FormatRead format={preview.metadata_format} />
      {counts
        .filter(([, count]) => count > 0)
        .map(([key, count]) => (
          <p key={key} className="text-xs text-paper-600 dark:text-paper-400">
            {t(key, { count })}
          </p>
        ))}
      {rows.length > 0 && preview.metadata_format === HarvestFormat.marcxml && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("harvestRun.headingsPreview", { count: headingsIn(rows) })}
        </p>
      )}
      <RecordRows rows={rows} />
      {preview.truncated && (
        <Caution message={t("harvestRun.truncatedPreview")} />
      )}
    </div>
  );
}

/**
 * The headings the listed records carry. Only the listed ones: the preview
 * lists the first records the server caps it at, and counts no more.
 */
function headingsIn(rows: MarcPreviewRow[]): number {
  return rows.reduce((sum, row) => sum + (row.classifications ?? []).length, 0);
}

function HarvestResult({ result }: { result: HarvestResultOut }) {
  const { t } = useTranslation();
  return (
    <ResultPanel>
      <p>
        {t("marc.result", {
          rowsRead: result.rows_read,
          matched: result.matched,
          created: result.created,
        })}
      </p>
      {result.created > 0 && (
        <p className="text-xs">
          <Link
            to={`/?harvest=${result.harvest_id}`}
            className="text-accent-700 underline dark:text-accent-300"
          >
            {t("harvestRun.addedBooks")}
          </Link>
        </p>
      )}
      <FormatRead format={result.metadata_format} />
      {result.skipped > 0 && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("marc.resultSkipped", { count: result.skipped })}
        </p>
      )}
      {result.deleted > 0 && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("harvestRun.deleted", { count: result.deleted })}
        </p>
      )}
      {result.headings_pending > 0 && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("harvestRun.resultHeadings", {
            count: result.headings_pending,
          })}
        </p>
      )}
      {result.truncated && (
        <Caution message={t("harvestRun.truncatedResult")} />
      )}
      <TitleList
        heading={t("marc.resultInTrash", { count: result.in_trash ?? 0 })}
        titles={result.in_trash_titles}
      />
      <TitleList
        heading={t("marc.resultAmbiguous", { count: result.ambiguous ?? 0 })}
        titles={result.ambiguous_titles}
      />
    </ResultPanel>
  );
}

/**
 * Says a run read Dublin Core, a fallback the server takes only where the
 * repository offers no MARCXML it can ask for, and which carries less. A
 * MARCXML run says nothing: it is the ordinary case and asks nothing of the
 * admin.
 */
function FormatRead({ format }: { format: HarvestFormat }) {
  const { t } = useTranslation();
  if (format !== HarvestFormat.dublin_core) return null;
  return <Caution message={t("harvestRun.readDublinCore")} />;
}

/** What an admin should weigh before trusting the counts: a run cut short, or one read in Dublin Core. */
function Caution({ message }: { message: string }) {
  return (
    <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 dark:text-amber-300 dark:bg-amber-950 dark:border-amber-900">
      {message}
    </p>
  );
}

/**
 * The refusals the harvest routes give for a reason of their own, in words.
 * Anything else goes through the shared reader, as every other card's refusal
 * does: a 403, a rate limit, and a 502, whose detail the server writes for the
 * admin and which names the fault, the set or the format as often as the
 * address.
 *
 * **A 409 is worded by its `code`**, which `backend/routers/imports.py` puts on
 * the refusals of the harvester's own: another harvest running, at either
 * step, a run no longer to be carried on from, at either step, and a stored
 * repository other than the address this tab held when it read, at the apply.
 * A 409 with no code is the apply's lost race with another change to the same
 * books.
 */
function HarvestRefusal({
  readError,
  harvestError,
}: {
  readError: unknown;
  harvestError: unknown;
}) {
  const { t } = useTranslation();
  const error = readError ?? harvestError;
  const key = error instanceof ApiError ? refusalKey(error) : undefined;
  if (key === undefined) return <ImportError error={error} />;
  return <ImportAlert>{t(key)}</ImportAlert>;
}

const REFUSAL_BY_CODE: Readonly<Record<string, MessageKey>> = {
  harvest_running: "harvestRun.running",
  not_resumable: "harvestRun.notResumable",
  repository_changed: "harvestRun.repositoryChanged",
};

function refusalKey(error: ApiError): MessageKey | undefined {
  // The route does not exist while the switch is off or no address is stored.
  if (error.status === 404) return "harvestRun.off";
  if (error.status !== 409) return undefined;
  // `Object.hasOwn`, because a plain object answers "toString" from its
  // prototype rather than undefined.
  const code = error.code ?? "";
  return Object.hasOwn(REFUSAL_BY_CODE, code)
    ? REFUSAL_BY_CODE[code]
    : "harvestRun.lostRace";
}
