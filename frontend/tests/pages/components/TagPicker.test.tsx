/** Tests for src/pages/components/TagPicker.tsx: shared by three pages. */

import { fireEvent, screen } from "@testing-library/react";
import { renderLocalised } from "../../utils";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Locale, TagCategory, TagKey } from "../../../src/api/generated/model";
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

  it("shows a German reader the German name of a seeded tag", () => {
    // The ticket's first user story. The picker is where a German household
    // meets the English vocabulary, and where a tag suggested from a DDC
    // number arrives pre-selected.
    //
    // Selected rather than clicked open: a category holding a selection opens
    // itself, which keeps this test synchronous and asserts one thing.
    const tags = makeTagSet();
    renderLocalised(
      <TagPicker tags={tags} selectedIds={[tags[0]!.id]} onToggle={vi.fn()} />,
      { locale: Locale.de },
    );

    expect(
      screen.getByRole("button", { name: "Belletristik" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Fiction" }),
    ).not.toBeInTheDocument();
  });

  it("leaves a tag the library invented as it was typed", () => {
    // A tag with no key is theirs, in any language. It is also the shape a
    // renamed seeded tag arrives in, which is how a rename survives.
    const invented = makeTag({
      name: "Holiday reads",
      category: TagCategory.custom,
    });
    renderLocalised(
      <TagPicker
        tags={[invented]}
        selectedIds={[invented.id]}
        onToggle={vi.fn()}
      />,
      { locale: Locale.de },
    );

    expect(
      screen.getByRole("button", { name: "Holiday reads" }),
    ).toBeInTheDocument();
  });

  it("orders a category by the name it prints, not the one it stores", () => {
    // Belletristik files under B and Comics under C. On the English names
    // behind them the order is the other way round: correct against data the
    // reader cannot see.
    const comics = makeTag({
      name: "Comics",
      category: TagCategory.type,
      key: TagKey.comics,
    });
    const fiction = makeTag({
      name: "Fiction",
      category: TagCategory.type,
      key: TagKey.fiction,
    });
    renderLocalised(
      <TagPicker
        tags={[comics, fiction]}
        selectedIds={[comics.id]}
        onToggle={vi.fn()}
      />,
      { locale: Locale.de },
    );

    const chips = screen
      .getAllByRole("button")
      .map((button) => button.textContent)
      .filter((text) => text === "Belletristik" || text === "Comics");
    expect(chips).toEqual(["Belletristik", "Comics"]);
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
      expect(
        screen.getByRole("button", { name: /Genre 1/ }),
      ).toBeInTheDocument();
    });

    it("opens a category that holds a selection, unasked", () => {
      // A selection you cannot see is worse than a long list.
      const tags = makeTagSet();
      renderLocalised(
        <TagPicker
          tags={tags}
          selectedIds={[tags[1]!.id]}
          onToggle={vi.fn()}
        />,
      );

      expect(
        screen.getByRole("button", { name: "Fantasy" }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Genre/ })).toHaveAttribute(
        "aria-expanded",
        "true",
      );
    });

    it("counts the selection in the heading", () => {
      const tags = makeTagSet();
      renderLocalised(
        <TagPicker
          tags={tags}
          selectedIds={[tags[1]!.id]}
          onToggle={vi.fn()}
        />,
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
    fireEvent.change(screen.getByLabelText("New tag"), {
      target: { value: "Holiday reads" },
    });
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

    await userEvent
      .setup()
      .type(screen.getByLabelText("New tag"), "Loft{Enter}");

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
    fireEvent.change(screen.getByLabelText("New tag"), {
      target: { value: "  Loft  " },
    });
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

  it("groups a curated tag under its own heading", () => {
    renderLocalised(
      <TagPicker
        tags={[
          makeTag({ name: "Holiday reads", category: TagCategory.custom }),
        ]}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("Your tags")).toBeInTheDocument();
  });
});
