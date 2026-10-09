/**
 * @vitest-environment node
 *
 * A global and a `finally`. No DOM.
 */
/**
 * Tests for tests/lib/withoutDecompression.ts.
 *
 * **A test helper with a test of its own, because this one is load bearing for
 * a rule rather than a convenience.** It removes a global that five readers
 * need, under a suite that shares one environment across files, and
 * `tests/setup.ts` asks it whether a leak has happened. A helper that restored
 * nothing, or a memo that answered per file, would leave the backstop reporting
 * clean over exactly the failure it exists for.
 */

import { describe, expect, it } from "vitest";

import {
  hadDecompressionStream,
  withoutDecompressionStream,
} from "./withoutDecompression";

/**
 * `tests/setup.ts`, read as text.
 *
 * `import.meta.glob` rather than `node:fs`, for the reason
 * `tests/houseRules.test.ts` gives at its own copy: a guard test is a poor
 * reason to add `@types/node` and widen the global types.
 */
const SETUP_SOURCE = (
  import.meta.glob("../setup.ts", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>
)["../setup.ts"]!;

describe("a runtime that cannot inflate, for one call", () => {
  it("takes the global away and puts it back", async () => {
    expect(typeof DecompressionStream).toBe("function");

    await withoutDecompressionStream(async () => {
      expect(typeof DecompressionStream).toBe("undefined");
    });

    expect(typeof DecompressionStream).toBe("function");
  });

  it("puts it back when the call throws", async () => {
    // The `finally`, asserted rather than read: a helper that restored on the
    // ordinary path only would leak on exactly the runs where a test failed,
    // which is when a suite is hardest to read.
    await expect(
      withoutDecompressionStream(async () => {
        throw new Error("the test failed");
      }),
    ).rejects.toThrow("the test failed");

    expect(typeof DecompressionStream).toBe("function");
  });

  it("refuses to run where there is no inflater to remove", async () => {
    // **An arm that passes vacuously is worse than an absent arm**, which is
    // what this refusal is for: in an environment with no `DecompressionStream`
    // every reader answers `no-inflate` already, and an arm asserting that
    // would be green while testing no guard at all. Reached by nesting, which
    // is the one way to be inside such an environment here.
    await expect(
      withoutDecompressionStream(() =>
        withoutDecompressionStream(async () => "unreachable"),
      ),
    ).rejects.toThrow("no own DecompressionStream to remove");

    expect(typeof DecompressionStream).toBe("function");
  });
});

describe("what this worker started with", () => {
  it("is asked once at setup's module scope, before any test can move it", () => {
    // **A text arm, because no behavioural one can see this.** The memo answers
    // from its first call, and by the time any test body runs it may already
    // have been taken by an earlier file in the worker. What has to be true is
    // that the first call happens while `tests/setup.ts` is evaluating, which
    // is before any test in that file.
    //
    // Both seats measured the same defect from opposite ends when the only
    // caller was the `afterEach`: a leak in the first test executed in a worker
    // recorded `false` and disarmed the check for every file after it, at
    // `SUITE EXIT: 0` with nothing reported.
    //
    // **Module scope is read as an unindented call**, which prettier settles
    // and `format:check` runs in CI: a call inside a hook is indented, and this
    // arm is about where the call is rather than about how it is spelled.
    const setup = SETUP_SOURCE;
    // An anchor: a file this arm could not read would satisfy every negative
    // question asked of it.
    expect(setup).toContain("afterEach(");

    expect(setup).toMatch(/^hadDecompressionStream\(\);$/m);
  });

  it("keeps answering yes while the global is away", () => {
    // **The memo, and the reason it is one.** `tests/setup.ts` runs this in
    // `afterEach` and its own module scope runs again for every test file, so a
    // capture taken there would read `false` in the first file after a leak and
    // report clean for every file after that. Asked inside the removal, which
    // is where a per file capture and a per worker memo give different answers.
    expect(hadDecompressionStream()).toBe(true);

    const real = Object.getOwnPropertyDescriptor(
      globalThis,
      "DecompressionStream",
    )!;
    delete (globalThis as { DecompressionStream?: unknown })
      .DecompressionStream;
    try {
      expect(hadDecompressionStream()).toBe(true);
    } finally {
      Object.defineProperty(globalThis, "DecompressionStream", real);
    }
  });
});
