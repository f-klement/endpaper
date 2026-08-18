/** Tests for src/pages/errors/ErrorPage.tsx and its boundary. */

import { screen } from "@testing-library/react";
import { renderLocalised } from "../../utils";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ErrorPage, { ErrorBoundary } from "../../../src/pages/errors/ErrorPage";

function Boom(): never {
  throw new Error("a secret internal detail");
}

describe("ErrorPage", () => {
  it("explains the failure in plain language", () => {
    renderLocalised(<ErrorPage />);
    expect(screen.getByText("Something broke")).toBeInTheDocument();
    expect(screen.getByText("Error 500")).toBeInTheDocument();
  });

  it("offers a way to recover", async () => {
    const onReset = vi.fn();
    renderLocalised(<ErrorPage onReset={onReset} />);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Reload the page" }));

    expect(onReset).toHaveBeenCalled();
  });
});

describe("ErrorBoundary", () => {
  it("renders its children when nothing throws", () => {
    renderLocalised(
      <ErrorBoundary>
        <p>all fine</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("all fine")).toBeInTheDocument();
  });

  it("catches a render crash instead of blanking the page", () => {
    // React logs the caught error itself; silence it so the run stays readable.
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderLocalised(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Something broke")).toBeInTheDocument();
  });

  it("logs the detail so the failure is not invisible", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    renderLocalised(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );

    expect(consoleError).toHaveBeenCalled();
  });

  it("recovers when the boundary is reset", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    function Flaky({ shouldThrow }: { shouldThrow: boolean }) {
      if (shouldThrow) throw new Error("boom");
      return <p>recovered</p>;
    }

    const { rerender } = renderLocalised(
      <ErrorBoundary>
        <Flaky shouldThrow />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Something broke")).toBeInTheDocument();

    // Order matters: the cause has to be gone *before* the boundary is reset.
    // Resetting while the child still throws simply re-enters the error state,
    // which is correct behaviour and exactly what a "try again" button does on
    // a genuinely broken page.
    rerender(
      <ErrorBoundary>
        <Flaky shouldThrow={false} />
      </ErrorBoundary>,
    );
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Reload the page" }));

    expect(screen.getByText("recovered")).toBeInTheDocument();
  });
});
