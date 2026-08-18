/** Tests for src/components/ErrorState.tsx. */

import { screen } from "@testing-library/react";
import { renderLocalised } from "../utils";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../src/api/mutator";
import ErrorState, { errorText } from "../../src/components/ErrorState";

describe("errorText", () => {
  it("uses an Error's message", () => {
    expect(errorText(new Error("Book not found"), "fallback")).toBe(
      "Book not found",
    );
  });

  it("uses an ApiError's message", () => {
    expect(errorText(new ApiError("Already exists", 409), "fallback")).toBe(
      "Already exists",
    );
  });

  it("accepts a bare string", () => {
    expect(errorText("something", "fallback")).toBe("something");
  });

  it("falls back for a thrown value with no message", () => {
    // Anything can be thrown in JavaScript, so this must not crash the page
    // that is trying to report the failure.
    expect(errorText({ weird: true }, "fallback")).toBe("fallback");
    expect(errorText(null, "fallback")).toBe("fallback");
    expect(errorText(new Error(""), "fallback")).toBe("fallback");
  });
});

describe("ErrorState", () => {
  it("is announced as an alert", () => {
    renderLocalised(<ErrorState error={new Error("boom")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });

  it("shows the fallback when the error carries no message", () => {
    renderLocalised(
      <ErrorState error={null} fallback="Could not load your library." />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not load your library.",
    );
  });

  it("offers no retry unless one is given", () => {
    renderLocalised(<ErrorState error={new Error("boom")} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("calls onRetry when offered and clicked", async () => {
    const onRetry = vi.fn();
    renderLocalised(<ErrorState error={new Error("boom")} onRetry={onRetry} />);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Try again" }));

    expect(onRetry).toHaveBeenCalledOnce();
  });
});
