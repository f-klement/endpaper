/**
 * The contract every door is held to, held itself: what a door is handed of
 * the meter, and the ledger that refuses a declared bound no control overran.
 *
 * **Each row is a route measured past the first version**, so the rows are
 * the evasions and the control is the same door with nothing done to it.
 */

import { describe, expect, it } from "vitest";

import * as doorLedger from "./doorLedger";
import { declared, overran, uncontrolled } from "./doorLedger";
import { type DoorMeter } from "./meter";
import { expectNamedOutcome, overrunBreach, type Door } from "./readerContract";

const MIB = 1024 * 1024;

/** One ceiling, the bound every row below reads past. */
const perReadOnly = () => ({ perRead: MIB });

/** A door reading four mebibytes at once, after `first` has had its go. */
function reading(
  first: (meter: DoorMeter, file: File) => void,
): Door<null, number> {
  return {
    module: doorLedger,
    ceilings: perReadOnly,
    build: async () => new Uint8Array(4 * MIB),
    open: async (file, meter) => {
      first(meter, file);
      return (await file.arrayBuffer()).byteLength;
    },
  };
}

const BREACH = `read ${4 * MIB} bytes at once against a ceiling of ${MIB}`;

describe("what a door is handed of the meter", () => {
  it("refuses the read past the ceiling, with nothing done to the meter", async () => {
    await expect(
      expectNamedOutcome(
        reading(() => {}),
        { spec: null, patches: [] },
      ),
    ).rejects.toThrow(BREACH);
  });

  it.each([
    [
      "the ceilings written through Reflect",
      (meter: DoorMeter) => Reflect.set(meter, "ceilings", {}),
    ],
    [
      "the ceilings emptied in place",
      (meter: DoorMeter) => {
        const held: unknown = Reflect.get(meter, "ceilings");
        if (typeof held === "object" && held !== null) {
          for (const key of Object.keys(held))
            Reflect.deleteProperty(held, key);
        }
      },
    ],
    [
      "the meter reached off the file",
      (_: DoorMeter, file: File) => {
        const held: unknown = Reflect.get(file, "meter");
        if (typeof held === "object" && held !== null) {
          Reflect.set(held, "ceilings", {});
        }
      },
    ],
  ])("still refuses it with %s", async (_, route) => {
    // Each passed a four mebibyte read past a one mebibyte ceiling while the
    // door was handed the meter itself, measured.
    await expect(
      expectNamedOutcome(reading(route), { spec: null, patches: [] }),
    ).rejects.toThrow(BREACH);
  });

  it("still reports the breach a door swallowed and then tried to clear", async () => {
    const door: Door<null, number> = {
      ...reading(() => {}),
      open: async (file, meter) => {
        try {
          await file.arrayBuffer();
        } catch {
          // Swallowed, as a reader turning the sentinel into an answer does.
        }
        Reflect.set(meter, "reason", null);
        return 0;
      },
    };

    await expect(
      expectNamedOutcome(door, { spec: null, patches: [] }),
    ).rejects.toThrow(BREACH);
  });

  it("is three closures and nothing else, which nothing can add to", async () => {
    const handed: DoorMeter[] = [];
    await expectNamedOutcome(
      {
        ...reading(() => {}),
        build: async () => new Uint8Array(1),
        open: async (_, meter) => {
          handed.push(meter);
          return 0;
        },
      },
      { spec: null, patches: [] },
    );

    const keys = Object.keys(handed[0]!);
    keys.sort();
    expect(keys).toEqual(["boundEachInflater", "counted", "require"]);
    expect(Object.isFrozen(handed[0])).toBe(true);
  });

  it("declares the ceiling it is held to, so deleting it reds", async () => {
    // This file's own control, which the ledger asks of every file.
    expect(
      await overrunBreach(
        reading(() => {}),
        {
          ceiling: "perRead",
          bound: MIB,
        },
      ),
    ).toContain(`at once against a ceiling of ${MIB}`);
  });
});

/**
 * The bounds the ledger names for this owner alone, since the ledger is the
 * file's own. Matched on the start of the owner's source, which is how the
 * ledger names it, whitespace folded the same way.
 */
function about(owner: () => unknown): string[] {
  const named = String(owner).replace(/\s+/g, " ").slice(0, 120);
  return uncontrolled()
    .filter((line) => line.endsWith(`, declared by ${named}`))
    .map((line) => line.slice(0, -`, declared by ${named}`.length));
}

/** A declaration nothing drives, for the ledger arms. */
const owner = () => ({ reads: 2, perRead: 3 });

/** A door's ceilings the second ledger arm overruns by the wrong bound first. */
const ceilings = () => ({ perRead: 4 });

describe("the ledger of what a file's doors declared", () => {
  it("names a declared bound until a control overruns it, and then nothing", () => {
    declared(owner, owner());

    expect(about(owner)).toEqual(["perRead, reads"]);
    overran(owner, "reads");
    expect(about(owner)).toEqual(["perRead"]);
    overran(owner, "perRead");
    expect(about(owner)).toEqual([]);
  });

  it("is told only of a breach naming the bound the control aimed at", async () => {
    // **A control refused by another bound is not a control of this one**: a
    // door declaring a per read bound, overrun by count, answers no breach at
    // all, and the bound stays named until its own control runs.
    const door: Door<null, number> = { ...reading(() => {}), ceilings };
    declared(ceilings, ceilings());

    expect(
      await overrunBreach(door, { ceiling: "reads", bound: 1 }),
    ).toBeNull();
    expect(about(ceilings)).toEqual(["perRead"]);
    expect(
      await overrunBreach(door, { ceiling: "perRead", bound: 4 }),
    ).toContain("at once against a ceiling of 4");
    expect(about(ceilings)).toEqual([]);
  });
});
