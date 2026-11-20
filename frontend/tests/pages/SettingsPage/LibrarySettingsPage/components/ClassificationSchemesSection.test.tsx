/** Tests for
 * src/pages/SettingsPage/LibrarySettingsPage/components/ClassificationSchemesSection.tsx. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  Locale,
  type ClassificationSchemeOut,
} from "../../../../../src/api/generated/model";
import { ApiError } from "../../../../../src/api/mutator";
import ClassificationSchemesSection from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/ClassificationSchemesSection";
import { renderLocalised } from "../../../../utils";

const DEWEY: ClassificationSchemeOut = {
  scheme: "ddc",
  name: "Dewey Decimal Classification",
  filing: "dewey",
  built_in: true,
};
const RVK: ClassificationSchemeOut = {
  scheme: "rvk",
  name: "Regensburger Verbundklassifikation",
  filing: "generic",
  built_in: false,
};

type SectionProps = React.ComponentProps<typeof ClassificationSchemesSection>;

function renderSection(
  over: Partial<SectionProps> = {},
  locale: Locale = Locale.en,
) {
  const props: SectionProps = {
    schemes: [DEWEY, RVK],
    isBusy: false,
    error: null,
    onDefine: vi.fn<SectionProps["onDefine"]>(),
    onRename: vi.fn<SectionProps["onRename"]>(),
    onRemove: vi.fn<SectionProps["onRemove"]>(),
    ...over,
  };
  renderLocalised(<ClassificationSchemesSection {...props} />, { locale });
  return props;
}

function row(text: string): HTMLElement {
  return screen.getByText(text).closest("li")!;
}

const RENAME_LABEL = "New name for Regensburger Verbundklassifikation";

/** Open the library's own scheme's rename box and type a new name into it. */
async function openRenameBox(name: string) {
  await userEvent.click(
    within(row("Regensburger Verbundklassifikation")).getByRole("button", {
      name: "Edit",
    }),
  );
  const box = screen.getByLabelText(RENAME_LABEL);
  await userEvent.clear(box);
  await userEvent.type(box, name);
}

afterEach(() => vi.restoreAllMocks());

describe("ClassificationSchemesSection", () => {
  it("offers no rename or delete on a built in scheme", () => {
    renderSection();
    // By its code: "Dewey" is also the filing rule's name, shown on the row
    // and offered in the form below.
    expect(within(row("ddc")).queryAllByRole("button")).toEqual([]);
  });

  it("deletes a library's own scheme by its code once confirmed", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const props = renderSection();

    await userEvent.click(
      within(row("Regensburger Verbundklassifikation")).getByRole("button", {
        name: "Delete",
      }),
    );

    expect(props.onRemove).toHaveBeenCalledWith("rvk");
  });

  it("renames a library's own scheme by its code and closes the box once accepted", async () => {
    const props = renderSection({
      onRename: vi.fn<SectionProps["onRename"]>((_scheme, _name, callbacks) =>
        callbacks.onSuccess(),
      ),
    });

    await openRenameBox("  Regensburger Klassifikation ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(props.onRename).toHaveBeenCalledWith(
      "rvk",
      "Regensburger Klassifikation",
      expect.anything(),
    );
    expect(screen.queryByLabelText(RENAME_LABEL)).not.toBeInTheDocument();
  });

  it("keeps the rename box open under the server's sentence when a rename is refused", async () => {
    renderSection({
      onRename: vi.fn<SectionProps["onRename"]>((_scheme, _name, callbacks) =>
        callbacks.onError(new ApiError("That name is already taken.", 409)),
      ),
    });

    await openRenameBox("ASB");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.getByText(/already taken/)).toBeInTheDocument();
    expect(screen.getByLabelText(RENAME_LABEL)).toHaveValue("ASB");
  });

  it("defines a scheme with its code, name and rule", async () => {
    const props = renderSection();

    await userEvent.type(screen.getByLabelText("Code"), "ASB");
    await userEvent.type(
      screen.getByLabelText("Name"),
      "Allgemeine Systematik",
    );
    await userEvent.selectOptions(screen.getByLabelText("Sorts like"), "lcc");
    await userEvent.click(screen.getByRole("button", { name: "Add scheme" }));

    expect(props.onDefine).toHaveBeenCalledWith(
      { scheme: "asb", name: "Allgemeine Systematik", filing: "lcc" },
      expect.any(Function),
    );
  });

  it("words a refused delete as the books the admin can see", () => {
    renderSection({ error: inUse(2) });
    expect(
      screen.getByText(
        "2 books you can see still use this scheme, so it cannot be deleted.",
      ),
    ).toBeInTheDocument();
  });

  it("words a refused delete over one book as one", () => {
    renderSection({ error: inUse(1) });
    expect(
      screen.getByText(/^1 book you can see still uses this scheme/),
    ).toBeInTheDocument();
  });

  it("gives no number where only books the admin cannot see use it", () => {
    renderSection({ error: inUse(0) });
    expect(
      screen.getByText(/^Books you cannot see still use this scheme/),
    ).toBeInTheDocument();
  });

  it("words a refused delete in German for a German reader", () => {
    renderSection({ error: inUse(2) }, Locale.de);
    expect(screen.getByText(/^2 sichtbare Bücher/)).toBeInTheDocument();
  });

  it("shows any other refusal as the server said it", () => {
    renderSection({
      error: new ApiError("A scheme with the code 'rvk' already exists.", 409),
    });
    expect(screen.getByText(/already exists/)).toBeInTheDocument();
  });
});

/** The server's 409 for a delete books still block, as the mutator reads it. */
function inUse(count: number): ApiError {
  return new ApiError(
    "English sentence",
    409,
    undefined,
    "scheme_in_use",
    count,
  );
}
