import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Icon } from "../../../components";
import { useTranslation } from "../../../i18n";

interface PublicShellProps {
  children: ReactNode;
}

/**
 * The frame the published catalogue sits in, for a reader with no account.
 *
 * **A signed out reader has no `NavBar`**, which is what makes this necessary:
 * without it the public pages would render as bare content with no landmark, no
 * way back to the top of the catalogue and no way in for somebody who does have
 * an account.
 *
 * Three things and no more. A `<header>` carrying the catalogue's name as a
 * link home, a `<main>` for the content, and a way to sign in. Anything else
 * would be a second application drawn beside the first.
 *
 * The skip link is the one piece of chrome a public catalogue needs more than
 * the signed in app does: a reader arriving from a search result lands on a
 * page whose first interactive element is a search box they may not want, and
 * a public terminal is the most likely place in this application for somebody
 * to be navigating by keyboard alone.
 */
export default function PublicShell({ children }: PublicShellProps) {
  const { t } = useTranslation();

  return (
    <>
      {/* Off screen until focused, which is the whole point: it is for the
          reader who tabs, and invisible to everyone else. */}
      <a
        href="#public-catalogue-main"
        // No ring of its own. `index.css` draws one ring for the whole app on
        // `:focus-visible`, and a control that brings its own is the control
        // that gets missed the next time that one moves; twenty-one of them
        // were. What is here is only what makes an `sr-only` link visible once
        // it has focus.
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-3 focus:px-3 focus:py-2 focus:rounded-lg focus:bg-paper-0 focus:text-paper-900 dark:focus:bg-paper-900 dark:focus:text-paper-100"
      >
        {t("public.skipToContent")}
      </a>
      <header className="border-b border-paper-200 dark:border-paper-800">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3 flex items-center gap-3">
          <Link
            to="/catalogue"
            className="flex items-center gap-2 font-semibold text-paper-900 dark:text-paper-100"
          >
            <Icon name="library" className="w-5 h-5" />
            {t("public.title")}
          </Link>
          <Link
            to="/login"
            className="ml-auto text-sm font-medium text-accent-700 dark:text-accent-300"
          >
            {t("public.signIn")}
          </Link>
        </div>
      </header>
      {/* `tabIndex={-1}` so the skip link can move focus here. Without it the
          browser scrolls to the anchor and leaves focus in the header, so the
          next Tab goes back to the link that was just used. */}
      <main id="public-catalogue-main" tabIndex={-1}>
        {children}
      </main>
    </>
  );
}
