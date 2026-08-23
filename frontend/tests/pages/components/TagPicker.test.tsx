/** Tests for src/pages/components/TagPicker.tsx: shared by three pages. */

import { fireEvent, screen } from "@testing-library/react";
import { renderLocalised } from "../../utils";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TagCategory } from "../../../src/api/generated/model";
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

    const user = userEvent.setup();
    // Categories start closed: the curated vocabulary is 105 tags, and all of
    // them on screen at once is a wall rather than a picker.
    await user.click(screen.getByRole("button", { name: /Genre/ }));
    await user.click(screen.getByRole("button", { name: "Fantasy" }));

    expect(onToggle).toHaveBeenCalledWith(tags[1]!.id);
  });

  it("marks a selected tag as pressed", async () => {
    const tags = makeTagSet();
    renderLocalised(
      <TagPicker tags={tags} selectedIds={[tags[1]!.id]} onToggle={vi.fn()} />,
    );

    // Genre opens itself because something in it is selected; Type does not.
    expect(screen.getByRole("button", { name: "Fantasy" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await userEvent.setup().click(screen.getByRole("button", { name: /Type/ }));
    expect(screen.getByRole("button", { name: "Fiction" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  describe("collapsing", () => {
    it("hides the tags until a category is opened", () => {
      renderLocalised(
        <TagPicker tags={makeTagSet()} selectedIds={[]} onToggle={vi.fn()} />,
      );

      expect(screen.getByRole("button", { name: /Genre/ })).toHaveAttribute(
        "aria-expanded",
        "false",
      );
      expect(
        screen.queryByRole("button", { name: "Fantasy" }),
      ).not.toBeInTheDocument();
    });

    it("says how many are in each category", () => {
      renderLocalised(
        <TagPicker tags={makeTagSet()} selectedIds={[]} onToggle={vi.fn()} />,
      );
      // The shape of the vocabulary stays visible while its contents do not.
      expect(screen.getByRole("button", { name: /Genre 1/ })).toBeInTheDocument();
    });

    it("opens a category that holds a selection, unasked", () => {
      // A selection you cannot see is worse than a long list.
      const tags = makeTagSet();
      renderLocalised(
        <TagPicker tags={tags} selectedIds={[tags[1]!.id]} onToggle={vi.fn()} />,
      );

      expect(screen.getByRole("button", { name: "Fantasy" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Genre/ })).toHaveAttribute(
        "aria-expanded",
        "true",
      );
    });

    it("counts the selection in the heading", () => {
      const tags = makeTagSet();
      renderLocalised(
        <TagPicker tags={tags} selectedIds={[tags[1]!.id]} onToggle={vi.fn()} />,
      );
      expect(
        screen.getByRole("button", { name: /1 of 1/ }),
      ).toBeInTheDocument();
    });
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

describe("TagPicker, inventing a tag", () => {
  it("offers no create control unless one is wanted", () => {
    // The filter panel passes no handler: inventing a tag while narrowing a
    // list is a different act from putting one on a book, and offering it
    // there produces tags nothing carries.
    renderLocalised(
      <TagPicker tags={makeTagSet()} selectedIds={[]} onToggle={vi.fn()} />,
    );
    expect(
      screen.queryByRole("button", { name: "Create" }),
    ).not.toBeInTheDocument();
  });

  it("reports the typed name", async () => {
    const onCreate = vi.fn();
    renderLocalised(
      <TagPicker
        tags={makeTagSet()}
        selectedIds={[]}
        onToggle={vi.fn()}
        onCreate={onCreate}
      />,
    );

    const user = userEvent.setup();
    fireEvent.change(screen.getByLabelText("New tag"), { target: { value: "Holiday reads" } });
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(onCreate).toHaveBeenCalledWith("Holiday reads");
  });

  it("creates on Enter without submitting the surrounding form", async () => {
    // The picker sits inside forms. Without preventDefault the Enter that
    // means "add this tag" submits the book instead.
    const onCreate = vi.fn();
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    renderLocalised(
      <form onSubmit={onSubmit}>
        <TagPicker
          tags={makeTagSet()}
          selectedIds={[]}
          onToggle={vi.fn()}
          onCreate={onCreate}
        />
      </form>,
    );

    await userEvent.setup().type(screen.getByLabelText("New tag"), "Loft{Enter}");

    expect(onCreate).toHaveBeenCalledWith("Loft");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("trims what was typed", async () => {
    const onCreate = vi.fn();
    renderLocalised(
      <TagPicker
        tags={makeTagSet()}
        selectedIds={[]}
        onToggle={vi.fn()}
        onCreate={onCreate}
      />,
    );

    const user = userEvent.setup();
    fireEvent.change(screen.getByLabelText("New tag"), { target: { value: "  Loft  " } });
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(onCreate).toHaveBeenCalledWith("Loft");
  });

  it("will not create an empty tag", async () => {
    const onCreate = vi.fn();
    renderLocalised(
      <TagPicker
        tags={makeTagSet()}
        selectedIds={[]}
        onToggle={vi.fn()}
        onCreate={onCreate}
      />,
    );

    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
    await userEvent.setup().type(screen.getByLabelText("New tag"), "   ");
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("clears the box after creating, ready for the next one", async () => {
    renderLocalised(
      <TagPicker
        tags={makeTagSet()}
        selectedIds={[]}
        onToggle={vi.fn()}
        onCreate={vi.fn()}
      />,
    );

    const user = userEvent.setup();
    const box = screen.getByLabelText("New tag");
    fireEvent.change(box, { target: { value: "Loft" } });
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(box).toHaveValue("");
  });

  it("groups a household tag under its own heading", () => {
    renderLocalised(
      <TagPicker
        tags={[makeTag({ name: "Holiday reads", category: TagCategory.custom })]}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("Household tags")).toBeInTheDocument();
  });
});

