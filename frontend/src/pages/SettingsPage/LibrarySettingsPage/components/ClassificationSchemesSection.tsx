import { useState, type FormEvent } from "react";

import {
  FilingRuleName,
  type ClassificationSchemeCreate,
  type ClassificationSchemeOut,
} from "../../../../api/generated/model";
import { ApiError } from "../../../../api/mutator";
import { Button, ErrorState } from "../../../../components";
import { useTranslation, type Translate } from "../../../../i18n";
import type { MessageKey } from "../../../../i18n/en";
import { schemeLabel } from "../../../../lib/classificationLabels";
import { SettingsSection } from "../../../components";
import type { RenameCallbacks } from "../hooks";

/** Match `CLASSIFICATION_SCHEME_CODE_MAX` and `_NAME_MAX` in the backend's
 * models.py. A courtesy, not a check: the server is the authority. */
const CODE_MAX = 20;
const NAME_MAX = 80;

/** `SCHEME_IN_USE` in the backend's routers/settings.py. */
const SCHEME_IN_USE = "scheme_in_use";

const RULE_LABEL: Record<FilingRuleName, MessageKey> = {
  [FilingRuleName.generic]: "schemes.ruleGeneric",
  [FilingRuleName.dewey]: "schemes.ruleDewey",
  [FilingRuleName.lcc]: "schemes.ruleLcc",
};

interface ClassificationSchemesSectionProps {
  schemes: ClassificationSchemeOut[];
  isBusy: boolean;
  error: unknown;
  onDefine: (scheme: ClassificationSchemeCreate, onDone: () => void) => void;
  onRename: (scheme: string, name: string, callbacks: RenameCallbacks) => void;
  onRemove: (scheme: string) => void;
}

/**
 * The schemes a heading may quote, and a library's own beside the four built in.
 *
 * **A built in scheme offers no control**, because the server refuses every
 * write to one: code reads it. A library's own may be renamed, and deleted;
 * the server refuses a delete while a book still quotes the scheme and says
 * how many the admin can see, which `error` carries to the top of the
 * section, worded here in the reader's language.
 *
 * **The filing rule is chosen once.** Every stored shelf key was computed
 * under it, so the row shows it and offers no way to change it.
 */
export default function ClassificationSchemesSection({
  schemes,
  isBusy,
  error,
  onDefine,
  onRename,
  onRemove,
}: ClassificationSchemesSectionProps) {
  const { t } = useTranslation();
  const [renaming, setRenaming] = useState<string | null>(null);

  return (
    <SettingsSection title={t("schemes.title")} icon="book">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("schemes.explain")}
      </p>
      {error != null && <ErrorState error={inReadersWords(error, t)} />}
      <ul className="space-y-1.5">
        {schemes.map((scheme) => (
          <SchemeRow
            key={scheme.scheme}
            scheme={scheme}
            isBusy={isBusy}
            renaming={renaming === scheme.scheme}
            onStartRename={() => setRenaming(scheme.scheme)}
            onStopRenaming={() => setRenaming(null)}
            onRename={onRename}
            onRemove={onRemove}
          />
        ))}
      </ul>
      <DefineForm isBusy={isBusy} onDefine={onDefine} />
    </SettingsSection>
  );
}

/**
 * A refused delete in the reader's language, from the count the server sent
 * beside its English sentence; any other error as it came.
 *
 * **The count is of the books the admin can see**, and the sentence says so
 * (owner, 2026-11-20): another member's private book blocks the delete too,
 * and where only such books do, the count is 0 and no number is shown.
 */
function inReadersWords(error: unknown, t: Translate): unknown {
  if (!(error instanceof ApiError) || error.code !== SCHEME_IN_USE) {
    return error;
  }
  const count = error.count ?? 0;
  if (count === 0) return new Error(t("schemes.inUseUnseen"));
  if (count === 1) return new Error(t("schemes.inUseOne"));
  return new Error(t("schemes.inUse", { count }));
}

/** The three fields a new scheme takes, cleared only once the server took it. */
function DefineForm({
  isBusy,
  onDefine,
}: Pick<ClassificationSchemesSectionProps, "isBusy" | "onDefine">) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [filing, setFiling] = useState<FilingRuleName>(FilingRuleName.generic);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    onDefine({ scheme: code.trim(), name: name.trim(), filing }, () => {
      setCode("");
      setName("");
      setFiling(FilingRuleName.generic);
    });
  };

  return (
    <form onSubmit={submit} className="flex flex-wrap gap-2 items-end">
      <label className="w-28">
        <span className="text-xs text-paper-600 dark:text-paper-400">
          {t("schemes.codeLabel")}
        </span>
        <input
          type="text"
          value={code}
          onChange={(event) => setCode(event.target.value.toLowerCase())}
          maxLength={CODE_MAX}
          placeholder="rvk"
          className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
        />
      </label>
      <label className="flex-1 min-w-40">
        <span className="text-xs text-paper-600 dark:text-paper-400">
          {t("schemes.nameLabel")}
        </span>
        <input
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={NAME_MAX}
          className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
        />
      </label>
      <label>
        <span className="text-xs text-paper-600 dark:text-paper-400">
          {t("schemes.ruleLabel")}
        </span>
        <select
          value={filing}
          onChange={(event) => setFiling(event.target.value as FilingRuleName)}
          className="w-full px-3 py-2 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
        >
          {Object.values(FilingRuleName).map((rule) => (
            <option key={rule} value={rule}>
              {t(RULE_LABEL[rule])}
            </option>
          ))}
        </select>
      </label>
      <Button
        type="submit"
        size="sm"
        disabled={isBusy || !code.trim() || !name.trim()}
      >
        {t("schemes.addButton")}
      </Button>
    </form>
  );
}

interface SchemeRowProps {
  scheme: ClassificationSchemeOut;
  isBusy: boolean;
  renaming: boolean;
  onStartRename: () => void;
  onStopRenaming: () => void;
  onRename: ClassificationSchemesSectionProps["onRename"];
  onRemove: ClassificationSchemesSectionProps["onRemove"];
}

/** One scheme: its name, code and rule, or the rename box in their place. */
function SchemeRow({
  scheme,
  isBusy,
  renaming,
  onStartRename,
  onStopRenaming,
  onRename,
  onRemove,
}: SchemeRowProps) {
  const { t } = useTranslation();
  // A built in scheme's name is the reader's translation, as on every chip.
  const name = scheme.built_in ? schemeLabel(scheme.scheme, t) : scheme.name;
  return (
    <li className="text-sm">
      {renaming ? (
        <RenameBox
          scheme={scheme}
          isBusy={isBusy}
          onRename={onRename}
          onStopRenaming={onStopRenaming}
        />
      ) : (
        <div className="flex items-center gap-2">
          <span className="flex-1 text-paper-700 dark:text-paper-200">
            {name}{" "}
            <span className="text-xs text-paper-600 dark:text-paper-400">
              {scheme.scheme}
            </span>
          </span>
          <span className="text-xs text-paper-600 dark:text-paper-400">
            {t(RULE_LABEL[scheme.filing])}
          </span>
          {!scheme.built_in && (
            <>
              <Button size="sm" variant="ghost" onClick={onStartRename}>
                {t("common.edit")}
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={isBusy}
                onClick={() => {
                  if (
                    window.confirm(
                      t("schemes.deleteConfirm", { name: scheme.name }),
                    )
                  ) {
                    onRemove(scheme.scheme);
                  }
                }}
              >
                {t("common.delete")}
              </Button>
            </>
          )}
        </div>
      )}
    </li>
  );
}

/** The rename box, and a refused rename's sentence under it. */
function RenameBox({
  scheme,
  isBusy,
  onRename,
  onStopRenaming,
}: Pick<SchemeRowProps, "scheme" | "isBusy" | "onRename" | "onStopRenaming">) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(scheme.name);
  const [refusal, setRefusal] = useState<unknown>(null);
  const save = () => {
    setRefusal(null);
    onRename(scheme.scheme, draft.trim(), {
      onSuccess: onStopRenaming,
      onError: setRefusal,
    });
  };
  return (
    <>
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          maxLength={NAME_MAX}
          aria-label={t("schemes.renameLabel", { name: scheme.name })}
          className="flex-1 px-3 py-1.5 rounded-lg border border-paper-200 text-sm dark:border-paper-700"
        />
        <Button size="sm" onClick={save} disabled={isBusy || !draft.trim()}>
          {t("common.save")}
        </Button>
        <Button size="sm" variant="secondary" onClick={onStopRenaming}>
          {t("common.cancel")}
        </Button>
      </div>
      {refusal != null && (
        <div className="mt-1">
          <ErrorState error={refusal} />
        </div>
      )}
    </>
  );
}
