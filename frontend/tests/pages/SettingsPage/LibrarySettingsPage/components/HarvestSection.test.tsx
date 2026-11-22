/** Tests for
 * src/pages/SettingsPage/LibrarySettingsPage/components/HarvestSection.tsx. */

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Locale,
  type SettingsOut,
} from "../../../../../src/api/generated/model";
import HarvestSection from "../../../../../src/pages/SettingsPage/LibrarySettingsPage/components/HarvestSection";
import { renderLocalised } from "../../../../utils";

const REPOSITORY = "http://10.0.0.10/oai";

type SectionProps = React.ComponentProps<typeof HarvestSection>;

function renderSection(
  stored: Partial<SettingsOut> = {},
  over: Partial<SectionProps> = {},
  locale: Locale = Locale.en,
) {
  const props: SectionProps = {
    settings: {
      oai_harvest_enabled: false,
      oai_harvest_base_url: "",
      ...stored,
    } as SettingsOut,
    isSaving: false,
    saveError: null,
    onSave: vi.fn<SectionProps["onSave"]>(),
    ...over,
  };
  renderLocalised(<HarvestSection {...props} />, { locale });
  return props;
}

function theSwitch(): HTMLElement {
  return screen.getByRole("checkbox", {
    name: /Harvest from the repository below/,
  });
}

describe("HarvestSection", () => {
  it("says the address is the one setting that makes the server connect where a person typed", () => {
    renderSection();

    expect(
      screen.getByText(
        /This is the one setting that makes the server connect to an address somebody typed/,
      ),
    ).toBeInTheDocument();
  });

  it("keeps the switch off while no address is stored, and says why", () => {
    renderSection();

    expect(theSwitch()).toBeDisabled();
    expect(
      screen.getByText("Enter the repository address below first."),
    ).toBeInTheDocument();
  });

  it("turns the harvester on once an address is stored", async () => {
    const props = renderSection({ oai_harvest_base_url: REPOSITORY });

    await userEvent.click(theSwitch());

    expect(props.onSave).toHaveBeenCalledWith({ oai_harvest_enabled: true });
  });

  it("saves a typed address trimmed, by its own button", async () => {
    const props = renderSection();

    fireEvent.change(screen.getByLabelText("Repository address"), {
      target: { value: `  ${REPOSITORY} ` },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save address" }));

    expect(props.onSave).toHaveBeenCalledWith({
      oai_harvest_base_url: REPOSITORY,
    });
  });

  it("does not offer to clear the address while the harvester is on", () => {
    renderSection({
      oai_harvest_enabled: true,
      oai_harvest_base_url: REPOSITORY,
    });

    fireEvent.change(screen.getByLabelText("Repository address"), {
      target: { value: "" },
    });

    expect(screen.getByRole("button", { name: "Save address" })).toBeDisabled();
  });

  it("starts the draft again from an address stored elsewhere", () => {
    const props: SectionProps = {
      settings: {
        oai_harvest_enabled: false,
        oai_harvest_base_url: "",
      } as SettingsOut,
      isSaving: false,
      saveError: null,
      onSave: vi.fn<SectionProps["onSave"]>(),
    };
    const { rerender } = renderLocalised(<HarvestSection {...props} />);

    rerender(
      <HarvestSection
        {...props}
        settings={
          { ...props.settings, oai_harvest_base_url: REPOSITORY } as SettingsOut
        }
      />,
    );

    expect(screen.getByLabelText("Repository address")).toHaveValue(REPOSITORY);
    expect(
      screen.queryByRole("button", { name: "Save address" }),
    ).not.toBeInTheDocument();
  });

  it("shows why a save was refused", () => {
    renderSection(
      {},
      {
        saveError: new Error(
          "The repository address must be an http or https address.",
        ),
      },
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("speaks German to a German reader", () => {
    renderSection({}, {}, Locale.de);

    expect(
      screen.getByRole("heading", { name: "Einen anderen Katalog übernehmen" }),
    ).toBeInTheDocument();
  });
});
