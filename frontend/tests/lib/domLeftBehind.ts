/**
 * What a test left in `document.body` once `cleanup()` had run, as a message
 * naming it; `null` when it left nothing.
 *
 * **`cleanup()` removes only the containers the testing library made.** A node
 * appended to the body directly, a portal target, or a root made with
 * `createRoot` outlives it, and under `isolate: false` it outlives the file:
 * the next file in the worker finds two of everything and fails with "Found
 * multiple elements" on a test that passes alone. `tests/setup.ts` asks this
 * after every test's cleanup, and before every test, where a write landing
 * after the previous cleanup (a timer, a resolved promise) shows up; there
 * `previous` names the test that ran before it in the worker, which may be the
 * last test of another file.
 *
 * **Empties the body before it answers**, so one leak fails one test rather
 * than every test after it in the worker.
 */
export function domLeftBehind(
  when: "after" | "before",
  previous?: string,
): string | null {
  if (typeof document === "undefined" || !document.body) return null;
  const nodes = [...document.body.childNodes];
  if (nodes.length === 0) return null;
  const shown = nodes
    .map((node) =>
      node instanceof Element
        ? node.outerHTML.slice(0, 200)
        : `${node.nodeName} ${JSON.stringify(node.textContent?.slice(0, 80))}`,
    )
    .join(" | ");
  document.body.replaceChildren();
  return when === "after"
    ? `This test left ${nodes.length} node(s) in document.body after ` +
        "cleanup(). Under isolate: false they reach every later file in the " +
        "worker as duplicate elements. Render through the testing library, " +
        `or remove what the test appended in a finally: ${shown}`
    : `This test found ${nodes.length} node(s) in document.body before it ` +
        "began, written after the previous test's cleanup() by something " +
        "that test left running (a timer, a promise, a listener), so the " +
        `leaker is the test before this one in the worker, ` +
        `${previous ?? "which no test recorded"}: ${shown}`;
}
