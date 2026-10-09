/**
 * A runtime that cannot inflate, for the length of one call.
 *
 * **The one refusal in the reader family whose cause is the runtime rather than
 * the file.** `zip.ts` and `pdf.ts` each answer `no-inflate` when the engine has
 * no `DecompressionStream`, and a member reading that sentence is being told to
 * look at their browser rather than at their book. Node has one, so nothing
 * reached either arm and neither said anything about what a member is told.
 *
 * **Removed rather than stubbed to `undefined`, which is the distinction that
 * makes this a test of the guard.** Both readers ask
 * `typeof DecompressionStream === "undefined"`, and what `typeof` is for is a
 * name that is not bound at all: `vi.stubGlobal("DecompressionStream",
 * undefined)` leaves the property in place, so the guard's own line goes on
 * being unnecessary and deleting it changes no answer.
 *
 * **What deleting each guard actually does, because the obvious answer is wrong
 * in both readers and costs the zip half of it.** Neither `ReferenceError`
 * escapes: `zip.ts` catches it around `new DecompressionStream("deflate-raw")`
 * and answers the same `no-inflate` with a different sentence, so the arm there
 * asserts the message; `pdf.ts` catches it in `catch { continue; }` and falls to
 * `PdfError("damaged")`, which is the wrong sentence and is what its arm
 * observes. Measured by the design seat: with the guard deleted and this helper
 * asserting the failure code alone, the whole suite passed at 3,194 tests.
 *
 * **Put back in a `finally`, because the suite runs `isolate: false`.** A
 * removal left behind reaches every later file in the worker: five readers open
 * a zip and the sixth inflates PDF streams, so what a leak produces is a page
 * of files reported as unreadable in a file that did nothing wrong.
 * `tests/setup.ts` fails a test that leaves it missing, which is the backstop
 * for a route that does not go through here.
 */
export async function withoutDecompressionStream<T>(
  run: () => Promise<T>,
): Promise<T> {
  const real = Object.getOwnPropertyDescriptor(
    globalThis,
    "DecompressionStream",
  );
  // **Loud rather than vacuous.** An environment that never had one would make
  // every arm below pass while asserting nothing about a guard, which is the
  // failure this whole file exists to avoid.
  if (real === undefined) {
    throw new Error(
      "this environment has no own DecompressionStream to remove, so the " +
        "no-inflate arms would assert nothing",
    );
  }
  delete (globalThis as { DecompressionStream?: unknown }).DecompressionStream;
  try {
    // The readers read the name off the global at call time, and this asserts
    // that the removal is the one they see rather than one on another object.
    if (typeof DecompressionStream !== "undefined") {
      throw new Error("DecompressionStream survived being deleted");
    }
    return await run();
  } finally {
    Object.defineProperty(globalThis, "DecompressionStream", real);
  }
}

/**
 * Whether this worker's environment ever had an inflater.
 *
 * **Memoised on `globalThis` and not in a module scope `const`, which is the
 * difference between a backstop and a comment.** `tests/setup.ts` evaluates
 * once per test file, so a removal that survives a file boundary makes the next
 * file capture `false` and the check goes quiet for every remaining file in the
 * worker: precisely the leak it exists to catch. Measured by the security seat
 * on two files, the first deleting the global from `afterAll`: the second ran
 * with no `DecompressionStream` and nothing said so, `SUITE EXIT: 0`. The fork
 * pool reuses the process, so `globalThis` outlives the module registry, which
 * is the palette cache's argument in that file.
 *
 * `??=` and not `||=`, because `false` is an answer here: an environment that
 * genuinely has no inflater must keep answering `false` rather than being asked
 * again by every later file.
 */
export function hadDecompressionStream(): boolean {
  const store = globalThis as { __endpaperHadDecompression__?: boolean };
  return (store.__endpaperHadDecompression__ ??=
    typeof DecompressionStream !== "undefined");
}
