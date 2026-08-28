/**
 * Which collapsible sections a reader has opened or closed by hand.
 *
 * localStorage rather than the account, for the same reason `libraryView` and
 * the saved searches are: this is a habit rather than library data, it needs
 * no endpoint, no schema and no migration, and the cost of getting it wrong is
 * one tap. Per device is therefore also per browser, and a phone and a laptop
 * remember separately.
 *
 * **The stored value is three states, not two, and that is the whole design.**
 * A section's default depends on the book (a book that is out shows its loan; a
 * book with one copy does not open a copies section), so "closed" and "nobody
 * has said" cannot be the same stored value. If they were, a reader who closed
 * the loan section on a borrowed book would find it open again on the next
 * visit, because the condition would win every time. Absence means "use the
 * condition"; a present value means the reader has spoken and the condition is
 * over. `resolveOpen()` is the only place that rule lives.
 *
 * One entry per section, not one for the page: a single flag could only ever
 * mean "collapse everything", which throws away the conditional defaults.
 *
 * **The store is a parameter because two pages folded, and their ids collided.**
 * Both the book page and the settings page had a section called `about`. One
 * shared key would have made closing the blurb on a book close the app's own
 * about card, and neither page would have shown anything wrong. `SectionStore`
 * is a union rather than a `string`, so a page has to name its store here and a
 * typo is a compile error rather than a silently shared entry.
 *
 * **The settings page stopped folding on 2026-08-27** and nothing writes
 * `settingsSections` any more: settings is a route tree, and navigation is the
 * state. The name is kept in the union deliberately rather than tidied away.
 * Two reasons, and the second is the load bearing one: entries written by older
 * builds are still in readers' browsers, so the key is spoken for and a later
 * folding page must not reuse it and inherit them; and the merge in
 * `writeSectionChoice`, which is what stops one page's write clearing another's
 * entries, can only be tested against two stores. Deleting the name would
 * delete that test with it.
 */

/** Bumped when the stored shape changes. Anything else is dropped, not read. */
const VERSION = 1;

/** One localStorage key per store. See the note above about `about`. */
export type SectionStore = "bookDetailSections" | "settingsSections";

/** What a reader said about one section. Absence is the third state. */
export type SectionChoice = "open" | "closed";

export type SectionChoices = Record<string, SectionChoice>;

interface Stored {
  version: number;
  sections: SectionChoices;
}

function isChoice(value: unknown): value is SectionChoice {
  return value === "open" || value === "closed";
}

/**
 * The remembered choices, or none.
 *
 * Every failure path returns an empty map rather than throwing: a private
 * window that refuses to answer, storage that has been cleared, a value written
 * by a future version, a half-written entry. None of those is a reason to fail
 * to render a book, and an empty map is exactly the state the conditional
 * defaults are written for.
 *
 * **Ids for sections that no longer exist are kept, not pruned.** A section
 * renamed or dropped later leaves its entry behind; nothing asks for that id,
 * so nothing renders it, and keeping it means a section that comes back finds
 * what the reader last said. Only values that are not "open" or "closed" are
 * dropped, so a corrupt entry cannot make a section open itself.
 */
export function readSectionChoices(store: SectionStore): SectionChoices {
  try {
    const raw = localStorage.getItem(store);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Stored;
    if (parsed.version !== VERSION || typeof parsed.sections !== "object")
      return {};
    const choices: SectionChoices = {};
    for (const [id, value] of Object.entries(parsed.sections ?? {})) {
      if (isChoice(value)) choices[id] = value;
    }
    return choices;
  } catch {
    return {};
  }
}

/**
 * Remember one section's state, leaving every other entry alone.
 *
 * Merged against what is stored rather than against what this tab holds in
 * memory, so a second tab open on another book does not overwrite a choice made
 * here. Only this page's own store is read and rewritten, so the other page's
 * entries cannot be lost to a merge. Silent on failure, for the reason above.
 */
export function writeSectionChoice(
  store: SectionStore,
  id: string,
  isOpen: boolean,
): void {
  try {
    const sections = { ...readSectionChoices(store), [id]: choiceFor(isOpen) };
    localStorage.setItem(
      store,
      JSON.stringify({ version: VERSION, sections } satisfies Stored),
    );
  } catch {
    // Storage full or refused. The choice still holds for this visit, which is
    // the part the reader can see.
  }
}

function choiceFor(isOpen: boolean): SectionChoice {
  return isOpen ? "open" : "closed";
}

/**
 * The three state rule: a stored choice beats the book, absence defers to it.
 *
 * Deliberately not `choice === "open"` with a default of false. That collapses
 * the third state and is invisible in any test that only checks the default.
 */
export function resolveOpen(
  choice: SectionChoice | undefined,
  conditionalDefault: boolean,
): boolean {
  return choice === undefined ? conditionalDefault : choice === "open";
}
