/**
 * @vitest-environment node
 *
 * Touches no DOM. Building one costs more than this file spends running.
 */
/**
 * Tests for src/pages/SettingsPage/LibrarySettingsPage/importing.ts.
 *
 * The write every import card on that page shares. Both hooks are exercised
 * against a real server stub in `hooks.test.tsx`, which is where the ordering
 * matters to a member; what is here is the property that has no card in it: a
 * request is never in flight beside another, whatever the caller does.
 */

import { describe, expect, it, vi } from "vitest";

import type { BookCreate } from "../../../../src/api/generated/model";
import {
  statusOf,
  writeBooks,
  type ImportProgress,
} from "../../../../src/pages/SettingsPage/LibrarySettingsPage/importing";

function bodies(count: number): BookCreate[] {
  return Array.from({ length: count }, (_, index) => ({
    title: `Book ${index + 1}`,
  })) as BookCreate[];
}

function collector() {
  const progress: ImportProgress[] = [];
  return { progress, onProgress: (one: ImportProgress) => progress.push(one) };
}

describe("writing a shelf somebody already had", () => {
  it("never has two requests in flight at once", async () => {
    // **Sequential rather than `Promise.all`**, and this is the assertion that
    // sees it: nine hundred concurrent requests against one SQLite writer is
    // not a faster import. A `Promise.all` passes every count based check here
    // and fails this one.
    let inFlight = 0;
    let most = 0;
    const seen = collector();

    const outcome = await writeBooks(bodies(4), {
      post: async () => {
        inFlight += 1;
        most = Math.max(most, inFlight);
        await Promise.resolve();
        inFlight -= 1;
      },
      onProgress: seen.onProgress,
      stopped: () => false,
    });

    expect(most).toBe(1);
    expect(outcome).toEqual({ added: 4, failures: [], stopped: false });
    expect(seen.progress.at(-1)).toEqual({ done: 4, total: 4 });
  });

  it("keeps a refused book with its title and the status it got", async () => {
    // "Sixty could not be added" after a nine hundred book import is
    // unrecoverable: nothing says which sixty.
    const outcome = await writeBooks(bodies(3), {
      post: async (body) => {
        if (body.title === "Book 2") throw { status: 409 };
      },
      onProgress: () => {},
      stopped: () => false,
    });

    expect(outcome.added).toBe(2);
    expect(outcome.failures).toEqual([{ title: "Book 2", status: 409 }]);
  });

  it("records a request that never got a status at all", async () => {
    // A connection that never answered is not a 500, and reporting it as one
    // would tell a member the server refused a book it never saw.
    const outcome = await writeBooks(bodies(1), {
      post: async () => {
        throw new Error("the network went away");
      },
      onProgress: () => {},
      stopped: () => false,
    });

    expect(outcome.failures).toEqual([{ title: "Book 1", status: null }]);
  });

  it("asks between every request whether it was stopped", async () => {
    // A function rather than a value, and this is why: the answer changes
    // while the loop runs, and a boolean read once says `false` for ever.
    const post = vi.fn(async () => {});
    let done = 0;

    const outcome = await writeBooks(bodies(5), {
      post,
      onProgress: () => {
        done += 1;
      },
      stopped: () => done > 2,
    });

    expect(post.mock.calls.length).toBeLessThan(5);
    expect(outcome.stopped).toBe(true);
  });

  it("does nothing at all for a pick with nothing importable in it", async () => {
    const post = vi.fn(async () => {});

    const outcome = await writeBooks([], {
      post,
      onProgress: () => {},
      stopped: () => false,
    });

    expect(post).not.toHaveBeenCalled();
    expect(outcome).toEqual({ added: 0, failures: [], stopped: false });
  });
});

describe("what the server answered for one book", () => {
  it("reads a numeric status and refuses everything else", () => {
    expect(statusOf({ status: 409 })).toBe(409);
    expect(statusOf({ status: "409" })).toBeNull();
    expect(statusOf(new Error("no status"))).toBeNull();
    expect(statusOf(null)).toBeNull();
    expect(statusOf(undefined)).toBeNull();
  });
});
