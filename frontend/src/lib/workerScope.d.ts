/**
 * The parts of a classic worker's global scope that
 * `textRecognition.worker.ts` calls, which the `DOM` library this package
 * compiles against does not declare.
 *
 * **Declared here rather than in the worker, so that the worker spells
 * `importScripts` only where it calls it.** `tests/houseRules.test.ts` counts
 * that name as a way to the network in any `lib/` module and exempts the one
 * call by its expression; a declaration of it in the worker would be a second
 * spelling the rule refuses. A `.d.ts` executes nothing, which is why the rule
 * does not read one.
 */
export interface WorkerScope {
  importScripts(url: string): void;
  /** A worker's, which takes a transfer list and no target origin. */
  postMessage(message: unknown, transfer: Transferable[]): void;
  addEventListener(
    type: "message",
    listener: (event: MessageEvent<unknown>) => void,
  ): void;
}
