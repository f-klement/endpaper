/** Tests for src/pages/BookDetail/components/ClassificationPanel. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ClassificationScheme,
  HeadingKind,
} from "../../../../src/api/generated/model";
import ClassificationPanel, {
  headingHref,
} from "../../../../src/pages/BookDetail/components/ClassificationPanel";
import { renderLocalised } from "../../../utils";

const DEWEY = {
  scheme: ClassificationScheme.ddc,
  number: "155.9042",
  label: null,
};
const SUBJECT = {
  scheme: ClassificationScheme.lcsh,
  number: "Stress management",
  label: null,
};

describe("what the panel shows", () => {
  it("says so plainly when the book carries none", () => {
    renderLocalised(<ClassificationPanel classifications={[]} />);

    expect(screen.getByText("No classification yet.")).toBeInTheDocument();
  });

  it("names the scheme beside every number", () => {
    // Not decoration: `004` is computing in Dewey and is not a Library of
    // Congress call number at all, so a number with no scheme cannot be read.
    renderLocalised(<ClassificationPanel classifications={[DEWEY, SUBJECT]} />);

    expect(screen.getByText("Dewey")).toBeInTheDocument();
    expect(screen.getByText("Subject heading")).toBeInTheDocument();
  });

  it("renders a number with no caption as a number, not a template with a hole in it", () => {
    // MARC 082 carries the notation alone: the field holds the number and the
    // printed schedule holds the words. Every Dewey row here has a null label.
    const { container } = renderLocalised(
      <ClassificationPanel classifications={[DEWEY]} />,
    );

    expect(container.textContent).toContain("155.9042");
    expect(container.textContent).not.toContain("null");
    expect(container.textContent).not.toContain("undefined");
  });

  it("shows the caption where the record carried one", () => {
    renderLocalised(
      <ClassificationPanel
        classifications={[
          {
            scheme: ClassificationScheme.gnd,
            number: "4203576-4",
            label: "Schatz",
          },
        ]}
      />,
    );

    expect(screen.getByText("Schatz")).toBeInTheDocument();
    expect(screen.getByText("4203576-4")).toBeInTheDocument();
  });
});

describe("a heading that is not about what the book is about", () => {
  // `#162`: the DNB writes a carrier and a content type into the same subject
  // fields as a subject, each with a GND number on it, so an unmarked chip says
  // this book is about CD-ROM.
  const CARRIER = {
    scheme: ClassificationScheme.gnd,
    number: "4139307-7",
    label: "CD-ROM",
    kind: HeadingKind.carrier,
  };

  it("says a carrier is a carrier", () => {
    renderLocalised(<ClassificationPanel classifications={[CARRIER]} />);

    expect(screen.getByText("Carrier type")).toBeInTheDocument();
    expect(screen.getByText("CD-ROM")).toBeInTheDocument();
  });

  it("says a content type is one", () => {
    renderLocalised(
      <ClassificationPanel
        classifications={[
          {
            scheme: ClassificationScheme.gnd,
            number: "1071854844",
            label: "Fiktionale Darstellung",
            kind: HeadingKind.content,
          },
        ]}
      />,
    );

    expect(screen.getByText("Content type")).toBeInTheDocument();
  });

  it("marks nothing on an ordinary subject", () => {
    // Anti vacuity for the two above: a panel that printed a kind on every
    // chip would pass them and say nothing.
    const { container } = renderLocalised(
      <ClassificationPanel classifications={[DEWEY, SUBJECT]} />,
    );

    expect(container.textContent).not.toContain("Carrier type");
    expect(container.textContent).not.toContain("Content type");
  });

  it("marks nothing on a heading no record ever declared for", () => {
    // Every row written before the column existed reads as a subject, which is
    // what almost all of them are.
    const { container } = renderLocalised(
      <ClassificationPanel
        classifications={[
          {
            scheme: ClassificationScheme.gnd,
            number: "4203576-4",
            label: "Schatz",
            kind: null,
          },
        ]}
      />,
    );

    expect(container.textContent).not.toContain("Carrier type");
    expect(container.textContent).not.toContain("Content type");
  });

  it("still filters on the identifier and not on the words", () => {
    // `#147`: the words are what a reader picks and the identifier is what the
    // filter carries. `CD-ROM` is a caption two catalogues may spell
    // differently; `4139307-7` is not.
    renderLocalised(<ClassificationPanel classifications={[CARRIER]} />);

    expect(screen.getByRole("link", { name: /CD-ROM/ })).toHaveAttribute(
      "href",
      "/?classification=gnd%3A4139307-7",
    );
  });
});

describe("the link each heading leads to", () => {
  it("filters the library by that exact heading", () => {
    renderLocalised(<ClassificationPanel classifications={[DEWEY]} />);

    expect(screen.getByRole("link", { name: /155\.9042/ })).toHaveAttribute(
      "href",
      "/?classification=ddc%3A155.9042",
    );
  });

  it("survives a heading carrying a comma", () => {
    // The measurement the whole wire format was chosen for. An LCSH number is
    // the authorised heading string and those carry commas, so a hand built
    // query string is where one gets lost.
    expect(
      headingHref({
        scheme: ClassificationScheme.lcsh,
        number: "Mental health, Public",
        label: null,
      }),
    ).toBe("/?classification=lcsh%3AMental+health%2C+Public");
  });

  it("survives a heading carrying a colon", () => {
    // The backend splits on the first colon only, so the second is data.
    expect(
      headingHref({
        scheme: ClassificationScheme.lcsh,
        number: "Photography: a history",
        label: null,
      }),
    ).toBe("/?classification=lcsh%3APhotography%3A+a+history");
  });
});
