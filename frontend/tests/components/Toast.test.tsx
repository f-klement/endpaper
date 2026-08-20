/** Tests for src/components/Toast.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import Toast from "../../src/components/Toast";
import { renderLocalised } from "../utils";

afterEach(() => vi.useRealTimers());

describe("Toast", () => {
  it("shows the message", () => {
    renderLocalised(<Toast message="Moved to the trash." onDismiss={vi.fn()} />);
    expect(screen.getByText("Moved to the trash.")).toBeInTheDocument();
  });

  it("reports politely rather than interrupting", () => {
    // `alert` would cut a screen reader off mid-sentence, which is right for a
    // failure and rude for "that worked".
    renderLocalised(<Toast message="Done" onDismiss={vi.fn()} />);
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");
  });

  it("runs the action and then dismisses", async () => {
    const onClick = vi.fn();
    const onDismiss = vi.fn();
    renderLocalised(
      <Toast
        message="Moved"
        action={{ label: "Undo", onClick }}
        onDismiss={onDismiss}
      />,
    );

    await userEvent.setup().click(screen.getByRole("button", { name: "Undo" }));

    expect(onClick).toHaveBeenCalledOnce();
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("renders no action button when there is nothing to do", () => {
    renderLocalised(<Toast message="Done" onDismiss={vi.fn()} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("dismisses itself after the timeout", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    renderLocalised(
      <Toast message="Done" onDismiss={onDismiss} timeout={1000} />,
    );

    expect(onDismiss).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("cancels its timer when it goes away", () => {
    // Otherwise dismissing by hand leaves a callback pending against a
    // component that is no longer there.
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    const { unmount } = renderLocalised(
      <Toast message="Done" onDismiss={onDismiss} timeout={1000} />,
    );

    unmount();
    vi.advanceTimersByTime(2000);
    expect(onDismiss).not.toHaveBeenCalled();
  });
});
