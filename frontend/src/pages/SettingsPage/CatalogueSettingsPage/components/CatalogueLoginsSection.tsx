import { useState } from "react";

import type { SettingsOut } from "../../../../api/generated/model";
import { ErrorState } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import { catalogueName } from "../../../../lib/catalogueName";
import { SettingsSection } from "../../../components";
import { useCredentialKeyStatus, useSourceCredentials } from "../hooks";

/**
 * A login at a catalogue that will not answer without one.
 *
 * **Only the logins that exist are listed, plus a way to add one to any
 * source.** A form per catalogue would be ten password boxes on a screen where
 * nine households need none, and "this source needs a login and has not got
 * one" is already said in the provider list above, as a source that is switched
 * on and not ready. One fact, one place.
 *
 * **A login is write only, like the Google Books key beside it.** The server
 * never sends one back, so the fields cannot mirror `settings`: an empty box
 * means "leave the stored login alone", and what is stored is described by its
 * masked username instead.
 *
 * A login the deployment pinned is shown as such and cannot be edited here,
 * because there is nothing here to change: the environment's wins, and the
 * server refuses a write rather than storing something nothing will read.
 */
export default function CatalogueLoginsSection({
  settings,
}: {
  settings: SettingsOut;
}) {
  const { t } = useTranslation();
  const credentials = useSourceCredentials();
  const key = useCredentialKeyStatus();
  const [adding, setAdding] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const rows = settings.catalogue_sources ?? [];
  const held = rows.filter((row) => row.has_credential);
  const editing = rows.find((row) => row.source === adding);
  // A login cannot be stored without a key, and the control that makes one is
  // in the section below this. Saying so here is cheaper than a 409 the reader
  // has to provoke, and the order is deliberate: this section is what somebody
  // came for, and the key is only interesting because of it.
  const needsKeyFirst = key !== undefined && !key.configured;

  const clear = () => {
    setAdding("");
    setUsername("");
    setPassword("");
  };

  return (
    <SettingsSection title={t("settings.catalogueLogins")} icon="lock">
      <p className="text-xs text-paper-600 leading-relaxed dark:text-paper-400">
        {t("settings.catalogueLoginsHint")}
      </p>

      {held.length === 0 && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("settings.credentialMissing")}
        </p>
      )}

      {credentials.error != null && (
        <ErrorState
          error={credentials.error}
          fallback={t("settings.couldNotLoad")}
        />
      )}

      <ul className="space-y-2">
        {held.map((row) => (
          <li
            key={row.source}
            className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-paper-200 px-3 py-2 dark:border-paper-700"
          >
            <div className="space-y-0.5">
              <p className="text-sm font-medium">
                {t(catalogueName(row.source))}
              </p>
              {row.credential_from_env && row.credential_unreadable ? (
                // Both true is a variable somebody set to something that is not
                // a credential. Testing `from_env` first told them it was
                // supplied by the server and working, which is the exact
                // reassurance this state exists to remove.
                <p className="text-xs text-danger-700 dark:text-danger-200">
                  {t("settings.credentialFromEnvBroken", {
                    variable: `CATALOGUE_CREDENTIAL_${row.source.toUpperCase()}`,
                  })}
                </p>
              ) : row.credential_from_env ? (
                <p className="text-xs text-amber-800 dark:text-amber-200">
                  {t("settings.credentialFromEnv", {
                    variable: `CATALOGUE_CREDENTIAL_${row.source.toUpperCase()}`,
                  })}
                </p>
              ) : row.credential_unreadable ? (
                <p className="text-xs text-amber-800 dark:text-amber-200">
                  {t("settings.credentialUnreadable")}
                </p>
              ) : (
                <p className="text-xs text-paper-600 dark:text-paper-400">
                  {t("settings.credentialSet", {
                    preview: row.credential_username_preview ?? "",
                  })}
                </p>
              )}
            </div>
            {!row.credential_from_env && (
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setAdding(row.source)}
                  className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium hover:bg-paper-100 transition-colors dark:border-paper-700 dark:hover:bg-paper-800"
                >
                  {t("settings.credentialChange")}
                </button>
                <button
                  type="button"
                  disabled={credentials.isWorking}
                  onClick={() => credentials.remove(row.source)}
                  className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium text-danger-600 hover:bg-danger-100 disabled:opacity-40 transition-colors dark:border-paper-700 dark:text-danger-300"
                >
                  {t("settings.credentialClear")}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>

      <div className="space-y-1.5">
        <label
          htmlFor="catalogue-login-source"
          className="block text-xs font-medium text-paper-600 dark:text-paper-300"
        >
          {t("settings.credentialAdd")}
        </label>
        <select
          id="catalogue-login-source"
          value={adding}
          disabled={needsKeyFirst}
          onChange={(event) => setAdding(event.target.value)}
          className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm disabled:bg-paper-50 disabled:text-paper-400 disabled:cursor-not-allowed dark:border-paper-700 dark:disabled:bg-paper-800"
        >
          <option value="">{t("settings.credentialAddChoose")}</option>
          {rows
            .filter((row) => !row.credential_from_env && !row.has_credential)
            .map((row) => (
              <option key={row.source} value={row.source}>
                {t(catalogueName(row.source))}
              </option>
            ))}
        </select>
        {needsKeyFirst && (
          <p className="text-xs text-amber-800 dark:text-amber-200">
            {t("settings.credentialNeedsKeyFirst")}
          </p>
        )}
      </div>

      {editing && (
        <div className="space-y-1.5">
          {/* **The form names the catalogue itself.** The picker used to be the
              label by accident: it showed the chosen row. Taking held sources
              out of it, so that Change is the one route to editing one, left a
              username and a password with nothing saying whose, above a picker
              that had fallen back to "Choose a catalogue" because its value
              matched none of its options. */}
          <p className="text-sm font-medium">
            {t(catalogueName(editing.source))}
          </p>
          <label
            htmlFor="catalogue-login-username"
            className="block text-xs font-medium text-paper-600 dark:text-paper-300"
          >
            {t("settings.credentialUsername")}
          </label>
          <input
            id="catalogue-login-username"
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
          />
          <label
            htmlFor="catalogue-login-password"
            className="block text-xs font-medium text-paper-600 dark:text-paper-300"
          >
            {t("settings.credentialPassword")}
          </label>
          <input
            id="catalogue-login-password"
            type="password"
            autoComplete="off"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="w-full px-3 py-2 rounded-xl border border-paper-200 text-sm dark:border-paper-700"
          />
          <div className="flex gap-2 pt-1">
            <button
              type="button"
              disabled={
                credentials.isWorking ||
                username.trim() === "" ||
                password === ""
              }
              onClick={() =>
                credentials.save(
                  editing.source,
                  username.trim(),
                  password,
                  clear,
                )
              }
              className="px-3 py-1.5 rounded-lg bg-accent-fill text-on-accent text-xs font-medium hover:bg-accent-fill-hover disabled:opacity-40 transition-colors"
            >
              {t("settings.credentialSave")}
            </button>
            <button
              type="button"
              onClick={clear}
              className="px-3 py-1.5 rounded-lg border border-paper-200 text-xs font-medium dark:border-paper-700"
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}
    </SettingsSection>
  );
}
