/**
 * Tests for src/pages/LoginPage/hooks.ts: what the recovery and address
 * confirmation hooks send.
 *
 * The panels that use them are tested with these hooks' results passed in as
 * props, so the request each verb makes is pinned here: the route, and the
 * body under the names the server reads.
 */

import { act, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  useAddressConfirmation,
  useRecovery,
} from "../../../src/pages/LoginPage/hooks";
import { mockApi, renderHookWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  api = mockApi();
  api.on("/auth/", { status: 202, body: { detail: "accepted" } });
});

describe("useRecovery", () => {
  it("asks for a reset under the username it was given", async () => {
    const { result } = renderHookWithProviders(() => useRecovery());

    act(() => result.current.ask("ada"));

    await waitFor(() => expect(result.current.hasAsked).toBe(true));
    expect(api.lastCall("/auth/reset/request", "POST")?.body).toEqual({
      username: "ada",
    });
  });

  it("spends the code with the new password under the server's name for it", async () => {
    const { result } = renderHookWithProviders(() => useRecovery());

    act(() => result.current.redeem("ada", "123456", "a new passphrase"));

    await waitFor(() => expect(result.current.hasRedeemed).toBe(true));
    expect(api.lastCall("/auth/reset/redeem", "POST")?.body).toEqual({
      username: "ada",
      code: "123456",
      new_password: "a new passphrase",
    });
  });
});

describe("useAddressConfirmation", () => {
  it("returns the code sent to the address", async () => {
    const { result } = renderHookWithProviders(() => useAddressConfirmation());

    act(() => result.current.confirm("ada", "654321"));

    await waitFor(() => expect(result.current.hasConfirmed).toBe(true));
    expect(api.lastCall(/\/auth\/verify$/, "POST")?.body).toEqual({
      username: "ada",
      code: "654321",
    });
  });

  it("asks for another code under the username it was given", async () => {
    const { result } = renderHookWithProviders(() => useAddressConfirmation());

    act(() => result.current.resend("ada"));

    await waitFor(() => expect(result.current.hasResent).toBe(true));
    expect(api.lastCall("/auth/verify/request", "POST")?.body).toEqual({
      username: "ada",
    });
  });
});
