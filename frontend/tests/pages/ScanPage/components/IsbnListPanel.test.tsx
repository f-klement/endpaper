/** Tests for src/pages/ScanPage/components/IsbnListPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import IsbnListPanel from "../../../../src/pages/ScanPage/components/IsbnListPanel";
import { ISBN_LIST_LIMIT } from "../../../../src/pages/ScanPage/queue";
import { renderLocalised } from "../../../utils";

const DUNE_13 = "9780441013593";
const OTHER_13 = "9780306406157";

function renderPanel(waiting = 0) {
  const onList = vi.fn<(isbns: readonly string[]) => void>();
  renderLocalised(<IsbnListPanel onList={onList} waiting={waiting} />);
  return { onList, user: userEvent.setup() };
}

/** `count` distinct valid ISBN-13s, one a line. */
function manyIsbns(count: number): string {
  const lines: string[] = [];
  for (let n = 0; n < count; n += 1) {
    const body = `978${String(n).padStart(9, "0")}`;
    let total = 0;
    for (let index = 0; index < 12; index += 1) {
      total += Number(body[index]) * (index % 2 === 0 ? 1 : 3);
    }
    lines.push(body + String((10 - (total % 10)) % 10));
  }
  return lines.join("\n");
}

describe("IsbnListPanel", () => {
  it("hands over the valid ISBNs of a pasted list and says how many", async () => {
    const { onList, user } = renderPanel();
    await user.type(screen.getByLabelText("ISBNs"), `${DUNE_13}, ${OTHER_13}`);
    await user.click(screen.getByRole("button", { name: "Look these up" }));

    expect(onList).toHaveBeenCalledWith([DUNE_13, OTHER_13]);
    expect(
      screen.getByText("ISBNs queued for the lookup: 2"),
    ).toBeInTheDocument();
  });

  it("names an ISBN whose check digit fails and does not hand it over", async () => {
    const { onList, user } = renderPanel();
    await user.type(screen.getByLabelText("ISBNs"), `9780441013594 ${DUNE_13}`);
    await user.click(screen.getByRole("button", { name: "Look these up" }));

    expect(onList).toHaveBeenCalledWith([DUNE_13]);
    expect(screen.getByText(/check digit does not match/)).toBeInTheDocument();
    expect(screen.getByText("9780441013594")).toBeInTheDocument();
  });

  it("hands over nothing for a list with no valid ISBN, and says so", async () => {
    const { onList, user } = renderPanel();
    await user.type(screen.getByLabelText("ISBNs"), "9780441013594");
    await user.click(screen.getByRole("button", { name: "Look these up" }));

    expect(onList).not.toHaveBeenCalled();
    expect(
      screen.getByText("ISBNs queued for the lookup: 0"),
    ).toBeInTheDocument();
  });

  it("refuses a list over the bound whole, keeping the text to split", async () => {
    const { onList, user } = renderPanel();
    const field = screen.getByLabelText("ISBNs") as HTMLTextAreaElement;
    // Pasted rather than typed: typing six thousand characters is minutes.
    await user.click(field);
    await user.paste(manyIsbns(ISBN_LIST_LIMIT + 1));
    await user.click(screen.getByRole("button", { name: "Look these up" }));

    expect(onList).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      `This list holds ${ISBN_LIST_LIMIT + 1} ISBNs`,
    );
    expect(field.value).not.toBe("");
  });

  it("refuses a list the rows already waiting leave no room for", async () => {
    // The bound is the queue's: a second list of five hundred would leave a
    // thousand rows waiting, which no single list may.
    const { onList, user } = renderPanel(ISBN_LIST_LIMIT - 1);
    await user.type(screen.getByLabelText("ISBNs"), `${DUNE_13} ${OTHER_13}`);
    await user.click(screen.getByRole("button", { name: "Look these up" }));

    expect(onList).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This list holds 2 ISBNs, and 1 more can join the queue now",
    );
  });

  it("names the invalid ISBNs of a list with no valid one even when the queue is full", async () => {
    const { onList, user } = renderPanel(ISBN_LIST_LIMIT + 100);
    await user.type(screen.getByLabelText("ISBNs"), "9780441013594");
    await user.click(screen.getByRole("button", { name: "Look these up" }));

    expect(onList).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("9780441013594")).toBeInTheDocument();
  });

  it("names the first fifty invalid ISBNs and counts the rest", async () => {
    // Thirteen digits under a prefix that is not Bookland's: shaped like an
    // ISBN and refused, one distinct token each.
    const bad = Array.from(
      { length: 52 },
      (_unused, n) => `123${String(n).padStart(10, "0")}`,
    );
    const { user } = renderPanel();
    await user.click(screen.getByLabelText("ISBNs"));
    await user.paste(bad.join("\n"));
    await user.click(screen.getByRole("button", { name: "Look these up" }));

    expect(screen.getAllByRole("listitem")).toHaveLength(50);
    expect(screen.getByText("And 2 more, not shown.")).toBeInTheDocument();
  });

  it("takes a list at the bound", async () => {
    const { onList, user } = renderPanel();
    await user.click(screen.getByLabelText("ISBNs"));
    await user.paste(manyIsbns(ISBN_LIST_LIMIT));
    await user.click(screen.getByRole("button", { name: "Look these up" }));

    expect(onList.mock.calls[0]?.[0]).toHaveLength(ISBN_LIST_LIMIT);
  });

  it("reads a picked text file as the same list", async () => {
    const { onList, user } = renderPanel();
    const file = new File([`isbn\n${DUNE_13}\n`], "list.csv", {
      type: "text/csv",
    });
    await user.upload(
      screen.getByLabelText("Or pick a text or CSV file"),
      file,
    );

    await vi.waitFor(() => expect(onList).toHaveBeenCalledWith([DUNE_13]));
    expect(screen.getByText(/passed over: 1/)).toBeInTheDocument();
  });

  it("says a picked file was unreadable when taking its list fails", async () => {
    const onList = vi.fn<(isbns: readonly string[]) => void>(() => {
      throw new Error("the queue refused the rows");
    });
    renderLocalised(<IsbnListPanel onList={onList} waiting={0} />);
    const file = new File([`${DUNE_13}\n`], "list.txt", { type: "text/plain" });
    await userEvent
      .setup()
      .upload(screen.getByLabelText("Or pick a text or CSV file"), file);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not be read",
    );
  });

  it("refuses a file too large to be a list before reading it", async () => {
    const { onList, user } = renderPanel();
    const file = new File(["x"], "huge.txt", { type: "text/plain" });
    Object.defineProperty(file, "size", { value: 1024 * 1024 + 1 });
    await user.upload(
      screen.getByLabelText("Or pick a text or CSV file"),
      file,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "too large to be a list",
    );
    expect(onList).not.toHaveBeenCalled();
  });
});
