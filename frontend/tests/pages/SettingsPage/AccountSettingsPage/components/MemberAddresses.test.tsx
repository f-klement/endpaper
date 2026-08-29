/**
 * Tests for AccountSettingsPage/components/MemberAddresses.tsx.
 *
 * The page test covers the list an admin sees and the write it makes. What is
 * here is the four states around it, and one of them is the rule this component
 * exists for: **a member is shown nothing, not a refusal.** Every other settings
 * screen says "only an admin can change these" beside what it is refusing,
 * which is right for a library setting and wrong for other people's addresses.
 */

import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import MemberAddresses from "../../../../../src/pages/SettingsPage/AccountSettingsPage/components/MemberAddresses";
import type { UseMemberEmailsResult } from "../../../../../src/pages/SettingsPage/AccountSettingsPage/hooks";
import { renderLocalised } from "../../../../utils";

function state(
  overrides: Partial<UseMemberEmailsResult> = {},
): UseMemberEmailsResult {
  return {
    members: [{ id: 1, username: "kim", email: null, editable: true }],
    isOffered: true,
    isLoading: false,
    isForbidden: false,
    error: null,
    save: vi.fn(),
    isSaving: false,
    saveError: null,
    isDirectoryOwned: false,
    hasSaved: false,
    ...overrides,
  };
}

describe("MemberAddresses", () => {
  it("draws nothing at all for a member, not even a refusal", () => {
    // The ordinary case: the request was never made, because the session says
    // this caller is not an admin.
    const { container } = renderLocalised(
      <MemberAddresses
        state={state({ isOffered: false, members: undefined })}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing for a 403 either, which is what a stale session looks like", () => {
    // The belt to the prop's braces. A prop is not a control, so the server's
    // own answer has to land somewhere, and it lands here saying nothing.
    const { container } = renderLocalised(
      <MemberAddresses
        state={state({ isForbidden: true, members: undefined })}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("waits rather than drawing an empty list", () => {
    renderLocalised(
      <MemberAddresses
        state={state({ isLoading: true, members: undefined })}
      />,
    );

    expect(screen.queryByText("Member addresses")).not.toBeInTheDocument();
  });

  it("reports a load that failed for a reason other than permission", () => {
    // `ErrorState` prefers the server's own message and falls back only when
    // there is none, so the assertion is the alert rather than the fallback
    // string: asserting the fallback would pass only for an error nobody can
    // explain, which is the case this is least about.
    renderLocalised(
      <MemberAddresses
        state={state({ error: new Error("boom"), members: undefined })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("boom");
    expect(screen.queryByText("Member addresses")).not.toBeInTheDocument();
  });

  it("says a save landed", () => {
    renderLocalised(<MemberAddresses state={state({ hasSaved: true })} />);

    expect(screen.getByRole("status")).toHaveTextContent("Settings saved.");
  });

  it("explains a directory refusal instead of reporting an error", () => {
    renderLocalised(
      <MemberAddresses
        state={state({
          isDirectoryOwned: true,
          saveError: new Error("409"),
        })}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      /the directory's to set/,
    );
    expect(screen.queryByText(/could not be saved/)).not.toBeInTheDocument();
  });
});
