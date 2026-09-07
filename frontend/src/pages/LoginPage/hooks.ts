import { useState } from "react";

import {
  useAuthConfig,
  useConfirmAddress,
  useLogin,
  useRedeemPasswordReset,
  useRegister,
  useRequestPasswordReset,
  useRequestVerification,
} from "../../api/generated/endpoints/auth/auth";
import {
  useGetFeatureFlags,
  useGetLoginImage,
  useSetLoginImage,
} from "../../api/generated/endpoints/settings/settings";
import {
  AuthMode,
  type RegistrationOut,
  type UserOut,
} from "../../api/generated/model";

export type Mode = "login" | "register";

export interface UseLoginFormResult {
  mode: Mode;
  setMode: (mode: Mode) => void;
  registrationEnabled: boolean;
  /** True when a directory authenticates, so the form is not our own. */
  isDirectoryLogin: boolean;
  /** Whether this deployment will reset a local password at all. */
  passwordResetEnabled: boolean;
  /** Whether a new account has to confirm its address before it may sign in. */
  verificationRequired: boolean;
  /** Set when registration made an account that cannot sign in yet. */
  awaitingConfirmation: boolean;

  submit: (username: string, password: string, email: string) => void;
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
  // **Both default to false when the config has not arrived**, unlike
  // `registrationEnabled` above, and the asymmetry is deliberate. Assuming
  // registration is open costs a failed request the server refuses anyway;
  // assuming a recovery link exists draws a control that 403s, and assuming an
  // address is required makes a form demand a field the deployment does not
  // want. Absent means offer less.
  const passwordResetEnabled = config.data?.password_reset_enabled ?? false;
  const verificationRequired = config.data?.verification_required ?? false;

  const handleSuccess = (data: { user: UserOut; access_token: string }) => {
    onSuccess(data.user, data.access_token);
  };

  const login = useLogin({ mutation: { onSuccess: handleSuccess } });
  const register = useRegister({
    mutation: {
      onSuccess: (data: RegistrationOut) => {
        // **A registration that produced no token produced no session**, which
        // is the whole of the account policy on this side: the account exists
        // and may do nothing until it is confirmed. Reading `token` rather than
        // `verification_required` is deliberate, because the thing that decides
        // whether to sign somebody in is whether there is anything to sign them
        // in with.
        if (data.token) {
          handleSuccess(data.token);
        }
      },
    },
  });

  const active = mode === "login" ? login : register;

  return {
    mode,
    setMode: (next) => {
      setMode(next);
      setDismissed(true);
    },
    registrationEnabled,
    isDirectoryLogin,
    passwordResetEnabled,
    verificationRequired,
    awaitingConfirmation: register.data?.token == null && register.isSuccess,

    // **The address goes only to registration.** `LoginRequest` has no such
    // field, and sending one would be a payload the sign in route never asked
    // for. An empty string is sent as nothing at all: `UserCreate` reads "" as
    // no address, and this keeps the two ends agreeing rather than relying on
    // it.
    //
    // The branch is `active`, the one derived above, rather than a second read
    // of `mode`: two derivations of one fact a line apart is how they come to
    // disagree.
    submit: (username, password, email) => {
      setDismissed(false);
      if (active === register) {
        register.mutate({
          data: { username, password, ...(email ? { email } : {}) },
        });
        return;
      }
      login.mutate({ data: { username, password } });
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

export interface UseRecoveryResult {
  ask: (username: string) => void;
  isAsking: boolean;
  /** The request went in. Says nothing about whether the account exists. */
  hasAsked: boolean;
  askError: unknown;

  redeem: (username: string, code: string, newPassword: string) => void;
  isRedeeming: boolean;
  hasRedeemed: boolean;
  redeemError: unknown;
}

/**
 * Asking an admin to approve a reset, and spending the code they read out.
 *
 * Two mutations rather than a wizard with a step counter: they are separated by
 * a telephone call, so the member closes the page between them and comes back
 * with a code. Nothing is remembered across that, which is also why the redeem
 * form asks for the username again.
 *
 * **Neither answer says whether the account exists.** The request returns 202
 * either way and the redemption returns one message for every failure, so there
 * is nothing here for a screen to be more specific with. That is the server's
 * rule; this hook simply has nothing finer to report.
 */
export function useRecovery(): UseRecoveryResult {
  const ask = useRequestPasswordReset();
  const redeem = useRedeemPasswordReset();

  return {
    // `mutate`, not `mutateAsync`: nothing awaits either of these, and
    // mutateAsync rejects on failure, leaving an unhandled rejection behind
    // every wrong code.
    ask: (username) => ask.mutate({ data: { username } }),
    isAsking: ask.isPending,
    hasAsked: ask.isSuccess,
    askError: ask.error,

    redeem: (username, code, newPassword) =>
      redeem.mutate({ data: { username, code, new_password: newPassword } }),
    isRedeeming: redeem.isPending,
    hasRedeemed: redeem.isSuccess,
    redeemError: redeem.error,
  };
}

export interface UseAddressConfirmationResult {
  confirm: (username: string, code: string) => void;
  isConfirming: boolean;
  hasConfirmed: boolean;
  confirmError: unknown;

  resend: (username: string) => void;
  isResending: boolean;
  hasResent: boolean;
  resendError: unknown;
}

/**
 * Returning the code sent to an address, and asking for another one.
 *
 * The same shape as `useRecovery` and for the same reason: a code arrives by
 * mail, so the member leaves and comes back. The resend answers 202 whatever it
 * found, including for an account that is already confirmed.
 */
export function useAddressConfirmation(): UseAddressConfirmationResult {
  const confirm = useConfirmAddress();
  const resend = useRequestVerification();

  return {
    confirm: (username, code) => confirm.mutate({ data: { username, code } }),
    isConfirming: confirm.isPending,
    hasConfirmed: confirm.isSuccess,
    confirmError: confirm.error,

    resend: (username) => resend.mutate({ data: { username } }),
    isResending: resend.isPending,
    hasResent: resend.isSuccess,
    resendError: resend.error,
  };
}
