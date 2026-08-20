/**
 * The icon set.
 *
 * Emoji were doing the work of icons throughout this app: in the sidebar, in
 * every page title, in empty states, on status pills. Three problems, and only
 * the first is about taste.
 *
 * 1. They are the loudest thing on any screen. A full-colour glyph at 20px
 *    outweighs the heading beside it, which is what made the interface read as
 *    a toy rather than as an application.
 * 2. They are not the same drawing anywhere. The font is the platform's, so the
 *    same interface is a different set of pictures on Android, iOS, Windows and
 *    Linux, at different weights and different optical sizes. Nothing that
 *    varies per device can be part of a considered layout.
 * 3. They cannot take a colour. An emoji ignores `currentColor`, so it cannot
 *    dim with disabled text or invert in dark mode, which is why every one of
 *    them needed a `grayscale opacity-*` patch to look tolerable.
 *
 * These are stroked outlines on one grid: 24 units, 1.5 stroke, round caps and
 * joins, `currentColor` throughout. They inherit colour, weight of attention
 * and opacity from whatever they sit in, which is the whole point.
 *
 * Inline rather than an icon package. The CSP here allows no external fonts or
 * scripts, the app already ships a large bundle, and a set this size is
 * cheaper as markup than as a dependency plus a tree-shaking configuration.
 */

import type { SVGProps } from "react";

/** Every icon this app has. A union, so a typo is a compile error. */
export type IconName =
  | "alert"
  | "ban"
  | "book"
  | "bookmark"
  | "camera"
  | "check"
  | "chevron"
  | "flag"
  | "globe"
  | "handshake"
  | "inbox"
  | "lamp"
  | "library"
  | "link"
  | "list"
  | "search"
  | "settings"
  | "sparkle"
  | "star"
  | "tag"
  | "theme"
  | "user"
  | "eye"
  | "eyeOff"
  | "chart"
  | "close"
  | "trash"
  | "undo"
  | "lock";

/**
 * Path data, on a 24 unit grid.
 *
 * `d` is stroked. `fill` is the rare glyph that reads better solid, currently
 * only the filled half of a star, where an outline at 12px turns to mush.
 */
const PATHS: Record<IconName, { d: string; fill?: string }> = {
  library: {
    d: "M4 4.5h4v15H4zM10 4.5h3.5v15H10zM15.6 5.2l3.4.9-3.5 13.5-3.4-.9z",
  },
  camera: {
    d: "M3 8.5A2.5 2.5 0 0 1 5.5 6h1.7l1.2-2h6.2l1.2 2h1.7A2.5 2.5 0 0 1 21 8.5v8A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5zM12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z",
  },
  link: {
    d: "M10.5 13.5a4 4 0 0 0 5.7 0l2.6-2.6a4 4 0 1 0-5.7-5.7l-1.3 1.3M13.5 10.5a4 4 0 0 0-5.7 0l-2.6 2.6a4 4 0 1 0 5.7 5.7l1.3-1.3",
  },
  handshake: {
    d: "M11 7 8.6 9.4a1.7 1.7 0 0 0 2.4 2.4l1.5-1.5 3.4 3.4a1.7 1.7 0 0 1-2.4 2.4M13.5 16.1a1.7 1.7 0 0 1-2.4 2.4l-.6-.6M3 7.5l3-1.5 5 1 5-1 3 1.5M3 7.5v7l2 1M21 7.5v7l-2 1",
  },
  chart: { d: "M4 20V10M10 20V4M16 20v-7M4 20h16" },
  settings: {
    d: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 14.5a1.5 1.5 0 0 0 .3 1.7l.1.1a1.8 1.8 0 1 1-2.6 2.6l-.1-.1a1.5 1.5 0 0 0-2.6 1.1v.2a1.8 1.8 0 1 1-3.6 0v-.1a1.5 1.5 0 0 0-2.6-1.1l-.1.1a1.8 1.8 0 1 1-2.6-2.6l.1-.1a1.5 1.5 0 0 0-1.1-2.6h-.2a1.8 1.8 0 1 1 0-3.6h.1a1.5 1.5 0 0 0 1.1-2.6l-.1-.1a1.8 1.8 0 1 1 2.6-2.6l.1.1a1.5 1.5 0 0 0 2.6-1.1V4a1.8 1.8 0 1 1 3.6 0v.1a1.5 1.5 0 0 0 2.6 1.1l.1-.1a1.8 1.8 0 1 1 2.6 2.6l-.1.1a1.5 1.5 0 0 0 1.1 2.6h.2a1.8 1.8 0 1 1 0 3.6h-.1a1.5 1.5 0 0 0-1.4.9z",
  },
  user: {
    d: "M20 20v-1.5a4.5 4.5 0 0 0-4.5-4.5h-7A4.5 4.5 0 0 0 4 18.5V20M12 10.5a3.75 3.75 0 1 0 0-7.5 3.75 3.75 0 0 0 0 7.5z",
  },
  search: { d: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4.1-4.1" },
  book: {
    d: "M5 4.5A1.5 1.5 0 0 1 6.5 3H18v15.5H6.5A1.5 1.5 0 0 0 5 20zM5 4.5v14M18 18.5V21H6.5",
  },
  inbox: {
    d: "M4 13.5h4l1.2 2.2h5.6L16 13.5h4M4 13.5 6.4 5.2A1.5 1.5 0 0 1 7.8 4h8.4a1.5 1.5 0 0 1 1.4 1.2L20 13.5v4A1.5 1.5 0 0 1 18.5 19h-13A1.5 1.5 0 0 1 4 17.5z",
  },
  tag: {
    d: "M11.6 3.5H4.5a1 1 0 0 0-1 1v7.1a1 1 0 0 0 .3.7l8 8a1 1 0 0 0 1.4 0l7.1-7.1a1 1 0 0 0 0-1.4l-8-8a1 1 0 0 0-.7-.3zM7.8 8.3h.01",
  },
  check: { d: "M4.5 12.8 9.5 17.8 19.5 6.5" },
  bookmark: { d: "M6 4.5A1.5 1.5 0 0 1 7.5 3h9A1.5 1.5 0 0 1 18 4.5V21l-6-4-6 4z" },
  list: {
    d: "M9 5h11M9 12h11M9 19h11M4.5 5h.01M4.5 12h.01M4.5 19h.01",
  },
  flag: { d: "M5 21V4M5 4h11l-2 4 2 4H5" },
  eye: {
    d: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  },
  eyeOff: {
    d: "M9.9 5.8A8.9 8.9 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.7 3.6M6.2 7.9A17 17 0 0 0 2.5 12S6 18.5 12 18.5c1 0 1.9-.2 2.7-.5M3 3l18 18M10 10a3 3 0 0 0 4 4",
  },
  globe: {
    d: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3.2 9.5h17.6M3.2 14.5h17.6M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z",
  },
  theme: {
    d: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 3v18a9 9 0 0 0 0-18z",
  },
  lamp: {
    d: "M9.2 17.5h5.6M10 20.5h4M12 3a6 6 0 0 0-3.5 10.9c.5.4.8 1 .8 1.6h5.4c0-.6.3-1.2.8-1.6A6 6 0 0 0 12 3z",
  },
  sparkle: {
    d: "M12 3.5 13.8 9l5.7 1.8-5.7 1.8L12 18.5l-1.8-5.9L4.5 10.8 10.2 9zM18.5 16l.7 2.1 2.1.7-2.1.7-.7 2.1-.7-2.1-2.1-.7 2.1-.7z",
  },
  ban: { d: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM5.6 5.6l12.8 12.8" },
  alert: {
    d: "M12 8.5v5M12 17h.01M10.3 3.9 2.6 17.2A2 2 0 0 0 4.3 20.2h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  },
  chevron: { d: "M9 5.5 15.5 12 9 18.5" },
  close: { d: "M6 6l12 12M18 6L6 18" },
  trash: {
    d: "M4.5 7h15M9.5 7V5.2a1.2 1.2 0 0 1 1.2-1.2h2.6a1.2 1.2 0 0 1 1.2 1.2V7M6.8 7l.9 12a1.5 1.5 0 0 0 1.5 1.4h5.6a1.5 1.5 0 0 0 1.5-1.4l.9-12M10.5 11v6M13.5 11v6",
  },
  // An arrow turning back on itself. The hook is what reads as "undo" at
  // 16px; a plain left arrow reads as "back", which is a different promise.
  undo: { d: "M4 9h9.5a5.5 5.5 0 1 1 0 11H8M4 9l4-4M4 9l4 4" },
  lock: {
    d: "M6.5 10.5h11a1.5 1.5 0 0 1 1.5 1.5v7a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 19v-7a1.5 1.5 0 0 1 1.5-1.5zM8 10.5V7a4 4 0 0 1 8 0v3.5",
  },
  star: {
    d: "m12 3.8 2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.5 10l5.9-.9z",
  },
};

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  /** Fills the shape as well as stroking it. Only `star` uses this today. */
  filled?: boolean;
  /** A label makes the icon meaningful to a screen reader instead of decorative. */
  title?: string;
}

/**
 * One icon.
 *
 * Decorative by default: `aria-hidden` unless given a `title`. That is the
 * right default because nearly every icon here sits beside its own label, and
 * announcing both makes a screen reader say everything twice.
 */
export default function Icon({
  name,
  filled = false,
  title,
  className = "w-4 h-4",
  ...rest
}: IconProps) {
  const { d } = PATHS[name];
  return (
    <svg
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      {...rest}
    >
      <path d={d} />
    </svg>
  );
}
