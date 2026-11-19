/** Tests for src/pages/BookDetail/components/CoverImagesPanel.tsx. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  Locale,
  type CoverImageOut,
} from "../../../../src/api/generated/model";
import CoverImagesPanel from "../../../../src/pages/BookDetail/components/CoverImagesPanel";
import { renderLocalised } from "../../../utils";

const BACK: CoverImageOut = { id: 4, url: "/covers/7/images/4.png" };
const SPINE: CoverImageOut = { id: 9, url: "/covers/7/images/9.jpg" };

function renderPanel(
  images: CoverImageOut[],
  {
    busy = new Set<number>(),
    isUploading = false,
    listError = null,
    locale = Locale.en,
  }: {
    busy?: ReadonlySet<number>;
    isUploading?: boolean;
    listError?: unknown;
    locale?: Locale;
  } = {},
) {
  const onUpload = vi.fn<(file: File) => void>();
  const onRemove = vi.fn<(image: CoverImageOut) => void>();
  const onShelve = vi.fn<(image: CoverImageOut) => void>();
  renderLocalised(
    <CoverImagesPanel
      title="Dune"
      images={images}
      isUploading={isUploading}
      busy={busy}
      listError={listError}
      error={null}
      onUpload={onUpload}
      onRemove={onRemove}
      onShelve={onShelve}
    />,
    { locale },
  );
  return { onUpload, onRemove, onShelve };
}

describe("CoverImagesPanel", () => {
  it("draws each image from the url the server gave", () => {
    renderPanel([BACK, SPINE]);

    expect(screen.getByAltText("Image 1 of Dune")).toHaveAttribute(
      "src",
      BACK.url,
    );
    expect(screen.getByAltText("Image 2 of Dune")).toHaveAttribute(
      "src",
      SPINE.url,
    );
  });

  it("shelves the image whose button was pressed", async () => {
    const { onShelve } = renderPanel([BACK, SPINE]);

    await userEvent.click(
      screen.getByRole("button", { name: "Show image 2 on the shelf" }),
    );

    expect(onShelve).toHaveBeenCalledWith(SPINE);
  });

  it("removes the image whose button was pressed", async () => {
    const { onRemove } = renderPanel([BACK, SPINE]);

    await userEvent.click(
      screen.getByRole("button", { name: "Remove image 1" }),
    );

    expect(onRemove).toHaveBeenCalledWith(BACK);
  });

  it("disables both buttons of an image while it is being written", () => {
    renderPanel([BACK, SPINE], { busy: new Set([BACK.id]) });

    expect(
      screen.getByRole("button", { name: "Show image 1 on the shelf" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Remove image 1" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Remove image 2" }),
    ).toBeEnabled();
  });

  it("hands a picked file to the upload", async () => {
    const { onUpload } = renderPanel([]);
    const file = new File(["x"], "back.png", { type: "image/png" });

    await userEvent.upload(screen.getByLabelText("Add an image"), file);

    expect(onUpload).toHaveBeenCalledWith(file);
  });

  it("says when the list could not be read rather than showing none", () => {
    renderPanel([], { listError: {} });

    expect(
      screen.getByText("This copy's images could not be loaded."),
    ).toBeInTheDocument();
  });

  it("is in German when the reader is", () => {
    renderPanel([BACK], { locale: Locale.de });

    expect(
      screen.getByRole("button", { name: "Bild 1 als Titelbild verwenden" }),
    ).toBeInTheDocument();
  });
});
