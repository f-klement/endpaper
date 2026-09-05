/**
 * Which reader the catalogue is being drawn for.
 *
 * **The library's concept, not any one screen's.** A household reads its
 * catalogue as a list of things it owns; a cataloguer reads the same rows as
 * records. Which of the two is looking decides the column set, the default
 * view, and whatever else comes next, so it belongs to none of them.
 *
 * **Derived, never stored.** The mode is a reading of the `library_mode` flag
 * and there is nothing to migrate, no second spelling to keep in step, and no
 * state that can disagree with the flag.
 */

export const CATALOGUE_MODES = ["household", "cataloguer"] as const;

export type CatalogueMode = (typeof CATALOGUE_MODES)[number];

/**
 * The mode for a library mode flag.
 *
 * `undefined` is household, deliberately. The flags are fetched, so there is a
 * moment before they arrive, and the household set is the one every existing
 * library already sees: a cataloguer briefly sees the old table, where the
 * other way round every household would see a cataloguer's table flash past on
 * every load.
 */
export function catalogueMode(libraryMode: boolean | undefined): CatalogueMode {
  return libraryMode === true ? "cataloguer" : "household";
}
