/**
 * The six settings routes, as data.
 *
 * Settings is an index, not a page: each entry is a heading, one sentence
 * saying what the route holds, and a link to it. The table is here rather than
 * inlined in the JSX so the index, the route table in `app/routes.tsx` and any
 * test that walks the tree read the same list.
 *
 * **The summaries are the whole value of the index.** A household that has to
 * open three screens to find one setting is worse off than it was under a
 * single long page, so each sentence names what is actually behind the link
 * rather than restating its title.
 *
 * **Three routes hold nothing for a member who is not an admin**, and the index
 * says so by leaving them out rather than by advertising a screen that answers
 * "only an admin can change these". The long page this replaced refused in
 * place, once, beside the cards it was refusing; six links with no such mark
 * would turn one refusal into three, each of them a tap away and each announced
 * with a sentence promising content.
 *
 * The routes stay mounted regardless, so a deep link still lands and still
 * refuses. This flag decides what is offered, never what is allowed: the
 * endpoints behind these screens are `require_admin`, and `AdminSettings` is
 * what a member actually meets.
 *
 * The grouping is the owner's, settled 2026-08-27, and two of its placements
 * came from reading the strings rather than the section names: the default
 * language is *"Default language for new visitors"*, which is the interface
 * language rather than a cataloguing decision, so it sits with Appearance; and
 * the cover store's own text names the import as the thing that creates work
 * for it, so it sits with Your library. See `docs/decisions.md`.
 */

import type { IconName } from "../../components";
import type { MessageKey } from "../../i18n";

export interface SettingsRoute {
  /** Absolute, so a link needs no joining and a test can assert it verbatim. */
  path: string;
  icon: IconName;
  title: MessageKey;
  /** One sentence: what is behind the link. */
  summary: MessageKey;
  /** Left off the index for a member. Never a permission: see above. */
  adminOnly?: true;
}

export const SETTINGS_ROUTES: SettingsRoute[] = [
  {
    path: "/settings/appearance",
    icon: "theme",
    title: "settings.appearance.title",
    summary: "settings.appearance.summary",
  },
  {
    path: "/settings/catalogue",
    icon: "search",
    title: "settings.catalogue.title",
    summary: "settings.catalogue.summary",
    adminOnly: true,
  },
  {
    path: "/settings/library",
    icon: "book",
    title: "settings.library.title",
    summary: "settings.library.summary",
  },
  {
    path: "/settings/lending",
    icon: "handshake",
    title: "settings.lending.title",
    summary: "settings.lending.summary",
    adminOnly: true,
  },
  {
    path: "/settings/data",
    icon: "inbox",
    title: "settings.data.title",
    summary: "settings.data.summary",
    adminOnly: true,
  },
  {
    path: "/settings/about",
    icon: "library",
    title: "about.title",
    summary: "settings.about.summary",
  },
];
