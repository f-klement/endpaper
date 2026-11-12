/**
 * Tests for src/pages/BookDetail/components/AccessPanel.tsx.
 *
 * A digital copy is requested and granted rather than lent: the requester sees
 * where their request stands, the holder answers it.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AccessStatus,
  type AccessRequestOut,
  BookFormat,
  type UserOut,
} from "../../../../src/api/generated/model";
import AccessPanel from "../../../../src/pages/BookDetail/components/AccessPanel";
import { makeBook, makeUser, resetIds } from "../../../factories";
import { renderLocalised } from "../../../utils";

beforeEach(resetIds);

const holder = makeUser({ id: 1, username: "ana" });
const asker = makeUser({ id: 2, username: "ben" });
const merger = makeUser({ id: 3, username: "cy" });

function asked(
  status: AccessStatus,
  id = 10,
  requestedBy = asker,
): AccessRequestOut {
  return {
    id,
    book_id: 5,
    status,
    requested_by: requestedBy,
    holder,
    requested_at: "2026-10-15T09:00:00Z",
    decided_by: status === AccessStatus.pending ? null : holder,
    decided_at: status === AccessStatus.pending ? null : "2026-10-15T10:00:00Z",
  };
}

function renderPanel(
  viewer: number,
  requests: AccessRequestOut[],
  addedBy: UserOut | null = holder,
) {
  const onRequest = vi.fn<() => void>();
  const onDecide = vi.fn<(requestId: number, granted: boolean) => void>();
  renderLocalised(
    <AccessPanel
      book={makeBook({ id: 5, format: BookFormat.ebook, added_by: addedBy })}
      currentUserId={viewer}
      requests={requests}
      isBusy={false}
      onRequest={onRequest}
      onDecide={onDecide}
    />,
  );
  return { onRequest, onDecide };
}

describe("a member who does not hold the copy", () => {
  it("asks for access", async () => {
    const { onRequest } = renderPanel(asker.id, []);
    await userEvent.setup().click(screen.getByText("Request access"));
    expect(onRequest).toHaveBeenCalledOnce();
  });

  it("is told who granted access and where the file comes from", () => {
    renderPanel(asker.id, [asked(AccessStatus.granted)]);
    expect(
      screen.getByText("ana granted you access. Ask them for the file."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Request access")).not.toBeInTheDocument();
  });

  it("may ask again after a refusal, and is told who refused", () => {
    renderPanel(asker.id, [asked(AccessStatus.declined)]);
    expect(
      screen.getByText("ana declined. You can ask again."),
    ).toBeInTheDocument();
    expect(screen.getByText("Request access")).toBeInTheDocument();
  });

  it("waits on a request already made, without a second button", () => {
    renderPanel(asker.id, [asked(AccessStatus.pending)]);
    expect(
      screen.getByText("You asked ana for access. Waiting for an answer."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Request access")).not.toBeInTheDocument();
  });

  it("is not told that nobody has asked, which is the holder's news", () => {
    renderPanel(asker.id, []);
    expect(
      screen.queryByText("Nobody has asked for access."),
    ).not.toBeInTheDocument();
  });
});

describe("a copy nobody holds", () => {
  it("says there is nobody to ask, and offers no request", () => {
    renderPanel(asker.id, [], null);
    expect(
      screen.getByText("Nobody else holds this copy to ask."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Request access")).not.toBeInTheDocument();
  });

  it("offers no new request after a refusal", () => {
    // The holder's account went after it declined: the request still names
    // them, but there is nobody left to ask again.
    renderPanel(asker.id, [asked(AccessStatus.declined)], null);
    expect(screen.queryByText("Request access")).not.toBeInTheDocument();
  });
});

describe("the holder", () => {
  it("grants a waiting request", async () => {
    const { onDecide } = renderPanel(holder.id, [asked(AccessStatus.pending)]);
    await userEvent.setup().click(screen.getByText("Grant"));
    expect(onDecide).toHaveBeenCalledWith(10, true);
  });

  it("is the one a request names, not whoever added the entry it moved to", () => {
    // After a merge the entry's adder is somebody the request was never
    // addressed to; the server does not list it to them, and nor does this.
    renderPanel(merger.id, [asked(AccessStatus.pending)], merger);
    expect(screen.queryByText("Grant")).not.toBeInTheDocument();
  });

  it("declines a waiting request", async () => {
    const { onDecide } = renderPanel(holder.id, [asked(AccessStatus.pending)]);
    await userEvent.setup().click(screen.getByText("Decline"));
    expect(onDecide).toHaveBeenCalledWith(10, false);
  });

  it("reads where each request addressed to them stands", () => {
    renderPanel(holder.id, [
      asked(AccessStatus.granted, 10, makeUser({ id: 4, username: "dee" })),
      asked(AccessStatus.declined, 11, makeUser({ id: 5, username: "eve" })),
      asked(AccessStatus.pending, 12),
    ]);
    expect(screen.getByText("Access granted to dee")).toBeInTheDocument();
    expect(screen.getByText("Declined for eve")).toBeInTheDocument();
    expect(
      screen.getByText("ben is waiting for an answer"),
    ).toBeInTheDocument();
  });

  it("is told when nobody has asked", () => {
    renderPanel(holder.id, []);
    expect(
      screen.getByText("Nobody has asked for access."),
    ).toBeInTheDocument();
  });

  it("is offered no request of their own", () => {
    renderPanel(holder.id, []);
    expect(screen.queryByText("Request access")).not.toBeInTheDocument();
  });
});
