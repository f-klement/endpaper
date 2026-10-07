/** Tests for
 * src/pages/SettingsPage/LibrarySettingsPage/components/CustomFieldsSection.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CustomFieldOut } from "../../../../../src/api/generated/model";
import CustomFieldsSection from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/CustomFieldsSection";
import { renderLocalised } from "../../../../utils";

const LINK: CustomFieldOut = {
  id: 1,
  name: "Calibre-web",
  kind: "url",
  renamable: true,
};
const TEXT: CustomFieldOut = {
  id: 2,
  name: "Bought from",
  kind: "text",
  renamable: true,
};

type SectionProps = React.ComponentProps<typeof CustomFieldsSection>;

/** A rename the server accepts, which is what closes the edit row. */
const accepts = () =>
  vi.fn<SectionProps["onRename"]>((_id, _name, callbacks) =>
    callbacks.onSuccess(),
  );

/** A rename the server refuses, with the sentence it would have sent. */
const refuses = (message: string) =>
  vi.fn<SectionProps["onRename"]>((_id, _name, callbacks) =>
    callbacks.onError(new Error(message)),
  );

function renderSection(overrides = {}) {
  const props = {
    fields: [LINK, TEXT],
    isAdmin: true,
    isBusy: false,
    error: null,
    onDefine: vi.fn<SectionProps["onDefine"]>(),
    onRename: accepts(),
    onRemove: vi.fn<SectionProps["onRemove"]>(),
    ...overrides,
  };
  renderLocalised(<CustomFieldsSection {...props} />);
  return props;
}

/** Open the first row's edit box and type a new name into it. */
async function typeANewName(into: string) {
  await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]!);
  const box = screen.getByLabelText("New name for Calibre-web");
  await userEvent.clear(box);
  await userEvent.type(box, into);
  return box;
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

    await typeANewName("Ebook");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(props.onRename).toHaveBeenCalledWith(1, "Ebook", expect.anything());
    expect(props.onRemove).not.toHaveBeenCalled();
  });

  it("closes the edit row once the server has accepted", async () => {
    renderSection();

    await typeANewName("Ebook");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.queryByLabelText("New name for Calibre-web")).toBeNull();
  });

  it("keeps the name that was typed when the server refuses", async () => {
    // The row used to close on dispatch, so a refusal arrived at a row that
    // was gone and the only way forward was to press Edit and retype.
    renderSection({
      onRename: refuses(
        "Only the member who defined this field can rename it.",
      ),
    });

    await typeANewName("Ebook");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.getByLabelText("New name for Calibre-web")).toHaveValue(
      "Ebook",
    );
  });

  it("shows a refused rename beside the row it was typed in", async () => {
    renderSection({
      onRename: refuses(
        "Only the member who defined this field can rename it.",
      ),
    });

    await typeANewName("Ebook");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const row = screen.getByLabelText("New name for Calibre-web").closest("li");
    expect(
      within(row!).getByText(
        "Only the member who defined this field can rename it.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a refused rename once, and not above the section as well", async () => {
    // **Scoped within the row, a second copy above the section is invisible**,
    // and printing it twice is exactly what folding the rename back into the
    // hook's section level error would do. That fold is the one decision both
    // halves of this change rest on, so the count is asserted over the whole
    // document rather than inside the row.
    //
    // **`ignore` exempts the screen reader announcer and nothing else.**
    // Announcing an async error means an `aria-live` node carrying the same
    // sentence, which adds no second visible copy; a count that reds on it
    // sends the next accessibility change back here to edit the guard, which
    // is how a rule teaches people to weaken it. The default is
    // `script, style`, so this adds a third rather than replacing them.
    //
    // **`.sr-only[aria-live]` and not `[aria-live]`, which was the first
    // spelling and admitted too much.** A toast region is an `aria-live`
    // container holding a **visible** copy, so the wide form let a genuine
    // second copy through: driven, 20 passed with the sentence rendered
    // visibly inside one. The class is what separates an announcement from a
    // rendering.
    //
    // **It exempts the element carrying the text, never an ancestor**, which
    // is this option's rule rather than this arm's. A sentence nested inside
    // the announcer rather than written on it is still counted, so an
    // announcer built as a wrapper around a child needs the class on the node
    // holding the words. Driven: the same region with the text one level down
    // reds.
    //
    // **That shape already exists here**, so it is a case somebody will meet
    // rather than a hypothetical: `pages/ScanPage/components/RapidQueue.tsx`
    // toggles `sr-only` on a wrapper and puts `aria-live` on the paragraph
    // inside it, so the node holding the words never carries the class.
    // Nothing in this file renders it, so this arm is unaffected; an arm over
    // that component reaching for this exemption would not get it.
    renderSection({
      onRename: refuses(
        "Only the member who defined this field can rename it.",
      ),
    });

    await typeANewName("Ebook");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(
      screen.getAllByText(
        "Only the member who defined this field can rename it.",
        { ignore: "script, style, .sr-only[aria-live]" },
      ),
    ).toHaveLength(1);
  });

  it("drops a refusal when the rename is given up on", async () => {
    renderSection({ onRename: refuses("That name is taken.") });

    await typeANewName("Ebook");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByText("That name is taken.")).toBeNull();
  });

  it("offers no rename for a field the server says is not renamable", () => {
    // Only the definer may relabel a field, and an admin may relabel any
    // field they can address. Both are the server's answer rather than a rule
    // this component derives, so the one flag is what the control reads.
    renderSection({ fields: [{ ...LINK, renamable: false }] });

    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("still draws the rest of a row it may not rename", () => {
    // Hiding the row rather than the control would take a field off the page
    // of everybody who did not define it, which is the opposite of what the
    // list is for: a field is there to be filled in on a book.
    renderSection({ fields: [{ ...LINK, renamable: false }] });

    const list = screen.getByRole("list");
    expect(within(list).getByText("Calibre-web")).toBeInTheDocument();
    expect(within(list).getByText("A web link")).toBeInTheDocument();
  });

  it("offers the rename only on the rows that carry it", async () => {
    renderSection({ fields: [{ ...LINK, renamable: false }, TEXT] });

    await userEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(screen.getByLabelText("New name for Bought from")).toBeVisible();
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
      error: new Error("This library already has a field with that name."),
    });

    expect(
      screen.getByText("This library already has a field with that name."),
    ).toBeInTheDocument();
  });
});
