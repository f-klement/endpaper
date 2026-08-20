/** Tests for src/pages/components/CoverImage.tsx. */

import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CoverImage from "../../../src/pages/components/CoverImage";
import { renderLocalised } from "../../utils";

/** The placeholder is an svg with no accessible name, so it is found by tag. */
function placeholder(container: HTMLElement): SVGElement | null {
  return container.querySelector("svg");
}

describe("CoverImage", () => {
  it("renders the cover it is given", () => {
    renderLocalised(<CoverImage src="/covers/1.jpg" alt="Dune" />);
    expect(screen.getByRole("img", { name: "Dune" })).toHaveAttribute(
      "src",
      "/covers/1.jpg",
    );
  });

  it("renders the placeholder when there is no cover", () => {
    const { container } = renderLocalised(<CoverImage src={null} alt="Dune" />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(placeholder(container)).toBeInTheDocument();
  });

  it("swaps in the placeholder when the cover fails to load", () => {
    // The old handler set display:none, which takes the element out of the
    // flow: on the book page that collapsed the header to zero height and the
    // back button landed on top of the title.
    const { container } = renderLocalised(
      <CoverImage src="https://example.invalid/x.jpg" alt="Dune" />,
    );

    fireEvent.error(screen.getByRole("img", { name: "Dune" }));

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(placeholder(container)).toBeInTheDocument();
  });

  it("keeps the same box size after a failure", () => {
    const { container } = renderLocalised(
      <CoverImage
        src="https://example.invalid/x.jpg"
        alt="Dune"
        className="w-12 h-16"
      />,
    );

    fireEvent.error(screen.getByRole("img", { name: "Dune" }));

    const box = container.firstElementChild!;
    expect(box.className).toContain("w-12");
    expect(box.className).toContain("h-16");
  });

  it("gives a new cover a fresh attempt", () => {
    // The failure is remembered by URL, so a re-cover or a metadata refresh is
    // tried rather than being written off by a stale boolean.
    const { rerender } = renderLocalised(
      <CoverImage src="https://example.invalid/x.jpg" alt="Dune" />,
    );
    fireEvent.error(screen.getByRole("img", { name: "Dune" }));

    rerender(<CoverImage src="/covers/1.jpg" alt="Dune" />);

    expect(screen.getByRole("img", { name: "Dune" })).toHaveAttribute(
      "src",
      "/covers/1.jpg",
    );
  });

  it("does not retry a cover that already failed", () => {
    const { rerender } = renderLocalised(
      <CoverImage src="https://example.invalid/x.jpg" alt="Dune" />,
    );
    fireEvent.error(screen.getByRole("img", { name: "Dune" }));

    rerender(<CoverImage src="https://example.invalid/x.jpg" alt="Dune" />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("hides the placeholder from screen readers", () => {
    // It carries no information the alt text does not already carry.
    const { container } = renderLocalised(<CoverImage src={null} alt="Dune" />);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  });

  it("passes the loading hint through", () => {
    renderLocalised(
      <CoverImage src="/covers/1.jpg" alt="Dune" loading="lazy" />,
    );
    expect(screen.getByRole("img", { name: "Dune" })).toHaveAttribute(
      "loading",
      "lazy",
    );
  });
});
