/**
 * Components shared by several pages, but too domain-specific for
 * `src/components/`.
 *
 * The colocation rule in one line: one page → that page's folder; several
 * pages → here; general and domain-free → `src/components/`.
 */

export { default as CoverImage } from "./CoverImage";
export { default as LocationField } from "./LocationField";
export { Page, PageHeader, PageCount } from "./Page";
export { default as TagPicker } from "./TagPicker";
