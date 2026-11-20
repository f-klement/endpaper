/** Tests for src/pages/ScanPage/components/CatalogueNarrowing.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CatalogueSource } from "../../../../src/api/generated/model";
import CatalogueNarrowing, {
  NarrowedTo,
} from "../../../../src/pages/ScanPage/components/CatalogueNarrowing";
import { Locale } from "../../../../src/api/generated/model";
import { renderLocalised } from "../../../utils";

function renderNarrowing(
  catalogues: CatalogueSource[],
  chosen: CatalogueSource[] = [],
) {
  const onChange = vi.fn<(chosen: CatalogueSource[]) => void>();
  renderLocalised(
    <CatalogueNarrowing
      catalogues={catalogues}
      chosen={chosen}
      onChange={onChange}
      hint="search.narrow.searchHint"
    />,
  );
  return onChange;
}

describe("CatalogueNarrowing", () => {
  it("offers nothing where there is one catalogue to ask", () => {
    renderNarrowing(["dnb"]);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("keeps the ticks in the library's order, whatever order they were clicked in", async () => {
    const onChange = renderNarrowing(["dnb", "k10plus", "bnf"], ["bnf"]);
    await userEvent.click(
      screen.getByText("Asking only National Library of France"),
    );

    await userEvent.click(
      screen.getByRole("checkbox", { name: "German National Library" }),
    );

    expect(onChange).toHaveBeenCalledWith(["dnb", "bnf"]);
  });
});

describe("NarrowedTo", () => {
  it("says nothing of a request that asked every catalogue", () => {
    const { container } = renderLocalised(<NarrowedTo asked={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the catalogues in German", () => {
    renderLocalised(<NarrowedTo asked={["dnb"]} />, { locale: Locale.de });
    expect(
      screen.getByText("Es wurden nur Deutsche Nationalbibliothek gefragt."),
    ).toBeInTheDocument();
  });
});
