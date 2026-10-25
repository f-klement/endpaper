import { Route, Routes } from "react-router-dom";

import type { AuthMode, UserOut } from "../api/generated/model";
import AppearancePage from "../pages/AppearancePage";
import AuthorsPage from "../pages/AuthorsPage";
import BookDetail from "../pages/BookDetail";
import CollectionsPage from "../pages/CollectionsPage";
import DuplicatesPage from "../pages/DuplicatesPage";
import { NotFoundPage } from "../pages/errors";
import Home from "../pages/Home";
import LoansPage from "../pages/LoansPage";
import LoginPage from "../pages/LoginPage";
import OverduePage from "../pages/OverduePage";
import PublicCataloguePage, {
  PublicBookPage,
} from "../pages/PublicCataloguePage";
import QuotesPage from "../pages/QuotesPage";
import ScanPage from "../pages/ScanPage";
import SeriesPage from "../pages/SeriesPage";
import SettingsPage, {
  AboutSettingsPage,
  AccountSettingsPage,
  AppearanceSettingsPage,
  CatalogueSettingsPage,
  DataSettingsPage,
  LendingSettingsPage,
  LibrarySettingsPage,
  PublicCatalogueSettingsPage,
} from "../pages/SettingsPage";
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
      {/* A child path of `/loans` rather than a sibling at the root, because
          that is what it is: the same records, narrowed to the ones worth
          chasing. React Router matches whole paths, so the order of these two
          does not decide anything; the nesting is for the reader's address
          bar and their back button. */}
      <Route path="/loans/overdue" element={<OverduePage />} />
      <Route path="/series" element={<SeriesPage />} />
      <Route path="/authors" element={<AuthorsPage />} />
      <Route path="/collections" element={<CollectionsPage />} />
      <Route path="/quotes" element={<QuotesPage />} />
      <Route path="/duplicates" element={<DuplicatesPage />} />
      <Route path="/stats" element={<StatsPage />} />
      {/* Settings is an index of six routes rather than one long page. The
          order here is the order `SETTINGS_ROUTES` draws them in, and that
          table is what the index page reads: a route added in one place and
          not the other is a link to a 404, or a screen nothing reaches. */}
      <Route path="/settings" element={<SettingsPage currentUser={user} />} />
      <Route path="/settings/appearance" element={<AppearanceSettingsPage />} />
      {/* A child of Appearance rather than a sibling, because that is what it
          is: the palette and wallpaper picker the Appearance screen links to.
          Inside the signed-in table, deliberately. `ThemeProvider` sits above
          the session gate and does not unmount on sign-out, so a picker the
          login screen could reach would write a choice into the account that
          left. See `ThemeProvider.release`. */}
      <Route path="/settings/appearance/theme" element={<AppearancePage />} />
      <Route
        path="/settings/account"
        element={<AccountSettingsPage currentUser={user} />}
      />
      <Route path="/settings/catalogue" element={<CatalogueSettingsPage />} />
      <Route path="/settings/library" element={<LibrarySettingsPage />} />
      <Route
        path="/settings/public"
        element={<PublicCatalogueSettingsPage />}
      />
      <Route path="/settings/lending" element={<LendingSettingsPage />} />
      <Route
        path="/settings/data"
        element={<DataSettingsPage mode={mode} onSignIn={onSignIn} />}
      />
      <Route path="/settings/about" element={<AboutSettingsPage />} />
      <Route path="/trash" element={<TrashPage />} />
      {/* The published catalogue, mounted here **as well as** above the
          session gate in `App.tsx`. A member following a link to a public
          record would otherwise land on the 404 page, and an admin who has
          just switched publishing on has no way to look at what they
          published. The two screens are identical either way: they read the
          public endpoints, which attach no token and answer the same to
          everybody. */}
      <Route path="/catalogue" element={<PublicCataloguePage />} />
      <Route path="/catalogue/:id" element={<PublicBookPage />} />
      {/* Reachable while signed in so "Switch Account" can show the form
          without ending the current session first. */}
      <Route path="/login" element={<LoginPage onSignIn={onSignIn} />} />
      {/* A real 404 page. This used to redirect to "/", which quietly hid
          every mistyped or dead link. */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
