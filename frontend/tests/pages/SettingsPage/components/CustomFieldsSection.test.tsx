/** Tests for src/pages/SettingsPage/components/CustomFieldsSection.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CustomFieldOut } from "../../../../src/api/generated/model";
import CustomFieldsSection from "../../../../src/pages/SettingsPage/components/CustomFieldsSection";
import { renderLocalised } from "../../../utils";

const LINK: CustomFieldOut = { id: 1, name: "Calibre-web", kind: "url" };
const TEXT: CustomFieldOut = { id: 2, name: "Bought from", kind: "text" };

function renderSection(overrides = {}) {
  const props = {
    isOpen: true,
    onToggle: vi.fn(),
    fields: [LINK, TEXT],
    isAdmin: true,
    isBusy: false,
    error: null,
    onDefine: vi.fn(),
    onRename: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
  renderLocalised(<CustomFieldsSection {...props} />);
  return props;
}

afterEach(() => vi.restoreAllMocks());

describe("CustomFieldsSection", () => {
  it("lists what the library has defined", () => {
    renderSection();

    expect(screen.getByText("Calibre-web")).toBeInTheDocument();
    expect(screen.getByText("Bought from")).toBeInTheDocument();
  });

  it("says which fields hold a link", () => {
    // Scoped to the list, because the add form's own select carries both
    // labels as options and `getByText` would find two of each.
    renderSection();
    const list = screen.getByRole("list");

    expect(within(list).getByText("A web link")).toBeInTheDocument();
    expect(within(list).getByText("Text")).toBeInTheDocument();
  });

  it("defines a field with the kind that was chosen", async () => {
    const props = renderSection({ fields: [] });

    await userEvent.type(screen.getByLabelText("Field name"), "Calibre-web");
    await userEvent.selectOptions(
      screen.getByLabelText("What it holds"),
      "url",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));

    expect(props.onDefine).toHaveBeenCalledWith("Calibre-web", "url");
  });

  it("defaults a new field to text", async () => {
    // Detection turns prose that happens to start with http into a link, so
    // the safe kind is the one somebody gets without choosing.
    const props = renderSection({ fields: [] });

    await userEvent.type(screen.getByLabelText("Field name"), "Bought from");
    await userEvent.click(screen.getByRole("button", { name: "Add field" }));

    expect(props.onDefine).toHaveBeenCalledWith("Bought from", "text");
  });

  it("will not define a field with a blank name", async () => {
    renderSection({ fields: [] });

    expect(screen.getByRole("button", { name: "Add field" })).toBeDisabled();
  });

  it("renames a field without touching anything else", async () => {
    const props = renderSection();

    await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]!);
    const box = screen.getByLabelText("New name for Calibre-web");
    await userEvent.clear(box);
    await userEvent.type(box, "Ebook");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(props.onRename).toHaveBeenCalledWith(1, "Ebook");
    expect(props.onRemove).not.toHaveBeenCalled();
  });

  it("asks before deleting, and names what goes", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const props = renderSection();

    await userEvent.click(
      screen.getAllByRole("button", { name: "Delete" })[0]!,
    );

    expect(confirm).toHaveBeenCalledWith(
      "Delete Calibre-web? Its value is removed from every book, and this cannot be undone.",
    );
    expect(props.onRemove).toHaveBeenCalledWith(1);
  });

  it("does not delete when the confirmation is refused", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const props = renderSection();

    await userEvent.click(
      screen.getAllByRole("button", { name: "Delete" })[0]!,
    );

    expect(props.onRemove).not.toHaveBeenCalled();
  });

  it("offers no delete to a member who is not an admin", () => {
    // The endpoint answers 403, so drawing the control would be an offer the
    // app cannot keep.
    renderSection({ isAdmin: false });

    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("still lets a member who is not an admin define one", () => {
    // Additive and changes no book, exactly as inventing a tag is.
    renderSection({ isAdmin: false, fields: [] });

    expect(
      screen.getByRole("button", { name: "Add field" }),
    ).toBeInTheDocument();
  });

  it("says so when nothing is defined", () => {
    renderSection({ fields: [] });

    expect(screen.getByText("No custom fields yet")).toBeInTheDocument();
  });

  it("shows what the server refused", () => {
    renderSection({
      error: new Error("This library already has a field called Calibre-web."),
    });

    expect(
      screen.getByText("This library already has a field called Calibre-web."),
    ).toBeInTheDocument();
  });
});
