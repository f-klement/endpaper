/** Tests for src/app/routes.tsx: the signed-in route table. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { AuthMode } from "../../src/api/generated/model";
import AppRoutes from "../../src/app/routes";
import { rememberCarried } from "../../src/lib/carryOver";
import { makeUser, resetIds } from "../factories";
import { mockApi, renderWithProviders, type MockApi } from "../utils";

let api: MockApi;

/** No sign-in happens here. */
const noop = () => {};

beforeEach(() => {
  resetIds();
  api = mockApi();
  api.on("/api/books/tags", { body: [] });
  api.on("/api/collections", { body: [] });
});

describe("AppRoutes", () => {
  it("starts the scan form from the new member's carry when the account changes on the page", async () => {
    // Under proxy, returning to one's own account refetches who is signed in
    // without passing through signed out, so the page stays mounted unless
    // the route remounts it.
    const before = makeUser();
    const after = makeUser();
    rememberCarried(before.id, { isPrivate: true });
    api.on("/api/books/lookup", {
      body: {
        isbn: "9780441013593",
        title: "Dune",
        subtitle: null,
        author: "Frank Herbert",
        publisher: "Chilton",
        year: 1965,
        description: null,
        cover_url: null,
        classifications: [],
        suggested_tag_ids: [],
      },
    });
    const { rerender } = renderWithProviders(
      <AppRoutes user={before} mode={AuthMode.proxy} onSignIn={noop} />,
      { route: "/scan" },
    );
    rerender(<AppRoutes user={after} mode={AuthMode.proxy} onSignIn={noop} />);

    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox", { name: "ISBN" }),
      "9780441013593",
    );
    await user.click(screen.getByRole("button", { name: "Look up" }));

    await screen.findByRole("button", { name: "Add to Library" });
    expect(
      screen.queryByText("the last one you added was", { exact: false }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });
});
