/** Tests for src/pages/AuthorsPage/components/SuggestionCard. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AuthorSuggestionOut,
  SuggestionReason,
} from "../../../../src/api/generated/model";
import SuggestionCard from "../../../../src/pages/AuthorsPage/components/SuggestionCard";
import { renderLocalised } from "../../../utils";

const GROUP: AuthorSuggestionOut = {
  keys: ["j smith", "james smith", "john smith"],
  names: ["J. Smith", "James Smith", "John Smith"],
  reasons: ["initials"],
};

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("SuggestionCard", () => {
  it("offers no free text field, because the merge bar already does", () => {
    // Every key in a group also has a card with a checkbox, so the bar reaches
    // the same write with the same two strings. This card carried a duplicate.
    renderLocalised(
      <SuggestionCard group={GROUP} isMerging={false} onMerge={vi.fn()} />,
    );

    expect(
      screen.queryByLabelText("Or a name none of them has"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("A name to use instead"),
    ).not.toBeInTheDocument();
  });

  it("says which rule offered the group", () => {
    renderLocalised(
      <SuggestionCard group={GROUP} isMerging={false} onMerge={vi.fn()} />,
    );

    expect(
      screen.getByText("an initial against a full name"),
    ).toBeInTheDocument();
  });

  it("says it in words when the rule is a shared authority record", () => {
    renderLocalised(
      <SuggestionCard
        group={{ ...GROUP, reasons: ["identity"] }}
        isMerging={false}
        onMerge={vi.fn()}
      />,
    );

    expect(screen.getByText("the same authority record")).toBeInTheDocument();
    expect(screen.queryByText("identity")).not.toBeInTheDocument();
  });

  it("drops a rule this build does not know rather than printing its name", () => {
    // Version skew: an older page against a newer API. The map is exhaustive by
    // type, so this is unreachable for a client and server built together, and
    // it is exactly how `identity` once reached a reader as a bare word.
    renderLocalised(
      <SuggestionCard
        group={{
          ...GROUP,
          // Cast because the type says this value cannot exist, which is the
          // guard working. The runtime still has to survive it.
          reasons: ["initials", "sortition"] as SuggestionReason[],
        }}
        isMerging={false}
        onMerge={vi.fn()}
      />,
    );

    expect(
      screen.getByText("an initial against a full name"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/sortition/)).not.toBeInTheDocument();
  });

  it("merges the whole group into the name that is kept", async () => {
    const onMerge = vi.fn();
    renderLocalised(
      <SuggestionCard group={GROUP} isMerging={false} onMerge={onMerge} />,
    );

    const [first] = screen.getAllByRole("button", { name: "Keep this name" });
    await userEvent.setup().click(first!);

    expect(onMerge).toHaveBeenCalledWith(GROUP.keys, "J. Smith");
  });

  it("leaves out anybody unchecked, because the grouping is transitive", async () => {
    // `J. Smith` pulls two different people into one group. Offering the group
    // as a single button would make the wrong answer the easy one.
    const onMerge = vi.fn();
    renderLocalised(
      <SuggestionCard group={GROUP} isMerging={false} onMerge={onMerge} />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByLabelText("Include James Smith"));
    const [, , third] = screen.getAllByRole("button", {
      name: "Keep this name",
    });
    await user.click(third!);

    expect(onMerge).toHaveBeenCalledWith(
      ["j smith", "john smith"],
      "John Smith",
    );
  });

  it("cannot keep a name that has been unchecked", async () => {
    renderLocalised(
      <SuggestionCard group={GROUP} isMerging={false} onMerge={vi.fn()} />,
    );

    await userEvent.setup().click(screen.getByLabelText("Include J. Smith"));

    const [first] = screen.getAllByRole("button", { name: "Keep this name" });
    expect(first).toBeDisabled();
  });

  it("sends nothing when the reader cancels", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const onMerge = vi.fn();
    renderLocalised(
      <SuggestionCard group={GROUP} isMerging={false} onMerge={onMerge} />,
    );

    const [first] = screen.getAllByRole("button", { name: "Keep this name" });
    await userEvent.setup().click(first!);

    expect(onMerge).not.toHaveBeenCalled();
  });
});
