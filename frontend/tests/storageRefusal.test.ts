/** Tests for tests/storageRefusal.ts. */

import { expect, it } from "vitest";

import { whileStorageRefuses } from "./storageRefusal";

it("holds the refusal until an async body has finished", async () => {
  // The arms that use it reach storage before their body's first await, so
  // they pass with a refusal that ends there. This one reads after it.
  localStorage.setItem("probe", "kept");

  await whileStorageRefuses("getItem", async () => {
    await Promise.resolve();
    expect(() => localStorage.getItem("probe")).toThrow("refused");
  });

  expect(localStorage.getItem("probe")).toBe("kept");
});
