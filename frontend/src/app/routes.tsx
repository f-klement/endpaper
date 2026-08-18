import { Route, Routes } from "react-router-dom";

import type { UserOut } from "../api/generated/model";
import BookDetail from "../pages/BookDetail";
import DuplicatesPage from "../pages/DuplicatesPage";
import { NotFoundPage } from "../pages/errors";
import Home from "../pages/Home";
import LoansPage from "../pages/LoansPage";
import LoginPage from "../pages/LoginPage";
import ScanPage from "../pages/ScanPage";
import SeriesPage from "../pages/SeriesPage";
import SettingsPage from "../pages/SettingsPage";
import StatsPage from "../pages/StatsPage";

interface AppRoutesProps {
  user: UserOut;
  onSignIn: (user: UserOut, token: string) => void;
}

/**
 * The signed-in route table.
 *
 * Every import here comes from a page's `index.ts`, never from a file inside
 * one. That barrel is the page's public surface.
 */
export default function AppRoutes({ user, onSignIn }: AppRoutesProps) {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/scan" element={<ScanPage />} />
      <Route path="/book/:id" element={<BookDetail currentUser={user} />} />
      <Route path="/loans" element={<LoansPage />} />
      <Route path="/series" element={<SeriesPage />} />
      <Route path="/duplicates" element={<DuplicatesPage />} />
      <Route path="/stats" element={<StatsPage />} />
      <Route path="/settings" element={<SettingsPage />} />
      {/* Reachable while signed in so "Switch Account" can show the form
          without ending the current session first. */}
      <Route path="/login" element={<LoginPage onSignIn={onSignIn} />} />
      {/* A real 404 page. This used to redirect to "/", which quietly hid
          every mistyped or dead link. */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
