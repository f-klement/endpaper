/**
 * @vitest-environment node
 *
 * The pure rules under `scripts/notices.ts`: which package a bundled module
 * belongs to, and which built files nothing accounts for. The collection
 * itself reads a real build and runs in the image's frontend stage.
 */
import { describe, expect, it } from "vitest";

import {
  isLicenceFile,
  licenceTexts,
  ownerOfVirtual,
  packageOf,
  unaccounted,
  workboxPackages,
} from "../../scripts/notices";

const ROOT = "/app/frontend";

describe("the package a bundled module belongs to", () => {
  it("is the directory under node_modules, relative to the frontend", () => {
    expect(packageOf(`${ROOT}/node_modules/react/index.js`, ROOT)).toBe(
      "node_modules/react",
    );
  });

  it("takes two segments for a scoped name", () => {
    expect(
      packageOf(`${ROOT}/node_modules/@zxing/library/esm/index.js`, ROOT),
    ).toBe("node_modules/@zxing/library");
  });

  it("is the innermost copy when a package nests another", () => {
    expect(
      packageOf(`${ROOT}/node_modules/a/node_modules/b/x.js?url`, ROOT),
    ).toBe("node_modules/a/node_modules/b");
  });

  it("is nothing for the application's own code", () => {
    expect(packageOf(`${ROOT}/src/main.tsx`, ROOT)).toBeNull();
  });
});

describe("the owner of a virtual module", () => {
  it("is Vite for its preload helper and Rolldown for its runtime", () => {
    expect(ownerOfVirtual("\0vite/preload-helper.js")).toBe("vite");
    expect(ownerOfVirtual("\0rolldown/runtime.js")).toBe("rolldown");
  });

  it("is unknown for an id nobody has read, so the collection fails", () => {
    expect(ownerOfVirtual("\0some-plugin/helper")).toBeNull();
  });
});

it("names each Workbox package a built worker carries, once", () => {
  const source =
    'self["workbox:core:7.4.0"]&&_();self["workbox:core:7.4.0"];' +
    "self['workbox:precaching:7.4.0']";

  expect(workboxPackages(source)).toEqual([
    "workbox-core",
    "workbox-precaching",
  ]);
});

it("reads LICENSE, LICENCE.md, COPYING, COPYRIGHT, UNLICENSE and NOTICE as licence files and not a README or AUTHORS", () => {
  expect(
    [
      "LICENSE",
      "LICENCE.md",
      "license-mit",
      "COPYING",
      "COPYRIGHT",
      "UNLICENSE",
      "NOTICE",
      "README.md",
      "AUTHORS",
    ].map(isLicenceFile),
  ).toEqual([true, true, true, true, true, true, true, false, false]);
});

it("takes no empty or whitespace only file as licence text", () => {
  const files: Record<string, string> = {
    LICENSE: "",
    NOTICE: "  \n\t",
    "COPYING.md": "Apache",
    "README.md": "readme",
  };

  expect(licenceTexts(Object.keys(files), (name) => files[name] ?? "")).toEqual(
    [{ file: "COPYING.md", text: "Apache" }],
  );
});

describe("the built files nothing accounts for", () => {
  it("are none when each came from the bundle, from public or from the PWA plugin", () => {
    expect(
      unaccounted(
        [
          "assets/index-a.js",
          "icons/x.png",
          "sw.js",
          "workbox-0d3611f4.js",
          "registerSW.js",
        ],
        new Set(["assets/index-a.js"]),
        new Set(["icons/x.png"]),
      ),
    ).toEqual([]);
  });

  it("name a file no rule knows", () => {
    expect(unaccounted(["assets/injected.js"], new Set(), new Set())).toEqual([
      "assets/injected.js",
    ]);
  });
});
