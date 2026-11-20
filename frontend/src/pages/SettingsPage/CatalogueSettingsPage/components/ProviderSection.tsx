import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

import type {
  CatalogueSource,
  CatalogueSourceOut,
  ClassificationScheme,
  CredentialKind,
  SettingsOut,
  SettingsUpdate,
  Transport,
} from "../../../../api/generated/model";
import { Button, Icon } from "../../../../components";
import { useTranslation } from "../../../../i18n";
import type { MessageKey } from "../../../../i18n/en";
import { catalogueName } from "../../../../lib/catalogueName";
import { statusOf } from "../../../../lib/providerStatus";
import { SettingsSection } from "../../../components";
import ToggleField from "../../components/ToggleField";

interface ProviderSectionProps {
  settings: SettingsOut;
  onSave: (data: SettingsUpdate) => void;
}

/**
 * The catalogues this library asks, and the order it asks them in.
 *
 * **The order is the order they are asked, and nothing else.** Which source is
 * believed when two disagree about one field is a separate rule that stays in
 * the backend, and the section says so rather than implying otherwise: a
 * control that quietly reached half of what a reader expects is worse than one
 * that states its limits. `backend/sources.py` carries the argument, and the
 * short version is that no single order reproduces both of today's behaviours,
 * so one list driving both would move something nobody touched.
 *
 * **What enabling costs is two opposite rules, so it is stated as two
 * sentences rather than a column of seconds.** On title search every enabled
 * source goes out at once inside one deadline, so one more costs no wall clock
 * unless it turns out to be the slowest. On an ISBN lookup the leading pair is
 * asked together and the rest one at a time, so there it really is additive.
 * Per source latencies exist in the backend and are deliberately not shown:
 * that file says three times that its figures come from different samples, and
 * a table of numbers that cannot be compared with each other is worse than no
 * table.
 *
 * **Switching a source off can cost more than that source**, so two cases ask
 * first. Turning off the last catalogue switched on means every lookup finds
 * nothing: cataloguing by hand is a legitimate choice, and it should be chosen
 * rather than arrived at. Turning off the only enabled supplier of a
 * classification scheme silently empties that field on every book looked up
 * afterwards. Which schemes a row supplies is served, derived from the reader
 * in the backend's `sources.CLASSIFIES`; this only compares the rows.
 *
 * **Two buttons, not drag and drop.** A drag target is unreachable by keyboard
 * and awkward on a phone, and this list is seven rows that move one step at a
 * time. Each button names the source and the direction, the ends are disabled
 * rather than missing so the row does not change shape, and every move is
 * announced, because moving a row the reader cannot see move is the whole
 * accessibility problem in one.
 */
export default function ProviderSection({
  settings,
  onSave,
}: ProviderSectionProps) {
  const { t, locale } = useTranslation();
  // **A disjunction, not a comma list.** Two groups rendered as
  // "beginning 978-618, 978-960", which reads as "and" where the rule is "or".
  // `Intl.ListFormat` also gets the German right, "oder" rather than a
  // hard coded English word, and handles one, two and three or more without a
  // branch here. Rebuilt only when the language changes.
  const groups = useMemo(
    () => new Intl.ListFormat(locale, { type: "disjunction" }),
    [locale],
  );
  // "and" rather than "or": a row supplies every scheme it lists.
  const together = useMemo(
    () => new Intl.ListFormat(locale, { type: "conjunction" }),
    [locale],
  );
  // **A module level constant, not a fresh `[]`.** `catalogue_sources` is
  // optional on the generated type, so `?? []` builds a new array on every
  // render, the effect in `useDebouncedRoster` depends on its identity, and the
  // pair is an infinite render loop for any response that omits the field. The
  // server always sends it, which is exactly what would have made this a
  // defect nothing hit until something changed upstream.
  const server = settings.catalogue_sources ?? NO_SOURCES;
  const [rows, commit] = useDebouncedRoster(server, onSave);
  const [announcement, setAnnouncement] = useState("");
  const { buttons, refocusAfter } = useRefocus();

  const move = (from: number, direction: -1 | 1) => {
    const swap = swapped(rows, from, direction);
    if (swap === undefined) return;
    commit(swap.next);
    refocusAfter(swap, direction);
    setAnnouncement(
      t("providers.moved", {
        name: t(catalogueName(swap.moving.source)),
        position: String(swap.to + 1),
        total: String(swap.next.length),
      }),
    );
  };

  const setEnabled = (index: number, enabled: boolean) => {
    const question = enabled ? null : switchOffQuestion(rows, index);
    if (question !== null) {
      const { key, name, schemes } = question;
      const asked = t(key, {
        name: t(catalogueName(name)),
        schemes: together.format(schemes.map((scheme) => t(SCHEME[scheme]))),
      });
      if (!window.confirm(asked)) return;
    }
    const next = rows.map((row, at) =>
      at === index ? { ...row, enabled } : row,
    );
    commit(next);
  };

  return (
    <SettingsSection title={t("providers.title")} icon="search">
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("providers.hint")}
      </p>
      <p className="text-xs text-paper-600 dark:text-paper-400">
        {t("providers.costHint")}
      </p>
      {/* **Only when a row carries it.** The marking is empty on the shipped
          roster, and a paragraph explaining a group this install has nobody in
          reads as a setting somebody has lost. */}
      {rows.some((row) => row.slow) && (
        <p className="text-xs text-paper-600 dark:text-paper-400">
          {t("providers.slowLegend")}
        </p>
      )}

      <ul className="space-y-3">
        {rows.map((row, index) => (
          // Keyed on the source, never the index: a key that moves with the
          // row is what lets React keep the focused button focused across a
          // reorder, and an index key would move focus to whatever slid into
          // the slot.
          <ProviderRow
            key={row.source}
            row={row}
            groups={groups}
            together={together}
            isFirst={index === 0}
            isLast={index === rows.length - 1}
            buttons={buttons}
            onToggle={(checked) => setEnabled(index, checked)}
            onMove={(direction) => move(index, direction)}
          />
        ))}
      </ul>

      {/* Polite, and outside the list, so a move is read after the button's own
          label rather than interrupting it.

          **`aria-live` without `role="status"`, deliberately.** The role implies
          exactly this live region, so it would add nothing, and it would put a
          second `status` on a screen that already has one: `AdminSettings`
          renders the "Settings saved." banner with it. Two of them make the
          banner ambiguous to anything looking for it, which a test caught
          before a reader had to. */}
      <p aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement}
      </p>
    </SettingsSection>
  );
}

/** One source: its toggle, its status lines, and the two move buttons. */
function ProviderRow({
  row,
  groups,
  together,
  isFirst,
  isLast,
  buttons,
  onToggle,
  onMove,
}: {
  row: CatalogueSourceOut;
  groups: Intl.ListFormat;
  together: Intl.ListFormat;
  isFirst: boolean;
  isLast: boolean;
  buttons: RefocusTargets;
  onToggle: (checked: boolean) => void;
  onMove: (direction: -1 | 1) => void;
}) {
  const { t } = useTranslation();
  const name = t(catalogueName(row.source));
  return (
    <li className="flex items-start gap-3 border-t border-paper-200 pt-3 first:border-0 first:pt-0 dark:border-paper-800">
      <div className="min-w-0 flex-1">
        <ToggleField
          label={name}
          hint={t(statusOf(row), {
            groups: groups.format(row.serves_groups),
          })}
          checked={row.enabled}
          disabled={false}
          onChange={onToggle}
        />
        {/* **A second line rather than an eighth arm in `statusOf`.**
            Slow co-occurs with almost every value that chain returns: a
            slow catalogue can also need a key, sit in the leading pair, or
            carry a regional remit. One line per row would have to swallow
            one of those or never fire for it, which is the defect
            `lib/providerStatus.ts` records having shipped once already.

            It also says the thing the ticket asked this section for: off
            because it is slow reads differently from off because it is
            broken, and only if the screen says which. */}
        {row.slow && (
          <p className="mt-1 text-xs text-paper-600 dark:text-paper-400">
            {t("providers.slow")}
          </p>
        )}
        <HowAsked row={row} together={together} />
      </div>
      <div className="flex shrink-0 gap-1">
        {/* **Not disabled while a save is in flight.** The local list is
            what is drawn, the save is debounced and sends the whole
            roster so the last one wins, and disabling every button when
            the timer fires would take focus off the one under the
            reader's finger in the middle of a run. */}
        <Button
          variant="secondary"
          size="sm"
          ref={(node: HTMLButtonElement | null) => {
            buttons.current.set(`${row.source}:up`, node);
          }}
          disabled={isFirst}
          aria-label={t("providers.moveUp", { name })}
          onClick={() => onMove(-1)}
        >
          <Icon name="chevron" className="w-4 h-4 -rotate-90" />
        </Button>
        <Button
          variant="secondary"
          size="sm"
          ref={(node: HTMLButtonElement | null) => {
            buttons.current.set(`${row.source}:down`, node);
          }}
          disabled={isLast}
          aria-label={t("providers.moveDown", { name })}
          onClick={() => onMove(1)}
        >
          <Icon name="chevron" className="w-4 h-4 rotate-90" />
        </Button>
      </div>
    </li>
  );
}

/**
 * How a catalogue is asked: protocol, record schema, whether the connection is
 * encrypted, what it wants before it answers, and which schemes it supplies.
 *
 * **What a policy is written about, and not the address**, which changes
 * without the policy changing and would turn this screen into a place people
 * edit endpoints. Every value is derived on the server from the catalogue's
 * own row, so it cannot drift from what a request does.
 *
 * Shown whether the row is on or off: the point is to read it before deciding.
 */
function HowAsked({
  row,
  together,
}: {
  row: CatalogueSourceOut;
  together: Intl.ListFormat;
}) {
  const { t } = useTranslation();
  const credential = CREDENTIAL[row.credential];
  const schemes = row.classification_schemes.map((scheme) => t(SCHEME[scheme]));
  const before = [
    t(PROTOCOL[row.protocol], { version: row.protocol_version }).trim(),
    row.record_schema
      ? t("providers.how.schema", { schema: row.record_schema })
      : t("providers.how.noSchema"),
  ].join(" · ");
  const after = [
    ...(credential === null ? [] : [t(credential)]),
    ...(schemes.length === 0
      ? []
      : [t("providers.how.supplies", { schemes: together.format(schemes) })]),
  ];
  return (
    <p className="mt-1 text-xs text-paper-600 dark:text-paper-400">
      {before}
      {" · "}
      {/* **Set apart when it is not, because that is the one a network policy
          forbids.** Queries to this catalogue cross the network in clear text,
          and the Library of Congress row is the reason the line exists. */}
      {row.encrypted ? (
        t("providers.how.encrypted")
      ) : (
        <span className="font-medium text-amber-800 dark:text-amber-300">
          {t("providers.how.unencrypted")}
        </span>
      )}
      {after.map((part) => ` · ${part}`).join("")}
    </p>
  );
}

/** Why switching this row off needs asking first, or null where it does not. */
interface SwitchOffQuestion {
  key: MessageKey;
  name: CatalogueSource;
  schemes: ClassificationScheme[];
}

/**
 * The question to ask before switching `rows[index]` off.
 *
 * **Every catalogue off comes first**, because it is the larger consequence
 * and implies the other: nothing supplies any scheme once nothing is asked.
 * Otherwise the schemes this row supplies that no other row in force does.
 * A row not in force asks nothing, so pressing a toggle twice does not ask
 * twice, and a row that could not answer loses nothing by going.
 */
function switchOffQuestion(
  rows: CatalogueSourceOut[],
  index: number,
): SwitchOffQuestion | null {
  const leaving = rows[index];
  if (leaving === undefined || !inForce(leaving)) return null;
  const staying = rows.filter((row, at) => at !== index && inForce(row));
  if (staying.length === 0) {
    return {
      key: "providers.confirm.allOff",
      name: leaving.source,
      schemes: [],
    };
  }
  const kept = new Set(staying.flatMap((row) => row.classification_schemes));
  const lost = leaving.classification_schemes.filter(
    (scheme) => !kept.has(scheme),
  );
  if (lost.length === 0) return null;
  return {
    key: "providers.confirm.lastSupplier",
    name: leaving.source,
    schemes: lost,
  };
}

/**
 * Whether lookups ask this row: switched on **and** able to answer, the
 * server's `sources.in_force`. Counting `enabled` alone took a row without its
 * key for a supplier, so switching the last answering catalogue off asked
 * nothing.
 */
function inForce(row: CatalogueSourceOut): boolean {
  return row.enabled && row.ready;
}

/** Each protocol's label, typed so a new transport cannot go unnamed. */
const PROTOCOL: Record<Transport, MessageKey> = {
  sru: "providers.how.sru",
  z3950: "providers.how.z3950",
  bespoke: "providers.how.bespoke",
};

/** What a catalogue wants before it answers, and nothing where it wants nothing. */
const CREDENTIAL: Record<CredentialKind, MessageKey | null> = {
  none: null,
  api_key: "providers.how.apiKey",
  login: "providers.how.login",
};

/** Each scheme's name, typed so a new scheme cannot go unnamed. */
const SCHEME: Record<ClassificationScheme, MessageKey> = {
  ddc: "providers.scheme.ddc",
  lcc: "providers.scheme.lcc",
  gnd: "providers.scheme.gnd",
  lcsh: "providers.scheme.lcsh",
};

/** A row moved one step: the new list, the row that moved, and where to. */
interface Swap {
  next: CatalogueSourceOut[];
  moving: CatalogueSourceOut;
  to: number;
}

/** `rows` with one row moved a step, or undefined where it would leave the list. */
function swapped(
  rows: CatalogueSourceOut[],
  from: number,
  direction: -1 | 1,
): Swap | undefined {
  const to = from + direction;
  if (to < 0 || to >= rows.length) return undefined;
  const next = [...rows];
  const moving = next[from];
  const displaced = next[to];
  if (moving === undefined || displaced === undefined) return undefined;
  next[from] = displaced;
  next[to] = moving;
  return { next, moving, to };
}

/**
 * The local roster, and a `commit` that draws a change at once and saves it
 * debounced.
 *
 * The save is debounced, so a burst of four presses is one request rather
 * than four. The pending payload is held in a ref as well as the timer,
 * because leaving the screen mid burst has to flush rather than discard: a
 * reorder that vanished on navigation would look like the server refusing it.
 */
function useDebouncedRoster(
  server: CatalogueSourceOut[],
  onSave: (data: SettingsUpdate) => void,
): [CatalogueSourceOut[], (next: CatalogueSourceOut[]) => void] {
  const [rows, setRows] = useState<CatalogueSourceOut[]>(server);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pending = useRef<SettingsUpdate | undefined>(undefined);
  const save = useRef(onSave);
  save.current = onSave;

  const flush = () => {
    if (timer.current !== undefined) {
      clearTimeout(timer.current);
      timer.current = undefined;
    }
    if (pending.current !== undefined) {
      save.current(pending.current);
      pending.current = undefined;
    }
  };

  // Re-seed from the server only while nothing local is waiting to be sent, or
  // a save landing mid burst would snap a half finished reorder back.
  useEffect(() => {
    if (timer.current === undefined) setRows(server);
    // The list is replaced wholesale by the mutation's `onSuccess`, so identity
    // is the right dependency here and a deep compare would only hide that.
  }, [server]);

  // Flush on the way out, so a reorder made and navigated away from within the
  // debounce window is still sent. The empty dependency array captures the
  // first render's `flush`, and that is safe rather than lucky: it reads only
  // refs, and `save.current` is reassigned on every render, so the closure
  // being stale cannot make it call a stale `onSave`.
  useEffect(() => () => flush(), []);

  const commit = (next: CatalogueSourceOut[]) => {
    setRows(next);
    pending.current = {
      catalogue_sources: next.map((row) => ({
        source: row.source,
        enabled: row.enabled,
      })),
    };
    if (timer.current !== undefined) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = undefined;
      flush();
    }, SAVE_DELAY_MS);
  };

  return [rows, commit];
}

/** Every move button, keyed `source:up` or `source:down`. */
type RefocusTargets = RefObject<Map<string, HTMLButtonElement | null>>;

/**
 * Which button to focus after a move.
 *
 * **A disabled element loses focus to the body**, so the press that lands a
 * row at either end silently ends the run: the reader presses again and
 * nothing happens because nothing is focused. Keying rows on the source keeps
 * the DOM node, which is necessary and not sufficient. After a move that
 * disables the button under the finger, focus moves to the other button of
 * the same row.
 */
function useRefocus() {
  const [refocus, setRefocus] = useState<{
    source: CatalogueSource;
    direction: "up" | "down";
  } | null>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement | null>());

  useEffect(() => {
    if (refocus === null) return;
    buttons.current.get(`${refocus.source}:${refocus.direction}`)?.focus();
    setRefocus(null);
  }, [refocus]);

  // The button just pressed is about to be disabled if the row landed at an
  // end, so hand focus to its sibling rather than letting it fall to the body.
  const refocusAfter = (swap: Swap, direction: -1 | 1) => {
    const landedAtAnEnd = swap.to === 0 || swap.to === swap.next.length - 1;
    if (landedAtAnEnd) {
      setRefocus({
        source: swap.moving.source,
        direction: direction === -1 ? "down" : "up",
      });
    }
  };

  return { buttons, refocusAfter };
}

/**
 * How long a burst of presses is collected before one save goes out.
 *
 * Long enough that moving a source three places is one request, short enough
 * that a reader who presses once and looks away does not wonder whether it
 * took. Tested with `fireEvent` and fake timers, never `user-event`, which
 * schedules its own async work and deadlocks against them.
 */
const SAVE_DELAY_MS = 600;

/** Stable, so an absent list cannot make a new array on every render. */
const NO_SOURCES: CatalogueSourceOut[] = [];
