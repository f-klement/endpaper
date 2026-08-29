/**
 * Tests for src/pages/SettingsPage/SettingsPage.tsx.
 *
 * Settings is an index of routes since 2026-08-27. It held thirteen
 * collapsible sections across one file, and the fold was doing a route's job.
 *
 * So what is asserted here is the map and nothing else: every entry, in the
 * order the table gives, each one a link to its own route, each one carrying
 * the sentence that says what is behind it. **The sentences are the whole value
 * of this page**, so their absence is a failure rather than a cosmetic one:
 * headings alone would make a household open three screens to find one setting.
 *
 * What is not here any more, deliberately: every assertion about which card
 * arrives open. Nothing folds, and `lib/sectionState.ts` no longer has a
 * settings caller. The rule those tests pinned survives for the book page,
 * which folds against a condition and has no route to fold into.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Locale } from "../../../src/api/generated/model";
import { en } from "../../../src/i18n/en";
import SettingsPage from "../../../src/pages/SettingsPage";
import { SETTINGS_ROUTES } from "../../../src/pages/SettingsPage/types";
import { makeUser } from "../../factories";
import { mockApi, renderWithProviders } from "../../utils";

beforeEach(() => {
  localStorage.clear();
  mockApi();
});

/**
 * The index, for an account.
 *
 * The account is a prop and not the cached session, which is the whole of what
 * this page reads: some entries are admin only, and under proxy
 * auth `localStorage["user"]` is not the identity. Whether the prop is right in
 * each auth mode is `AppRoutes`' business and is tested in `tests/app/`.
 */
function render(isAdmin: boolean) {
  return renderWithProviders(
    <SettingsPage currentUser={makeUser({ is_admin: isAdmin })} />,
  );
}

/**
 * The headings an admin is offered, in the order the index draws them.
 *
 * Derived from the table rather than written out, and that is a change made
 * after a route added by one seat broke four hand written counts belonging to
 * another. **Which routes exist is asserted whole, once, in `types.test.ts`.**
 * Repeating the list here bought a second place to edit and no second check:
 * every assertion in this file is about what the index *draws*, which is "one
 * link per row of the table" whatever the table holds.
 */
const HEADINGS = SETTINGS_ROUTES.map((route) => en[route.title]);

/** What is left when the admin only routes are dropped. */
const MEMBER_ROUTES = SETTINGS_ROUTES.filter((route) => !route.adminOnly);

describe("SettingsPage", () => {
  it("is one link per route and nothing else for an admin", () => {
    render(true);

    expect(screen.getAllByRole("link")).toHaveLength(SETTINGS_ROUTES.length);
  });

  it("offers a member only the screens that hold something for them", () => {
    // The page this replaced refused in place, once, beside the cards it was
    // refusing. Links with no mark would turn that into a dead end per admin
    // only route, each a tap apart and each advertised with a sentence
    // promising content.
    render(false);

    expect(
      screen.getAllByRole("link").map((link) => link.getAttribute("href")),
    ).toEqual(MEMBER_ROUTES.map((route) => route.path));
    for (const route of MEMBER_ROUTES) {
      expect(
        screen.getByRole("link", { name: new RegExp(en[route.title]) }),
      ).toBeInTheDocument();
    }
  });

  it("does not read the cached account", () => {
    // It did, for one round, and that was the defect. Under proxy auth
    // `localStorage["user"]` is written only by a switch into a test account,
    // and a test account is never an admin, so the key is null for a proxy
    // admin always: reading it dropped every admin only entry off their own
    // index. The
    // account is a prop now, and storage disagreeing with it changes nothing.
    localStorage.setItem("user", JSON.stringify(makeUser({ is_admin: false })));
    render(true);

    expect(screen.getAllByRole("link")).toHaveLength(SETTINGS_ROUTES.length);
  });

  it("filters its own copy and leaves the table alone", () => {
    // The flag decides what is offered, never what is allowed, so every marked
    // route is still in the table the router is written against. That they are
    // still *mounted* is a different claim and is asserted where the router's
    // source is actually read: `types.test.ts::has a route mounted at every
    // path it lists`. Which routes carry the flag is asserted whole there too.
    render(false);

    // `MEMBER_ROUTES` is defined as the complement of this filter, so
    // comparing their lengths would compare a number with itself. What is
    // worth asserting is that the filter has a subject at all, and then that
    // every route it names is absent from what a member is shown.
    const adminOnly = SETTINGS_ROUTES.filter((route) => route.adminOnly);
    expect(adminOnly.length).toBeGreaterThan(0);
    for (const route of adminOnly) {
      expect(
        screen.queryByRole("link", { name: new RegExp(en[route.title]) }),
      ).not.toBeInTheDocument();
    }
  });

  it("draws them in the order the table gives", () => {
    // The table is what `app/routes.tsx` is written against, so the order
    // being the table's rather than the JSX's is what keeps one edit enough.
    render(true);

    const headings = screen
      .getAllByRole("link")
      .map((link) => link.textContent ?? "");

    expect(
      headings.map((text, index) => text.startsWith(HEADINGS[index]!)),
    ).toEqual(HEADINGS.map(() => true));
  });

  it("points each entry at its own route", () => {
    render(true);

    expect(
      screen.getAllByRole("link").map((link) => link.getAttribute("href")),
    ).toEqual(SETTINGS_ROUTES.map((route) => route.path));
  });

  it("says what is behind every link, not just its name", () => {
    // A heading alone makes a household open three screens to find one
    // setting, which is worse than the long page this replaced. Asserted as a
    // property of every route rather than by quoting one sentence, so adding a
    // route added with no description fails here.
    render(true);

    for (const link of screen.getAllByRole("link")) {
      const [heading, ...rest] = [...link.querySelectorAll("span > span")].map(
        (node) => node.textContent ?? "",
      );
      expect(heading).not.toBe("");
      expect(rest.join("")).not.toBe("");
    }
  });

  it("reaches every entry from the keyboard", async () => {
    // Links, not click handlers on a div: a card that a thumb can hit has to
    // be a control a Tab can reach, and this page is now the only way into
    // five screens.
    render(true);
    const user = userEvent.setup();

    for (const link of screen.getAllByRole("link")) {
      await user.tab();
      expect(link).toHaveFocus();
    }
  });

  it("translates the headings and the sentences", () => {
    renderWithProviders(
      <SettingsPage currentUser={makeUser({ is_admin: true })} />,
      { locale: Locale.de },
    );

    expect(
      screen.getByRole("link", { name: /Katalogquellen/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Woher die Angaben zu einem Buch stammen/),
    ).toBeInTheDocument();
  });

  it("asks the server for nothing", () => {
    // It used to fetch the admin settings record on every visit by every
    // member, which was a 403 for most of them. The index is a static map.
    const api = mockApi();
    render(true);

    expect(api.calls).toHaveLength(0);
  });

  it("folds nothing", () => {
    // The collapse state was a second way to hide a section beside the
    // navigation, and keeping both is how an app ends up with two answers to
    // "where did that go".
    render(true);

    expect(screen.queryAllByRole("button", { expanded: false })).toHaveLength(
      0,
    );
    expect(localStorage.getItem("settingsSections")).toBeNull();
  });
});
