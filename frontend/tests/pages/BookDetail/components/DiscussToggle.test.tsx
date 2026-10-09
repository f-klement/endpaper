/** Tests for src/pages/BookDetail/components/DiscussToggle.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DiscussToggle from "../../../../src/pages/BookDetail/components/DiscussToggle";
import { makeBook, makeUser, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

describe("DiscussToggle", () => {
  it("asks in the reader's own words", () => {
    renderLocalised(
      <DiscussToggle book={makeBook()} currentUserId={1} onChange={vi.fn()} />,
    );

    expect(
      screen.getByLabelText(
        "I would like to talk about this book, ask me about it",
      ),
    ).toBeInTheDocument();
  });

  it("is off on a book nobody has offered", () => {
    renderLocalised(
      <DiscussToggle book={makeBook()} currentUserId={1} onChange={vi.fn()} />,
    );

    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("reflects the reader's own offer", () => {
    renderLocalised(
      <DiscussToggle
        book={makeBook({ my_wants_to_discuss: true })}
        currentUserId={1}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("checkbox")).toBeChecked();
  });

  it("reports being ticked", async () => {
    const onChange = vi.fn();
    renderLocalised(
      <DiscussToggle book={makeBook()} currentUserId={1} onChange={onChange} />,
    );

    await userEvent.setup().click(screen.getByRole("checkbox"));

    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("reports being unticked", async () => {
    const onChange = vi.fn();
    renderLocalised(
      <DiscussToggle
        book={makeBook({ my_wants_to_discuss: true })}
        currentUserId={1}
        onChange={onChange}
      />,
    );

    await userEvent.setup().click(screen.getByRole("checkbox"));

    expect(onChange).toHaveBeenCalledWith(false);
  });

  it("names whoever else has offered", () => {
    // The whole point of the flag: a marker only its owner can see is not a
    // way to be asked about anything.
    const ana = makeUser({ id: 7, username: "ana" });
    renderLocalised(
      <DiscussToggle
        book={makeBook({ discuss_with: [ana] })}
        currentUserId={1}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Ask ana about this book.")).toBeInTheDocument();
  });

  it("leaves the reader out of the list of people to ask", () => {
    // They know. Telling somebody to ask themselves is noise on every book
    // they ticked.
    const me = makeUser({ id: 1, username: "me" });
    renderLocalised(
      <DiscussToggle
        book={makeBook({ my_wants_to_discuss: true, discuss_with: [me] })}
        currentUserId={1}
        onChange={vi.fn()}
      />,
    );

    expect(screen.queryByText(/Ask/)).not.toBeInTheDocument();
  });

  it("names the others when the reader is one of them", () => {
    const me = makeUser({ id: 1, username: "me" });
    const ben = makeUser({ id: 2, username: "ben" });
    renderLocalised(
      <DiscussToggle
        book={makeBook({ my_wants_to_discuss: true, discuss_with: [me, ben] })}
        currentUserId={1}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Ask ben about this book.")).toBeInTheDocument();
  });
});
