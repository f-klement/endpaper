/** Tests for src/pages/BookDetail/components/OnlineLinksPanel. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LinkRelationship } from "../../../../src/api/generated/model";
import OnlineLinksPanel from "../../../../src/pages/BookDetail/components/OnlineLinksPanel";
import { renderLocalised } from "../../../utils";

describe("a catalogue's online links on the book page", () => {
  it("renders a link by its text, opening elsewhere without an opener", () => {
    renderLocalised(
      <OnlineLinksPanel
        links={[
          {
            id: 1,
            url: "https://d-nb.info/1234/04",
            label: "Inhaltsverzeichnis",
            relation: LinkRelationship.related,
          },
        ]}
        onRemove={() => {}}
      />,
    );

    const link = screen.getByRole("link", { name: "Inhaltsverzeichnis" });
    expect(link).toHaveAttribute("href", "https://d-nb.info/1234/04");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("Related")).toBeInTheDocument();
  });

  it("shows a stored URL safeHref refuses as text, never as an href", () => {
    renderLocalised(
      <OnlineLinksPanel
        links={[
          { id: 2, url: "javascript:alert(1)", label: null, relation: null },
        ]}
        onRemove={() => {}}
      />,
    );

    expect(screen.getByText("javascript:alert(1)")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("hands the whole link to the remove control named by its text", () => {
    const removed: unknown[] = [];
    const link = {
      id: 3,
      url: "https://a.example/x",
      label: "Volltext",
      relation: null,
    };
    renderLocalised(
      <OnlineLinksPanel links={[link]} onRemove={(row) => removed.push(row)} />,
    );

    screen.getByRole("button", { name: "Remove Volltext" }).click();

    expect(removed).toEqual([link]);
  });
});
