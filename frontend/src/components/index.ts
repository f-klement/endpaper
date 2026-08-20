/**
 * General, reusable, presentational components.
 *
 * The bar for living here is that a component is useful to more than one page
 * *and* carries no knowledge of the domain. Anything that mentions a book, a
 * loan or a tag belongs in a page folder, or (if several pages share it) in
 * `pages/components/`.
 */

export { default as Button } from "./Button";
export type { ButtonSize, ButtonVariant } from "./Button";
export { default as EmptyState } from "./EmptyState";
export { default as ErrorState, errorText } from "./ErrorState";
export { default as HelpButton } from "./HelpButton";
export { default as Icon } from "./Icon";
export type { IconName } from "./Icon";
export { default as Modal } from "./Modal";
export { default as Skeleton } from "./Skeleton";
export { default as StarRating } from "./StarRating";
export { default as Spinner } from "./Spinner";
export { default as Toast, type ToastAction } from "./Toast";
