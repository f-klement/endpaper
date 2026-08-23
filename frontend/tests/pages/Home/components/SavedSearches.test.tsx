/** Tests for src/pages/Home/components/SavedSearches.tsx. */

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import SavedSearches from "../../../../src/pages/Home/components/SavedSearches";
import { DEFAULT_FILTERS, type BookFilters } from "../../../../src/pages/Home/types";
import { renderLocalised } from "../../../utils";

const LOFT = {
  id: "1",
  name: "Loft",
  filters: { ...DEFAULT_FILTERS, location: "Loft" } as BookFilters,
};

function renderSaved(overrides: Partial<React.ComponentProps<typeof SavedSearches>> = {}) {
  const props = {
    searches: [LOFT],
    canSave: true,
    onApply: vi.fn(),
    onSave: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  };
  renderLocalised(<SavedSearches {...props} />);
  return props;
}

describe("SavedSearches", () => {
  it("applies a saved view when it is chosen", async () => {
    const props = renderSaved();

    await userEvent.setup().click(screen.getByRole("button", { name: "Loft" }));

    expect(props.onApply).toHaveBeenCalledWith(LOFT.filters);
  });

  it("forgets one when asked", async () => {
    const props = renderSaved();

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Forget Loft" }));

    expect(props.onDelete).toHaveBeenCalledWith("1");
  });

  it("offers no save control until something is filtered", () => {
    // Saving "everything" is offering to save the page they are already on.
    renderSaved({ canSave: false });
    expect(
      screen.queryByRole("button", { name: "Save this view" }),
    ).not.toBeInTheDocument();
  });

  it("renders nothing at all with no views and nothing to save", () => {
    const { container } = renderLocalised(
      <SavedSearches
        searches={[]}
        canSave={false}
        onApply={vi.fn()}
        onSave={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("saves under the typed name", async () => {
    const props = renderSaved();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Save this view" }));
    fireEvent.change(screen.getByLabelText("Name for this view"), { target: { value: "Kitchen" } });
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(props.onSave).toHaveBeenCalledWith("Kitchen");
  });

  it("saves on Enter as well as on the button", async () => {
    const props = renderSaved();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Save this view" }));
    await user.type(screen.getByLabelText("Name for this view"), "Kitchen{Enter}");

    expect(props.onSave).toHaveBeenCalledWith("Kitchen");
  });

  it("will not save an empty name", async () => {
    const props = renderSaved();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Save this view" }));

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(props.onSave).not.toHaveBeenCalled();
  });

  it("abandons naming on Escape", async () => {
    renderSaved();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Save this view" }));
    await user.type(screen.getByLabelText("Name for this view"), "{Escape}");

    expect(
      screen.getByRole("button", { name: "Save this view" }),
    ).toBeInTheDocument();
  });
});
