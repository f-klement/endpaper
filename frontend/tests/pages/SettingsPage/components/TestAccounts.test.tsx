/**
 * Tests for src/pages/SettingsPage/components/TestAccounts.tsx.
 *
 * Presentational, so what is pinned here is what it asks for and what it says.
 * Every refusal that matters is the server's: this list holds only test
 * accounts because that is what the endpoint returns, and a switch to anything
 * else fails there whatever is typed in.
 */

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuthMode } from "../../../../src/api/generated/model";
import TestAccounts from "../../../../src/pages/SettingsPage/components/TestAccounts";
import { makeUser } from "../../../factories";
import { renderLocalised } from "../../../utils";

function renderSection(
  overrides: Partial<React.ComponentProps<typeof TestAccounts>> = {},
) {
  const props = {
    accounts: [makeUser({ username: "tester" })],
    isLoading: false,
    error: null,
    onCreate: vi.fn(),
    isCreating: false,
    createError: null,
    onSwitch: vi.fn(),
    isSwitching: false,
    switchError: null,
    mode: AuthMode.local,
    ...overrides,
  };
  renderLocalised(<TestAccounts {...props} />);
  return props;
}

describe("TestAccounts", () => {
  it("lists the accounts an admin may switch into", () => {
    renderSection({
      accounts: [
        makeUser({ username: "tester" }),
        makeUser({ username: "reader" }),
      ],
    });

    expect(screen.getByText("tester")).toBeInTheDocument();
    expect(screen.getByText("reader")).toBeInTheDocument();
  });

  it("says so when there are none", () => {
    renderSection({ accounts: [] });
    expect(screen.getByText("No test accounts yet.")).toBeInTheDocument();
  });

  it("asks for the password before switching", async () => {
    // The password is what makes this a login on another account's behalf
    // rather than impersonation. An admin who cannot produce it is an admin
    // who did not set it.
    const props = renderSection();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Switch to tester" }));

    expect(screen.getByLabelText("Password for tester")).toBeInTheDocument();
    expect(props.onSwitch).not.toHaveBeenCalled();
  });

  it("switches with the name and the password typed", async () => {
    const user = userEvent.setup();
    const props = renderSection();
    await user.click(screen.getByRole("button", { name: "Switch to tester" }));

    fireEvent.change(screen.getByLabelText("Password for tester"), {
      target: { value: "pw12345678" },
    });
    // The row's own control is labelled "Switch to tester", so this names the
    // submit button and nothing else.
    await user.click(screen.getByRole("button", { name: "Switch" }));

    expect(props.onSwitch).toHaveBeenCalledWith("tester", "pw12345678");
  });

  it("never keeps the password from one account to the next", async () => {
    const user = userEvent.setup();
    renderSection({
      accounts: [
        makeUser({ username: "tester" }),
        makeUser({ username: "reader" }),
      ],
    });

    await user.click(screen.getByRole("button", { name: "Switch to tester" }));
    fireEvent.change(screen.getByLabelText("Password for tester"), {
      target: { value: "pw12345678" },
    });
    await user.click(screen.getByRole("button", { name: "Switch to reader" }));

    expect(screen.getByLabelText("Password for reader")).toHaveValue("");
  });

  it("creates an account from the name and password given", async () => {
    const user = userEvent.setup();
    const props = renderSection();

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "newcomer" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "pw12345678" },
    });
    await user.click(
      screen.getByRole("button", { name: "Create test account" }),
    );

    expect(props.onCreate).toHaveBeenCalledWith("newcomer", "pw12345678");
  });

  it("says how to come back, per mode", () => {
    renderSection({ mode: AuthMode.proxy });
    expect(
      screen.getByText(/Return to my account in the menu/),
    ).toBeInTheDocument();
  });

  it("says the other thing when the token is the session", () => {
    // Under local and ldap the admin's own token has been replaced by the new
    // one, so getting back means signing in again. Said before the switch
    // rather than discovered after it.
    renderSection({ mode: AuthMode.ldap });
    expect(screen.getByText(/sign in again/)).toBeInTheDocument();
  });

  it("reports a refused switch", () => {
    renderSection({ switchError: new Error("nope") });
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("reports a refused creation", () => {
    renderSection({ createError: new Error("nope") });
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
