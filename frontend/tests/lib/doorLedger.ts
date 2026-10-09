/**
 * Which bounds the doors driven in one test file declared, and which of them
 * a positive control in that file overran.
 *
 * **Why it exists**: a property passes over a correct reader whatever its door
 * declares, so a door's `ceilings` can be emptied with every arm green.
 * Measured: the declarations of thirteen doors no control held, emptied over
 * two runs of 177 and 289 tests, every arm green; and an entity defect planted
 * in the Kindle reader went from four reds to none with its doors emptied. A control per door closes the
 * doors that have one; this closes the next door, by refusing a declared
 * bound no control in the same file overran.
 *
 * **Keyed by the `ceilings` function**, which is what a door and its control
 * share: a store's door is rebuilt per call around the same function, and a
 * control hands `overrunBreach` the same door. A door built inline in a test
 * with a fresh function per call is a fresh owner each time and needs its
 * function hoisted to be controlled, which is loud.
 *
 * **Per test file, by construction**: `tests/setup.ts` evaluates once per
 * file, opens a fresh ledger there and checks it after the file's last test.
 * A ledger per worker would hold whichever files the pool happened to put
 * together, and a control in one file would answer for a door in another.
 *
 * **What it does not hold, stated**: a bound a door's `open` holds itself
 * through `require`, which is not a ceiling; a door no test in the file
 * drives, which declares nothing here; and a bound deleted from a door's
 * `ceilings` together with its control, which leaves nothing declared and
 * nothing to overrun. A bound deleted alone reds its control, and a control
 * deleted alone reds the file here, both measured.
 */

import { type Ceilings } from "./meter";

type Bound = keyof Ceilings;

let declaredBy = new Map<object, Set<Bound>>();
let overrunBy = new Map<object, Set<Bound>>();

/** A fresh ledger, for the file about to run. */
export function openLedger(): void {
  declaredBy = new Map();
  overrunBy = new Map();
}

function add(to: Map<object, Set<Bound>>, owner: object, bound: Bound): void {
  const known = to.get(owner) ?? new Set<Bound>();
  known.add(bound);
  to.set(owner, known);
}

/** What a door's `ceilings` returned for one call. */
export function declared(owner: object, ceilings: Ceilings): void {
  for (const [bound, value] of Object.entries(ceilings)) {
    if (value !== undefined) add(declaredBy, owner, bound as Bound);
  }
}

/** A bound a control overran and the meter named. */
export function overran(owner: object, bound: Bound): void {
  add(overrunBy, owner, bound);
}

/**
 * Every declared bound no control overran, as sentences naming the bound and
 * the start of the function that declared it, so a red says where to look.
 */
export function uncontrolled(): string[] {
  const out: string[] = [];
  for (const [owner, bounds] of declaredBy) {
    const held = overrunBy.get(owner) ?? new Set<Bound>();
    const missing = [...bounds].filter((bound) => !held.has(bound));
    missing.sort();
    if (missing.length > 0) {
      const source = String(owner).replace(/\s+/g, " ").slice(0, 120);
      out.push(`${missing.join(", ")}, declared by ${source}`);
    }
  }
  return out;
}
