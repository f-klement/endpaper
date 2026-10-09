/** Tests for src/components/ErrorState.tsx. */

import { screen } from "@testing-library/react";
import { renderLocalised } from "../utils";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError, NetworkError } from "../../src/api/mutator";
import ErrorState, { errorText } from "../../src/components/ErrorState";
import { en } from "../../src/i18n/en";

/** The real English catalogue, so a renamed key fails here rather than lying. */
const t = ((key: keyof typeof en) => en[key]) as Parameters<
  typeof errorText
>[2];

describe("errorText", () => {
  it("uses an Error's message", () => {
    expect(errorText(new Error("Book not found"), "fallback", t)).toBe(
      "Book not found",
    );
  });

  it("uses an ApiError's message", () => {
    expect(errorText(new ApiError("Already exists", 409), "fallback", t)).toBe(
      "Already exists",
    );
  });

  it("accepts a bare string", () => {
    expect(errorText("something", "fallback", t)).toBe("something");
  });

  it("falls back for a thrown value with no message", () => {
    // Anything can be thrown in JavaScript, so this must not crash the page
    // that is trying to report the failure.
    expect(errorText({ weird: true }, "fallback", t)).toBe("fallback");
    expect(errorText(null, "fallback", t)).toBe("fallback");
    expect(errorText(new Error(""), "fallback", t)).toBe("fallback");
  });
});

describe("errorText on a network failure", () => {
  it("says the server could not be reached", () => {
    // The browser's own words for this are "Failed to fetch": untranslated,
    // not a sentence, and no use to somebody on a phone. Reported live from a
    // mobile client behind a VPN that was black-holing large responses.
    expect(
      errorText(
        new NetworkError(new TypeError("Failed to fetch")),
        "fallback",
        t,
      ),
    ).toBe(en["common.cannotReachServer"]);
  });

  it("never shows the browser's own message", () => {
    const text = errorText(
      new NetworkError(new TypeError("Failed to fetch")),
      "fallback",
      t,
    );
    expect(text).not.toContain("Failed to fetch");
  });

  it("leaves a server-written message alone", () => {
    // That one is already a sentence meant for the reader.
    expect(
      errorText(new ApiError("Book is already loaned out", 409), "fallback", t),
    ).toBe("Book is already loaned out");
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

  it("renders the friendly message for a rejected fetch", () => {
    renderLocalised(
      <ErrorState error={new NetworkError(new TypeError("Failed to fetch"))} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The server could not be reached",
    );
  });
});
