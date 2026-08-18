import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { ExportFormat, type UserOut } from "../../api/generated/model";
import { useTranslation, type MessageKey } from "../../i18n";
import { useExportLibrary } from "../hooks";

const LINKS: { to: string; label: MessageKey; glyph: string; end: boolean }[] =
  [
    { to: "/", label: "nav.library", glyph: "📚", end: true },
    { to: "/scan", label: "nav.scan", glyph: "📷", end: false },
    { to: "/series", label: "series.title", glyph: "🔗", end: false },
    { to: "/loans", label: "nav.loans", glyph: "🤝", end: false },
    { to: "/stats", label: "nav.stats", glyph: "📊", end: false },
    { to: "/settings", label: "nav.settings", glyph: "⚙️", end: false },
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
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [menuOpen]);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
      isActive
        ? "text-sky-600 bg-sky-50"
        : "text-gray-500 hover:text-gray-800 hover:bg-gray-50"
    }`;

  return (
    <nav className="fixed left-0 top-0 bottom-0 w-14 md:w-48 bg-white border-r border-gray-200 flex flex-col py-4 z-50 dark:bg-gray-900 dark:border-gray-700">
      <div className="flex flex-col gap-1 flex-1 px-2">
        {LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            className={linkClass}
          >
            <span className="text-xl shrink-0">{link.glyph}</span>
            <span className="hidden md:block text-sm font-medium">
              {t(link.label)}
            </span>
          </NavLink>
        ))}
      </div>

      <div className="px-2 relative" ref={menuRef}>
        {menuOpen && (
          <div className="absolute bottom-full left-2 right-2 mb-1 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden dark:bg-gray-900 dark:border-gray-700">
            <button
              onClick={() => {
                setMenuOpen(false);
                // Navigate rather than sign out: the current session survives
                // until a new login succeeds.
                navigate("/login");
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors dark:text-gray-200 dark:hover:bg-gray-800"
            >
              {t("nav.switchAccount")}
            </button>

            <button
              onClick={() => {
                setMenuOpen(false);
                navigate("/?status=want_to_read&ownership=not_owned");
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors dark:text-gray-200 dark:hover:bg-gray-800"
            >
              {t("nav.wishlist")}
            </button>

            <button
              onClick={() => {
                setMenuOpen(false);
                navigate("/duplicates");
              }}
              className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors dark:text-gray-200 dark:hover:bg-gray-800"
            >
              {t("duplicates.title")}
            </button>

            <button
              onClick={() => setExportOpen((open) => !open)}
              className="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-between dark:text-gray-200 dark:hover:bg-gray-800"
            >
              {t("nav.exportLibrary")}
              <span className="text-xs opacity-50">
                {exportOpen ? "▲" : "▶"}
              </span>
            </button>

            {exportOpen && (
              <div className="border-t border-gray-100 bg-gray-50 flex gap-2 px-4 py-2.5 dark:border-gray-800 dark:bg-gray-900">
                {[ExportFormat.csv, ExportFormat.txt].map((format) => (
                  <button
                    key={format}
                    onClick={() => {
                      exportLibrary(format);
                      setMenuOpen(false);
                    }}
                    className="flex-1 text-center py-1.5 text-xs font-medium rounded-lg border border-gray-200 bg-white text-gray-700 hover:bg-sky-50 hover:border-sky-300 transition-colors uppercase dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
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
              className="w-full text-left px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors dark:text-red-400"
            >
              {t("nav.logout")}
            </button>
          </div>
        )}

        <button
          onClick={() => setMenuOpen((open) => !open)}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-500 hover:text-gray-800 hover:bg-gray-50 transition-colors dark:text-gray-400 dark:hover:text-gray-100 dark:hover:bg-gray-800"
        >
          <span className="text-xl shrink-0">👤</span>
          <span className="hidden md:block text-sm font-medium">
            {user.username}
          </span>
        </button>
      </div>
    </nav>
  );
}
