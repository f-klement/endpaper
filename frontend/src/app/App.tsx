import { BrowserRouter, Route, Routes } from "react-router-dom";

import type { QueryClient } from "@tanstack/react-query";

import { Spinner } from "../components";
import { useTranslation } from "../i18n";
import { ErrorPage } from "../pages/errors";
import LoginPage from "../pages/LoginPage";
import { useSession } from "../pages/hooks";
import NavBar from "./components/NavBar";
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
  const { user, signIn, signOut, isResolving, proxyUnidentified } =
    useSession();

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
      {/* Offset matches NavBar's width at each breakpoint. */}
      <div className="ml-14 md:ml-48">
        <AppRoutes user={user} onSignIn={signIn} />
      </div>
      <NavBar user={user} onSignOut={signOut} />
    </>
  );
}
