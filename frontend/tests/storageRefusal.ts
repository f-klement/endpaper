/**
 * Making browser storage refuse, for the length of one body.
 *
 * Support code, so it mirrors nothing.
 */

/** The three storage methods the application calls. */
type StorageMethod = "getItem" | "setItem" | "removeItem";

/**
 * Run `body` with `localStorage.<method>` throwing, and put the method back
 * once `body` has finished.
 *
 * **On the instance, never on `Storage.prototype`.** happy-dom binds its own
 * copy of each storage method onto the instance the first time the method is
 * read, so a prototype spy installed after that is never called and its test
 * runs on storage that answered; `tests/houseRules.test.ts` refuses that
 * spelling. Put back by hand because `vi.restoreAllMocks()` does not reach an
 * instance, which `storageLeftBroken` in `tests/setup.ts` records.
 *
 * **An async body is awaited before the method goes back**, so the refusal
 * holds across every render a `findBy` waits through rather than ending at the
 * body's first `await`. The promise handed back then has to be awaited in its
 * turn: a test that drops it ends with storage still refusing, which the
 * `afterEach` in `tests/setup.ts` reports against that same test.
 */
export function whileStorageRefuses<T>(
  method: StorageMethod,
  body: () => T,
): T {
  const original = localStorage[method];
  const install = (value: unknown): void => {
    Object.defineProperty(localStorage, method, {
      configurable: true,
      writable: true,
      value,
    });
  };
  install(() => {
    throw new Error("refused");
  });

  let restoreNow = true;
  try {
    const result = body();
    if (result instanceof Promise) {
      restoreNow = false;
      return result.finally(() => install(original)) as T;
    }
    return result;
  } finally {
    if (restoreNow) install(original);
  }
}
