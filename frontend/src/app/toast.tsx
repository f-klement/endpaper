import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { Toast, type ToastAction } from "../components";

interface ToastRequest {
  message: string;
  action?: ToastAction;
}

interface ToastContextValue {
  show: (request: ToastRequest) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/**
 * One toast at a time, shown above everything.
 *
 * App chrome rather than a page, so it lives here with the sidebar and the
 * providers. One at a time deliberately: a stack of them covers the thing the
 * reader was looking at, and the only producer is a delete, which nobody does
 * twice in eight seconds by accident.
 *
 * The undo action lives in the caller, not here. This knows nothing about
 * books, which is what keeps it reusable and keeps `src/components/Toast`
 * domain free.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<ToastRequest | null>(null);

  const show = useCallback((next: ToastRequest) => setRequest(next), []);
  const value = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {request && (
        // Above the sidebar's z-50, and inset from the bottom on a phone where
        // the sidebar is a narrow rail rather than a column.
        <div className="fixed bottom-4 left-1/2 z-[60] w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2">
          <Toast
            message={request.message}
            action={request.action}
            onDismiss={() => setRequest(null)}
          />
        </div>
      )}
    </ToastContext.Provider>
  );
}

/**
 * Show a transient message.
 *
 * Returns a no-op outside a provider rather than throwing. A toast is a
 * courtesy: a test that renders one component in isolation should not fail
 * because nothing was listening.
 */
export function useToast(): ToastContextValue {
  return useContext(ToastContext) ?? { show: () => undefined };
}
