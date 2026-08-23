import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { onSessionEnded } from "../api/mutator";
import { Spinner } from "../components";
import { useTranslation } from "../i18n";
import { ErrorPage, SessionEndedPage } from "../pages/errors";
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
  const sessionEnded = useSessionEndedAtEdge();
  const {
    user,
    mode,
    signIn,
    signOut,
    isResolving,
    proxyUnidentified,
    isSwitched,
  } = useSession();

  // Before every other branch, and that ordering is the fix. This state is
  // reached from inside a request, so whatever the shell was showing at the
  // time is what it keeps showing: for the reader who reported it that was the
  // spinner below, for ever.
  if (sessionEnded) {
    return <SessionEndedPage />;
  }

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

/**
 * True once the proxy has signed us out and a reload has not brought us back.
 *
 * Component state rather than a module flag in `mutator.ts`: a flag would
 * outlive the mount that read it, so the second test in a file, or a second
 * mount in a browser, would start out already dead.
 *
 * **The cache is emptied here, and this is the only place that has to.** Every
 * other way a session ends leaves the document: `signOut` clears the client
 * itself, and `endSession` navigates to `/login`, which drops all memory with
 * the page. This branch does neither, so without the clear the QueryClient
 * would go on holding every book, loan, quote and setting the reader fetched,
 * behind a screen telling them their session is over.
 */
function useSessionEndedAtEdge(): boolean {
  const queryClient = useQueryClient();
  const [ended, setEnded] = useState(false);

  useEffect(
    () =>
      onSessionEnded(() => {
        queryClient.clear();
        setEnded(true);
      }),
    [queryClient],
  );

  return ended;
}
