/**
 * Tests for src/pages/ScanPage/components/PrintedIsbnReader.tsx.
 *
 * The engine is `tests/doubles/textRecognition.ts`, aliased in for the whole
 * suite and reset by `tests/setup.ts`; the camera is `tests/doubles/camera.ts`.
 */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fakeStream,
  getUserMedia,
  installCamera,
  stopTrack,
} from "../../../doubles/camera";
import * as recogniser from "../../../doubles/textRecognition";
import { Locale } from "../../../../src/api/generated/model";
import { renderLocalised } from "../../../utils";

import PrintedIsbnReader from "../../../../src/pages/ScanPage/components/PrintedIsbnReader";

beforeEach(() => {
  installCamera();
});

/** Render the reader and wait for the camera and the engine to be ready. */
async function openReader() {
  const onConfirm = vi.fn<(isbn: string) => void>();
  const rendered = renderLocalised(<PrintedIsbnReader onConfirm={onConfirm} />);
  const button = await screen.findByRole("button", { name: "Read the number" });
  await waitFor(() => expect(button).toBeEnabled());
  return { ...rendered, onConfirm, button };
}

describe("PrintedIsbnReader", () => {
  it("says the reader is loading, and offers no read, until the engine opens", async () => {
    recogniser.opening.mockReturnValue(new Promise(() => {}));
    renderLocalised(<PrintedIsbnReader onConfirm={() => {}} />);
    expect(
      await screen.findByRole("button", { name: "Loading the text reader..." }),
    ).toBeDisabled();
  });

  it("offers the ISBN read for confirmation and looks it up only on the member's tap", async () => {
    recogniser.read.mockResolvedValue("ISBN 978-3-16-148410-0");
    const { onConfirm, button } = await openReader();
    await userEvent.click(button);

    expect(
      await screen.findByText("Read ISBN 9783161484100"),
    ).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Look it up" }));
    expect(onConfirm).toHaveBeenCalledWith("9783161484100");
  });

  it("names a read whose check digit fails as a misread and offers only another read", async () => {
    recogniser.read.mockResolvedValue("ISBN 978-3-16-148410-1");
    const { onConfirm, button } = await openReader();
    await userEvent.click(button);

    expect(
      await screen.findByText(
        /Read 978-3-16-148410-1, but its check digit does not match/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Look it up" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Read again" }));
    expect(
      screen.getByRole("button", { name: "Read the number" }),
    ).toBeEnabled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("says when the box held no ISBN", async () => {
    recogniser.read.mockResolvedValue("Printed in Germany");
    const { button } = await openReader();
    await userEvent.click(button);
    expect(await screen.findByText(/No ISBN in the box/)).toBeInTheDocument();
  });

  it("tells the member to type the ISBN when the engine cannot start", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    recogniser.opening.mockRejectedValue(new Error("no SIMD"));
    renderLocalised(<PrintedIsbnReader onConfirm={() => {}} />);
    expect(
      await screen.findByText(/could not start in this browser/),
    ).toBeInTheDocument();
  });

  it("reads in German", async () => {
    recogniser.read.mockResolvedValue("ISBN 978-3-16-148410-1");
    renderLocalised(<PrintedIsbnReader onConfirm={() => {}} />, {
      locale: Locale.de,
    });
    const button = await screen.findByRole("button", { name: "Nummer lesen" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    expect(
      await screen.findByText(/die Prüfziffer stimmt nicht/),
    ).toBeInTheDocument();
  });

  it("names the camera's refusal when it will not open", async () => {
    getUserMedia.mockRejectedValue(new Error("Permission denied"));
    renderLocalised(<PrintedIsbnReader onConfirm={() => {}} />);
    expect(await screen.findByText("Permission denied")).toBeInTheDocument();
  });

  it("says the camera is unavailable when its refusal gives no reason", async () => {
    getUserMedia.mockRejectedValue("refused");
    renderLocalised(<PrintedIsbnReader onConfirm={() => {}} />);
    expect(await screen.findAllByText("Camera unavailable")).toHaveLength(2);
  });

  it("releases a camera that opens only after the reader closed", async () => {
    let open!: (stream: MediaStream) => void;
    getUserMedia.mockReturnValue(
      new Promise<MediaStream>((resolve) => {
        open = resolve;
      }),
    );
    const { unmount } = renderLocalised(
      <PrintedIsbnReader onConfirm={() => {}} />,
    );
    unmount();
    open(fakeStream());
    await waitFor(() => expect(stopTrack).toHaveBeenCalled());
  });

  it("shows the opened camera in the reader's picture", async () => {
    const stream = fakeStream();
    getUserMedia.mockResolvedValue(stream);
    const { container } = await openReader();
    expect(container.querySelector("video")!.srcObject).toBe(stream);
  });

  it("releases the camera and the engine when it closes", async () => {
    const { unmount } = await openReader();
    expect(getUserMedia).toHaveBeenCalledOnce();
    unmount();
    expect(stopTrack).toHaveBeenCalled();
    expect(recogniser.close).toHaveBeenCalledOnce();
  });
});
