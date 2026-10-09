/** Tests for src/components/Modal.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Modal from "../../src/components/Modal";
import { renderLocalised } from "../utils";

describe("Modal", () => {
  it("is a labelled dialog", () => {
    renderLocalised(
      <Modal title="How this works" onClose={vi.fn()}>
        body
      </Modal>,
    );

    expect(
      screen.getByRole("dialog", { name: "How this works" }),
    ).toBeInTheDocument();
  });

  it("renders what it is given", () => {
    renderLocalised(
      <Modal title="T" onClose={vi.fn()}>
        <p>the explanation</p>
      </Modal>,
    );

    expect(screen.getByText("the explanation")).toBeInTheDocument();
  });

  it("closes on the close button", async () => {
    const onClose = vi.fn();
    renderLocalised(
      <Modal title="T" onClose={onClose}>
        body
      </Modal>,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledOnce();
  });

  it("survives a jsdom without showModal", () => {
    // jsdom implements <dialog> but not showModal, which is why the call is
    // optional rather than assumed. Without that this throws on mount.
    expect(() =>
      renderLocalised(
        <Modal title="T" onClose={vi.fn()}>
          body
        </Modal>,
      ),
    ).not.toThrow();
  });
});
