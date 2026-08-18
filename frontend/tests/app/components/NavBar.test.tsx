/** Tests for src/app/components/NavBar.tsx: the sidebar and account menu. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigate };
});

import NavBar from "../../../src/app/components/NavBar";
import { makeUser, resetIds } from "../../factories";
import { mockApi, renderWithProviders, type MockApi } from "../../utils";

let api: MockApi;

beforeEach(() => {
  resetIds();
  navigate.mockReset();
  api = mockApi();
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

function renderNav(onSignOut = vi.fn()) {
  renderWithProviders(
    <NavBar user={makeUser({ username: "kim" })} onSignOut={onSignOut} />,
  );
  return onSignOut;
}

describe("NavBar", () => {
  it("links to each section", () => {
    renderNav();
    expect(screen.getByRole("link", { name: /Library/ })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByRole("link", { name: /Scan/ })).toHaveAttribute(
      "href",
      "/scan",
    );
    expect(screen.getByRole("link", { name: /Loans/ })).toHaveAttribute(
      "href",
      "/loans",
    );
    expect(screen.getByRole("link", { name: /Stats/ })).toHaveAttribute(
      "href",
      "/stats",
    );
  });

  it("shows the signed-in username", () => {
    renderNav();
    expect(screen.getByRole("button", { name: /kim/ })).toBeInTheDocument();
  });

  it("keeps the account menu closed until clicked", () => {
    renderNav();
    expect(
      screen.queryByRole("button", { name: "Logout" }),
    ).not.toBeInTheDocument();
  });

  it("opens the account menu", async () => {
    renderNav();
    await userEvent.setup().click(screen.getByRole("button", { name: /kim/ }));

    expect(screen.getByRole("button", { name: "Logout" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Switch Account" }),
    ).toBeInTheDocument();
  });

  it("signs out through its callback", async () => {
    const onSignOut = renderNav();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /kim/ }));
    await user.click(screen.getByRole("button", { name: "Logout" }));

    expect(onSignOut).toHaveBeenCalled();
  });

  it("navigates to the login page for Switch Account", async () => {
    // Deliberately keeps the current session until a new login succeeds.
    const onSignOut = renderNav();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /kim/ }));
    await user.click(screen.getByRole("button", { name: "Switch Account" }));

    expect(navigate).toHaveBeenCalledWith("/login");
    expect(onSignOut).not.toHaveBeenCalled();
  });

  it("closes the menu when a click lands outside it", async () => {
    renderNav();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /kim/ }));
    await user.click(document.body);

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Logout" }),
      ).not.toBeInTheDocument(),
    );
  });

  describe("export", () => {
    it("reveals the format picker", async () => {
      renderNav();
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /kim/ }));
      await user.click(screen.getByRole("button", { name: /Export Library/ }));

      expect(screen.getByRole("button", { name: "csv" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "txt" })).toBeInTheDocument();
    });

    it("exports in the chosen format", async () => {
      api.on("/api/books/export", {
        body: "txt",
        headers: { "content-type": "text/plain" },
      });
      renderNav();

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /kim/ }));
      await user.click(screen.getByRole("button", { name: /Export Library/ }));
      await user.click(screen.getByRole("button", { name: "txt" }));

      await waitFor(() =>
        expect(api.lastCall("/api/books/export")?.url).toContain("format=txt"),
      );
    });
  });
});
