import { useTranslation } from "../../i18n";
import ErrorLayout from "./components/ErrorLayout";

/**
 * The dead end an edge sign-out degrades to when reloading did not fix it.
 *
 * Not a route: nothing links here and no path renders it. The shell swaps it in
 * when `api/mutator.ts` reports that a session ended at the reverse proxy and
 * that it has already reloaded once for this, which is the moment the old build
 * started reloading forever behind a spinner.
 *
 * The button is a reload, the same top-level navigation the automatic path
 * takes, and that is deliberate rather than careless: it is the one request a
 * browser follows across origins, so it is the only thing that can reach a
 * portal on another hostname. The difference from the loop is that a person
 * asks for it, once.
 */
export default function SessionEndedPage() {
  const { t } = useTranslation();
  return (
    <ErrorLayout
      icon="lock"
      code={t("error.sessionEnded.code")}
      title={t("error.sessionEnded.title")}
      message={t("error.sessionEnded.message")}
      action={
        <button
          // The only screen in this app that arrives unbidden: it replaces the
          // tree from inside a response handler, so focus was on an element
          // that has just unmounted and falls to <body>. Every other terminal
          // state here follows a click. This puts focus on the one control.
          autoFocus
          onClick={() => window.location.reload()}
          className="inline-block px-5 py-2.5 bg-accent-fill hover:bg-accent-fill-hover text-on-accent text-sm font-semibold rounded-lg transition-colors"
        >
          {t("error.sessionEnded.action")}
        </button>
      }
    />
  );
}
