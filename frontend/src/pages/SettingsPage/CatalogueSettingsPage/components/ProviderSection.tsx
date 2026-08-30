import { useEffect, useRef, useState } from "react";

import type {
  CatalogueSource,
  CatalogueSourceOut,
  SettingsOut,
  SettingsUpdate,
} from "../../../../api/generated/model";
import { Button, Icon } from "../../../../components";
import { useTranslation, type MessageKey } from "../../../../i18n";
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
  const { t } = useTranslation();
  // **A module level constant, not a fresh `[]`.** `catalogue_sources` is
  // optional on the generated type, so `?? []` builds a new array on every
  // render, the effect below depends on its identity, and the pair is an
  // infinite render loop for any response that omits the field. The server
  // always sends it, which is exactly what would have made this a defect
  // nothing hit until something changed upstream.
  const server = settings.catalogue_sources ?? NO_SOURCES;
  const [rows, setRows] = useState<CatalogueSourceOut[]>(server);
  const [announcement, setAnnouncement] = useState("");
  // Which button to focus after a move, or null. **A disabled element loses
  // focus to the body**, so the press that lands a row at either end silently
  // ends the run: the reader presses again and nothing happens because nothing
  // is focused. Keying rows on the source keeps the DOM node, which is
  // necessary and not sufficient. After a move that disables the button under
  // the finger, focus moves to the other button of the same row.
  const [refocus, setRefocus] = useState<{
    source: CatalogueSource;
    direction: "up" | "down";
  } | null>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement | null>());

  // The save is debounced, so a burst of four presses is one request rather
  // than four. The pending payload is held in a ref as well as the timer,
  // because leaving the screen mid burst has to flush rather than discard: a
  // reorder that vanished on navigation would look like the server refusing it.
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

  useEffect(() => {
    if (refocus === null) return;
    buttons.current.get(`${refocus.source}:${refocus.direction}`)?.focus();
    setRefocus(null);
  }, [refocus]);

  const move = (from: number, direction: -1 | 1) => {
    const to = from + direction;
    if (to < 0 || to >= rows.length) return;
    const next = [...rows];
    const moving = next[from];
    const displaced = next[to];
    if (moving === undefined || displaced === undefined) return;
    next[from] = displaced;
    next[to] = moving;
    commit(next);
    // The button just pressed is about to be disabled if the row landed at an
    // end, so hand focus to its sibling rather than letting it fall to the body.
    const landedAtAnEnd = to === 0 || to === next.length - 1;
    if (landedAtAnEnd) {
      setRefocus({
        source: moving.source,
        direction: direction === -1 ? "down" : "up",
      });
    }
    setAnnouncement(
      t("providers.moved", {
        name: t(sourceName(moving.source)),
        position: String(to + 1),
        total: String(next.length),
      }),
    );
  };

  const setEnabled = (index: number, enabled: boolean) => {
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

      <ul className="space-y-3">
        {rows.map((row, index) => (
          // Keyed on the source, never the index: a key that moves with the
          // row is what lets React keep the focused button focused across a
          // reorder, and an index key would move focus to whatever slid into
          // the slot.
          <li
            key={row.source}
            className="flex items-start gap-3 border-t border-paper-200 pt-3 first:border-0 first:pt-0 dark:border-paper-800"
          >
            <div className="min-w-0 flex-1">
              <ToggleField
                label={t(sourceName(row.source))}
                hint={t(statusOf(row))}
                checked={row.enabled}
                disabled={false}
                onChange={(checked) => setEnabled(index, checked)}
              />
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
                disabled={index === 0}
                aria-label={t("providers.moveUp", {
                  name: t(sourceName(row.source)),
                })}
                onClick={() => move(index, -1)}
              >
                <Icon name="chevron" className="w-4 h-4 -rotate-90" />
              </Button>
              <Button
                variant="secondary"
                size="sm"
                ref={(node: HTMLButtonElement | null) => {
                  buttons.current.set(`${row.source}:down`, node);
                }}
                disabled={index === rows.length - 1}
                aria-label={t("providers.moveDown", {
                  name: t(sourceName(row.source)),
                })}
                onClick={() => move(index, 1)}
              >
                <Icon name="chevron" className="w-4 h-4 rotate-90" />
              </Button>
            </div>
          </li>
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

/** The catalogue's name, which is a proper noun and is not translated. */
function sourceName(source: CatalogueSource): MessageKey {
  return `providers.name.${source}` as MessageKey;
}

/**
 * The one line under a source: why it is not answering, or what it answers.
 *
 * **Ordered by what a reader can act on.** A missing key is the most likely
 * cause of "why is this not working", so it comes first even for a source that
 * is switched on and looks fine. Then whether it is in the pair asked on every
 * scan, which is what the order actually buys. Then the search only case,
 * which explains why moving it changes nothing about scanning a barcode.
 */
function statusOf(row: CatalogueSourceOut): MessageKey {
  // **Two causes, not one.** A source that needs a key and has none wants a
  // key; one that has the key and still is not ready is switched off in its own
  // card below, and telling that library to add a key it already has is the
  // exact symptom this section exists to remove. `ready` alone conflated them.
  if (row.needs_a_key && !row.ready) {
    return row.has_key
      ? "providers.status.switchedOffBelow"
      : "providers.status.needsKey";
  }
  if (!row.answers_lookup) return "providers.status.searchOnly";
  if (row.enabled && row.asked_first) return "providers.status.askedFirst";
  if (row.enabled) return "providers.status.askedAfter";
  return "providers.status.off";
}
