import { BrowserRouter, Route, Routes } from "react-router-dom";

import type { QueryClient } from "@tanstack/react-query";

import { Spinner } from "../components";
import { useTranslation } from "../i18n";
import { ErrorPage } from "../pages/errors";
import LoginPage from "../pages/LoginPage";
import { useSession } from "../pages/hooks";
import AppearanceSync from "./components/AppearanceSync";
import NavBar, { BAR_OFFSET } from "./components/NavBar";
import Providers from "./providers";
import AppRoutes from "./routes";

interface AppProps {
  /** Injectable so tests can supply a client with retries disabled. */
  queryClient?: QueryClient;
}

/**
 * The application shell.
 *
 * Routing is gated on the session: signed out, every path renders the login
 * page, so there is no route that can be reached without an account.
 */
export default function App({ queryClient }: AppProps) {
  return (
    <Providers queryClient={queryClient}>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </Providers>
  );
}

/** Inside the router, so pages and NavBar can use routing hooks. */
function AppShell() {
  const { t } = useTranslation();
  const {
    user,
    mode,
    signIn,
    signOut,
    isResolving,
    proxyUnidentified,
    isSwitched,
  } = useSession();

  // Under proxy auth the identity arrives from the server, so there is a
  // moment before we know who this is. Rendering the login form during it
  // would flash a screen that mode never uses.
  if (isResolving) {
    return <Spinner label={t("login.signingYouIn")} />;
  }

  if (proxyUnidentified) {
    // The upstream did not identify anyone. A login form would be useless
    // here, since this deployment has no local passwords to offer.
    return <ErrorPage />;
  }

  if (!user) {
    return (
      <Routes>
        <Route path="*" element={<LoginPage onSignIn={signIn} />} />
      </Routes>
    );
  }

  return (
    <>
      {/* Renders nothing. Here rather than in Providers because the appearance
          belongs to an account, and this is the first place one is known. */}
      <AppearanceSync accountId={user.id} />
      {/* The bar is fixed, so without this padding the first thing on every
          page sits underneath it. Imported rather than restated: see
          NavBar.BAR_OFFSET. */}
      <div className={BAR_OFFSET}>
        <AppRoutes user={user} mode={mode} onSignIn={signIn} />
      </div>
      <NavBar
        user={user}
        mode={mode}
        isSwitched={isSwitched}
        onSignOut={signOut}
      />
    </>
  );
}
