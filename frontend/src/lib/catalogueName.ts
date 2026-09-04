import type { CatalogueSource } from "../api/generated/model";
import type { MessageKey } from "../i18n/en";

/**
 * The message key holding a catalogue's name.
 *
 * **Shared rather than page local, since two screens now name a catalogue to a
 * reader.** The settings list has always done it; the search panel does it too,
 * because the line offering a longer search says which catalogues it would add.
 * A second copy of this one liner would be the thing that goes stale when the
 * key prefix changes, and `tests/lib/catalogueName.test.ts` pins every source on
 * the roster against the catalogue rather than trusting the template.
 *
 * The name itself is a proper noun and is not translated.
 */
export function catalogueName(source: CatalogueSource): MessageKey {
  return `providers.name.${source}` as MessageKey;
}
