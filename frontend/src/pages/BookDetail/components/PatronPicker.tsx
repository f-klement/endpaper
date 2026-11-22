import { useState } from "react";

import type { PatronOut } from "../../../api/generated/model";
import { Button, ErrorState, Modal, Spinner } from "../../../components";
import { useTranslation } from "../../../i18n";
import { numericDate } from "../../../lib/date";
import { PatronForm, SearchBar } from "../../components";
import {
  usePatronSearch,
  useRegisterPatron,
  type UsePatronSearchResult,
} from "../../hooks";
import { BLANK_DRAFT, calendarToday, hasExpired } from "../../types";

/**
 * A patron the desk picked, with the day it was picked on.
 *
 * The day travels with the patron so the expiry line is judged against a date
 * fixed when the answer arrived, never a clock read during render.
 */
export interface PickedPatron {
  patron: PatronOut;
  /** `YYYY-MM-DD`, the reader's own calendar day. */
  today: string;
}

interface PatronPickerProps {
  picked: PickedPatron | null;
  onPick: (picked: PickedPatron | null) => void;
}

type Dialog = "closed" | "find" | "register";

/**
 * Who takes the book, when it is a patron: somebody already registered, or
 * somebody registered here and now. Used only by `LoanPanel`, and only for an
 * admin, since a search answers with people's contact details.
 *
 * **Registering hands back the stored record**, which becomes the pick, so
 * the loan that follows names that patron by id and a second loan to the same
 * person finds them rather than registering them again. A loan that fails
 * after the registration keeps the pick, so trying again registers nobody.
 */
export default function PatronPicker({ picked, onPick }: PatronPickerProps) {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<Dialog>("closed");
  const registration = useRegisterPatron();

  const close = () => setDialog("closed");
  const pick = (next: PickedPatron) => {
    onPick(next);
    close();
  };
  const openRegister = () => {
    registration.reset();
    setDialog("register");
  };

  return (
    <div className="flex-1 min-w-0">
      {picked ? (
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <PatronSummary picked={picked} />
          <button
            type="button"
            onClick={() => onPick(null)}
            className="text-xs text-paper-600 hover:underline dark:text-paper-400"
          >
            {t("loans.patronChange")}
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => setDialog("find")}
          >
            {t("loans.patronExisting")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={openRegister}
          >
            {t("loans.patronNew")}
          </Button>
        </div>
      )}

      {dialog === "find" && <FindPatron onPick={pick} onClose={close} />}
      {dialog === "register" && (
        <PatronForm
          title={t("patrons.newTitle")}
          initial={BLANK_DRAFT}
          submitLabel={t("patrons.register")}
          busyLabel={t("patrons.registering")}
          isSaving={registration.isRegistering}
          error={registration.error}
          onSubmit={(body) =>
            registration.register(body, (patron) =>
              // Today is read here, in the answer's handler, not in a render.
              pick({ patron, today: calendarToday(new Date()) }),
            )
          }
          onClose={close}
        />
      )}
    </div>
  );
}

/**
 * Name, card, and the registration's expiry when it has one.
 *
 * **A lapsed registration is said in words and still lends**: refusing the
 * person at the desk over a date is a circulation policy, which this
 * application does not have, so the desk is told and decides.
 */
function PatronSummary({ picked }: { picked: PickedPatron }) {
  const { t, locale } = useTranslation();
  const { patron, today } = picked;
  const expired = hasExpired(patron, today);
  return (
    <span className="text-sm text-paper-700 dark:text-paper-200">
      <span className="font-medium">{patron.name}</span>{" "}
      <span className="text-xs font-mono text-paper-600 dark:text-paper-400">
        {t("patrons.card", { number: patron.card_number })}
      </span>
      {patron.expires_on != null && (
        <span
          className={
            expired
              ? "block text-xs font-medium text-danger-600 dark:text-danger-300"
              : "block text-xs text-paper-600 dark:text-paper-400"
          }
        >
          {t(expired ? "patrons.expiredOn" : "patrons.validUntil", {
            date: numericDate(patron.expires_on, locale),
          })}
        </span>
      )}
    </span>
  );
}

/**
 * One search field over name, email and card number, because at a counter
 * with somebody waiting one field is the whole point.
 */
function FindPatron({
  onPick,
  onClose,
}: {
  onPick: (picked: PickedPatron) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [term, setTerm] = useState("");
  const search = usePatronSearch(term);
  return (
    <Modal title={t("loans.patronFindTitle")} onClose={onClose}>
      <SearchBar
        onSearch={setTerm}
        label={t("patrons.search")}
        placeholder={t("patrons.searchPlaceholder")}
      />
      <div className="mt-3">
        <Matches search={search} onPick={onPick} />
      </div>
    </Modal>
  );
}

/** The hint before a search, the load error, no match, or a row per patron. */
function Matches({
  search,
  onPick,
}: {
  search: UsePatronSearchResult;
  onPick: (picked: PickedPatron) => void;
}) {
  const { t } = useTranslation();
  if (!search.hasTerm) {
    return <Note text={t("patrons.searchHint")} />;
  }
  if (search.isLoading) return <Spinner label={t("common.loading")} />;
  if (search.error != null) {
    return (
      <ErrorState
        error={search.error}
        fallback={t("patrons.couldNotLoad")}
        onRetry={search.refetch}
      />
    );
  }
  if (search.patrons.length === 0) return <Note text={t("patrons.noMatch")} />;
  return (
    <>
      <ul className="grid gap-2">
        {search.patrons.map((patron) => (
          <li key={patron.id}>
            <button
              type="button"
              onClick={() => onPick({ patron, today: search.today })}
              className="w-full text-left rounded-xl border border-paper-200 px-3 py-2 hover:bg-paper-100 dark:border-paper-700 dark:hover:bg-paper-800"
            >
              <PatronSummary picked={{ patron, today: search.today }} />
            </button>
          </li>
        ))}
      </ul>
      {search.isCapped && (
        <Note text={t("patrons.capped", { count: search.patrons.length })} />
      )}
    </>
  );
}

function Note({ text }: { text: string }) {
  return (
    <p className="text-sm text-paper-600 mt-2 dark:text-paper-400">{text}</p>
  );
}
