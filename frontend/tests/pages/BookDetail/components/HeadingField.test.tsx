/** Tests for src/pages/BookDetail/components/HeadingField. */

import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  Locale,
  type ClassificationOut,
  type SuggestingVocabularyOut,
} from "../../../../src/api/generated/model";
import HeadingField from "../../../../src/pages/BookDetail/components/HeadingField";
import { renderLocalised } from "../../../utils";

const GND: SuggestingVocabularyOut = { scheme: "gnd", name: "GND" };
const LCSH: SuggestingVocabularyOut = { scheme: "lcsh", name: "LCSH" };
const KATZE: ClassificationOut = {
  scheme: "gnd",
  number: "4029849-4",
  label: "Katze",
};

function renderField(
  vocabularies: SuggestingVocabularyOut[],
  {
    suggestions = [],
    locale = Locale.en,
  }: { suggestions?: ClassificationOut[]; locale?: Locale } = {},
) {
  const onPick = vi.fn<(heading: ClassificationOut) => void>();
  const onType = vi.fn<(text: string) => void>();
  const onChooseScheme = vi.fn<(scheme: string) => void>();
  renderLocalised(
    <HeadingField
      vocabularies={vocabularies}
      scheme={vocabularies[0]?.scheme ?? ""}
      onChooseScheme={onChooseScheme}
      typed=""
      onType={onType}
      suggestions={suggestions}
      onPick={onPick}
      isPicking={false}
      error={null}
    />,
    { locale },
  );
  return { onPick, onType, onChooseScheme };
}

describe("HeadingField", () => {
  it("draws nothing while no vocabulary is offered", () => {
    renderField([]);

    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("hands what is typed to the caller", () => {
    const { onType } = renderField([GND]);

    const field = screen.getByRole("searchbox", { name: "Find a heading" });
    fireEvent.change(field, { target: { value: "Kat" } });

    expect(onType).toHaveBeenCalledWith("Kat");
  });

  it("picks the suggestion pressed, unchanged", () => {
    const { onPick } = renderField([GND], { suggestions: [KATZE] });

    fireEvent.click(screen.getByRole("button", { name: /Katze/ }));

    expect(onPick).toHaveBeenCalledWith(KATZE);
  });

  it("names an unlabelled heading once", () => {
    const heading: ClassificationOut = {
      scheme: "lcsh",
      number: "Computer science",
      label: null,
    };
    renderField([LCSH], { suggestions: [heading] });

    expect(
      screen.getByRole("button", { name: "Computer science" }),
    ).toBeTruthy();
  });

  it("offers no vocabulary choice with one copy loaded", () => {
    renderField([GND]);

    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("chooses between two loaded vocabularies", () => {
    const { onChooseScheme } = renderField([GND, LCSH]);

    fireEvent.change(screen.getByRole("combobox", { name: "Vocabulary" }), {
      target: { value: "lcsh" },
    });

    expect(onChooseScheme).toHaveBeenCalledWith("lcsh");
  });

  it("labels the field in German", () => {
    renderField([GND], { locale: Locale.de });

    expect(
      screen.getByRole("searchbox", { name: "Schlagwort suchen" }),
    ).toBeInTheDocument();
  });
});
