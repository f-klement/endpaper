/** Tests for src/lib/loanState.ts. */

import { describe, expect, it } from "vitest";

import type { LoanOut } from "../../src/api/generated/model";
import { loanState } from "../../src/lib/loanState";
import { makeLoan } from "../factories";
import { langOf, withoutProse } from "../withoutProse";
// The one enumeration of `src/`, which refuses a corpus that is no longer the
// tree. The pattern used to be written here, where narrowing it was one edit
// in the file holding the rule it disarmed.
import { sourceEntries as entries, sourceText } from "../sourceModules";

/** The module that owns the rule, and the one this file exempts by name. */
const OWNER = "lib/loanState.ts";

const COLUMN = /\breturned_at\b/;

/**
 * Whether this module reads the column, as opposed to talking about it.
 *
 * `withoutProse` is what makes that difference, and it is here for the next
 * docstring that explains this rule rather than for anything in the tree
 * today: prose naming the column would otherwise be reported as the
 * violation. What pins the behaviour is the arm feeding this both answers,
 * not this sentence, which is why no census of today's comments is written
 * here.
 */
function namesTheColumn(path: string, source: string): boolean {
  return COLUMN.test(withoutProse(source, langOf(path)));
}

describe("a loan's return state", () => {
  it("calls a loan with no return stamp still out", () => {
    expect(loanState(makeLoan({ returned_at: null }))).toEqual({
      isOpen: true,
      returnedOn: null,
    });
  });

  it("calls a loan carrying a stamp back, and hands the date on", () => {
    // The date is answered beside the verdict rather than left to the caller
    // to fetch, because a caller that went back to the column for it would be
    // the second derivation this module exists to remove.
    expect(
      loanState(makeLoan({ returned_at: "2026-02-20T12:00:00Z" })),
    ).toEqual({
      isOpen: false,
      returnedOn: "2026-02-20T12:00:00Z",
    });
  });

  it("calls a loan whose stamp is empty still out", () => {
    // Inside the declared type and unreachable from the server, which is why
    // it is the `||` against `??` decision rather than an edge case: the
    // alternative draws the row as returned and hands an empty value to a
    // date formatter.
    expect(loanState(makeLoan({ returned_at: "" }))).toEqual({
      isOpen: true,
      returnedOn: null,
    });
  });

  it("calls a loan whose stamp is missing altogether still out", () => {
    // The generated type says the key is always there. A payload is still
    // JSON, and a reader that fails open here shows a live loan with its
    // return button rather than a closed one nobody can reopen.
    expect(loanState(makeLoan({ returned_at: undefined }))).toEqual({
      isOpen: true,
      returnedOn: null,
    });
  });

  it("never answers open and returned at once", () => {
    // The invariant the pair exists for: two fields read off one value cannot
    // disagree.
    //
    // **Four values, named, and not a claim about the domain.** They are the
    // three the declared `string | null` admits once an absent key is counted,
    // plus a stamp. What a hand built object could carry is the arm below.
    for (const stamp of [null, undefined, "", "2026-02-20T12:00:00Z"]) {
      const state = loanState(makeLoan({ returned_at: stamp }));

      expect(state.isOpen).toBe(state.returnedOn === null);
      expect(state.returnedOn).not.toBe("");
    }
  });

  it("turns every falsy stamp it is given into null", () => {
    // **Why this is worth an arm outside the declared type.** `returnedOn` is
    // rendered straight into the card behind `&&`, and falsy does not mean
    // invisible there. Measured over the eight: `0`, `-0` and `0n` each reach
    // a reader as "0" and `NaN` as "NaN", while `null`, `undefined`, `""` and
    // `false` render nothing. Normalising all eight to null is what turns
    // `LoanState.returnedOn`'s promise into one about what can appear on
    // screen rather than one about a single value.
    //
    // **Completed rather than sampled, because this set really is closed**,
    // which is what separates it from the corpus the spelling rule walks: the
    // language has eight falsy primitives and all eight are here. Closed is
    // what makes a set safe to enumerate; it is not what makes a member
    // tested, so they are walked rather than counted.
    //
    // The ninth falsy value is `document.all`, excluded because it is a
    // browser quirk on one host object rather than a value a payload field
    // can hold, and it cannot be constructed to be handed here.
    //
    // The casts are the point rather than a convenience: none of these can
    // arrive through `LoanOut`, and the arm is about what the function does
    // with what it is handed, not about what the schema allows.
    for (const stamp of [null, undefined, "", false, 0, -0, 0n, NaN]) {
      const loan = { returned_at: stamp } as unknown as LoanOut;

      expect(loanState(loan)).toEqual({ isOpen: true, returnedOn: null });
    }
  });
});

/**
 * Which modules under `src` may name the column.
 *
 * The browser's half of
 * `backend/tests/test_house_rules.py::TestOnlyTheLendingDeskNamesReturnedAt`,
 * which keeps the same rule on the other side of the wire. **A partition, and
 * both halves are asserted**: the hand written side equals the owner, so a
 * fourth derivation is a failure naming the file, and the generated side is
 * non empty, so the exemption cannot quietly become a blanket.
 *
 * **What it cannot see** is the mechanism the backend rule states for its own
 * half: this matches the characters, so a computed access, a walk over the
 * payload's keys, or anything reaching the value through a name chosen
 * somewhere else reads the column without spelling it. How much that leaves
 * out is deliberately not claimed. An arm's job is to fail on a fourth reading
 * somebody writes, and the ones anybody writes are spelled.
 */
describe("only the loan state module reads the return column", () => {
  /**
   * The two directories the generator owns, which is the half exempted here.
   *
   * **Directories and not a filename.** A schema module is named after its
   * payload, so renaming `LoanOut` in the backend renames the file, and an
   * exemption naming it would red on a branch that changed nothing about this
   * rule. These two strings are `orval.config.ts`'s own `target` and
   * `schemas`, which move only when somebody edits the file that defines the
   * exemption.
   *
   * **Nothing that executes can hide in them**, which is what makes a
   * directory safe to exempt: that config sets `clean: true`, so each is wiped
   * and rewritten from `openapi.json` on every generation.
   *
   * **Their parent is not exempt, deliberately.** The wipe is keyed on these
   * two paths, so a hand written module directly under `api/generated/` would
   * sit outside it and survive, and exempting the parent would cover exactly
   * that gap.
   */
  const GENERATED = ["api/generated/endpoints/", "api/generated/model/"];

  const isGenerated = (path: string) =>
    GENERATED.some((dir) => path.startsWith(dir));

  /**
   * What to do instead, for the arm whose failure is a file that should not
   * be reading the column.
   *
   * **Only that arm.** A bare diff leaves editing the exemption as the
   * shortest road back to green, which is a rule teaching people to weaken
   * it. It is deliberately not on the count arm below, whose failure is a
   * second read inside the owner or a renamed column: nobody has added a
   * module in either case, and in the first the reader is the owner, so this
   * advice would go to the one file that cannot take it.
   */
  const REMEDY =
    "Whether a book is still out is `lib/loanState.ts`'s to answer: ask " +
    "`loanState(loan)` and read `isOpen` or `returnedOn`. Adding a module " +
    "here is claiming the column means something other than the state of a " +
    "loan.";

  it("is named by the owner and by nothing else hand written", () => {
    const found = entries()
      .filter(([path, source]) => namesTheColumn(path, source))
      .map(([path]) => path)
      .sort();

    expect(
      found.filter((path) => !isGenerated(path)),
      REMEDY,
    ).toEqual([OWNER]);
  });

  it("is named by the generated client, so the exemption is not a blanket", () => {
    // The other half of the partition above. An exemption that matched
    // nothing would let these two directories quietly widen to cover a tree
    // that no longer carries the payload's own field name, and the equality
    // arm would stay green through it.
    const generated = entries()
      .filter(([path, source]) => namesTheColumn(path, source))
      .map(([path]) => path)
      .filter(isGenerated);

    expect(generated).not.toEqual([]);
  });

  it("is named by the owner exactly once, so the rule above is not vacuous", () => {
    // Anti vacuity, and exact rather than a floor: the equality above is
    // satisfied by a pass that finds nothing anywhere, which is what a rename
    // of the column produces. One is the whole of the rule, so any second
    // reading inside the owner is a decision to re-measure rather than a
    // tidy up.
    //
    // `?? []` so that no match reads as an empty set rather than as a matcher
    // complaining about null, which is the answer this arm exists to report.
    const reads =
      withoutProse(sourceText(OWNER), "ts").match(/\breturned_at\b/g) ?? [];

    expect(reads).toHaveLength(1);
  });

  it("reads the whole tree and not a corner of it", () => {
    // **This arm used to assert the extension set, and that closed one
    // narrowing rather than the class.** A pattern cut to `.ts` takes every
    // `.tsx` module out, which is every card and the rendering half of each
    // page folder, and the count that guarded it before cleared comfortably.
    // It leaves the page hook modules, which is where a loan payload is
    // actually read, so that narrowing is not the one that hides a violation
    // from this rule. The next one is: narrowed by directory instead, the
    // corpus keeps both languages, keeps every exempted file, and drops the
    // pages whole, measured at exit 0 with a real violation live.
    //
    // So the corpus comes from `tests/sourceModules.ts`, which enumerates the
    // tree four ways and refuses them when they disagree, and what is left
    // here is that this rule reaches that refusal.
    expect(() => entries()).not.toThrow();
  });

  it("does not take a comment naming the column for a read", () => {
    // The instrument, tested on both answers. Every file arguing about this
    // rule names the column in prose, so a scanner that counted those would
    // fail on the documentation and pass on the next real read.
    expect(
      namesTheColumn(
        "pages/Fake.tsx",
        "// returned_at is the column\nexport const open = true;\n",
      ),
    ).toBe(false);
    expect(
      namesTheColumn(
        "pages/Fake.tsx",
        "export const open = !loan.returned_at;\n",
      ),
    ).toBe(true);
  });
});
