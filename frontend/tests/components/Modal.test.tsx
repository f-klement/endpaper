/** Tests for src/components/Modal.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Modal from "../../src/components/Modal";
import { renderLocalised } from "../utils";

type OnClose = NonNullable<React.ComponentProps<typeof Modal>["onClose"]>;

describe("Modal", () => {
  it("is a labelled dialog", () => {
    renderLocalised(
      <Modal title="How this works" onClose={vi.fn<OnClose>()}>
        body
      </Modal>,
    );

    expect(
      screen.getByRole("dialog", { name: "How this works" }),
    ).toBeInTheDocument();
  });

  it("renders what it is given", () => {
    renderLocalised(
      <Modal title="T" onClose={vi.fn<OnClose>()}>
        <p>the explanation</p>
      </Modal>,
    );

    expect(screen.getByText("the explanation")).toBeInTheDocument();
  });

  it("closes on the close button", async () => {
    const onClose = vi.fn<OnClose>();
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
        <Modal title="T" onClose={vi.fn<OnClose>()}>
          body
        </Modal>,
      ),
    ).not.toThrow();
  });

  it("opens in the top layer on mount", () => {
    renderLocalised(
      <Modal title="T" onClose={vi.fn<OnClose>()}>
        body
      </Modal>,
    );

    expect(screen.getByRole("dialog")).toHaveAttribute("open");
  });

  it("closes on a click on its own backdrop", async () => {
    const onClose = vi.fn<OnClose>();
    renderLocalised(
      <Modal title="T" onClose={onClose}>
        body
      </Modal>,
    );

    await userEvent.setup().click(screen.getByRole("dialog"));

    expect(onClose).toHaveBeenCalledOnce();
  });

  it("stays open on a click inside its content", async () => {
    const onClose = vi.fn<OnClose>();
    renderLocalised(
      <Modal title="T" onClose={onClose}>
        <p>the explanation</p>
      </Modal>,
    );

    await userEvent.setup().click(screen.getByText("the explanation"));

    expect(onClose).not.toHaveBeenCalled();
  });

  it("tells its parent when the browser closes it, as Escape does", () => {
    const onClose = vi.fn<OnClose>();
    renderLocalised(
      <Modal title="T" onClose={onClose}>
        body
      </Modal>,
    );

    (screen.getByRole("dialog") as HTMLDialogElement).close();

    expect(onClose).toHaveBeenCalledOnce();
  });

  it("closes the dialog when it unmounts", () => {
    const { unmount } = renderLocalised(
      <Modal title="T" onClose={vi.fn<OnClose>()}>
        body
      </Modal>,
    );
    const dialog = screen.getByRole("dialog");

    unmount();

    expect(dialog).not.toHaveAttribute("open");
  });
});
