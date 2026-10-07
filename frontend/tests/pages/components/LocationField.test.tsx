/** Tests for src/pages/components/LocationField.tsx: shared by two flows. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import LocationField from "../../../src/pages/components/LocationField";
import { renderLocalised } from "../../utils";

type OnChange = NonNullable<
  React.ComponentProps<typeof LocationField>["onChange"]
>;

const SHELVES = [
  { name: "Living room shelf 3", book_count: 40 },
  { name: "Loft box 2", book_count: 12 },
];

describe("LocationField", () => {
  it("offers the shelves already in use as suggestions", () => {
    const { container } = renderLocalised(
      <LocationField
        value=""
        onChange={vi.fn<OnChange>()}
        locations={SHELVES}
      />,
    );
    const options = [...container.querySelectorAll("datalist option")];
    expect(options.map((option) => option.getAttribute("value"))).toEqual([
      "Living room shelf 3",
      "Loft box 2",
    ]);
  });

  it("still accepts a shelf nobody has used yet", async () => {
    const onChange = vi.fn<OnChange>();
    renderLocalised(
      <LocationField value="" onChange={onChange} locations={SHELVES} />,
    );
    await userEvent.type(screen.getByLabelText("Where it is"), "S");
    expect(onChange).toHaveBeenCalledWith("S");
  });

  it("binds no list when there are no shelves yet", () => {
    const { container } = renderLocalised(
      <LocationField value="" onChange={vi.fn<OnChange>()} locations={[]} />,
    );
    expect(container.querySelector("datalist")).toBeNull();
    expect(screen.getByLabelText("Where it is")).not.toHaveAttribute("list");
  });

  it("gives each instance its own list, so two can be mounted at once", () => {
    const { container } = renderLocalised(
      <>
        <LocationField
          value=""
          onChange={vi.fn<OnChange>()}
          locations={SHELVES}
        />
        <LocationField
          value=""
          onChange={vi.fn<OnChange>()}
          locations={SHELVES}
        />
      </>,
    );
    const ids = [...container.querySelectorAll("datalist")].map(
      (list) => list.id,
    );
    expect(ids).toHaveLength(2);
    expect(ids[0]).not.toBe(ids[1]);
  });

  it("caps what can be typed at the column's length", () => {
    renderLocalised(
      <LocationField value="" onChange={vi.fn<OnChange>()} locations={[]} />,
    );
    expect(screen.getByLabelText("Where it is")).toHaveAttribute(
      "maxlength",
      "120",
    );
  });
});
