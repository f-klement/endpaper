import { Component, type ErrorInfo, type ReactNode } from "react";

import { useTranslation } from "../../i18n";

import ErrorLayout from "./components/ErrorLayout";

interface ErrorPageProps {
  /** Shown only in development; never rendered in a production build. */
  error?: unknown;
  onReset?: () => void;
}

/**
 * The client-side equivalent of a 500: a render crashed.
 *
 * The message is deliberately generic. In development the actual error is
 * shown underneath, because that is the one place it helps; in a production
 * build it is withheld, for the same reason the backend never returns a
 * traceback: it can quote internal detail back to whoever tripped it.
 */
export default function ErrorPage({ error, onReset }: ErrorPageProps) {
  const { t } = useTranslation();
  return (
    <ErrorLayout
      icon="alert"
      code={t("error.500.code")}
      title={t("error.500.title")}
      message={
        <>
          {t("error.500.message")}
          {import.meta.env.DEV && error instanceof Error && (
            <span className="mt-3 block text-left text-xs font-mono text-bloom-500 break-words dark:text-bloom-300">
              {error.message}
            </span>
          )}
        </>
      }
      action={
        <button
          onClick={onReset ?? (() => window.location.reload())}
          className="inline-block px-5 py-2.5 bg-accent-600 hover:bg-accent-700 text-white text-sm font-semibold rounded-lg transition-colors"
        >
          {t("error.reload")}
        </button>
      }
    />
  );
}

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: unknown;
}

/**
 * Catches a render-time crash anywhere below it.
 *
 * Without this, one component throwing unmounts the whole tree and leaves a
 * blank white page with no explanation and no way back.
 *
 * Must be a class: there is still no hook equivalent of componentDidCatch.
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The detail has to go somewhere, or the failure is invisible.
    console.error("Unhandled render error:", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error != null) {
      return (
        <ErrorPage
          error={this.state.error}
          onReset={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}
