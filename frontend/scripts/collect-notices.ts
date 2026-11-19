/**
 * Write the JavaScript half of the image's third party notices.
 *
 * `bun run scripts/collect-notices.ts <out.json>`, after `bun run build` and
 * before `node_modules` is deleted, since the licence texts are read from it.
 * The Dockerfile's frontend stage runs it; `scripts/notices.ts` says what it
 * collects and what fails it.
 */
import { collectNotices } from "./notices";

const out = process.argv[2];
if (out === undefined) {
  console.error("usage: bun run scripts/collect-notices.ts <out.json>");
  process.exit(2);
}
const failures = collectNotices(out);
if (failures.length > 0) {
  console.error(
    `notices: ${failures.length} failure(s), nothing written\n  ${failures.join("\n  ")}`,
  );
  process.exit(1);
}
console.log(`notices: written to ${out}`);
