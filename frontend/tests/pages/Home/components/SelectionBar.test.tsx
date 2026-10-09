/** Tests for src/pages/Home/components/SelectionBar.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Locale,
  OwnershipStatus,
  TagCategory,
  TagKey,
} from "../../../../src/api/generated/model";
import { makeCollection, makeTag } from "../../../factories";
import SelectionBar from "../../../../src/pages/Home/components/SelectionBar";
import { renderLocalised } from "../../../utils";

function renderBar(
  overrides: Partial<Parameters<typeof SelectionBar>[0]> = {},
) {
  const props = {
    selectedCount: 2,
    isApplying: false,
    result: null,
    error: null,
    tags: [],
    collections: [],
    onSelectAll: vi.fn(),
    onRun: vi.fn(),
    onClear: vi.fn(),
    onApply: vi.fn(),
    onDone: vi.fn(),
    ...overrides,
  };
  renderLocalised(<SelectionBar {...props} />);
  return props;
}

describe("SelectionBar", () => {
  it("reports how many are selected", () => {
    renderBar({ selectedCount: 7 });
    expect(screen.getByText("7 selected")).toBeInTheDocument();
  });

  it("confirms the selection as owned", async () => {
    const props = renderBar();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Mark as on the shelf" }));

    expect(props.onApply).toHaveBeenCalledWith(OwnershipStatus.owned);
  });

  it("can also mark them as not owned", async () => {
    const props = renderBar();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Mark as not owned" }));

    expect(props.onApply).toHaveBeenCalledWith(OwnershipStatus.not_owned);
  });

  describe("with nothing selected", () => {
    it("disables both actions", () => {
      renderBar({ selectedCount: 0 });
      expect(
        screen.getByRole("button", { name: "Mark as on the shelf" }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Mark as not owned" }),
      ).toBeDisabled();
    });

    it("still allows selecting everything", () => {
      renderBar({ selectedCount: 0 });
      expect(screen.getByRole("button", { name: "Select all" })).toBeEnabled();
    });
  });

  it("disables the actions while a request is in flight", () => {
    // Clicking twice would send the same ids again, and the second reply would
    // report every book as unchanged.
    renderBar({ isApplying: true });
    expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled();
  });

  it("reports what the update did", () => {
    renderBar({ result: { updated: 4, unchanged: 1, skipped: 2 } });
    expect(screen.getByRole("status")).toHaveTextContent(
      "4 updated, 1 already set, 2 skipped.",
    );
  });

  it("shows a failure", () => {
    renderBar({ error: new Error("Too many books") });
    expect(screen.getByRole("alert")).toHaveTextContent("Too many books");
  });

  it("hands the remaining controls upwards", async () => {
    const props = renderBar();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Select all" }));
    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    await user.click(screen.getByRole("button", { name: "Done" }));

    expect(props.onSelectAll).toHaveBeenCalledOnce();
    expect(props.onClear).toHaveBeenCalledOnce();
    expect(props.onDone).toHaveBeenCalledOnce();
  });
});

describe("SelectionBar extra actions", () => {
  it("keeps the destructive ones behind a disclosure", () => {
    // Deleting forty books should not sit one mis-tap from "mark as owned".
    renderBar();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
  });

  it("reveals them on request", async () => {
    renderBar();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /More actions/ }));

    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("sets a reading status for the selection", async () => {
    const props = renderBar();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /More actions/ }));

    await user.selectOptions(
      screen.getByLabelText("Set reading status"),
      "read",
    );

    expect(props.onRun).toHaveBeenCalledWith("set_status", "read");
  });

  it("adds a tag to the selection", async () => {
    const props = renderBar({
      tags: [{ id: 7, name: "Fiction", category: "type" }],
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /More actions/ }));

    await user.selectOptions(screen.getByLabelText("Add tag"), "7");

    expect(props.onRun).toHaveBeenCalledWith("add_tag", 7);
  });

  it("names the tags in the reader's language, in the order they print", async () => {
    // Two seeded tags in one category. Sorted on the stored English names the
    // order is Comics, Fiction; on the German ones it is Belletristik, Comics,
    // and this list shows the German ones.
    renderLocalised(
      <SelectionBar
        selectedCount={2}
        isApplying={false}
        result={null}
        error={null}
        tags={[
          makeTag({
            name: "Comics",
            category: TagCategory.type,
            key: TagKey.comics,
          }),
          makeTag({
            name: "Fiction",
            category: TagCategory.type,
            key: TagKey.fiction,
          }),
        ]}
        collections={[]}
        onSelectAll={vi.fn()}
        onRun={vi.fn()}
        onClear={vi.fn()}
        onApply={vi.fn()}
        onDone={vi.fn()}
      />,
      { locale: Locale.de },
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Weitere Aktionen/ }));

    // Scoped to the tag select. The bar holds a status select too, and an
    // unscoped option query reads both of them.
    const options = within(screen.getByLabelText("Schlagwort hinzufügen"))
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(options.slice(1)).toEqual(["Belletristik", "Comics"]);
  });

  it("asks before deleting", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const props = renderBar();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /More actions/ }));

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(window.confirm).toHaveBeenCalled();
    expect(props.onRun).toHaveBeenCalledWith("delete");
  });

  it("does not delete when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const props = renderBar();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /More actions/ }));

    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(props.onRun).not.toHaveBeenCalled();
  });

  it("treats a cancelled location prompt as no change", async () => {
    // null is cancel; an empty string is a deliberate clear. Conflating them
    // would wipe the location of every selected book on a stray Escape.
    vi.spyOn(window, "prompt").mockReturnValue(null);
    const props = renderBar();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /More actions/ }));

    await user.click(screen.getByRole("button", { name: "Set location" }));

    expect(props.onRun).not.toHaveBeenCalled();
  });

  it("offers no collection picker until the library has one", async () => {
    renderBar();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /More actions/ }));

    expect(
      screen.queryByLabelText("Put in a collection"),
    ).not.toBeInTheDocument();
  });

  it("files the selection into a collection", async () => {
    const props = renderBar({
      collections: [makeCollection({ id: 3, name: "Ebooks" })],
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /More actions/ }));

    await user.selectOptions(screen.getByLabelText("Put in a collection"), "3");

    expect(props.onRun).toHaveBeenCalledWith("set_collection", 3);
  });

  it("sends an empty value to take them out of every collection", async () => {
    // The placeholder is already the empty string, so clearing needs an option
    // of its own. It has to reach the API as the empty value all the same.
    const props = renderBar({
      collections: [makeCollection({ id: 3, name: "Ebooks" })],
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /More actions/ }));

    await user.selectOptions(
      screen.getByLabelText("Put in a collection"),
      "none",
    );

    expect(props.onRun).toHaveBeenCalledWith("set_collection", "");
  });

  it("sends an empty location as a deliberate clear", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("");
    const props = renderBar();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /More actions/ }));

    await user.click(screen.getByRole("button", { name: "Set location" }));

    expect(props.onRun).toHaveBeenCalledWith("set_location", "");
  });
});
