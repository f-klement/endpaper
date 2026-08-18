/** Tests for src/pages/components/TagPicker.tsx: shared by three pages. */

import { screen } from "@testing-library/react";
import { renderLocalised } from "../../utils";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TagPicker from "../../../src/pages/components/TagPicker";
import { makeTag, makeTagSet, resetIds } from "../../factories";

beforeEach(resetIds);

describe("TagPicker", () => {
  it("groups tags under their category heading", () => {
    renderLocalised(
      <TagPicker tags={makeTagSet()} selectedIds={[]} onToggle={vi.fn()} />,
    );
    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByText("Genre")).toBeInTheDocument();
    expect(screen.getByText("Age")).toBeInTheDocument();
  });

  it("omits a category with no tags", () => {
    renderLocalised(
      <TagPicker
        tags={[makeTag({ name: "Fantasy" })]}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("Genre")).toBeInTheDocument();
    expect(screen.queryByText("Type")).not.toBeInTheDocument();
  });

  it("renders nothing for an empty tag list", () => {
    const { container } = renderLocalised(
      <TagPicker tags={[]} selectedIds={[]} onToggle={vi.fn()} />,
    );
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("reports the tag id when one is clicked", async () => {
    const tags = makeTagSet();
    const onToggle = vi.fn();
    renderLocalised(
      <TagPicker tags={tags} selectedIds={[]} onToggle={onToggle} />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Fantasy" }));

    expect(onToggle).toHaveBeenCalledWith(tags[1]!.id);
  });

  it("marks a selected tag as pressed", () => {
    const tags = makeTagSet();
    renderLocalised(
      <TagPicker tags={tags} selectedIds={[tags[1]!.id]} onToggle={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: "Fantasy" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Fiction" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("reports a click on an already-selected tag too", () => {
    // The caller decides what a second click means; this component only says
    // which tag was pressed.
    const tags = makeTagSet();
    const onToggle = vi.fn();
    renderLocalised(
      <TagPicker tags={tags} selectedIds={[tags[1]!.id]} onToggle={onToggle} />,
    );
    screen.getByRole("button", { name: "Fantasy" }).click();
    expect(onToggle).toHaveBeenCalledWith(tags[1]!.id);
  });
});
