import { defineConfig } from "orval";

/**
 * Generates the typed API client and its React Query hooks from the backend's
 * OpenAPI schema.
 *
 * Run `bun run api:generate`, which dumps `openapi.json` from FastAPI first.
 * The output is committed, so a fresh clone can typecheck, test and build
 * without a Python toolchain, and CI can diff the regenerated result to catch
 * a client that has fallen behind the API.
 *
 * Nothing outside a page's own `hooks.ts` should import from the generated
 * directory. That indirection is what stops a regeneration rippling through
 * every component.
 */
export default defineConfig({
  endpaper: {
    input: {
      target: "./openapi.json",
    },
    output: {
      // One directory per OpenAPI tag (books, auth, loans, …), which maps
      // cleanly onto the pages that consume them.
      mode: "tags-split",
      target: "./src/api/generated/endpoints",
      schemas: "./src/api/generated/model",
      client: "react-query",
      httpClient: "fetch",
      // Wipe the directory each run so a deleted endpoint's hook does not
      // linger and keep compiling.
      clean: true,
      indexFiles: true,
      override: {
        mutator: {
          path: "./src/api/mutator.ts",
          name: "customFetch",
        },
        fetch: {
          // Return the parsed body, not orval's `{ data, status, headers }`
          // envelope. The envelope is what its *built-in* fetch client
          // returns; our mutator returns the body and throws on any non-2xx,
          // so leaving this on would have every generated type describe a
          // shape the code never actually produces.
          includeHttpResponseReturnType: false,
        },
        // NOTE: do not add a top-level `query` block here. Setting one applies
        // to *every* operation, including POST/PUT/PATCH/DELETE, which orval
        // then generates as useQuery instead of useMutation. That is not a
        // cosmetic difference: a query runs on mount and on retry, so
        // `useDeleteBook(id)` would delete the book as soon as a component
        // rendered. Scope query options to the specific operation instead.
        operations: {
          // The two listings that page through a long list. Everything else
          // fetches one page and stops.
          //
          // Keyed by the raw operationId from the schema (snake_case, set by
          // the backend's custom_operation_id), not by the camelised hook name.
          //
          // **The public catalogue is here because it was written without it
          // and was wrong.** A plain query returns one page, so "Show more"
          // replaced the results instead of adding to them, and during the
          // second page's fetch `total` was 0, which took the button out of the
          // DOM under a reader who had just pressed it and dropped their focus
          // to `body`. The signed in grid had solved that a release earlier and
          // its own comment names the failure; the fix is to use the same
          // machinery rather than to hand roll a second answer.
          list_books: {
            query: {
              useInfinite: true,
              useInfiniteQueryParam: "page",
            },
          },
          list_public_books: {
            query: {
              useInfinite: true,
              useInfiniteQueryParam: "page",
            },
          },
        },
      },
    },
    hooks: {
      // Format the generated output so it does not fight the repo's style and
      // produce noisy diffs.
      afterAllFilesWrite: "bunx prettier --write",
    },
  },
});
