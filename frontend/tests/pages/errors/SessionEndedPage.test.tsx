/** Tests for src/pages/errors/SessionEndedPage.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Locale } from "../../../src/api/generated/model";
import SessionEndedPage from "../../../src/pages/errors/SessionEndedPage";
import { renderLocalised } from "../../utils";

beforeEach(() => {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { href: "http://localhost/", pathname: "/", reload: vi.fn() },
  });
});

describe("SessionEndedPage", () => {
  it("says what happened rather than spinning", () => {
    renderLocalised(<SessionEndedPage />);
    expect(screen.getByText("Your session ended")).toBeInTheDocument();
  });

  it("offers the one action that can reach the portal", async () => {
    // A top-level navigation. Nothing else is followed across origins, so a
    // link to this app's own /login would be redirected the same way every
    // request already was.
    renderLocalised(<SessionEndedPage />);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Sign in again" }));

    expect(window.location.reload).toHaveBeenCalledTimes(1);
  });

  it("puts focus on that action", () => {
    // The one screen in this app that arrives without being asked for. It
    // replaces the tree from inside a response handler, so focus was on an
    // element that has just unmounted and would otherwise fall to <body>.
    renderLocalised(<SessionEndedPage />);
    expect(screen.getByRole("button", { name: "Sign in again" })).toHaveFocus();
  });

  it("is translated", () => {
    // The screen a reader is most likely to meet in a bad moment, so it is
    // worth pinning that it is not English in the middle of a German page.
    renderLocalised(<SessionEndedPage />, { locale: Locale.de });
    expect(screen.getByText("Deine Sitzung ist beendet")).toBeInTheDocument();
  });
});
