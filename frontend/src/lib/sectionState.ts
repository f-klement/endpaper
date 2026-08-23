/**
 * Which collapsible sections a reader has opened or closed by hand.
 *
 * localStorage rather than the account, for the same reason `libraryView` and
 * the saved searches are: this is a habit rather than household data, it needs
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
 */

/** Bumped when the stored shape changes. Anything else is dropped, not read. */
const VERSION = 1;

const STORAGE_KEY = "bookDetailSections";

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
export function readSectionChoices(): SectionChoices {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
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
 * here. Silent on failure, for the reason above.
 */
export function writeSectionChoice(id: string, isOpen: boolean): void {
  try {
    const sections = { ...readSectionChoices(), [id]: choiceFor(isOpen) };
    localStorage.setItem(
      STORAGE_KEY,
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
