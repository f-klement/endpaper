/** Tests for src/components/SectionIcon.tsx. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SectionIcon from "../../src/components/SectionIcon";
import { renderLocalised } from "../utils";

describe("SectionIcon", () => {
  it("is not announced, so the heading beside it is not read twice", () => {
    renderLocalised(
      <h2>
        <SectionIcon name="inbox" />
        Backup
      </h2>,
    );

    expect(screen.getByRole("heading", { name: "Backup" })).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
