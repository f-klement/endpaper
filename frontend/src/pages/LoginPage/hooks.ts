import { useState } from "react";

import {
  useAuthConfig,
  useLogin,
  useRegister,
} from "../../api/generated/endpoints/auth/auth";
import {
  useGetFeatureFlags,
  useGetLoginImage,
  useSetLoginImage,
} from "../../api/generated/endpoints/settings/settings";
import { AuthMode, type UserOut } from "../../api/generated/model";

export type Mode = "login" | "register";

export interface UseLoginFormResult {
  mode: Mode;
  setMode: (mode: Mode) => void;
  registrationEnabled: boolean;
  /** True when a directory authenticates, so the form is not our own. */
  isDirectoryLogin: boolean;

  submit: (username: string, password: string) => void;
  isSubmitting: boolean;
  error: unknown;
  clearError: () => void;
}

/**
 * Sign-in and registration.
 *
 * `onSuccess` receives the account and token; storing them is the caller's
 * job, so this hook stays unaware of how the session is kept.
 */
export function useLoginForm(
  onSuccess: (user: UserOut, token: string) => void,
): UseLoginFormResult {
  const [mode, setMode] = useState<Mode>("login");
  const [dismissed, setDismissed] = useState(false);

  const config = useAuthConfig();
  // Assume open until told otherwise: the backend rejects a disabled signup
  // anyway, so a failed config fetch should not hide a working tab.
  const registrationEnabled = config.data?.registration_enabled ?? true;
  const isDirectoryLogin = config.data?.auth_mode === AuthMode.ldap;

  const handleSuccess = (data: { user: UserOut; access_token: string }) => {
    onSuccess(data.user, data.access_token);
  };

  const login = useLogin({ mutation: { onSuccess: handleSuccess } });
  const register = useRegister({ mutation: { onSuccess: handleSuccess } });

  const active = mode === "login" ? login : register;

  return {
    mode,
    setMode: (next) => {
      setMode(next);
      setDismissed(true);
    },
    registrationEnabled,
    isDirectoryLogin,

    submit: (username, password) => {
      setDismissed(false);
      active.mutate({ data: { username, password } });
    },
    isSubmitting: active.isPending,
    error: dismissed ? null : active.error,
    clearError: () => setDismissed(true),
  };
}

export interface UseLoginBackgroundResult {
  url: string | null;
  isUploading: boolean;
  error: unknown;
  upload: (file: File) => void;
}

/** The admin-set login background. A 404 simply means none is set. */
export function useLoginBackground(): UseLoginBackgroundResult {
  const [cacheBustedUrl, setCacheBustedUrl] = useState<string | null>(null);

  const current = useGetLoginImage({
    query: {
      // A missing background is the normal case, not a fault worth retrying.
      retry: false,
    },
  });

  const upload = useSetLoginImage({
    mutation: {
      onSuccess: (data) => {
        // The filename is stable, so without a changing query the browser
        // would keep showing the previous image.
        setCacheBustedUrl(`${data.url}?t=${Date.now()}`);
      },
    },
  });

  return {
    url: cacheBustedUrl ?? current.data?.url ?? null,
    isUploading: upload.isPending,
    error: upload.error,
    upload: (file) => upload.mutate({ data: { file } }),
  };
}

/**
 * Whether this deployment has a published catalogue to offer.
 *
 * Read here rather than through `app/hooks` so a page never imports from the
 * shell: the dependency runs the other way, and `ScanPage` and `BookDetail`
 * both read the same flags through their own `hooks.ts` for the same reason.
 *
 * `public_catalogue_published` is the **server's** conjunction of library mode
 * and the publish switch, not either row, so a browser cannot get the nesting
 * rule wrong by reading one of them. `retry: false` because the login page
 * renders regardless: a failure here means no link, not an error screen.
 */
export function usePublishedCatalogue(): boolean {
  const flags = useGetFeatureFlags({
    query: { retry: false, staleTime: 60_000 },
  });
  return flags.data?.public_catalogue_published === true;
}
