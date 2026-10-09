/** Tests for src/pages/SettingsPage/LibrarySettingsPage/components/StoreIdentifiersSection.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import StoreIdentifiersSection from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/StoreIdentifiersSection";
import { renderLocalised } from "../../../../utils";

const RUN = {
  examined: 50,
  enriched: 47,
  not_found: 1,
  unavailable: 1,
  unresolvable: 1,
  remaining: 850,
};

const CLEAN = {
  ...RUN,
  not_found: 0,
  unavailable: 0,
  unresolvable: 0,
  remaining: 0,
};

describe("StoreIdentifiersSection", () => {
  it("offers to look the books up", () => {
    renderLocalised(
      <StoreIdentifiersSection
        result={null}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(
      screen.getByRole("button", { name: /Look up books by their store id/ }),
    ).toBeInTheDocument();
  });

  it("runs on a click", async () => {
    const onRun = vi.fn();
    renderLocalised(
      <StoreIdentifiersSection
        result={null}
        isRunning={false}
        error={null}
        onRun={onRun}
      />,
    );

    await userEvent
      .setup()
      .click(
        screen.getByRole("button", { name: /Look up books by their store id/ }),
      );

    expect(onRun).toHaveBeenCalledOnce();
  });

  it("says how many it filled in", () => {
    renderLocalised(
      <StoreIdentifiersSection
        result={RUN}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(
      screen.getByText(/Looked at 50 books and filled in 47/),
    ).toBeInTheDocument();
  });

  it("keeps a stale identifier, an outage and a value that is not an id apart", () => {
    /**
     * Three different things to do next: one says press again, one says
     * pressing will not help, and one says nothing was ever asked. Folding the
     * first two would send somebody to retype a book that was going to resolve
     * on its own; folding the last two tells them Google had no record of a
     * book nobody asked Google about.
     */
    renderLocalised(
      <StoreIdentifiersSection
        result={RUN}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(screen.getByText(/Google has no record for 1/)).toBeInTheDocument();
    expect(
      screen.getByText(/Google did not answer for 1 of them/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/1 of them carry something that is not a Google id/),
    ).toBeInTheDocument();
  });

  it("says nothing about either when neither happened", () => {
    renderLocalised(
      <StoreIdentifiersSection
        result={CLEAN}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(screen.queryByText(/Google has no record/)).not.toBeInTheDocument();
    expect(screen.queryByText(/did not answer/)).not.toBeInTheDocument();
    expect(screen.queryByText(/not a Google id/)).not.toBeInTheDocument();
  });

  it("tells the reader to press again while books are left", () => {
    renderLocalised(
      <StoreIdentifiersSection
        result={RUN}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(screen.getByText(/850 books still to go/)).toBeInTheDocument();
  });

  it("says so when the library is finished", () => {
    renderLocalised(
      <StoreIdentifiersSection
        result={CLEAN}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(
      screen.getByText(
        /Every book a Google id could fill in has been looked up/,
      ),
    ).toBeInTheDocument();
  });

  it("reports a failure rather than swallowing it", () => {
    renderLocalised(
      <StoreIdentifiersSection
        result={null}
        isRunning={false}
        error={new Error("nope")}
        onRun={() => {}}
      />,
    );

    // The role rather than the wording: `ErrorState` prefers the error's own
    // message where there is one and falls back to the sentence passed in, so
    // asserting the fallback text pins the wrong half.
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("reads in German too", () => {
    renderLocalised(
      <StoreIdentifiersSection
        result={RUN}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
      { locale: "de" },
    );

    expect(
      screen.getByRole("button", {
        name: /Bücher anhand der Store-Kennung nachschlagen/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/50 Bücher geprüft und 47 ergänzt/),
    ).toBeInTheDocument();
  });
});
