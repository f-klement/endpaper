import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { createQueryClient } from "../api/query-client";
import { useFeatureFlags } from "./hooks";
import { LocaleProvider } from "../i18n";
import { ThemeProvider } from "../theme";
import { ErrorBoundary } from "../pages/errors";
import { ToastProvider } from "./toast";

interface ProvidersProps {
  children: ReactNode;
  /** Injectable so tests can supply a client with retries disabled. */
  queryClient?: QueryClient;
}

/**
 * Everything the tree needs above the router.
 *
 * The boundary is outermost so a crash inside a provider, or inside any page,
 * still renders the error page rather than a blank document.
 */
export default function Providers({ children, queryClient }: ProvidersProps) {
  // useState, not a module constant: created once per mount, so each test gets
  // a clean cache instead of inheriting the previous test's data.
  const [client] = useState(() => queryClient ?? createQueryClient());

  return (
    <ErrorBoundary>
      <QueryClientProvider client={client}>
        <ThemeProvider>
          {/* Inside the locale gate: a toast is written in the reader's
              language, so it needs the catalogue that gate supplies. */}
          <LocaleGate>
            <ToastProvider>{children}</ToastProvider>
          </LocaleGate>
        </ThemeProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

/**
 * Supplies the server's default language to the locale provider.
 *
 * Rendered rather than awaited: the browser's own language is known
 * synchronously and answers the question for almost everyone, so blocking the
 * first paint on a network round trip would trade a real delay for a rare
 * improvement. The server default only matters for a browser set to a language
 * this app does not speak.
 */
function LocaleGate({ children }: { children: ReactNode }) {
  const flags = useFeatureFlags();

  return (
    <LocaleProvider serverDefault={flags?.default_locale}>
      {children}
    </LocaleProvider>
  );
}
