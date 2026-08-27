/** Tests for src/pages/SettingsPage/components/CoversSection.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import CoversSection from "../../../../src/pages/SettingsPage/components/CoversSection";
import { renderLocalised } from "../../../utils";

const NOTHING_LEFT = {
  examined: 12,
  stored: 9,
  unreachable: 0,
  still_missing: 3,
  remaining: 0,
};

describe("CoversSection", () => {
  it("offers to fetch the covers that are missing", () => {
    renderLocalised(
      <CoversSection
        isOpen
        onToggle={() => {}}
        result={null}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(
      screen.getByRole("button", { name: /Fetch missing covers/ }),
    ).toBeInTheDocument();
  });

  it("runs on a click", async () => {
    const onRun = vi.fn();
    renderLocalised(
      <CoversSection
        isOpen
        onToggle={() => {}}
        result={null}
        isRunning={false}
        error={null}
        onRun={onRun}
      />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Fetch missing covers/ }));

    expect(onRun).toHaveBeenCalledOnce();
  });

  it("says how many it stored and how many have no cover anywhere", () => {
    renderLocalised(
      <CoversSection
        isOpen
        onToggle={() => {}}
        result={NOTHING_LEFT}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("12");
    expect(status).toHaveTextContent("9");
    expect(status).toHaveTextContent("3");
  });

  it("asks for another run while books are still outstanding", () => {
    // The run is bounded server side, so this is the only thing that tells the
    // reader the job is unfinished.
    renderLocalised(
      <CoversSection
        isOpen
        onToggle={() => {}}
        result={{ ...NOTHING_LEFT, remaining: 480 }}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("480");
  });

  it("says the job is done when nothing is left", () => {
    renderLocalised(
      <CoversSection
        isOpen
        onToggle={() => {}}
        result={NOTHING_LEFT}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      /Every book that could have a cover has one/,
    );
  });

  it("names the covers it could not download separately", () => {
    // A pod with no egress puts every book here, and folding it into either of
    // the other counts reports a clean no-op in exactly that situation.
    renderLocalised(
      <CoversSection
        isOpen
        onToggle={() => {}}
        result={{
          ...NOTHING_LEFT,
          stored: 0,
          unreachable: 12,
          still_missing: 0,
        }}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      /12 of them have a cover somewhere that could not be downloaded/,
    );
  });

  it("says nothing about unreachable covers when there were none", () => {
    renderLocalised(
      <CoversSection
        isOpen
        onToggle={() => {}}
        result={NOTHING_LEFT}
        isRunning={false}
        error={null}
        onRun={() => {}}
      />,
    );

    expect(screen.getByRole("status")).not.toHaveTextContent(
      /could not be downloaded/,
    );
  });

  it("reports a failure rather than looking like it worked", () => {
    renderLocalised(
      <CoversSection
        isOpen
        onToggle={() => {}}
        result={null}
        isRunning={false}
        error={new Error("nope")}
        onRun={() => {}}
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
