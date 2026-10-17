/**
 * Landing a picked book on the catalogue: which Book already holds each of
 * its files, and what one add made of it.
 *
 * **One module for both doors that land files**, the Scan page's rapid queue
 * and the Calibre card on the library settings page. Each caller maps a
 * `Landing` to its own row or count; the rules are here, so the two cannot
 * disagree again. They did, three ways, while each walked the primitives on
 * its own.
 *
 * **Every request is handed in** (`LandingPorts`, and the lookup
 * `askWhoHolds` takes), which is what lets this live in `lib/`: only a
 * `hooks.ts` reaches the generated client. Reading a file's fingerprint is
 * not here either; `pages/hooks.locate` reads it while the `File` is in hand,
 * and this module takes the reference it makes.
 */

import type {
  AskedFileIn,
  BookFormat,
  BookOut,
  DigitalReferenceIn,
  HoldersOut,
} from "../api/generated/model";
import { writeOneAtATime } from "./bulkWrite";

/**
 * The `code` on the reference route's 409 for a Book at its file ceiling. The
 * backend suite reads this file for both codes as quoted literals, so a
 * respelling on one side only is red there.
 */
const REFERENCE_CEILING = "reference_ceiling";
/** The `code` on its 409 for a file another Book the member can see holds. */
const FILE_HELD_ELSEWHERE = "file_held_elsewhere";

/** The status every refusal this module reads answers with. */
const CONFLICT = 409;

/**
 * Which copy of the title a file's ISBN already belongs to takes the file's
 * location, or `undefined` where none may.
 *
 * **A copy of the same kind of object, or one nobody said the kind of.**
 * Owner's ruling, 2026-10-15. A reference says where the file of
 * *this row* is, and `books.format` is per row, so which row carries it already
 * states the relationship: an EPUB carrying its print ISBN, which Calibre
 * produces often, used to land as a file location on the household's
 * hardcover. Where no copy matches, the file is a new copy in its own format,
 * and that is a press the member makes (`addAsCopy`), never one this module
 * guesses.
 *
 * **Every copy and not only the one the 409 names.** The server names the
 * lowest id holder, and a copy shares its ISBN, so after `addAsCopy` made the
 * ebook beside a hardcover every later 409 still names the hardcover. Asking
 * that row alone offered the copy again on a re-pick, and the press made a
 * duplicate ebook.
 *
 * An exact format first, then an unset one, so a recorded ebook beats a row
 * nobody described. `copies` is in id order with the holder in it, which is
 * what `GET /{id}/copies` answers. A row whose own format is blank matches
 * only an unset copy; no file row is blank today, because every extension in
 * `fileName.FORMAT_FOR_EXTENSION` answers a format.
 */
export function whereItLands(
  copies: readonly Pick<BookOut, "id" | "format">[],
  fileFormat: BookFormat | "",
): number | undefined {
  const exact = copies.find(
    (copy) => copy.format != null && copy.format === fileFormat,
  );
  return (exact ?? copies.find((copy) => copy.format == null))?.id;
}

/**
 * How many files one `POST /api/books/file-holders` may name, and how many
 * references one sweep request carries.
 *
 * The schema's `maxItems` on `HoldersIn.files`, which
 * `tests/lib/fileLanding.test.ts` recomputes from `openapi.json`; the server
 * bounds a sweep by the same constant. A pick larger than this is asked in
 * chunks of it.
 */
export const FILES_PER_LOOKUP = 500;

/** Items in runs of `FILES_PER_LOOKUP`, the most one request takes. */
export function inChunks<T>(items: readonly T[]): T[][] {
  const chunks: T[][] = [];
  for (let start = 0; start < items.length; start += FILES_PER_LOOKUP) {
    chunks.push(items.slice(start, start + FILES_PER_LOOKUP));
  }
  return chunks;
}

/**
 * The holder lookup's answer for each item, `undefined` for an item whose
 * chunk failed or came back the wrong length.
 *
 * **Every chunk together** rather than one after another: each is a read, and
 * a pick needing more than one is a few thousand files.
 */
export async function lookUpHolders<T>(
  items: readonly T[],
  asked: (item: T) => AskedFileIn,
  lookup: (files: AskedFileIn[]) => Promise<HoldersOut[]>,
): Promise<(HoldersOut | undefined)[]> {
  const chunks = inChunks(items);
  const answered = await Promise.all(
    chunks.map((chunk) => lookup(chunk.map(asked)).catch(() => undefined)),
  );
  return chunks.flatMap((chunk, at) => {
    const answers = answered[at];
    const usable = answers !== undefined && answers.length === chunk.length;
    return chunk.map((_, index) => (usable ? answers[index] : undefined));
  });
}

/**
 * A Book already holding a file, and whether the file may land on it.
 *
 * `lands` is the landing rule's answer: the Book is the file's format or has
 * none recorded. A holder of another format is a match the file may not be
 * attached to, which is a reference left on a print row before that rule.
 */
export interface Held {
  readonly bookId: number;
  readonly lands: boolean;
  /**
   * Files of this book that another Book already holds and may take, by
   * `locationOf`, with that Book: `land` refreshes each there.
   */
  readonly elsewhere?: ReadonlyMap<string, number>;
  /**
   * Files of this book whose location only a Book they may not land on holds,
   * by `locationOf`. `land` sends none of them: the server refuses a location
   * another visible Book holds, so each would be a refusal on every add.
   */
  readonly inAnotherFormat?: ReadonlySet<string>;
}

/** Where a reference says a file is, as one key. */
function locationOf(reference: DigitalReferenceIn): string {
  return JSON.stringify([reference.root_label, reference.relative_path]);
}

/** Holders in the shape `whereItLands` reads. */
function asCopies(holders: HoldersOut["holders"]) {
  return holders.map((holder) => ({
    id: holder.book_id,
    format: holder.format,
  }));
}

/** What the lookup said about one file. */
interface HolderAnswer {
  readonly bookId: number;
  readonly lands: boolean;
  /** Its location is held, and only by Books it may not land on. */
  readonly stays: boolean;
}

/**
 * Which of the Books holding a file the row stands for, or `null` for none.
 *
 * **Only a holder the landing rule admits takes the file**, owner's ruling,
 * 2026-10-15, whether it matched by location or by fingerprint: a match on a
 * print row alone would otherwise write a new reference onto it. That case
 * answers the first holder with `lands` false, and the add offers the file
 * as its own copy, as a 409 of another format does.
 *
 * **Among the admitted, a holder at this very location first**, so a file
 * whose sighting is on an unset copy is refreshed there rather than gaining a
 * second reference on an exact copy that carries the same bytes elsewhere.
 *
 * **A location held only by Books the file may not land on stays where it
 * is.** Whichever Book the book lands on is then not a holder of it, so the
 * server would refuse it there.
 */
function holderOf(
  answer: HoldersOut,
  fileFormat: BookFormat | "",
): HolderAnswer | null {
  const first = answer.holders[0];
  if (first === undefined) return null;
  const here = answer.holders.filter((holder) => holder.same_location);
  // `whereItLands` admits only the file's format or an unset one, which is
  // the landing rule, so a print holder is never picked here.
  const hereLands = whereItLands(asCopies(here), fileFormat);
  const landing =
    hereLands ?? whereItLands(asCopies(answer.holders), fileFormat);
  const stays = here.length > 0 && hereLands === undefined;
  return landing === undefined
    ? { bookId: first.book_id, lands: false, stays }
    : { bookId: landing, lands: true, stays };
}

/**
 * One book to ask about: its key, where each of its files is, and what format
 * it would be.
 *
 * **Every file and not the first alone.** A Calibre book is a file per format,
 * and the first may have been rewritten since the library was last picked
 * (Calibre's metadata embedding does that) while the second is unchanged, so
 * asking by one file calls a held book new.
 */
export interface HolderQuestion {
  readonly key: string;
  readonly references: readonly DigitalReferenceIn[];
  readonly format: BookFormat | "";
}

/**
 * The one answer a book's files add up to, or `undefined` for a book that was
 * not answered.
 *
 * A holder the file may land on first, then any holder, so a book held in its
 * own format is never reported as another kind's because one of its files is
 * also held by a print copy. `null` only where every file was answered and
 * none is held: one unanswered file leaves the book unasked rather than new.
 */
function oneAnswer(
  answers: readonly (HolderAnswer | null | undefined)[],
): HolderAnswer | null | undefined {
  const held = answers.filter((one) => one != null);
  const chosen = held.find((one) => one.lands) ?? held[0];
  if (chosen !== undefined) return chosen;
  return answers.every((one) => one === null) ? null : undefined;
}

/**
 * Which Book already holds each of these books' files, by key.
 *
 * **One request a `FILES_PER_LOOKUP` files**, every file of every book, sent
 * together through `lookup`, which is `findFileHolders` in the caller's
 * `hooks.ts`.
 *
 * **A key missing from the answer was not answered**, because a chunk holding
 * one of its files failed. What that means is the caller's: the scan page
 * leaves the row unasked and asks again before it adds; the Settings import
 * asks once and adds such a book as new, where a duplicate ISBN still answers
 * 409. Never a reason to refuse the add: the lookup only stops a duplicate,
 * and the add is what the member pressed.
 */
export async function askWhoHolds(
  questions: readonly HolderQuestion[],
  lookup: (files: AskedFileIn[]) => Promise<HoldersOut[]>,
): Promise<Map<string, Held | null>> {
  const files = questions.flatMap((question) =>
    question.references.map((reference) => ({ question, reference })),
  );
  const answers = await lookUpHolders(
    files,
    ({ reference }) => ({
      root_label: reference.root_label,
      relative_path: reference.relative_path,
      partial_md5: reference.partial_md5 ?? null,
    }),
    lookup,
  );
  type Answered = {
    readonly reference: DigitalReferenceIn;
    readonly answer: HolderAnswer | null | undefined;
  };
  const byKey = new Map<string, Answered[]>();
  files.forEach(({ question, reference }, at) => {
    const found = answers[at];
    const answer =
      found === undefined ? undefined : holderOf(found, question.format);
    byKey.set(question.key, [
      ...(byKey.get(question.key) ?? []),
      { reference, answer },
    ]);
  });
  const held = new Map<string, Held | null>();
  for (const [key, ofThisBook] of byKey) {
    const one = oneAnswer(ofThisBook.map(({ answer }) => answer));
    if (one === undefined) continue;
    if (one === null) {
      held.set(key, null);
      continue;
    }
    const staying = new Set(
      ofThisBook.flatMap(({ reference, answer }) =>
        answer?.stays ? [locationOf(reference)] : [],
      ),
    );
    // **A file held by another Book stays on it.** Written onto the one
    // chosen, it became a second reference to the same file on a second
    // Book.
    const elsewhere = new Map(
      ofThisBook.flatMap(({ reference, answer }) =>
        answer?.lands &&
        answer.bookId !== one.bookId &&
        !staying.has(locationOf(reference))
          ? [[locationOf(reference), answer.bookId] as const]
          : [],
      ),
    );
    held.set(key, {
      bookId: one.bookId,
      lands: one.lands,
      ...(elsewhere.size > 0 ? { elsewhere } : {}),
      // Only on a Book the files land on: one they may not takes none.
      ...(one.lands && staying.size > 0 ? { inAnotherFormat: staying } : {}),
    });
  }
  return held;
}

/**
 * Every reference onto one Book, one after another, stopping at the first the
 * server refuses and rethrowing it. A folder sweep sends its chunks through it
 * too, for the same one writer.
 *
 * **One after another, through the loop every bulk write here shares**, for
 * that loop's reason (one SQLite writer) and for the per book ceiling: the
 * server holds it whatever arrives, and a client sending a book's files at
 * once is the client that makes it race. What was reported before a refusal
 * stays reported; each sighting is idempotent on its location.
 */
export async function reportEach<T = DigitalReferenceIn>(
  references: readonly T[],
  post: (reference: T) => Promise<unknown>,
): Promise<void> {
  // An object rather than a `let`: the loop's callbacks set it, and a
  // narrowed `let` reads `undefined` after the await whatever they did.
  const refusal: { refused: boolean; thrown?: unknown } = { refused: false };
  await writeOneAtATime(references, {
    post: (reference) =>
      post(reference).catch((thrown: unknown) => {
        refusal.refused = true;
        refusal.thrown = thrown;
        throw thrown;
      }),
    onProgress: () => {},
    stopped: () => refusal.refused,
  });
  if (refusal.refused) throw refusal.thrown;
}

/**
 * What one add made of a book. Each caller maps it to its own row or count,
 * in a `switch` ending `satisfies never`, so a kind added here is a type error
 * at each caller rather than a row either page drops.
 *
 * - `added`: a new Book, with every file recorded on it but those `left`
 *   counts, whose location the server said another Book holds.
 * - `added-unreferenced`: a new Book, and a refusal other than that stopped
 *   its remaining files; the Book exists, so this is never a failure.
 * - `on-holder`: a Book the member can see already held a file, so no Book
 *   was made and the files were refreshed there. `left` counts the files not
 *   recorded because another Book holds their location: the lookup said so
 *   (a print copy, so none was sent), or the server did.
 * - `other-format`: only a Book the files may not land on holds them, or the
 *   ISBN; nothing was written. `holderId` is the Book a copy would be made of.
 * - `at-ceiling`: on the holder, and a Book there refused a file for holding
 *   as many as a Book may.
 * - `tie`: the server refused the add as a duplicate and named no Book, which
 *   is a tie between Books outside one copy group and also how a holder the
 *   member cannot see answers. No file lands.
 * - `failed`: refused for any other reason, `thrown` saying why. A duplicate
 *   naming a Book is one of these even where its files were put on the copy
 *   of their kind, because no Book was made.
 */
export type Landing =
  | { readonly kind: "added"; readonly left: number }
  | { readonly kind: "added-unreferenced"; readonly left: number }
  | { readonly kind: "on-holder"; readonly left: number }
  | { readonly kind: "other-format"; readonly holderId: number }
  | { readonly kind: "at-ceiling" }
  | { readonly kind: "tie"; readonly thrown: unknown }
  | { readonly kind: "failed"; readonly thrown: unknown };

/** The requests `land` makes, each the caller's own mutation or read. */
export interface LandingPorts<Body> {
  readonly create: (body: Body) => Promise<{ readonly id: number }>;
  readonly report: (
    bookId: number,
    reference: DigitalReferenceIn,
  ) => Promise<unknown>;
  readonly copiesOf: (
    bookId: number,
  ) => Promise<readonly Pick<BookOut, "id" | "format">[]>;
}

/** One book to land. */
export interface LandingRequest<Body> {
  /** What `ports.create` posts. */
  readonly body: Body;
  readonly references: readonly DigitalReferenceIn[];
  readonly format: BookFormat | "";
  /**
   * The holder lookup's answer for this book: a Book, `null` for none, and
   * `undefined` for a book nobody could ask about, which is added.
   */
  readonly held: Held | null | undefined;
  /**
   * False where the identifier the create carries was read out of a file's
   * **name**, which is the one provenance that invents one: a duplicate's
   * holder then takes no file. `ScanPage/hooks.theIsbnWasRead` says why.
   */
  readonly identifierWasRead: boolean;
}

/** What a thrown refusal says, read off its shape as `importing.statusOf` does. */
function refusalOf(thrown: unknown): {
  readonly status?: unknown;
  readonly bookId?: unknown;
  readonly code?: unknown;
} {
  return typeof thrown === "object" && thrown !== null
    ? (thrown as { status?: unknown; bookId?: unknown; code?: unknown })
    : {};
}

/**
 * Add one book, or put its files on the Book that already holds them.
 *
 * **Never throws.** Every refusal is an outcome, so the caller decides which
 * are failures of its row; `failed` carries what was thrown.
 */
export async function land<Body>(
  request: LandingRequest<Body>,
  ports: LandingPorts<Body>,
): Promise<Landing> {
  const { references, held } = request;
  if (references.length > 0 && held) {
    // Held only by a Book of another format: never a reference on that Book
    // and never a second Book of its own.
    if (!held.lands) return { kind: "other-format", holderId: held.bookId };
    return onTheHolder(held, references, ports.report);
  }
  let bookId: number;
  try {
    bookId = (await ports.create(request.body)).id;
  } catch (thrown) {
    return asDuplicate(request, ports, thrown);
  }
  // The Book exists by now, so a refusal here is never the row's failure: a
  // created book reported as failed is added again into a duplicate. A
  // refusal is not always the server saying no either: a dropped connection
  // lands here too. A file another Book holds is left, as on the holder:
  // counting it unrecorded promised that a second pick records it, and the
  // server refuses that pick the same way.
  const sent = await sendEach(references, () => bookId, ports.report);
  return {
    kind: sent.refused === undefined ? "added" : "added-unreferenced",
    left: sent.left,
  };
}

/** What sending a book's files came to. */
interface Sent {
  /** Files left on another Book, which the server said holds them. */
  readonly left: number;
  /** The refusal that stopped the rest, where one did. */
  readonly refused?: { readonly thrown: unknown };
}

/**
 * Each file onto the Book `target` names for it, through `reportEach`.
 *
 * **A file another Book holds is that Book's**, so the route's
 * `file_held_elsewhere` refusal leaves that one file there, counted, and the
 * next is sent. It says nothing about the book's other files; stopping on it
 * left them unrecorded while both pages said they were recorded. Any other
 * refusal stops the rest, the ceiling among them, since every later file
 * would meet the same ceiling.
 */
async function sendEach(
  references: readonly DigitalReferenceIn[],
  target: (reference: DigitalReferenceIn) => number,
  report: LandingPorts<unknown>["report"],
): Promise<Sent> {
  // An object for `reportEach`'s reason: the callbacks write it.
  const count = { left: 0 };
  try {
    await reportEach(references, (reference) =>
      report(target(reference), reference).catch((thrown: unknown) => {
        const { status, code } = refusalOf(thrown);
        if (status !== CONFLICT || code !== FILE_HELD_ELSEWHERE) throw thrown;
        count.left += 1;
      }),
    );
  } catch (thrown) {
    return { left: count.left, refused: { thrown } };
  }
  return { left: count.left };
}

/**
 * Every file of a book already held: each onto the Book `held.elsewhere`
 * names for it, the rest onto `held.bookId`, and none that
 * `held.inAnotherFormat` names. Its ceiling is its own outcome.
 */
async function onTheHolder(
  held: Held,
  references: readonly DigitalReferenceIn[],
  report: LandingPorts<unknown>["report"],
): Promise<Landing> {
  const going = references.filter(
    (reference) => !held.inAnotherFormat?.has(locationOf(reference)),
  );
  const sent = await sendEach(
    going,
    (reference) => held.elsewhere?.get(locationOf(reference)) ?? held.bookId,
    report,
  );
  if (sent.refused !== undefined) {
    const { thrown } = sent.refused;
    const { status, code } = refusalOf(thrown);
    return status === CONFLICT && code === REFERENCE_CEILING
      ? { kind: "at-ceiling" }
      : { kind: "failed", thrown };
  }
  return {
    kind: "on-holder",
    left: references.length - going.length + sent.left,
  };
}

/**
 * Every file of a book onto the copy the member just made of it, which is the
 * Scan page's copy press.
 *
 * **The rule `onTheHolder` keeps, for the same reason**: a location only a
 * print copy holds is refused on the new copy as well, and stopping there
 * counted the whole row unrecorded on every press, with a hint that picking
 * the folder again would record it. `recorded` is false only where another
 * refusal stopped the rest.
 */
export async function recordOnCopy(
  copyId: number,
  references: readonly DigitalReferenceIn[],
  report: LandingPorts<unknown>["report"],
): Promise<{ readonly left: number; readonly recorded: boolean }> {
  const sent = await sendEach(references, () => copyId, report);
  return { left: sent.left, recorded: sent.refused === undefined };
}

/**
 * A refused create: a duplicate naming a Book takes the files on the copy of
 * their kind, one naming none is a tie, and anything else failed.
 *
 * **The Book a duplicate names is where its files are.** Re importing a
 * folder imported last month is the case a sighting is idempotent for, and
 * every book in it answers 409, so a reference posted only after a create
 * would be posted on exactly the pick that needs it least. The server names
 * a Book only where the member can see it.
 *
 * **The copies are asked rather than assumed**: the 409 names one Book and
 * not its format, nor its other copies. Copies that cannot be read are not
 * written to, because the landing rule cannot be answered for them.
 */
async function asDuplicate<Body>(
  request: LandingRequest<Body>,
  ports: LandingPorts<Body>,
  thrown: unknown,
): Promise<Landing> {
  const { status, bookId } = refusalOf(thrown);
  if (status !== CONFLICT) return { kind: "failed", thrown };
  if (typeof bookId !== "number") return { kind: "tie", thrown };
  if (request.references.length === 0 || !request.identifierWasRead) {
    return { kind: "failed", thrown };
  }
  const copies = await ports.copiesOf(bookId).catch(() => undefined);
  if (copies === undefined) return { kind: "failed", thrown };
  const target = whereItLands(copies, request.format);
  if (target === undefined) return { kind: "other-format", holderId: bookId };
  // The book is a failure whichever way this goes, and it carries the 409's
  // reason, so a refusal here is not counted a second time.
  await reportEach(request.references, (reference) =>
    ports.report(target, reference),
  ).catch(() => undefined);
  return { kind: "failed", thrown };
}

/** How many of a run's landings came to each count a caller shows. */
export interface LandingCounts {
  /** Books made, with or without their files. */
  readonly added: number;
  readonly unreferenced: number;
  /** Books already held, whose files were refreshed on the holder. */
  readonly already: number;
  readonly otherFormat: number;
  readonly atCeiling: number;
  /** Files another Book keeps, by each landing's `left`. */
  readonly filesLeft: number;
}

/**
 * **A `switch` ending `satisfies never`, as each caller's is**, so a kind
 * added to `Landing` is a type error here too rather than a landing both
 * pages' counts leave out.
 */
export function countLandings(landings: readonly Landing[]): LandingCounts {
  const counts = {
    added: 0,
    unreferenced: 0,
    already: 0,
    otherFormat: 0,
    atCeiling: 0,
    filesLeft: 0,
  };
  for (const landing of landings) {
    switch (landing.kind) {
      case "added-unreferenced":
        counts.unreferenced += 1;
        counts.added += 1;
        counts.filesLeft += landing.left;
        break;
      case "added":
        counts.added += 1;
        counts.filesLeft += landing.left;
        break;
      case "on-holder":
        counts.already += 1;
        counts.filesLeft += landing.left;
        break;
      case "other-format":
        counts.otherFormat += 1;
        break;
      case "at-ceiling":
        counts.atCeiling += 1;
        break;
      case "tie":
      case "failed":
        // Each caller lists these as failed rows, so no count holds them.
        break;
      default:
        landing satisfies never;
    }
  }
  return counts;
}

/**
 * Thrown by a caller for a `tie`, so its row says what that refusal means
 * rather than the server's sentence for any duplicate.
 *
 * **The server answers a tie between Books outside one copy group and a
 * holder hidden from this member alike**, a 409 with no `book_id`, so the
 * sentence a page gives it must be true of both. `status` is the duplicate's,
 * so a card with no sentence of its own still lists it as one.
 */
export class HeldUnnamed extends Error {
  readonly status = CONFLICT;
  constructor() {
    super("Held by no Book the server would name");
    this.name = "HeldUnnamed";
  }
}
