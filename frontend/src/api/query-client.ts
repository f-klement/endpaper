import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./mutator";

/** Statuses where retrying cannot help: the request itself is the problem. */
const NON_RETRYABLE = new Set([400, 401, 403, 404, 409, 413, 422]);

const MAX_RETRIES = 2;

/**
 * The shared cache and its defaults.
 *
 * Built by a factory rather than exported as a singleton so each test gets a
 * clean cache. A module-level client would carry one test's data into the
 * next and make failures depend on ordering.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A family bookshelf changes slowly. Half a minute of staleness saves
        // a refetch every time someone navigates back to the grid.
        staleTime: 30_000,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && NON_RETRYABLE.has(error.status)) {
            // Retrying a 404 just makes the user wait longer to be told the
            // same thing, and retrying a 401 fights the redirect to login.
            return false;
          }
          return failureCount < MAX_RETRIES;
        },
        refetchOnWindowFocus: false,
      },
      mutations: {
        // Never retry a mutation: a request that may already have created a
        // book should not be sent again on its own.
        retry: false,
      },
    },
  });
}
