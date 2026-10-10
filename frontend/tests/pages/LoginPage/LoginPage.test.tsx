/** Tests for src/pages/LoginPage. */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fc from "fast-check";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthMode } from "../../../src/api/generated/model";
import LoginPage from "../../../src/pages/LoginPage";
import { makeUser, resetIds } from "../../factories";
import { answersOf } from "../../lib/schemaArbitrary";
import { holds, PROFILE, PROPERTY, witness } from "../../property";
import { forget, overSchema } from "../../schemaPage";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

type OnSignIn = NonNullable<React.ComponentProps<typeof LoginPage>["onSignIn"]>;

let api: MockApi;

beforeEach(() => {
  resetIds();
  api = mockApi();
  // Both fire on mount; default them so each test stubs only what it cares about.
  api.on("/auth/config", { body: { registration_enabled: true } });
  api.on("/api/settings/login-image", {
    status: 404,
    body: { detail: "No login background" },
  });
});

async function fillAndSubmit(username: string, password: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), username);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(
    screen.getByRole("button", { name: /^(sign in|create account)$/i }),
  );
}

describe("LoginPage", () => {
  it("renders the sign-in form", async () => {
    renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
    expect(
      await screen.findByRole("button", { name: "Sign In" }),
    ).toBeInTheDocument();
  });

  describe("signing in", () => {
    it("hands the account and token to its caller", async () => {
      const account = makeUser({ username: "kim" });
      api.on("/auth/login", {
        body: {
          access_token: "token-123",
          token_type: "bearer",
          user: account,
        },
      });
      const onSignIn = vi.fn<OnSignIn>();
      renderWithProviders(<LoginPage onSignIn={onSignIn} />);

      await fillAndSubmit("kim", "password123");

      await waitFor(() =>
        expect(onSignIn).toHaveBeenCalledWith(account, "token-123"),
      );
    });

    it("posts the credentials", async () => {
      api.on("/auth/login", {
        body: { access_token: "t", token_type: "bearer", user: makeUser() },
      });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      await fillAndSubmit("kim", "password123");

      await waitFor(() =>
        expect(api.lastCall("/auth/login", "POST")?.body).toEqual({
          username: "kim",
          password: "password123",
        }),
      );
    });

    it("shows the server's rejection message", async () => {
      api.on("/auth/login", {
        status: 401,
        body: { detail: "Incorrect username or password" },
      });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      await fillAndSubmit("kim", "wrong");

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Incorrect username or password",
      );
    });

    it("does not sign in when the credentials are rejected", async () => {
      api.on("/auth/login", {
        status: 401,
        body: { detail: "Incorrect username or password" },
      });
      const onSignIn = vi.fn<OnSignIn>();
      renderWithProviders(<LoginPage onSignIn={onSignIn} />);

      await fillAndSubmit("kim", "wrong");

      await screen.findByRole("alert");
      expect(onSignIn).not.toHaveBeenCalled();
    });

    it("re-enables the button after a failure so you can retry", async () => {
      api.on("/auth/login", { status: 401, body: { detail: "nope" } });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      await fillAndSubmit("kim", "wrong");

      await screen.findByRole("alert");
      expect(screen.getByRole("button", { name: "Sign In" })).toBeEnabled();
    });

    it("surfaces a rate-limit refusal", async () => {
      api.on("/auth/login", {
        status: 429,
        body: { detail: "Too many attempts. Please wait and try again." },
      });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      await fillAndSubmit("kim", "wrong");

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Too many attempts",
      );
    });
  });

  describe("registration", () => {
    it("offers the register tab when signups are open", async () => {
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      expect(
        await screen.findByRole("button", { name: "Switch to registration" }),
      ).toBeInTheDocument();
    });

    it("hides the tabs when signups are closed", async () => {
      api.on("/auth/config", { body: { registration_enabled: false } });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      await waitFor(() =>
        expect(
          screen.queryByRole("button", { name: "Switch to registration" }),
        ).not.toBeInTheDocument(),
      );
    });

    it("registers through the register endpoint, not login", async () => {
      api.on("/auth/register", {
        // `RegistrationOut`, not a token: where the deployment confirms new
        // accounts there is no session to hand back, so the token is nested and
        // may be absent.
        body: {
          verification_required: false,
          token: { access_token: "t", token_type: "bearer", user: makeUser() },
        },
      });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      const user = userEvent.setup();
      await user.click(
        await screen.findByRole("button", { name: "Switch to registration" }),
      );
      await fillAndSubmit("newcomer", "password123");

      await waitFor(() =>
        expect(api.lastCall("/auth/register", "POST")).toBeDefined(),
      );
      expect(api.lastCall("/auth/login", "POST")).toBeUndefined();
    });

    it("explains that the first account becomes admin", async () => {
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      const user = userEvent.setup();
      await user.click(
        await screen.findByRole("button", { name: "Switch to registration" }),
      );

      expect(
        screen.getByText(/first account created becomes the admin/i),
      ).toBeInTheDocument();
    });

    // #103. The address is part of making the account, and it is optional at
    // both ends: the field may be left empty and the payload then carries none.
    it("offers no address field on the sign-in form", async () => {
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      await screen.findByLabelText("Username");

      expect(screen.queryByLabelText(/email address/i)).not.toBeInTheDocument();
    });

    it("sends an address given at registration", async () => {
      api.on("/auth/register", {
        // `RegistrationOut`, not a token: where the deployment confirms new
        // accounts there is no session to hand back, so the token is nested and
        // may be absent.
        body: {
          verification_required: false,
          token: { access_token: "t", token_type: "bearer", user: makeUser() },
        },
      });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      const user = userEvent.setup();
      await user.click(
        await screen.findByRole("button", { name: "Switch to registration" }),
      );
      await user.type(
        screen.getByLabelText(/email address/i),
        "new@example.org",
      );
      await fillAndSubmit("newcomer", "password123");

      await waitFor(() =>
        expect(api.lastCall("/auth/register", "POST")?.body).toEqual({
          username: "newcomer",
          password: "password123",
          email: "new@example.org",
        }),
      );
    });

    it("sends no address field when the box is left empty", async () => {
      api.on("/auth/register", {
        // `RegistrationOut`, not a token: where the deployment confirms new
        // accounts there is no session to hand back, so the token is nested and
        // may be absent.
        body: {
          verification_required: false,
          token: { access_token: "t", token_type: "bearer", user: makeUser() },
        },
      });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      const user = userEvent.setup();
      await user.click(
        await screen.findByRole("button", { name: "Switch to registration" }),
      );
      await fillAndSubmit("newcomer", "password123");

      await waitFor(() =>
        expect(api.lastCall("/auth/register", "POST")?.body).toEqual({
          username: "newcomer",
          password: "password123",
        }),
      );
    });

    it("clears a previous error when switching tabs", async () => {
      api.on("/auth/login", {
        status: 401,
        body: { detail: "Incorrect username or password" },
      });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      await fillAndSubmit("kim", "wrong");
      await screen.findByRole("alert");

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Switch to registration" }));

      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
  });

  describe("under directory auth", () => {
    // The directory owns the accounts, so this app's form is a place to type
    // credentials it forwards, and nothing else.
    beforeEach(() => {
      api.on("/auth/config", {
        body: { auth_mode: AuthMode.ldap, registration_enabled: false },
      });
    });

    it("still offers a login form", async () => {
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      expect(
        await screen.findByRole("button", { name: "Sign In" }),
      ).toBeInTheDocument();
    });

    it("offers no registration tab", async () => {
      // waitFor, not a findBy: the tabs render optimistically before the
      // config request lands, so asserting straight away would pass on the
      // pre-config frame whatever the server said.
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      await waitFor(() =>
        expect(
          screen.queryByRole("button", { name: "Switch to registration" }),
        ).not.toBeInTheDocument(),
      );
    });

    it("says where the accounts come from", async () => {
      // Otherwise a directory member with no local password is looking at a
      // form with nothing saying which credentials it wants.
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      expect(await screen.findByText(/directory/i)).toBeInTheDocument();
    });

    it("posts to the same login endpoint", async () => {
      // The bind happens server side; the client cannot tell the difference.
      api.on("/auth/login", {
        body: { access_token: "t", token_type: "bearer", user: makeUser() },
      });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      await fillAndSubmit("kim", "password123");

      await waitFor(() =>
        expect(api.lastCall("/auth/login", "POST")).toBeDefined(),
      );
    });
  });

  describe("in local mode", () => {
    it("does not mention a directory", async () => {
      api.on("/auth/config", {
        body: { auth_mode: AuthMode.local, registration_enabled: true },
      });
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      await screen.findByRole("button", { name: "Sign In" });
      expect(screen.queryByText(/directory/i)).not.toBeInTheDocument();
    });
  });

  describe("login background", () => {
    it("applies the configured image", async () => {
      api.on("/api/settings/login-image", {
        body: { url: "/covers/login_bg.png" },
      });
      const { container } = renderWithProviders(
        <LoginPage onSignIn={vi.fn<OnSignIn>()} />,
      );

      await waitFor(() =>
        expect(container.firstElementChild?.getAttribute("style")).toContain(
          "login_bg.png",
        ),
      );
    });

    it("renders fine when none is set", async () => {
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      expect(
        await screen.findByRole("button", { name: "Sign In" }),
      ).toBeInTheDocument();
    });

    it("offers the upload control to an admin", async () => {
      localStorage.setItem(
        "user",
        JSON.stringify(makeUser({ is_admin: true })),
      );
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      expect(
        await screen.findByText("Set background image"),
      ).toBeInTheDocument();
    });

    it("hides the upload control from a non-admin", async () => {
      localStorage.setItem(
        "user",
        JSON.stringify(makeUser({ is_admin: false })),
      );
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);

      await screen.findByRole("button", { name: "Sign In" });
      expect(
        screen.queryByText("Set background image"),
      ).not.toBeInTheDocument();
    });

    it("hides the upload control when nobody is signed in", async () => {
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      await screen.findByRole("button", { name: "Sign In" });
      expect(
        screen.queryByText("Set background image"),
      ).not.toBeInTheDocument();
    });

    it("survives a corrupt cached account", async () => {
      // A half-written localStorage value must not blank the login page.
      localStorage.setItem("user", "{not json");
      renderWithProviders(<LoginPage onSignIn={vi.fn<OnSignIn>()} />);
      expect(
        await screen.findByRole("button", { name: "Sign In" }),
      ).toBeInTheDocument();
    });

    it("uploads a new background and cache-busts it", async () => {
      localStorage.setItem(
        "user",
        JSON.stringify(makeUser({ is_admin: true })),
      );
      api.on(
        "/api/settings/login-image",
        { body: { url: "/covers/login_bg.png" } },
        "POST",
      );
      const { container } = renderWithProviders(
        <LoginPage onSignIn={vi.fn<OnSignIn>()} />,
      );

      const label = await screen.findByText(
        /background image|Change background/,
      );
      const input = label.querySelector("input[type=file]") as HTMLInputElement;
      await userEvent
        .setup()
        .upload(input, new File(["png"], "bg.png", { type: "image/png" }));

      // The filename is stable, so without a changing query the browser would
      // keep showing the previous image.
      await waitFor(() =>
        expect(container.firstElementChild?.getAttribute("style")).toMatch(
          /login_bg\.png\?t=\d+/,
        ),
      );
    });
  });
});

/** Type `value` into the field labelled `label`, where the page shows one. */
const typeInto =
  (label: string | RegExp, value: string) => (page: HTMLElement) => {
    const field = within(page).queryByLabelText(label);
    if (field !== null) fireEvent.change(field, { target: { value } });
  };

/** Press the form's submit button, where the page shows one. */
const submit = (page: HTMLElement) => {
  const button = within(page).queryByRole("button", {
    name: /^(sign in|create account)$/i,
  });
  if (button !== null) fireEvent.click(button);
};

/** Switch the form to registration, where the page offers it. */
const toRegister = (page: HTMLElement) => {
  const tab = within(page).queryByRole("button", {
    name: "Switch to registration",
  });
  if (tab !== null) fireEvent.click(tab);
};

/** The token a registration answered, or `undefined` where there is none. */
const tokenOf = (body: unknown) =>
  (body as { token?: unknown } | undefined)?.token;

describe("LoginPage over any answer the schema permits", () => {
  // What the page's hooks are handed is drawn from `openapi.json`, per
  // request. `tests/schemaPage.tsx` holds what the page may not do, and, since
  // the page renders to a visitor with no account, that it asks for nothing
  // the document requires an account for. Its main request is asked for on a
  // reader's act, so each example signs in, or, where it draws the choice and
  // the drawn configuration offers the tab, registers; that answer is drawn too.
  it("is drawn an error body and a session", async () => {
    await witness(answersOf("login"), {
      "is an error body": (answer) => answer.status === 422,
      "is a session": (answer) => answer.status === 200,
    });
  });

  it("is drawn an error body, a session and an account to confirm", async () => {
    await witness(answersOf("register"), {
      "is an error body": (answer) => answer.status === 422,
      "is a session": (answer) =>
        answer.status === 201 && tokenOf(answer.body) != null,
      "is an account to confirm": (answer) =>
        answer.status === 201 && tokenOf(answer.body) == null,
    });
  });

  it("neither throws nor shows a value nobody can name", PROPERTY, async () => {
    expect(
      await holds(
        fc.tuple(fc.boolean(), fc.gen()),
        async ([registers, answers]) => {
          try {
            const rendered = await overSchema(
              <LoginPage onSignIn={() => {}} />,
              answers,
              {
                uses: [
                  ...(registers ? [toRegister] : []),
                  typeInto("Username", "kim"),
                  typeInto("Password", "password123"),
                  typeInto(/^Email address/, "kim@example.org"),
                  submit,
                ],
                anonymous: true,
              },
            );
            expect(rendered.problems).toEqual([]);
            return rendered;
          } finally {
            forget();
          }
        },
        {
          "signed in": (_, rendered) => rendered.asked.includes("login"),
          registered: (_, rendered) => rendered.asked.includes("register"),
          "drew an alert": (_, rendered) => rendered.alerts.length > 0,
        },
      ),
    ).toBe(PROFILE.runs);
  });
});
