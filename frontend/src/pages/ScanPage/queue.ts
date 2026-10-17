/**
 * Rapid intake's queue: what a row is, and what each thing that happens to
 * one makes of it.
 *
 * **Pure, and that is the seam.** `useRapidIntake` in `hooks.ts` performs every
 * read and every request and hands what came back here as a `QueueEvent`;
 * `queueAfter` answers the queue it leaves. So a transition is tested by naming its
 * event, with no React, no request and no file, and the hook keeps only what
 * has to wait on something.
 */

import { BookFormat } from "../../api/generated/model";
import type {
  BookLookup,
  BookMatch,
  DigitalReferenceIn,
} from "../../api/generated/model";
import type { AudioFailure } from "../../lib/audiobook";
import type { AudiobookGroup } from "../../lib/audiobookGroups";
import { formatOf, type CalibreBook } from "../../lib/calibre";
import type { FileFailure } from "../../lib/fileReaders";
import {
  plainName,
  queryFor,
  readName,
  type FileNaming,
} from "../../lib/fileName";
import type { Held } from "../../lib/fileLanding";
import {
  blankDraft,
  draftFromAudiobook,
  draftFromCalibre,
  draftFromLookup,
  draftFromMatch,
  draftFromName,
  enrichedDraft,
  titlesCouldAgree,
  type BookDraft,
} from "./types";

/**
 * How many catalogue calls a minute the filename fallback may start.
 *
 * **Priced against the limiter the same member is already spending, not against
 * the deadline.** `backend/ratelimit.py`'s `METADATA_LIMIT` allows 60 metadata
 * calls a minute per member, and it is the limiter on the ISBN lookup behind
 * every scanned barcode and on the title search box as well as on this. So the
 * fallback takes half of it and leaves the other half to the page it runs on:
 * a folder of three hundred files must not be able to answer 429 to the barcode
 * somebody scans in the middle of it.
 *
 * **Half is chosen rather than measured**, and what it is chosen against is
 * stated so the next reader can move it: the other paths on this page.
 *
 * The wall clock it buys, for 300 files: 10.0 minutes here, against 6.0 to 9.0
 * serialised at the 1.2s to 1.8s a healthy search measures by
 * `metadata.SEARCH_DEADLINE_SECONDS`' own figure, which is 33 to 50 starts a
 * minute and over this share. So the pace costs at most four minutes and the
 * interval is above the slowest healthy search, which is why one call in flight
 * is never what binds.
 *
 * `tests/pages/ScanPage/hooks.test.tsx` recomputes the interval from the
 * backend's own constant rather than restating it.
 */
export const FALLBACK_STARTS_PER_MINUTE = 30;

/** One start per this long, which is the whole of the pace. */
export const FALLBACK_INTERVAL_MS = 60_000 / FALLBACK_STARTS_PER_MINUTE;

/**
 * How a row came to be standing under its own file name.
 *
 * A closed set, and it is a named type rather than an inline union so that
 * `OFFERED_AGAIN` can be keyed on it: a fourth answer is then a compile error
 * until somebody has decided whether it may be looked up again.
 */
export type CatalogueAnswer = "nothing" | "records" | "records-for-now";

/**
 * The reasons a row can carry that are a name and nothing else.
 *
 * **Declared rather than derived from `ScanReason["kind"]`**, and not because
 * one spelling catches more. Measured against a widened `kind`, the two produce
 * the same six errors in the same six places and differ in the last one's code
 * alone: `TS7053` on the `REASONS[reason.kind]` lookup, against `TS2345` in
 * that same expression.
 *
 * **It is the unwidened case that decides it.**
 * `Record<ScanReason["kind"], MessageKey>` demands a sentence for `file`,
 * `audio` and `server-said`, three keys nothing ever looks up because those
 * arms are answered before `REASONS` is reached. Measured: `TS2739` naming the
 * three, plus the import that spelling leaves unused.
 *
 * **What a type cannot say about this union is said in
 * `frontend/tests/houseRules.test.ts`**: three arms carry a payload and every
 * other is a name, which is a rule about arity rather than about any type, so
 * no spelling of a payload evades it.
 */
export type NamedScanReason =
  | "no-title"
  | "unreadable"
  | "not-in-catalogues"
  | "lookup-failed"
  | "kept-the-name"
  | "kept-for-now"
  | "unreachable"
  | "held-in-another-format"
  | "held-unnamed"
  | "in-trash"
  | "not-in-catalogues-as-stated"
  | "lookup-failed-as-stated"
  | "record-differs"
  | "kept-the-file";

/**
 * Why a row is where it is, as a name rather than as a sentence.
 *
 * **The words are chosen where the row is drawn**, which is `REASONS` in
 * `RapidQueue.tsx` and the two tables beside it. It is the discipline
 * `lib/fileReaders.ts` and `lib/stores.ts` state for their own readers, and the
 * one `OFFERED_AGAIN` keeps for `CatalogueAnswer` above: a reason with no
 * sentence for a member is a compile error rather than a row that says nothing.
 * Stored as a sentence it was also fixed in the locale in force at the moment
 * the file failed, where a name re-renders in the language being read.
 *
 * **No arm interpolates, and that is the cost of the change rather than a
 * property of it.** `string` took an interpolated sentence for free. The first
 * reason to want one, "could not read chapter 12 of 40", takes a `kind` of its
 * own outside `NamedScanReason`, carries the numbers, and is answered by its
 * own branch in `reasonText`. **Never a field hung on a name that is already
 * there**: `REASONS` is reached by the name alone, so the numbers would compile
 * and reach nothing.
 *
 * **Exactly one arm carries free text, and it is named for what it carries.**
 * That is `server-said`, and no type states it: a second free text arm compiles
 * clean once it has a branch, the first having made free text ordinary. So
 * `frontend/tests/houseRules.test.ts` states it, off this declaration, as the
 * three arms that may carry anything besides a `kind`. It cannot resolve an arm
 * spelled as a type from another module, and refuses that by a blunter rule.
 */
export type ScanReason =
  /** What a reader said about a picked file, over `fileReaders.FileFailure`. */
  | { kind: "file"; failure: FileFailure }
  /** What the audio reader said about one audio file. */
  | { kind: "audio"; failure: AudioFailure }
  /**
   * The server's own message, in whatever language it answered in.
   *
   * **The one free text arm.** Its sites are the batch and the copy press: a
   * refused request carries a `detail` written for the reader, and nothing on
   * this side can translate it.
   */
  | { kind: "server-said"; message: string }
  | { kind: NamedScanReason };

/**
 * What a row is in every state: where it came from and what it would be filed
 * as.
 */
interface RowFacts {
  /**
   * Identity in the queue, and what a removal names.
   *
   * **Not the ISBN, and that is the whole reason this field exists.** A file is
   * the second way into this queue and most files carry no ISBN at all:
   * measured over 79 real EPUBs, 4 did. Keying on one would collapse every
   * ISBN-less pick into a single entry.
   */
  key: string;
  /** What the queue shows and what a removal is announced by. */
  label: string;
  /** Empty when the entry came from a file that named none. */
  isbn: string;
  /**
   * What kind of object this copy is, where the way it arrived answers that.
   *
   * **A picked EPUB is an ebook and the container says so**, which is not the
   * guess `docs/decisions.md` refuses when it leaves `format` nullable: that
   * refuses a value written across every imported row on no evidence, and
   * `csv_import` already reads the literal string `epub` as this answer. A
   * barcode carries no such evidence and stays blank.
   */
  format: BookFormat | "";
  draft: BookDraft | null;
  /**
   * What to ask the catalogue about this file, derived from its name.
   *
   * Absent for a barcode, which needs no such thing, and for a file whose name
   * reduced to nothing a catalogue could be asked about.
   */
  query?: string;
  /**
   * Where the file this row was drafted from is, as the server takes it.
   *
   * **Derived at the pick and carried, because the `File` does not survive the
   * read.** Only the key and the label go into the queue, so by the time the
   * batch runs there is nothing left to ask. `lib/digitalReference.ts` decides
   * what this browser may honestly claim, and answers nothing for a file picked
   * one at a time.
   *
   * **Absent for an audiobook row**, and that is the format's own inversion
   * again rather than an omission: a row standing for forty chapter files has
   * no one file to point at, and a book holds sixteen references at the most.
   */
  reference?: DigitalReferenceIn;
  /**
   * Where this row's other files are, for a book that is several files.
   *
   * **Only a Calibre library's row has one**: Calibre keeps one book as one
   * record with a file per format, so the row is one book and each of its
   * files is a reference on it. Reported wherever `reference` is, after it;
   * the holder lookup asks by `reference` alone, because Calibre keeps every
   * format of a book in one directory and they move together.
   */
  moreReferences?: readonly DigitalReferenceIn[];
  /**
   * The Book that already holds this row's file, `null` where none the member
   * can see does, and absent until somebody has asked.
   *
   * **Asked by the file and not by its ISBN**: a location or KOReader's
   * fingerprint, through `POST /api/books/file-holders`. So a re-picked folder
   * is recognised whatever its files say, including the ones with no ISBN,
   * which a create would otherwise file a second time. A held row is never
   * added: where `lands`, `addAll` refreshes its sighting on that Book, and
   * otherwise the row is offered as its own copy, by the landing rule.
   */
  heldBy?: Held | null;
  /**
   * Whether this row's ISBN was read out of the file's **name**.
   *
   * **Carried rather than read off the state, because the state deliberately
   * stops saying it.** `answeredByIsbn` promotes a row to `found` whenever the
   * ISBN lookup answers, for a row standing under its name and for a `stated`
   * file alike, so after a successful lookup `found` covers a file that
   * stated its identifier and a name that happened to contain one.
   * `lookUpTheName` in the hook says as much: a name carrying an ISBN takes the route a barcode
   * takes. That collapse is right for the lookup and wrong for anything asking
   * where the identifier came from.
   *
   * Set by `fromTheName` and cleared by the `chosen` event, which are the only
   * two places that know. Read by `theIsbnWasRead`, and by `answeredByIsbn`, which
   * takes the record for such an ISBN whole rather than filling it from the
   * name's guesses.
   */
  isbnFromTheName?: true;
}

/**
 * The audio files a row was made of, and why each said nothing.
 *
 * **Present only for an audiobook**, and it is the whole of the inversion this
 * format brings: every other row here is one file, and one audiobook is
 * usually a folder of chapter files. `lib/audiobookGroups.ts` holds the rule.
 *
 * `group` is carried rather than counted, for two reasons that are the same
 * reason: the queue shows the member which files a candidate claims before
 * anything is added, and `splitApart` needs them back to undo a grouping the
 * member disagrees with. It is also what dedup is decided on, so picking the
 * same folder twice queues nothing twice.
 *
 * `fileReasons` is keyed by the file key, and is **set only while the row can
 * still be split**, which is the `split` event's own condition rather than a
 * second rule: more than one file. A row of one file already states what its
 * file said in `reason` and nothing can split it further, so a map there would
 * be the same value twice, and the two would part company at the first patch
 * of `reason`. A note from one file of forty describes that file rather than
 * the book, so a grouped row shows none of them; the split is where each file
 * becomes a row that has to state its own. Narrowed to the files this row
 * claims rather than the whole pick, so one row does not hold the reasons
 * belonging to every other row in the queue.
 *
 * **Not on the group's files**, which are `lib/audiobookGroups.ts`'s type:
 * what a member is told is not a fact about a grouping, and a page's union has
 * no business in `lib/`.
 */
type Grouping =
  | { group?: undefined; fileReasons?: undefined }
  | {
      group: AudiobookGroup;
      fileReasons?: ReadonlyMap<string, ScanReason>;
    };

/**
 * The fields that belong to some states and not to others. `ScannedEntry`
 * says which state may carry each.
 */
interface StateFields {
  /**
   * Why it could not be read, or could not be added once the batch has run.
   *
   * **A name, never a sentence**: see `ScanReason`. Absent is the absence, and
   * it is what a row going back to `searching` is set to; a `"none"` arm would
   * be a second spelling of the same thing.
   */
  reason: ScanReason;
  /**
   * What the catalogue answered, where the answer left the row under its own
   * name or, for a `stated` row, as its file describes it.
   *
   * **Values rather than one flag**, because the ways a row keeps its file name
   * are different sentences to the member. `"nothing"` is a catalogue with no
   * record, which for a title that exists only as a file is the ordinary
   * outcome and is what `fallback.aboutEbooks` explains. `"records"` is a
   * catalogue that had some and a member who preferred the name (or, on a
   * `stated` row, a record for its ISBN whose title shares no significant
   * word with the file's), and saying
   * anything about ebooks to them would describe something that did not happen.
   * `"records-for-now"` is the same records and a member who was clearing the
   * queue rather than answering about this book, so the row can be asked
   * again; `OFFERED_AGAIN` is where that difference is spent.
   *
   * **Absent means nothing has been asked**, which is what the run and the count
   * both read, and it is what a call that could not be made leaves behind: a
   * catalogue nobody reached has answered nothing and is worth asking again.
   */
  answered: CatalogueAnswer;
  /** What the catalogue offered for it, for the member to accept or reject. */
  matches: BookMatch[];
  /**
   * The picked files a reading row claims.
   *
   * **Set before the grouping is known**, which is the one job it has: an
   * audiobook's rows cannot be made until every file in the pick has been
   * read, and in that window the queue still has to be able to say that those
   * files are spoken for. Picking the same folder twice queues nothing twice
   * because of this. Once the files are grouped, `group` holds them and is
   * where the claim is read from: setting both would be one fact in two fields
   * that agree by construction and by nothing else.
   */
  claims: readonly string[];
  /**
   * The catalogue's record for a `stated` row's ISBN, where its title shares
   * no significant word with the title the file stated.
   *
   * **Held, not taken.** A file's ISBN can be a stranger's or a publisher
   * template's, and taking a record that names a different work would file
   * the wrong book with this file's identifiers, subjects and location on it,
   * with nothing on screen saying so. `titlesCouldAgree` says which records
   * are held and which it lets through, a same series volume among them. So the row stays as the file describes it,
   * which is what `addAll` adds, and the member takes the record
   * (`takeTheRecord`) or refuses it (`keepTheFile`). The raw record rather
   * than a merged draft, so a subject dropped meanwhile stays dropped when it
   * is taken. Carried by one arm alone, the `stated` arm whose reason is
   * `record-differs`, and that arm must carry it.
   */
  differentRecord: BookLookup;
  /**
   * The book this row's ISBN already belongs to, where that book is a
   * different kind of object from the file.
   *
   * Set beside the `held-in-another-format` reason, by `afterTheBatch`
   * reading a `batch-ran` event, and it is what `addAsCopy` copies.
   * `afterTheBatch` clears it for every other failure, so a row that later
   * fails for another reason stops offering the copy, and `copy-made` clears
   * it once the copy exists. A refused copy keeps it, so the press can be made
   * again.
   */
  copyOf: number;
}

/**
 * One row in state `S`: the facts, the `StateFields` it may carry, the ones
 * it must, and every other `StateFields` member declared absent.
 *
 * **The absent ones are declared, not merely left out**, because a spread
 * carries what its type does not name: `{ ...choosing, state: "found" }`
 * would compile with the records still on it. Declared `undefined`, the
 * records are a compile error there, and a transition says what it keeps.
 */
type InState<
  S extends string,
  May extends keyof StateFields = never,
  Must extends keyof StateFields = never,
> = RowFacts &
  Grouping & { state: S } & Partial<Pick<StateFields, May>> &
  Pick<StateFields, Must> & {
    [F in Exclude<keyof StateFields, May | Must>]?: undefined;
  };

/**
 * A reason a `stated` row holding no record may carry: any but
 * `record-differs`, which names the record held.
 */
type ReasonWithNoRecordHeld =
  | Exclude<ScanReason, { kind: NamedScanReason }>
  | { kind: Exclude<NamedScanReason, "record-differs"> };

/**
 * One book caught by the rapid scanner or picked as a file, and how it has
 * gone so far: one arm per state, each carrying the fields that state can
 * have.
 *
 * **`derived` is a book, not a failure, and that is the decision behind the
 * whole fallback path.** A file whose own metadata said nothing still has a
 * name, and a row carrying what the name said is added by `addAll` rather
 * than skipped. It is the same call the OPDS sync makes for a holding with no
 * description: reported as created, because it is.
 *
 * **`stated` is a file that named its own title and ISBN**, and is `found`
 * in every way but one: no catalogue has been asked about that ISBN. It is
 * added as the file describes it unless the paced lookup is pressed, which
 * asks what a scanned barcode is asked and keeps the file's own fields only
 * where the record has none (`types.enrichedDraft`).
 *
 * **`not-reached` is a barcode whose lookup reached no catalogue**, which
 * answers nothing about the book. It carries no draft, so the batch leaves
 * it, and the paced lookup offers it again, as it does a name whose lookup
 * failed the same way. `not-found` is the answer: nobody has the ISBN.
 *
 * **A `failed` row keeps what the catalogue answered**, because
 * `QueueFigures.emptyAnswers` counts a row the batch could not write as well
 * as one it has not reached.
 */
export type ScannedEntry =
  | InState<"looking-up">
  | InState<"reading", "claims">
  | InState<"derived", "reason" | "answered">
  | (InState<"stated", "reason" | "answered"> & {
      reason?: ReasonWithNoRecordHeld;
    })
  | (InState<"stated", "answered", "reason" | "differentRecord"> & {
      reason: { kind: "record-differs" };
    })
  | InState<"searching">
  | InState<"choosing", never, "matches">
  | InState<"found">
  | InState<"not-found">
  | InState<"not-reached">
  | InState<"failed", "reason" | "answered" | "copyOf">;

/** The arm of `ScannedEntry` for the state `S`. */
export type EntryIn<S extends ScannedEntry["state"]> = Extract<
  ScannedEntry,
  { state: S }
>;

/** A row with records on it, which is the one shape `deciding` may be true of. */
type OfferedRecords = Extract<ScannedEntry, { matches: BookMatch[] }>;

/**
 * A row the batch takes: `isReady`'s answer, as a type, so the batch reads a
 * draft without asserting one.
 */
export type ReadyEntry = Exclude<ScannedEntry, OfferedRecords> & {
  draft: BookDraft;
};

/**
 * Every `StateFields` member, absent, for `leaving` to spread.
 *
 * **Each one required**, so a field added to `StateFields` and not here is a
 * compile error rather than a field that survives every change of state.
 */
const NO_STATE_FIELDS: { readonly [F in keyof StateFields]-?: undefined } = {
  reason: undefined,
  answered: undefined,
  matches: undefined,
  claims: undefined,
  differentRecord: undefined,
  copyOf: undefined,
};

/**
 * A row's facts with everything its state carried taken off, for a change of
 * state to start from.
 *
 * **A transition names what it keeps**, as `afterTheBatch` keeps `answered`,
 * rather than clearing what it remembers to. So a `stated` row the batch
 * fails does not go on offering the record held for it, under a reason that
 * no longer says why.
 */
function leaving(row: ScannedEntry): RowFacts & Grouping {
  return { ...row, ...NO_STATE_FIELDS };
}

/**
 * What a rule decides about a row, for spreading over what `leaving` kept of
 * it. One arm per arm of `ScannedEntry` in state `S`, so the spread is
 * checked against that arm: the facts are optional, since `leaving` kept
 * them, and the state fields are as the arm declares them.
 */
type Becoming<S extends ScannedEntry["state"]> = BecomingOne<EntryIn<S>>;

/** `Becoming` for one arm, distributed over the arms `E` holds. */
type BecomingOne<E extends ScannedEntry> = E extends unknown
  ? Partial<Pick<E, keyof RowFacts>> & Omit<E, keyof RowFacts | keyof Grouping>
  : never;

/**
 * Every picked file an entry claims.
 *
 * One entry is one file everywhere except an audiobook, where it is many. Read
 * off the entries rather than kept beside them, because a second record of what
 * has been queued is a second record to keep in step.
 */
function claimedKeys(entries: readonly ScannedEntry[]): Set<string> {
  const keys = new Set<string>();
  for (const entry of entries) {
    const claimed = entry.group?.files.map((file) => file.key) ??
      entry.claims ?? [entry.key];
    for (const key of claimed) keys.add(key);
  }
  return keys;
}

/**
 * What every rule in this file makes of a row's state.
 *
 * **A total table keyed on the union rather than a comparison at each site**,
 * which is `OFFERED_AGAIN`'s rule one field over, and the field it is one over
 * is the one that was open: a new `ScannedEntry["state"]` used to compile
 * clean and be silently wrong in five places at once. Three predicates below
 * answered `false` for it, the run's own reading answered `false`, and the
 * queue's rows are drawn by a table in `RapidQueue.tsx` that had a line for
 * each of the eight states and no line for anything else, so the row appeared
 * on screen with nothing at all in it. Nothing was red anywhere. A new state
 * now fails to compile here and at that table, which are the two places its
 * author has to answer for it.
 *
 * **Three facts and not one flag per predicate.** Each is something a state
 * either is or is not, and the predicates below are conjunctions over them and
 * the fields beside them. `derived` is `askable` without `deciding`,
 * which is a reading of the two rather than a third entry (`stated` and
 * `not-reached` read the same, and `ROW_LINE` tells them apart): two fields that
 * agree by construction and by nothing else are what `StateFields.claims`
 * refuses one level down.
 *
 * **`deciding` is true of exactly the arms that carry `matches`**, which is
 * what lets `isBeingDecided` narrow to that arm in both branches: a state
 * marked deciding without records on it, or one with records not marked, is
 * a compile error here.
 */
interface QueueStateRules<S extends ScannedEntry["state"]> {
  /**
   * The file behind this row is still being read.
   *
   * What a stop has to be able to interrupt, and what the page reads to know a
   * pick is still going.
   */
  readonly stillReading: boolean;
  /**
   * A catalogue has something to be asked about this row, and its answer
   * would replace or fill the draft the row carries.
   *
   * True of a row standing under its file's name, whether nothing has been
   * offered for it or records are on screen, of a `stated` row, whose
   * file named an ISBN that no catalogue has been asked about, and of a
   * `not-reached` barcode, whose catalogues did not answer.
   */
  readonly askable: boolean;
  /** Records are offered on this row and the member has neither taken nor refused them. */
  readonly deciding: EntryIn<S> extends OfferedRecords ? true : false;
}

const QUEUE_STATES: {
  readonly [S in ScannedEntry["state"]]: QueueStateRules<S>;
} = {
  "looking-up": {
    stillReading: false,
    askable: false,
    deciding: false,
  },
  reading: { stillReading: true, askable: false, deciding: false },
  derived: { stillReading: false, askable: true, deciding: false },
  stated: { stillReading: false, askable: true, deciding: false },
  searching: {
    stillReading: false,
    askable: false,
    deciding: false,
  },
  choosing: { stillReading: false, askable: true, deciding: true },
  found: { stillReading: false, askable: false, deciding: false },
  "not-found": {
    stillReading: false,
    askable: false,
    deciding: false,
  },
  "not-reached": { stillReading: false, askable: true, deciding: false },
  failed: { stillReading: false, askable: false, deciding: false },
};

/**
 * What a barcode row becomes when its ISBN lookup throws, `unknown` being a 404.
 *
 * Shared by the lookup at the scan and the paced one that asks again, so the
 * two cannot read one throw two ways. A 404's blank draft keeps the row and
 * the batch leaves it for having no title; any other throw carries no draft.
 */
function barcodeMiss(
  isbn: string,
  unknown: boolean,
): Becoming<"not-found"> | Becoming<"not-reached"> {
  return unknown
    ? { state: "not-found", draft: blankDraft(isbn) }
    : { state: "not-reached", draft: null };
}

/**
 * An entry with records offered and neither taken nor refused.
 *
 * **Exported for `RapidQueue.tsx`**, which used to spell this state out by hand
 * beside the records it draws. One rule with one home, and the component asks
 * the question rather than knowing the answer: a predicate written twice is a
 * screen able to report something the page did not do, which is the reason
 * `QueueFigures` exists at all.
 */
export function isBeingDecided(entry: ScannedEntry): entry is OfferedRecords {
  return QUEUE_STATES[entry.state].deciding;
}

/**
 * A row the batch takes.
 *
 * **A row still being decided is not one**, for the reason a row with no
 * draft is not: it is exactly what somebody still has to decide about, and
 * filing it under its file name would throw away every record the catalogue
 * found for it with nothing said on screen.
 *
 * **Nor is a draft with no title**, which is `fromTheName`'s rule: the API
 * requires one, so offering it is a 422 on every press. A barcode no
 * catalogue knows is that draft, and its row already says it was not found.
 *
 * One predicate for `addAll` and for `QueueFigures.ready`, so the button that
 * figure holds is never live over a queue the batch would take nothing from.
 */
export function isReady(entry: ScannedEntry): entry is ReadyEntry {
  return (
    entry.draft !== null && entry.draft.title !== "" && !isBeingDecided(entry)
  );
}

/**
 * Whether an answer leaves the row worth offering a second pass.
 *
 * **A map keyed on the union rather than a disjunction**, which is what makes
 * this self enforcing: a fourth answer does not compile until it appears here,
 * so nobody can add one and inherit an offer, or the absence of one, by
 * omission. The default is exactly what the author of a new answer would not
 * think to state.
 *
 * A member who refused the records answered about that book and is not asked
 * again. A member who kept the names in bulk was clearing a queue rather than
 * answering, and the whole of the owner's decision on 2026-09-10 is that those
 * can come back.
 */
const OFFERED_AGAIN: Record<CatalogueAnswer, boolean> = {
  nothing: false,
  records: false,
  "records-for-now": true,
};

/**
 * What a row the catalogue did not settle says, by which draft it went back to.
 *
 * **Two sentences per outcome and not one**, because "kept under its file
 * name" is false of a `stated` row, which keeps what the file described.
 * `unknown` is a 404, nobody knowing the ISBN; `unreachable` is every other
 * failure to ask, which the hook's `nobodyKnows` reads apart.
 */
const UNSETTLED = {
  derived: { unknown: "not-in-catalogues", unreachable: "lookup-failed" },
  stated: {
    unknown: "not-in-catalogues-as-stated",
    unreachable: "lookup-failed-as-stated",
  },
} as const satisfies Record<
  "derived" | "stated",
  Record<"unknown" | "unreachable", NamedScanReason>
>;

/**
 * What one row becomes once the catalogue has a record for its ISBN.
 *
 * **A name's ISBN takes the record whole**: `theIsbnWasRead` distrusts that
 * provenance, so a stranger's record is not mixed with the name's guessed
 * author and year. **A file's stated ISBN keeps the file's fields where the
 * record has none**, `types.enrichedDraft`, unless the two titles cannot be
 * one book, when the record is held for the member
 * (`StateFields.differentRecord`) and the row stays as the file describes
 * it.
 */
function answeredByIsbn(one: ScannedEntry, lookup: BookLookup): ScannedEntry {
  if (one.isbnFromTheName) {
    return { ...leaving(one), state: "found", draft: draftFromLookup(lookup) };
  }
  const own = one.draft?.title ?? "";
  if (one.draft !== null && !titlesCouldAgree(lookup.title, own)) {
    return {
      ...leaving(one),
      state: "stated",
      answered: "records",
      reason: { kind: "record-differs" },
      differentRecord: lookup,
    };
  }
  return {
    ...leaving(one),
    state: "found",
    draft: enrichedDraft(lookup, one.draft),
  };
}

/**
 * An entry the catalogue has not been asked about and could be.
 *
 * One predicate rather than a filter written twice, because the count on the
 * button and the list the run walks have to be the same set: a button offering
 * to look up twelve and a run that looks up nine is a screen reporting
 * something the page did not do.
 *
 * **An answered row is never in here, whatever the answer**, which is the
 * invariant the bulk keep was not allowed to cost: a member who picks ten more
 * files and presses this must look up ten, not the two hundred and fifty they
 * had just cleared off the screen. Those are `canBeAskedAgain`, which is a
 * second control saying so in its own words.
 */
export function needsALookup(entry: ScannedEntry): boolean {
  const state = QUEUE_STATES[entry.state];
  return (
    state.askable &&
    !state.deciding &&
    entry.answered === undefined &&
    // A file already in the library has nothing to ask a catalogue, `stated`
    // rows included. Known only once the file holders answer has arrived: a
    // press before it, or after that call failed, looks the row up anyway.
    !entry.heldBy &&
    (entry.isbn !== "" || entry.query !== undefined)
  );
}

/**
 * An entry the catalogue answered, whose answer the member left open.
 *
 * **Disjoint from `needsALookup` by construction**, on `answered` being set
 * against unset rather than on two lists that happen not to overlap: a row in
 * both would be looked up twice by two presses that each said it was the whole
 * of the work.
 */
export function canBeAskedAgain(entry: ScannedEntry): boolean {
  const state = QUEUE_STATES[entry.state];
  return (
    state.askable &&
    !state.deciding &&
    entry.answered !== undefined &&
    OFFERED_AGAIN[entry.answered] &&
    (entry.isbn !== "" || entry.query !== undefined)
  );
}

/**
 * What the queue adds up to, counted once and read everywhere.
 *
 * **One value rather than a member each, because they are one reading of one
 * array.** Every figure here is derived from `entries` by a predicate this
 * module owns, and the screen's rule is that it may render them and may not
 * recompute them: a predicate written twice is a button offering to look up
 * twelve beside a run that looks up nine. Passed as a group so that another
 * figure reaches the component without another prop, and so the docstring
 * saying what each one counts has one home. There is deliberately no count of
 * them written here: the version of this sentence that said five was stale on
 * the day the sixth arrived, and it had anticipated that arrival in its own
 * next clause.
 *
 * **The two pace members are minutes and not counts**, which is why this is not
 * named for counting. They are derived from the counts beside them by one
 * arithmetic, so carrying them apart is how a figure on a button comes to quote
 * a pace the run it starts does not keep.
 */
export interface QueueFigures {
  /**
   * Rows a catalogue has not answered yet: a name with nothing else behind
   * it, an ISBN a file stated, or a barcode whose catalogues were not reached.
   */
  readonly waiting: number;
  /**
   * Files with records offered and neither taken nor refused.
   *
   * **Derived from the predicate `addAll` excludes, not from a second one
   * spelled the same.** The screen says how many rows the batch is going to
   * leave where they are, so a predicate written twice is a screen that can
   * report something the page did not do. Same reason `needsALookup` is one
   * function rather than a filter at each site.
   */
  readonly deciding: number;
  /**
   * Files kept under their names in bulk, which the catalogues may be asked
   * about again.
   *
   * **Not part of `waiting`, and that is the point of counting it separately.**
   * A member who clears a queue of two hundred and fifty and then picks ten more
   * files presses a button that says ten. These come back through a press of
   * their own, which names them.
   */
  readonly keptForNow: number;
  /**
   * Files a catalogue was asked about and had no record of.
   *
   * **Here rather than read off the rows by whoever draws them**, which is the
   * rule this interface states and the one place the queue component was still
   * breaking it: it held the only `entries.some` on the page, spelling an
   * answer out by hand to decide whether to say that catalogues list few
   * ebooks. A second reading of `answered` is a second place for that sentence
   * to appear beside a queue it is not true of.
   *
   * A count and not a flag, for the reason the figures beside it are counts:
   * what the screen does with it is the screen's, and a member who was offered
   * records and preferred the name is not counted here at all.
   */
  readonly emptyAnswers: number;
  /**
   * Rows the batch would take, by the predicate `addAll` filters on, so the
   * button it backs is held exactly when the batch would take no row.
   */
  readonly ready: number;
  /** Roughly how long looking all of them up would take, in minutes. */
  readonly paceMinutes: number;
  /** The same figure for a second pass over the names kept in bulk. */
  readonly keptPaceMinutes: number;
}

/**
 * The `items` that stand for no file the queue claims yet: a file already
 * queued is not queued again, whatever picked it.
 *
 * `keysOf` names every file an item stands for, one key or several. **An item
 * is dropped when any one of them is claimed**, not only the first, because an
 * audio row is keyed `audio:...` and stands for files under other keys: its own
 * key is claimed by nobody, and checking only that would queue a file a second
 * time under a new row. Dropping the whole item rather than trimming its files
 * is deliberate, since its key is derived from the files it stands for
 * (`groupKey`) and a trimmed row would carry a key that names a different set.
 *
 * The `picked` arm holds its rows to this, by `claims ?? [key]`. The hook asks
 * it first as well, because which files it reads, and which audio files make
 * the reading row, are decided by the answer before there is a row to hand in.
 */
export function notYetQueued<T>(
  entries: readonly ScannedEntry[],
  items: readonly T[],
  keysOf: (item: T) => string | readonly string[],
): T[] {
  const claimed = claimedKeys(entries);
  return items.filter((item) => {
    const keys = keysOf(item);
    return typeof keys === "string"
      ? !claimed.has(keys)
      : !keys.some((key) => claimed.has(key));
  });
}

/**
 * The queue key for an audiobook row, from the keys of the files it stands for.
 *
 * **The smallest member key and the count**, not a digest of them: the
 * smallest key is claimed by exactly one entry, and the count is what makes a
 * split's rows different keys from the group they came from. The reading row
 * a pick of audio stands as takes its key the same way.
 */
export function groupKey(keys: readonly string[]): string {
  return `audio:${[...keys].sort()[0]}:${keys.length}`;
}

/** The queue key for a scanned barcode. One book, one ISBN, one entry. */
export function scannedKey(isbn: string): string {
  return `isbn:${isbn}`;
}

/**
 * A row standing for files that are still being read.
 *
 * Its key, its label and its format are what the hook can say while it still
 * holds the `File`; `reference` is a picked file's location, `claims` the
 * files a pick of audio stands for until they are grouped.
 */
export type Picked = Pick<EntryIn<"reading">, "key" | "label" | "format"> &
  Partial<Pick<EntryIn<"reading">, "reference" | "claims">>;

/** One book a library's index holds, and where each of its files is. */
export interface LibraryBook {
  readonly book: CalibreBook;
  readonly files: readonly DigitalReferenceIn[];
}

/**
 * One row the batch reached and could not write, as the batch held it.
 *
 * **The copy offer is its own arm**, so the reason saying the ISBN is held in
 * another format and the book it offers to copy are set together or not at
 * all: a failure for any other reason clears the offer a previous run left.
 */
export type BatchFailure =
  | { readonly row: ScannedEntry; readonly heldInAnotherFormat: number }
  | { readonly row: ScannedEntry; readonly reason: ScanReason | undefined };

/**
 * Something that happened to the queue, or to the row `key` names in it.
 *
 * **Outcomes, never requests.** Each arm is what a read, a lookup, a member's
 * press or the batch came back with, so the hook decides when to ask and this
 * module decides what the answer makes of a row. A throw arrives already read,
 * a 404 as `unknown` and a refusal as its reason, because what a throw means
 * is decided beside the request that threw it.
 */
export type QueueEvent =
  /** A barcode arrived. A repeat changes nothing. */
  | { readonly kind: "captured"; readonly isbn: string }
  /**
   * Rows for picked files. A row whose key the queue already claims is
   * dropped (`notYetQueued`), and a pick that leaves none changes nothing.
   */
  | { readonly kind: "picked"; readonly rows: readonly Picked[] }
  /**
   * One picked file has been read: `said` is the draft its own metadata made
   * where it opened, and `note` why it said nothing where it did not.
   */
  | {
      readonly kind: "file-read";
      readonly key: string;
      readonly naming: FileNaming;
      readonly reference: DigitalReferenceIn | undefined;
      readonly said: BookDraft | undefined;
      readonly note: ScanReason | undefined;
    }
  /** A pick of audio has been read and grouped, the books in its row's place. */
  | {
      readonly kind: "audio-grouped";
      readonly pendingKey: string;
      readonly groups: readonly AudiobookGroup[];
      readonly reasons: ReadonlyMap<string, ScanReason>;
    }
  /**
   * One audiobook candidate filed as a book per part. `apart` is
   * `lib/audiobookGroups.splitApart`, handed in because that module is loaded
   * only when a pick needs it.
   */
  | {
      readonly kind: "split";
      readonly key: string;
      readonly apart: (group: AudiobookGroup) => readonly AudiobookGroup[];
    }
  /**
   * A library's books, whose rows take the place of its reading row.
   *
   * **The books and not their rows**, as every other event carries what
   * happened: this module makes the rows, so the hook has no row to hand over
   * and no state to write into one.
   */
  | {
      readonly kind: "library-read";
      readonly pendingKey: string;
      readonly books: readonly LibraryBook[];
    }
  /** The file holder lookup answered, by row key. */
  | {
      readonly kind: "holders-answered";
      readonly held: ReadonlyMap<string, Held | null>;
    }
  /** The paced run is asking about this row now. */
  | { readonly kind: "asked"; readonly key: string }
  /** A catalogue had a record for the row's ISBN, at the scan or in the run. */
  | {
      readonly kind: "isbn-answered";
      readonly key: string;
      readonly lookup: BookLookup;
    }
  /** A title search answered, with any number of records. */
  | {
      readonly kind: "search-answered";
      readonly key: string;
      readonly matches: BookMatch[];
    }
  /**
   * Asking threw. `asked` is the state the row stood in when it was asked,
   * which is what decides where it goes back to; `unknown` is a 404.
   */
  | {
      readonly kind: "not-answered";
      readonly key: string;
      readonly asked: ScannedEntry["state"];
      readonly unknown: boolean;
    }
  /** The member took one of the records offered. */
  | { readonly kind: "chosen"; readonly key: string; readonly match: BookMatch }
  | { readonly kind: "kept-the-name"; readonly key: string }
  | { readonly kind: "record-taken"; readonly key: string }
  | { readonly kind: "kept-the-file"; readonly key: string }
  | { readonly kind: "kept-every-name-for-now" }
  | {
      readonly kind: "subject-dropped";
      readonly key: string;
      readonly subject: string;
    }
  | { readonly kind: "removed"; readonly key: string }
  | { readonly kind: "cleared" }
  /** The batch ended, having reached `walked` and failed on `failures`. */
  | {
      readonly kind: "batch-ran";
      readonly walked: readonly string[];
      readonly failures: readonly BatchFailure[];
    }
  /** A held row's copy exists, so its offer goes. */
  | { readonly kind: "copy-made"; readonly key: string }
  /** The copy was refused: the offer stays and the reason says why. */
  | {
      readonly kind: "copy-refused";
      readonly key: string;
      readonly reason: ScanReason | undefined;
    };

/** Rewrite the one row with this key, leaving every other alone. */
function patch(
  entries: ScannedEntry[],
  key: string,
  change: (row: ScannedEntry) => ScannedEntry,
): ScannedEntry[] {
  return entries.map((row) => (row.key === key ? change(row) : row));
}

/**
 * The queue after `event`.
 *
 * **The same array back for a repeated barcode, for a pick that queues no
 * row and for an empty holder answer**, so the hook can tell a repeat from an
 * arrival by identity, and a render is not spent on nothing.
 */
export function queueAfter(
  entries: ScannedEntry[],
  event: QueueEvent,
): ScannedEntry[] {
  switch (event.kind) {
    case "captured": {
      const key = scannedKey(event.isbn);
      // The camera fires continuously while a barcode is in frame, so the same
      // book arrives many times a second. Without this the queue fills with
      // one book.
      if (entries.some((entry) => entry.key === key)) return entries;
      return [
        ...entries,
        {
          key,
          label: event.isbn,
          isbn: event.isbn,
          format: "",
          state: "looking-up",
          draft: null,
        },
      ];
    }
    case "picked": {
      const fresh = notYetQueued(
        entries,
        // **Named, not spread.** `Picked` is an open type, so a row built in a
        // callback or spread from another reaches here carrying fields it does
        // not name, and a spread would put a `copyOf` or a `heldBy` on a row
        // still being read.
        event.rows.map(({ key, label, format, reference, claims }) => ({
          key,
          label,
          format,
          reference,
          claims,
          isbn: "",
          state: "reading" as const,
          draft: null,
        })),
        (row) => row.claims ?? [row.key],
      );
      if (fresh.length === 0) return entries;
      return [...entries, ...fresh];
    }
    case "file-read":
      return patch(entries, event.key, (row) => ({
        ...leaving(row),
        ...whatTheFileSaid(event.naming, event.said, event.note),
        reference: event.reference,
      }));
    case "audio-grouped": {
      const candidates = event.groups.map((group) =>
        entryForGroup(group, event.reasons),
      );
      // **In the reading row's place, and only if it is still there.** A
      // member who discarded the queue while this was reading gets an empty
      // queue rather than rows arriving into the one they just emptied.
      return entries.flatMap((entry) =>
        entry.key === event.pendingKey ? candidates : [entry],
      );
    }
    case "split":
      return entries.flatMap((entry) => {
        if (entry.key !== event.key || !entry.group) return [entry];
        if (entry.group.files.length < 2) return [entry];
        // The reasons the pick read are the row's, so each part gets back what
        // its own file said: there is nothing left to read them from by now.
        const reasons = entry.fileReasons ?? new Map<string, ScanReason>();
        return event
          .apart(entry.group)
          .map((group) => entryForGroup(group, reasons));
      });
    case "library-read": {
      const queued = new Set(entries.map((entry) => entry.key));
      return [
        ...entries.filter((entry) => entry.key !== event.pendingKey),
        ...libraryRows(event.pendingKey, event.books).filter(
          (row) => !queued.has(row.key),
        ),
      ];
    }
    case "holders-answered":
      if (event.held.size === 0) return entries;
      return entries.map((entry) =>
        event.held.has(entry.key)
          ? { ...entry, heldBy: event.held.get(entry.key) }
          : entry,
      );
    case "asked":
      // **The note and the answer go with the state.** A row being asked about
      // has no answer and is not standing under its name for a reason it can
      // still state: leaving either behind renders a list of catalogue records
      // under the sentence saying the name was kept, and leaves the row counted
      // as kept while it is being decided again.
      return patch(entries, event.key, (row) => ({
        ...leaving(row),
        state: "searching",
      }));
    case "isbn-answered":
      // **Over the row as it stands now, not as the asking found it**: a
      // subject dropped while the lookup was in flight stays dropped.
      return patch(entries, event.key, (row) =>
        answeredByIsbn(row, event.lookup),
      );
    case "search-answered":
      return patch(entries, event.key, (row) =>
        event.matches.length === 0
          ? {
              ...leaving(row),
              state: "derived",
              answered: "nothing",
              reason: { kind: "not-in-catalogues" },
            }
          : { ...leaving(row), state: "choosing", matches: event.matches },
      );
    case "not-answered":
      return patch(entries, event.key, (row) =>
        notAnswered(row, event.asked, event.unknown),
      );
    case "chosen":
      return patch(entries, event.key, (row) => ({
        ...leaving(row),
        state: "found",
        isbn: event.match.isbn13 ?? "",
        draft: draftFromMatch(event.match),
        // A member looked at this record and took it, so the identifier is the
        // catalogue's rather than the name's.
        //
        // **It clears nothing today, and that is stated rather than left to be
        // reasoned from.** A flagged row has a non empty `isbn`, so the paced
        // run asks the ISBN lookup and never produces the `choosing` state this
        // event is pressed from, so no flagged row reaches here. Kept because
        // it is correct and free, and because the path that would produce one
        // is exactly the remedy `theIsbnWasRead`'s refusal is missing.
        isbnFromTheName: undefined,
      }));
    case "kept-the-name":
      return patch(entries, event.key, (row) => ({
        ...leaving(row),
        state: "derived",
        answered: "records",
        reason: { kind: "kept-the-name" },
      }));
    case "record-taken":
      return patch(entries, event.key, (row) =>
        row.differentRecord === undefined
          ? row
          : {
              ...leaving(row),
              state: "found",
              // Merged now, over the draft as it stands, for the reason
              // `answeredByIsbn` holds the raw record.
              draft: enrichedDraft(row.differentRecord, row.draft),
            },
      );
    case "kept-the-file":
      return patch(entries, event.key, (row) =>
        row.differentRecord === undefined
          ? row
          : {
              ...row,
              differentRecord: undefined,
              reason: { kind: "kept-the-file" },
            },
      );
    case "kept-every-name-for-now":
      return entries.map((entry) =>
        isBeingDecided(entry)
          ? {
              // The records go with the state rather than being held for an
              // undo: they are what the catalogue answers again, and holding
              // them would be a second store of a record with no rule for how
              // long it lives.
              ...leaving(entry),
              state: "derived",
              answered: "records-for-now",
              reason: { kind: "kept-for-now" },
            }
          : entry,
      );
    case "subject-dropped":
      return patch(entries, event.key, (row) => {
        if (row.draft === null) return row;
        // **Filtered by value and not by index**, because the row is rendered
        // from this same list: an index would be the renderer's and would
        // remove the wrong subject the moment anything reordered.
        // `boundCategories` folded the exact repeats out, so one value names
        // one chip.
        const kept = row.draft.categories?.filter(
          (one) => one !== event.subject,
        );
        return { ...row, draft: { ...row.draft, categories: kept } };
      });
    case "removed":
      return entries.filter((entry) => entry.key !== event.key);
    case "cleared":
      return [];
    case "batch-ran":
      return afterTheBatch(entries, event.walked, event.failures);
    case "copy-made":
      return patch(entries, event.key, (row) =>
        row.copyOf === undefined ? row : { ...row, copyOf: undefined },
      );
    case "copy-refused":
      return patch(entries, event.key, (row) =>
        row.copyOf === undefined ? row : { ...row, reason: event.reason },
      );
  }
}

/**
 * What a read file makes of its row.
 *
 * **A stated ISBN is offered the catalogue, never sent to it here**, so the
 * row is `stated` rather than looked up: the paced run is what asks, one press
 * for the queue, and a folder of five hundred is not five hundred metered
 * lookups at the moment it is picked. A file that opened and named no title
 * falls to its name, as one that did not open does.
 */
function whatTheFileSaid(
  naming: FileNaming,
  said: BookDraft | undefined,
  note: ScanReason | undefined,
): Becoming<"found" | "stated" | "derived" | "failed"> {
  if (said !== undefined && said.title !== "") {
    return said.isbn === ""
      ? { state: "found", isbn: said.isbn, draft: said }
      : { state: "stated", isbn: said.isbn, draft: said };
  }
  return fromTheName(naming, said === undefined ? note : { kind: "no-title" });
}

/**
 * Where a row goes back to when asking about it threw.
 *
 * A barcode, asked at the scan or again, goes where the scan's own reading
 * sends it, because the name path's reading files it under a file name it does
 * not have. A `stated` row goes back to its file's draft and says so; only a
 * row standing under its name is said to be kept under it.
 */
function notAnswered(
  row: ScannedEntry,
  asked: ScannedEntry["state"],
  unknown: boolean,
): ScannedEntry {
  if (asked === "looking-up" || asked === "not-reached") {
    return { ...leaving(row), ...barcodeMiss(row.isbn, unknown) };
  }
  const back = asked === "stated" ? "stated" : "derived";
  return {
    ...leaving(row),
    state: back,
    answered: unknown ? "nothing" : undefined,
    reason: { kind: UNSETTLED[back][unknown ? "unknown" : "unreachable"] },
  };
}

/**
 * The queue once the batch has run.
 *
 * **Only the rows that landed leave, and that means the ones never offered
 * stay too.** A barcode whose lookup was still in flight when the button was
 * pressed, and a file that could not be read, are exactly what somebody still
 * has to decide about. **Walked rather than offered is what a stop costs**:
 * the two sets are equal for a run that finished, and pruning by what was
 * offered clears the rows a member pressed stop in order to keep.
 *
 * A failure is kept with its reason rather than counted, because "6 could not
 * be added" after a shelf of thirty says nothing about which six.
 */
function afterTheBatch(
  entries: ScannedEntry[],
  walked: readonly string[],
  failures: readonly BatchFailure[],
): ScannedEntry[] {
  const failed = new Map(
    failures.map((failure): [string, ScannedEntry] => [
      failure.row.key,
      "heldInAnotherFormat" in failure
        ? {
            ...leaving(failure.row),
            state: "failed",
            answered: failure.row.answered,
            reason: { kind: "held-in-another-format" },
            copyOf: failure.heldInAnotherFormat,
          }
        : {
            // `leaving` takes off an offer a previous run made, which would
            // otherwise outlive the reason it was made for.
            ...leaving(failure.row),
            state: "failed",
            answered: failure.row.answered,
            reason: failure.reason,
          },
    ]),
  );
  const reached = new Set(walked);
  return entries
    .filter((entry) => !reached.has(entry.key) || failed.has(entry.key))
    .map((entry) => failed.get(entry.key) ?? entry);
}

/**
 * The rows a library's index makes, one a book, keyed by its Calibre id under
 * the library's own key.
 *
 * A book whose index entry names no title fails on its row, as a file naming
 * none does: the API requires one, which `Unknown` in the index is not. A
 * stated ISBN is offered the catalogue lookup, the rule `whatTheFileSaid`
 * keeps for a file.
 *
 * **Exported for the hook's holder lookup**, which asks about each row's
 * files; the queue makes its own rows from the same books, at `library-read`.
 */
export function libraryRows(
  pendingKey: string,
  books: readonly LibraryBook[],
): ScannedEntry[] {
  return books.map(({ book, files }) => libraryRow(pendingKey, book, files));
}

/** One book's row, for `libraryRows`. */
function libraryRow(
  pendingKey: string,
  book: CalibreBook,
  files: readonly DigitalReferenceIn[],
): ScannedEntry {
  const key = `${pendingKey}:${book.id}`;
  const format = formatOf(book) ?? "";
  const draft = draftFromCalibre(book);
  if (draft.title === "") {
    return {
      key,
      label: plainName(book.path.split("/").at(-1) || pendingKey),
      isbn: "",
      format,
      state: "failed",
      reason: { kind: "no-title" },
      draft: null,
    };
  }
  const [reference, ...more] = files;
  const facts: RowFacts = {
    key,
    label: plainName(draft.title),
    isbn: draft.isbn,
    format,
    draft,
    reference,
    moreReferences: more.length > 0 ? more : undefined,
  };
  return draft.isbn === ""
    ? { ...facts, state: "found" }
    : { ...facts, state: "stated" };
}

/**
 * Whether any picked file is still being read.
 *
 * Derived rather than counted. A count is a second record of the same fact
 * and drifts the first time a read ends on a path that forgets to decrement
 * it; the queue already says which entries are still being read.
 */
export function isReading(entries: readonly ScannedEntry[]): boolean {
  return entries.some((entry) => QUEUE_STATES[entry.state].stillReading);
}

/**
 * Roughly how long a paced run over this many files takes, in minutes.
 *
 * One arithmetic for both presses. Two counts is two numbers and it is the
 * same pace: writing it twice is how the second control comes to quote a
 * figure the run it starts does not keep. A floor of one minute, because
 * "about 0 minutes" is not a wait anybody recognises.
 */
function paceFor(count: number): number {
  return Math.max(1, Math.ceil((count * FALLBACK_INTERVAL_MS) / 60_000));
}

/**
 * What the queue adds up to: `QueueFigures`, each by the predicate the
 * control it backs acts on.
 */
export function figuresOf(entries: readonly ScannedEntry[]): QueueFigures {
  const waiting = entries.filter(needsALookup).length;
  const keptForNow = entries.filter(canBeAskedAgain).length;
  return {
    waiting,
    deciding: entries.filter(isBeingDecided).length,
    keptForNow,
    emptyAnswers: entries.filter((entry) => entry.answered === "nothing")
      .length,
    ready: entries.filter(isReady).length,
    paceMinutes: paceFor(waiting),
    keptPaceMinutes: paceFor(keptForNow),
  };
}

/**
 * The entry a file's own name makes, and the note saying why it came to that.
 *
 * A name reducing to nothing is the one way a picked file still fails: the API
 * requires a title, and saying so here is better than a 422 halfway through
 * somebody's batch.
 */
function fromTheName(
  naming: FileNaming,
  note: ScanReason | undefined,
  // **The state is in the return type rather than merely in both arms.** A
  // caller spreading this over a row has to end with one, and a `Partial`
  // says it might not, which is a row with no state and no compiler to say so.
): Becoming<"failed" | "derived"> {
  const clues = readName(naming);
  const draft = draftFromName(clues);
  if (draft.title === "") {
    return { state: "failed", reason: note ?? { kind: "no-title" } };
  }
  return {
    state: "derived",
    isbn: draft.isbn,
    draft,
    query: clues.query ?? undefined,
    reason: note,
    // The one site that knows, and it stays true through the lookup that
    // promotes this row to `found`: what the catalogue answered about an ISBN
    // does not change where the ISBN came from.
    isbnFromTheName: draft.isbn === "" ? undefined : true,
  };
}

/**
 * One candidate book, from the files the grouping rule put together, keyed
 * by `groupKey`.
 *
 * **What the files said is preferred to what they are called**, and only
 * where they said nothing does this fall to the folder name through the same
 * `fromTheName` every other picked file uses.
 */
function entryForGroup(
  group: AudiobookGroup,
  reasons: ReadonlyMap<string, ScanReason>,
): ScannedEntry {
  const keys = group.files.map((file) => file.key);
  // This row's own files, never the whole pick: see `Grouping`.
  const own = new Map(
    keys.flatMap((key) => {
      const reason = reasons.get(key);
      return reason === undefined ? [] : [[key, reason] as const];
    }),
  );
  const base = {
    key: groupKey(keys),
    isbn: "",
    // Not read off an extension, because a group has several. `isAudio` is
    // the test every member file passed to get here, and it is exactly this
    // answer from `FORMAT_FOR_EXTENSION`.
    format: BookFormat.audiobook,
    group,
    draft: null,
    // Only while this row can still be split: see `Grouping`.
    fileReasons: group.files.length > 1 && own.size > 0 ? own : undefined,
  };
  // Only from a group of one. A note from one file of forty describes that
  // file and would read as though the whole book had failed.
  const note = group.files.length === 1 ? own.get(keys[0]!) : undefined;

  const draft = draftFromAudiobook(group);
  if (draft !== null) {
    return {
      ...base,
      label: draft.title,
      state: "derived",
      draft,
      // **Through `queryFor`, not through a second bounding written here.**
      // What the catalogue is asked is a title and an author, which is what
      // `q` takes, and the cleaning, the floor and the cut in code points all
      // live in one place already. Not through `readName`, which is a rule
      // about a **file name**: it would strip a trailing `.mp3` off an album
      // and hunt an ISBN through the author line.
      query:
        queryFor([draft.title, draft.author].filter(Boolean).join(" ")) ??
        undefined,
      reason: note,
    };
  }

  const naming = groupNaming(group);
  return {
    ...base,
    label: plainName(naming.name),
    ...fromTheName(naming, note),
  };
}

/**
 * The name a group with no usable tags derives its book from.
 *
 * The folder for several files and the file itself for one, which is what a
 * person named after the book in each case: a chapter file is named after its
 * chapter, and the folder over it after the work.
 */
function groupNaming(group: AudiobookGroup): FileNaming {
  const first = group.files[0]!;
  if (group.files.length === 1) {
    return { name: first.name, folders: first.folders };
  }
  const own = first.folders.at(-1);
  return own === undefined
    ? { name: first.name, folders: [] }
    : { name: own, folders: first.folders.slice(0, -1) };
}
