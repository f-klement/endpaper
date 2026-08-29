/** Tests for src/pages/AuthorsPage/components/AuthorCard. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AuthorCard from "../../../../src/pages/AuthorsPage/components/AuthorCard";
import { renderLocalised } from "../../../utils";

function author(overrides: Record<string, unknown> = {}) {
  return {
    key: "frank herbert",
    name: "Frank Herbert",
    book_count: 3,
    spellings: ["Frank Herbert"],
    merged: [],
    ...overrides,
  };
}

describe("AuthorCard", () => {
  it("links by the name, which is what the filter chip then shows", () => {
    // The API takes the name or the key and resolves a folded spelling either
    // way, so neither is more durable. The name is what a reader recognises in
    // the chip: linking the key made the same filter describe itself as
    // "Author: frank herbert" here and "Author: Frank Herbert" from a book.
    renderLocalised(
      <AuthorCard
        author={author()}
        isBusy={false}
        isSelected={false}
        onToggleSelect={vi.fn()}
        onUndo={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("link", { name: "Show these books" }),
    ).toHaveAttribute("href", "/?author=Frank%20Herbert");
  });

  it("shows the other spellings, because they are why a merge is wanted", () => {
    renderLocalised(
      <AuthorCard
        author={author({ spellings: ["Frank Herbert", "frank herbert"] })}
        isBusy={false}
        isSelected={false}
        onToggleSelect={vi.fn()}
        onUndo={vi.fn()}
      />,
    );

    expect(screen.getByText("Also spelled: frank herbert")).toBeInTheDocument();
  });

  it("offers an undo per folded spelling, not one for the author", async () => {
    const onUndo = vi.fn();
    renderLocalised(
      <AuthorCard
        author={author({
          merged: [
            { alias_id: 4, spelling: "F. Herbert" },
            { alias_id: 5, spelling: "Herbert, Frank" },
          ],
        })}
        isBusy={false}
        isSelected={false}
        onToggleSelect={vi.fn()}
        onUndo={onUndo}
      />,
    );

    const undos = screen.getAllByRole("button", { name: "Undo this merge" });
    expect(undos).toHaveLength(2);
    await userEvent.setup().click(undos[1]!);

    expect(onUndo).toHaveBeenCalledWith(5);
  });

  it("does not repeat a folded spelling as an ordinary one", () => {
    renderLocalised(
      <AuthorCard
        author={author({
          spellings: ["Frank Herbert", "F. Herbert"],
          merged: [{ alias_id: 4, spelling: "F. Herbert" }],
        })}
        isBusy={false}
        isSelected={false}
        onToggleSelect={vi.fn()}
        onUndo={vi.fn()}
      />,
    );

    expect(screen.queryByText(/Also spelled/)).not.toBeInTheDocument();
    expect(screen.getByText("Folded in: F. Herbert")).toBeInTheDocument();
  });

  describe("the outward Wikipedia link", () => {
    // #89. Three product rules, in the owner's order: the app's current locale
    // first, fall back rather than give up, and the gate is identity rather
    // than language. The first two are the server's and are tested in
    // `backend/tests/test_authority.py`; what this card owns is that the button
    // appears only when the server offered one, that it leaves the app safely,
    // and that it never lies about which language it landed on.
    const card = (wikipedia?: {
      key: string;
      url: string;
      language?: string | null;
    }) =>
      renderLocalised(
        <AuthorCard
          author={author()}
          isBusy={false}
          isSelected={false}
          onToggleSelect={vi.fn()}
          onUndo={vi.fn()}
          wikipedia={wikipedia}
        />,
      );

    it("shows no second button for an author nobody has identified", () => {
      // The gate is identity, not the network: the server returns a row only
      // for an author carrying a confirmed authority identifier, so an absent
      // row is a fact about the shelf. #87 measured why that matters, two GND
      // records spelled `Stevenson, Robert Louis` of which one has no Wikidata
      // item, and an article about the wrong one is worse than none.
      card();

      expect(screen.queryByRole("link", { name: /Wikipedia/ })).toBeNull();
      expect(
        screen.getByRole("link", { name: "Show these books" }),
      ).toBeInTheDocument();
    });

    it("names the language when the article is not in the reader's", () => {
      // The owner's rule: a page you cannot read beats an absent button. Being
      // told which language it is is what stops that reading as a fault.
      //
      // **The language's name, not the subdomain.** "in fr" reads as a fault
      // rather than as information, and the first version of this test asserted
      // exactly that string. `hreflang` still carries the code, because that
      // attribute is defined to take one.
      card({
        key: "frank herbert",
        url: "https://fr.wikipedia.org/wiki/Frank_Herbert",
        language: "fr",
      });

      const link = screen.getByRole("link", {
        name: "Read about Frank Herbert on Wikipedia, in French",
      });
      expect(link).toHaveAttribute(
        "href",
        "https://fr.wikipedia.org/wiki/Frank_Herbert",
      );
      expect(link).toHaveAttribute("hreflang", "fr");
    });

    it("does not name the language when it is the one being read", () => {
      // The diagonal of the test above. `renderLocalised` forces English, so
      // `en` here is the reader's own and saying so would be noise on every
      // card in the ordinary case.
      card({
        key: "frank herbert",
        url: "https://en.wikipedia.org/wiki/Frank_Herbert",
        language: "en",
      });

      expect(
        screen.getByRole("link", {
          name: "Read about Frank Herbert on Wikipedia",
        }),
      ).toBeInTheDocument();
    });

    it("says it is Wikidata when no Wikipedia article was found", () => {
      // The floor of the fallback chain. `language` null means the URL is the
      // Wikidata item, which happens both when no edition holds an article and
      // when Wikidata could not be reached, and calling that "Wikipedia" would
      // be a promise the link does not keep.
      card({
        key: "frank herbert",
        url: "https://www.wikidata.org/wiki/Q123",
        language: null,
      });

      const link = screen.getByRole("link", {
        name: "Look Frank Herbert up on Wikidata",
      });
      expect(link).toHaveAttribute(
        "href",
        "https://www.wikidata.org/wiki/Q123",
      );
      expect(link).not.toHaveAttribute("hreflang");
    });

    it("shows the raw code for an edition Intl has no name for", () => {
      // The third tier reaches the unusual editions, and four of their codes
      // make `Intl.DisplayNames.of` throw rather than fall back: `bat-smg` is
      // one, measured in this project's runtime. Without the guard in
      // `lib/languageName` this render raises rather than degrading, so the
      // whole card would disappear behind the error boundary for exactly the
      // author the fallback tier exists to serve.
      card({
        key: "frank herbert",
        url: "https://bat-smg.wikipedia.org/wiki/Frank_Herbert",
        language: "bat-smg",
      });

      expect(
        screen.getByRole("link", {
          name: "Read about Frank Herbert on Wikipedia, in bat-smg",
        }),
      ).toBeInTheDocument();
    });

    it("shows no button at all for a URL safeHref refuses", () => {
      // **The `safeHref` call had no test and could have been deleted with the
      // suite green**, because every other fixture here supplies a URL it
      // accepts, so the falsy branch was never entered.
      //
      // No live hole: the server's `_WIKIPEDIA_ARTICLE` refuses this shape
      // before it is ever serialised. What this pins is that the agreement
      // between the two is not the only thing standing between a response and
      // an `href`, which is the whole reason the second check is here.
      card({
        key: "frank herbert",
        url: "javascript:alert(1)",
        language: "en",
      });

      expect(screen.queryByRole("link", { name: /Wikipedia/ })).toBeNull();
      expect(
        screen.getByRole("link", { name: "Show these books" }),
      ).toBeInTheDocument();
    });

    it("leaves the app in a new tab and tells the target nothing", () => {
      // `noreferrer` as well as `noopener`: the target is a third party and has
      // no business knowing which page linked to it. The same rule the book
      // page applies to its Goodreads link.
      card({
        key: "frank herbert",
        url: "https://en.wikipedia.org/wiki/Frank_Herbert",
        language: "en",
      });

      const link = screen.getByRole("link", { name: /Wikipedia/ });
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    });

    it("hides the W from assistive tech, which reads the label instead", () => {
      // The stylised W is the whole visible content of the button, so a screen
      // reader that announced it would say "W" and nothing else.
      card({
        key: "frank herbert",
        url: "https://en.wikipedia.org/wiki/Frank_Herbert",
        language: "en",
      });

      const link = screen.getByRole("link", { name: /Wikipedia/ });
      expect(link).toHaveTextContent("W");
      expect(link.querySelector("[aria-hidden='true']")).not.toBeNull();
    });
  });
});
