/** Tests for src/pages/Home/components/SavedSearches.tsx. */

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import SavedSearches from "../../../../src/pages/Home/components/SavedSearches";
import type { SavedSearch } from "../../../../src/lib/savedSearches";
import {
  DEFAULT_FILTERS,
  type BookFilters,
} from "../../../../src/pages/Home/types";
import { renderLocalised } from "../../../utils";

const LOFT = {
  id: "1",
  name: "Loft",
  filters: { ...DEFAULT_FILTERS, location: "Loft" } as BookFilters,
};

/**
 * The kept views arrive as one value with their two verbs on it, so the spies
 * live there rather than beside it. `onApply` stays a prop of its own: applying
 * a saved view writes the filters, which are not a preference.
 */
function renderSaved(
  overrides: { canSave?: boolean; searches?: SavedSearch[] } = {},
) {
  const props = {
    saved: {
      searches: overrides.searches ?? [LOFT],
      save: vi.fn(),
      remove: vi.fn(),
    },
    canSave: overrides.canSave ?? true,
    onApply: vi.fn(),
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

    expect(props.saved.remove).toHaveBeenCalledWith("1");
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
        saved={{ searches: [], save: vi.fn(), remove: vi.fn() }}
        canSave={false}
        onApply={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("saves under the typed name", async () => {
    const props = renderSaved();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Save this view" }));
    fireEvent.change(screen.getByLabelText("Name for this view"), {
      target: { value: "Kitchen" },
    });
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(props.saved.save).toHaveBeenCalledWith("Kitchen");
  });

  it("saves on Enter as well as on the button", async () => {
    const props = renderSaved();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Save this view" }));
    await user.type(
      screen.getByLabelText("Name for this view"),
      "Kitchen{Enter}",
    );

    expect(props.saved.save).toHaveBeenCalledWith("Kitchen");
  });

  it("will not save an empty name", async () => {
    const props = renderSaved();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Save this view" }));

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(props.saved.save).not.toHaveBeenCalled();
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
