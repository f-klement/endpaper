import { Link } from "react-router-dom";

import type { UserOut } from "../../api/generated/model";
import { Icon, SectionIcon } from "../../components";
import { useTranslation } from "../../i18n";
import { Page, PageHeader } from "../components";
import { SETTINGS_ROUTES } from "./types";

interface SettingsPageProps {
  /**
   * The session's account, never the cached one. `AppShell` renders the route
   * table only once this is known, so it is right in all three auth modes.
   */
  currentUser: UserOut;
}

/**
 * Settings is an index of six screens, not a screen.
 *
 * It held thirteen collapsible sections and about 3,270 lines across one route,
 * and had stopped being a page: two features built on one night had to be told
 * in advance which section each owned so they would not collide in this file
 * and in `hooks.ts`. The fold was doing a route's job.
 *
 * So each group is a real route now, and this is the map to them: a heading, a
 * sentence saying what is behind it, and a link. **The sentences are the whole
 * value of this page.** Six headings alone would make a household open three
 * screens to find one setting, which is worse than the long page it replaced.
 *
 * **Nothing here folds, and that is the point.** The collapse state was a
 * second way to hide a section beside the navigation, and keeping both is how
 * an app ends up with two answers to "where did that go". `lib/sectionState.ts`
 * still serves the book page, which folds against a condition and has no route
 * to fold into.
 *
 * The whole entry is the link rather than the title alone, so a thumb has a
 * card to hit instead of a line of text. The accessible name is therefore the
 * heading and the sentence together, which is what a reader listening to this
 * page wants: the sentence is the reason to follow the link.
 *
 * **A member who is not an admin is offered three of the six.** The page it
 * replaced refused in place, once, beside the cards it was refusing; six links
 * with no such mark would turn that into three dead ends, each a tap away and
 * each advertised with a sentence promising content. The three routes stay
 * mounted, so a deep link still lands and still meets `AdminSettings`.
 *
 * **The account comes down as a prop, which is the idiom inside `AppRoutes`.**
 * `BookDetail` takes the same one, and `NoteList` and `QuoteList` take
 * `is_admin` off a prop too. It costs no request, so this index stays a static
 * map, where asking the server would put a guaranteed 403 in front of every
 * member on the one settings screen that has nothing to refuse them.
 *
 * **Reading `localStorage["user"]` instead was tried and is wrong.** Under
 * proxy auth that entry is not the identity: it is written only by `signIn`,
 * which under proxy fires only on a switch into a test account, and a test
 * account is never an admin. So the key is null for a proxy admin always, and
 * reading it dropped three entries off their own index, reachable only by
 * typing the URL.
 *
 * **This filter may only ever fail by under-offering.** It decides what is
 * drawn and nothing else: the routes stay mounted, a deep link reaches the
 * component, `useSettings()` answers 403 and `AdminSettings` draws the refusal,
 * and every endpoint behind those screens is `require_admin`. A wrong answer
 * here costs an admin a link, and can never hand a member anything.
 */
export default function SettingsPage({ currentUser }: SettingsPageProps) {
  const { t } = useTranslation();
  const isAdmin = currentUser.is_admin;
  const routes = SETTINGS_ROUTES.filter((route) => isAdmin || !route.adminOnly);

  return (
    <Page width="narrow">
      <PageHeader icon="settings" title={t("settings.title")} />
      <nav aria-label={t("settings.title")} className="space-y-3">
        {routes.map((route) => (
          <Link
            key={route.path}
            to={route.path}
            className="card card-interactive flex items-center gap-3 p-4 hover:bg-paper-50 dark:hover:bg-paper-800"
          >
            <SectionIcon name={route.icon} />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-paper-900 dark:text-paper-100">
                {t(route.title)}
              </span>
              <span className="block text-xs text-paper-600 dark:text-paper-400">
                {t(route.summary)}
              </span>
            </span>
            <span
              aria-hidden="true"
              className="text-paper-600 dark:text-paper-400"
            >
              <Icon name="chevron" className="w-4 h-4" />
            </span>
          </Link>
        ))}
      </nav>
    </Page>
  );
}
