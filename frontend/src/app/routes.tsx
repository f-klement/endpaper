import { Route, Routes } from "react-router-dom";

import type { AuthMode, UserOut } from "../api/generated/model";
import AppearancePage from "../pages/AppearancePage";
import BookDetail from "../pages/BookDetail";
import CollectionsPage from "../pages/CollectionsPage";
import DuplicatesPage from "../pages/DuplicatesPage";
import { NotFoundPage } from "../pages/errors";
import Home from "../pages/Home";
import LoansPage from "../pages/LoansPage";
import LoginPage from "../pages/LoginPage";
import ScanPage from "../pages/ScanPage";
import SeriesPage from "../pages/SeriesPage";
import SettingsPage from "../pages/SettingsPage";
import StatsPage from "../pages/StatsPage";
import TrashPage from "../pages/TrashPage";

interface AppRoutesProps {
  user: UserOut;
  /** Settings says what returning from a switched session costs in this mode. */
  mode: AuthMode;
  /** Also how a switch lands: it is a sign-in on somebody else's account. */
  onSignIn: (user: UserOut, token: string) => void;
}

/**
 * The signed-in route table.
 *
 * Every import here comes from a page's `index.ts`, never from a file inside
 * one. That barrel is the page's public surface.
 */
export default function AppRoutes({ user, mode, onSignIn }: AppRoutesProps) {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/scan" element={<ScanPage />} />
      <Route path="/book/:id" element={<BookDetail currentUser={user} />} />
      <Route path="/loans" element={<LoansPage />} />
      <Route path="/series" element={<SeriesPage />} />
      <Route path="/collections" element={<CollectionsPage />} />
      <Route path="/duplicates" element={<DuplicatesPage />} />
      <Route path="/stats" element={<StatsPage />} />
      <Route
        path="/settings"
        element={<SettingsPage mode={mode} onSignIn={onSignIn} />}
      />
      {/* Inside the signed-in table, deliberately. `ThemeProvider` sits above
          the session gate and does not unmount on sign-out, so a picker the
          login screen could reach would write a choice into the account that
          left. See `ThemeProvider.release`. */}
      <Route path="/settings/appearance" element={<AppearancePage />} />
      <Route path="/trash" element={<TrashPage />} />
      {/* Reachable while signed in so "Switch Account" can show the form
          without ending the current session first. */}
      <Route path="/login" element={<LoginPage onSignIn={onSignIn} />} />
      {/* A real 404 page. This used to redirect to "/", which quietly hid
          every mistyped or dead link. */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
