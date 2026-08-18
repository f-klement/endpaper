/** Tests for src/components/StarRating.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import StarRating from "../../src/components/StarRating";
import { renderLocalised } from "../utils";

describe("StarRating", () => {
  describe("as a control", () => {
    it("is a radio group, not five loose buttons", () => {
      // The values are mutually exclusive, and a screen reader should hear one
      // control with five options rather than five unrelated ones.
      renderLocalised(<StarRating value={3} onChange={vi.fn()} />);

      expect(
        screen.getByRole("radiogroup", { name: "Your rating" }),
      ).toBeInTheDocument();
      expect(screen.getAllByRole("radio")).toHaveLength(5);
    });

    it("marks the current rating as checked", () => {
      renderLocalised(<StarRating value={3} onChange={vi.fn()} />);
      expect(
        screen.getByRole("radio", { name: "Rate 3 out of 5" }),
      ).toBeChecked();
    });

    it("reports a new rating", async () => {
      const onChange = vi.fn();
      renderLocalised(<StarRating value={null} onChange={onChange} />);

      await userEvent
        .setup()
        .click(screen.getByRole("radio", { name: "Rate 4 out of 5" }));

      expect(onChange).toHaveBeenCalledWith(4);
    });

    it("clears when the current rating is clicked again", async () => {
      // Otherwise a mis-tapped star is permanent: there is no other way back.
      const onChange = vi.fn();
      renderLocalised(<StarRating value={3} onChange={onChange} />);

      await userEvent
        .setup()
        .click(screen.getByRole("radio", { name: "Rate 3 out of 5" }));

      expect(onChange).toHaveBeenCalledWith(null);
    });

    it("offers an explicit clear once rated", async () => {
      const onChange = vi.fn();
      renderLocalised(<StarRating value={2} onChange={onChange} />);

      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Clear rating" }));

      expect(onChange).toHaveBeenCalledWith(null);
    });

    it("hides the clear control when there is nothing to clear", () => {
      renderLocalised(<StarRating value={null} onChange={vi.fn()} />);
      expect(
        screen.queryByRole("button", { name: "Clear rating" }),
      ).not.toBeInTheDocument();
    });
  });

  describe("as a display", () => {
    it("renders no controls without onChange", () => {
      renderLocalised(<StarRating value={4} />);
      expect(screen.queryByRole("radio")).not.toBeInTheDocument();
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
    });

    it("treats a missing rating as zero stars rather than crashing", () => {
      renderLocalised(<StarRating value={undefined} />);
      expect(screen.getByLabelText("Your rating")).toBeInTheDocument();
    });
  });
});
