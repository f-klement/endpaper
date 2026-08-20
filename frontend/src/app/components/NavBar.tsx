import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";

import {
  AuthMode,
  ExportFormat,
  type UserOut,
} from "../../api/generated/model";
import { Icon } from "../../components";
import type { IconName } from "../../components";
import { useTranslation, type MessageKey } from "../../i18n";
import { useExportLibrary } from "../hooks";

/**
 * The three destinations that stay on the bar as icons.
 *
 * Three because a phone's top bar has room for three and a wordmark, and these
 * are the three: the shelf, adding to it, and who has what. Everything else is
 * reached often enough to be in a menu and rarely enough not to be on the bar.
 *
 * Scan uses the magnifying glass, not a camera. That screen is a lookup, and it
 * is a lookup by search box as often as by barcode; the camera is the odd one
 * out beside the two glyphs beside it.
 */
const PRIMARY: { to: string; label: MessageKey; icon: IconName; end: boolean }[] =
  [
    { to: "/", label: "nav.library", icon: "library", end: true },
    { to: "/scan", label: "nav.scan", icon: "search", end: false },
    { to: "/loans", label: "nav.loans", icon: "handshake", end: false },
  ];

/** Everything else. Navigation only: the actions below are written out. */
const SECONDARY: { to: string; label: MessageKey }[] = [
  { to: "/series", label: "series.title" },
  { to: "/stats", label: "nav.stats" },
  { to: "/settings", label: "nav.settings" },
  { to: "/?status=want_to_read&ownership=not_owned", label: "nav.wishlist" },
  { to: "/duplicates", label: "duplicates.title" },
  { to: "/trash", label: "nav.trash" },
];

/**
 * The bar's height, and the top padding the content needs to clear it.
 *
 * The bar is fixed, so these two have to be the same number: too little and
 * the first thing on every page sits behind it, too much and there is a gap.
 * `App.tsx` imports `BAR_OFFSET` rather than restating it.
 *
 * Two literals for one number, and they must stay literals. Tailwind scans the
 * source for whole class names, so a composed `h-${n}` generates no CSS at all
 * and the bar silently loses its height in a production build. Keeping them
 * adjacent is as close to one fact as that scanner allows; the test asserts
 * they agree.
 */
export const BAR_HEIGHT = "h-14";
export const BAR_OFFSET = "pt-14";

interface NavBarProps {
  user: UserOut;
  /**
   * How this deployment authenticates. Under `proxy` the upstream owns the
   * session, so the menu offers neither sign out nor switch account.
   */
  mode: AuthMode;
  onSignOut: () => void;
}

const ITEM_CLASS =
  "block w-full text-left px-4 py-2.5 text-sm text-paper-700 " +
  "hover:bg-paper-100 transition-colors dark:text-paper-200 dark:hover:bg-paper-800";

/**
 * The application bar.
 *
 * Fixed to the top rather than a left rail. The rail cost 56px of a phone's
 * width on every screen to show three icons and a fold-out that had nowhere to
 * open into, and the app is mostly used from a phone.
 *
 * App chrome rather than a page, so it lives with App rather than in `pages/`.
 */
export default function NavBar({ user, mode, onSignOut }: NavBarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const { exportLibrary } = useExportLibrary();
  const { t } = useTranslation();

  // Under proxy auth both of these are inert: the upstream owns the session,
  // and the app re-identifies the same person on the very next request. An
  // offer that cannot do anything is worse than no offer.
  const ownsTheSession = mode !== AuthMode.proxy;

  useEffect(() => {
    if (!menuOpen) {
      setExportOpen(false);
      return;
    }
    function handleClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    // Escape closes it and hands focus back. Without this the only way out by
    // keyboard is to tab through every item in the menu.
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [menuOpen]);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    [
      "relative flex items-center gap-2 px-2.5 sm:px-3 h-9 rounded-lg text-sm font-medium",
      "transition-[background-color,color] duration-150 ease-[var(--ease-out-soft)]",
      // The underline is the state and the tint only supports it. Colour alone
      // would leave the current page indistinguishable to anyone who cannot
      // separate these two hues.
      isActive
        ? "text-accent-700 bg-accent-50 dark:text-accent-200 dark:bg-accent-500/12 " +
          "after:absolute after:left-2.5 after:right-2.5 after:-bottom-[7px] " +
          "after:h-[2px] after:rounded-full after:bg-accent-600 " +
          "dark:after:bg-accent-400"
        : "text-paper-500 hover:text-paper-900 hover:bg-paper-100 " +
          "dark:text-paper-400 dark:hover:text-paper-100 dark:hover:bg-paper-800/70",
    ].join(" ");

  function go(children: ReactNode, to: string, key: string) {
    return (
      <Link
        key={key}
        to={to}
        role="menuitem"
        onClick={() => setMenuOpen(false)}
        className={ITEM_CLASS}
      >
        {children}
      </Link>
    );
  }

  return (
    <nav
      className={`fixed top-0 left-0 right-0 ${BAR_HEIGHT} flex items-center gap-1 px-2 sm:px-4 z-50 bg-white/85 backdrop-blur-xl border-b border-paper-200/70 dark:bg-paper-900/85 dark:border-paper-800/70`}
    >
      {/* A wordmark, not a logo. The app previously opened straight into a
          column of emoji, which is the single thing that most made it read as
          a toy rather than as an application. */}
      <Link to="/" className="shrink-0 mr-1 sm:mr-3">
        <span className="hidden md:block text-[15px] font-semibold tracking-tight text-paper-900 dark:text-paper-100">
          Endpaper
        </span>
        <span
          aria-hidden="true"
          className="md:hidden block w-7 h-7 rounded-md bg-accent-600 text-white text-sm font-semibold grid place-items-center dark:bg-accent-500 dark:text-paper-950"
        >
          E
        </span>
      </Link>

      <div className="flex items-center gap-1 min-w-0">
        {PRIMARY.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            // The label is the accessible name at every width, so the icon
            // never has to carry the meaning on its own.
            aria-label={t(link.label)}
            className={linkClass}
          >
            <Icon name={link.icon} className="w-[18px] h-[18px] shrink-0" />
            <span className="hidden sm:block truncate">{t(link.label)}</span>
          </NavLink>
        ))}
      </div>

      <div className="ml-auto relative" ref={menuRef}>
        <button
          ref={triggerRef}
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          // Names the member, so who is signed in is answerable from the bar
          // without opening anything.
          aria-label={t("nav.menuFor", { name: user.username })}
          onClick={() => setMenuOpen((open) => !open)}
          className="flex items-center gap-2 h-9 pl-1 pr-2 rounded-lg text-sm font-medium text-paper-500 hover:text-paper-900 hover:bg-paper-100 transition-colors dark:text-paper-400 dark:hover:text-paper-100 dark:hover:bg-paper-800"
        >
          {/* An initial, not a generic person emoji. It is the one place the
              interface can say "this is you" rather than "this is a user". */}
          <span
            aria-hidden="true"
            className="shrink-0 w-7 h-7 rounded-full grid place-items-center text-xs font-semibold bg-accent-100 text-accent-700 dark:bg-accent-500/20 dark:text-accent-200"
          >
            {user.username.slice(0, 1).toUpperCase()}
          </span>
          <span className="hidden md:block truncate max-w-32">
            {user.username}
          </span>
          <Icon name="menu" className="w-[18px] h-[18px] shrink-0" />
        </button>

        {menuOpen && (
          // Right-aligned and its own width: it hangs off the bar rather than
          // being squeezed to the trigger, which is what a popover is for.
          <div
            role="menu"
            aria-label={t("nav.menu")}
            className="absolute right-0 top-full mt-2 w-56 bg-white border border-paper-200 rounded-xl shadow-[var(--shadow-lift)] overflow-hidden dark:bg-paper-900 dark:border-paper-800"
          >
            {SECONDARY.map((link) => go(t(link.label), link.to, link.to))}

            <button
              role="menuitem"
              onClick={() => setExportOpen((open) => !open)}
              className={`${ITEM_CLASS} flex items-center justify-between`}
            >
              {t("nav.exportLibrary")}
              <Icon
                name="chevron"
                className={`w-3.5 h-3.5 opacity-60 transition-transform duration-150 ${
                  exportOpen ? "rotate-90" : ""
                }`}
              />
            </button>

            {exportOpen && (
              <div className="border-t border-paper-200 bg-paper-100 flex gap-2 px-4 py-2.5 dark:border-paper-800 dark:bg-paper-950/60">
                {[ExportFormat.csv, ExportFormat.txt].map((format) => (
                  <button
                    key={format}
                    onClick={() => {
                      exportLibrary(format);
                      setMenuOpen(false);
                    }}
                    className="flex-1 text-center py-1.5 text-xs font-medium rounded-lg border border-paper-200 bg-white text-paper-700 hover:border-accent-300 hover:text-accent-700 transition-colors uppercase tracking-wide dark:border-paper-700 dark:bg-paper-900 dark:text-paper-200 dark:hover:text-accent-300"
                  >
                    {format}
                  </button>
                ))}
              </div>
            )}

            {ownsTheSession && (
              <>
                {/* A link, not a sign out: the current session survives until a
                    new login succeeds. */}
                {go(t("nav.switchAccount"), "/login", "switch")}

                <button
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    onSignOut();
                  }}
                  className="w-full text-left px-4 py-2.5 text-sm text-bloom-600 hover:bg-bloom-100 transition-colors dark:text-bloom-300 dark:hover:bg-bloom-700/25"
                >
                  {t("nav.logout")}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </nav>
  );
}
