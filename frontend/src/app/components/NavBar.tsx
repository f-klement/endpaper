import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { ExportFormat, type UserOut } from "../../api/generated/model";
import { Icon } from "../../components";
import type { IconName } from "../../components";
import { useTranslation, type MessageKey } from "../../i18n";
import { useExportLibrary } from "../hooks";

const LINKS: { to: string; label: MessageKey; icon: IconName; end: boolean }[] =
  [
    { to: "/", label: "nav.library", icon: "library", end: true },
    { to: "/scan", label: "nav.scan", icon: "camera", end: false },
    { to: "/series", label: "series.title", icon: "link", end: false },
    { to: "/loans", label: "nav.loans", icon: "handshake", end: false },
    { to: "/stats", label: "nav.stats", icon: "chart", end: false },
    { to: "/settings", label: "nav.settings", icon: "settings", end: false },
  ];

interface NavBarProps {
  user: UserOut;
  onSignOut: () => void;
}

/**
 * The persistent sidebar.
 *
 * Icons-only under `md`, labelled above it. App chrome rather than a page, so
 * it lives with App rather than in `pages/`.
 */
export default function NavBar({ user, onSignOut }: NavBarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const navigate = useNavigate();
  const { exportLibrary } = useExportLibrary();
  const { t } = useTranslation();

  // Close the account menu when a click lands outside it.
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
      "relative flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium",
      "transition-[background-color,color] duration-150 ease-[var(--ease-out-soft)]",
      // The marker is the state, and the tint only supports it. Colour alone
      // would leave the current page indistinguishable to anyone who cannot
      // separate these two hues.
      isActive
        ? "text-accent-700 bg-accent-50 dark:text-accent-200 dark:bg-accent-500/12 " +
          "before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 " +
          "before:h-5 before:w-[3px] before:rounded-r-full before:bg-accent-600 " +
          "dark:before:bg-accent-400"
        : "text-paper-500 hover:text-paper-900 hover:bg-paper-100 " +
          "dark:text-paper-400 dark:hover:text-paper-100 dark:hover:bg-paper-800/70",
    ].join(" ");

  return (
    <nav className="fixed left-0 top-0 bottom-0 w-14 md:w-52 flex flex-col py-4 z-50 bg-white/85 backdrop-blur-xl border-r border-paper-200/70 dark:bg-paper-900/85 dark:border-paper-800/70">
      {/* A wordmark, not a logo. The sidebar previously opened straight into a
          column of emoji, which is the single thing that most made this read as
          a toy rather than as an application. */}
      <div className="px-3 md:px-4 pb-4 mb-1">
        <span className="hidden md:block text-[15px] font-semibold tracking-tight text-paper-900 dark:text-paper-100">
          Endpaper
        </span>
        <span
          aria-hidden="true"
          className="md:hidden block w-7 h-7 rounded-md bg-accent-600 text-white text-sm font-semibold grid place-items-center dark:bg-accent-500 dark:text-paper-950"
        >
          E
        </span>
      </div>

      <div className="flex flex-col gap-1 flex-1 px-2">
        {LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            className={linkClass}
          >
            <Icon name={link.icon} className="w-[18px] h-[18px]" />
            <span className="hidden md:block truncate">{t(link.label)}</span>
          </NavLink>
        ))}
      </div>

      <div className="px-2 relative" ref={menuRef}>
        {menuOpen && (
          // Below `md` the rail is 56px wide, and `left-2 right-2` made this
          // menu 40px wide: every label wrapped to roughly one character per
          // line and folded in on itself. It is allowed to overhang the rail
          // there instead, which is what a popover is for. From `md` up the
          // rail is 208px and the original inset is right.
          <div
            role="menu"
            aria-label={t("nav.account")}
            className="absolute bottom-full left-2 mb-2 w-56 md:w-auto md:right-2 bg-white border border-paper-200 rounded-xl shadow-[var(--shadow-lift)] overflow-hidden dark:bg-paper-900 dark:border-paper-800"
          >
            <button
              onClick={() => {
                setMenuOpen(false);
                // Navigate rather than sign out: the current session survives
                // until a new login succeeds.
                navigate("/login");
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-paper-700 hover:bg-paper-100 transition-colors dark:text-paper-200 dark:hover:bg-paper-800"
            >
              {t("nav.switchAccount")}
            </button>

            <button
              onClick={() => {
                setMenuOpen(false);
                navigate("/?status=want_to_read&ownership=not_owned");
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-paper-700 hover:bg-paper-100 transition-colors dark:text-paper-200 dark:hover:bg-paper-800"
            >
              {t("nav.wishlist")}
            </button>

            <button
              onClick={() => {
                setMenuOpen(false);
                navigate("/duplicates");
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-paper-700 hover:bg-paper-100 transition-colors dark:text-paper-200 dark:hover:bg-paper-800"
            >
              {t("duplicates.title")}
            </button>

            <button
              onClick={() => {
                setMenuOpen(false);
                navigate("/trash");
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-paper-700 hover:bg-paper-100 transition-colors dark:text-paper-200 dark:hover:bg-paper-800"
            >
              {t("nav.trash")}
            </button>

            <button
              onClick={() => setExportOpen((open) => !open)}
              className="w-full text-left px-4 py-2.5 text-sm text-paper-700 hover:bg-paper-100 transition-colors flex items-center justify-between dark:text-paper-200 dark:hover:bg-paper-800"
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

            <button
              onClick={() => {
                setMenuOpen(false);
                onSignOut();
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-bloom-600 hover:bg-bloom-100 transition-colors dark:text-bloom-300 dark:hover:bg-bloom-700/25"
            >
              {t("nav.logout")}
            </button>
          </div>
        )}

        <button
          ref={triggerRef}
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          onClick={() => setMenuOpen((open) => !open)}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-paper-500 hover:text-paper-900 hover:bg-paper-100 transition-colors dark:text-paper-400 dark:hover:text-paper-100 dark:hover:bg-paper-800"
        >
          {/* An initial, not a generic person emoji. It is the one place the
              interface can say "this is you" rather than "this is a user". */}
          <span
            aria-hidden="true"
            className="shrink-0 w-7 h-7 rounded-full grid place-items-center text-xs font-semibold bg-accent-100 text-accent-700 dark:bg-accent-500/20 dark:text-accent-200"
          >
            {user.username.slice(0, 1).toUpperCase()}
          </span>
          <span className="hidden md:block truncate">{user.username}</span>
        </button>
      </div>
    </nav>
  );
}
