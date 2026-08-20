/**
 * Shared test infrastructure.
 *
 * Tests drive the real generated hooks and the real mutator, and stub only the
 * network boundary. That keeps them honest about query keys, cache
 * invalidation and request shapes, all of which a mocked API module would
 * hide, while still never touching the network.
 *
 * Support code, so it mirrors nothing: the mirrored files are the `*.test.tsx`
 * ones.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  render,
  renderHook,
  type RenderHookResult,
  type RenderOptions,
  type RenderResult,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, vi, type Mock } from "vitest";
import type { ReactElement, ReactNode } from "react";

import { Locale } from "../src/api/generated/model";
import { LocaleProvider } from "../src/i18n";
import { PATTERNS } from "../src/theme/patterns";
import { ThemeProvider } from "../src/theme";

// ── Network stubbing ──────────────────────────────────────────────────────────

export interface StubResponse {
  status?: number;
  /** Parsed JSON body. Omit for a 204. */
  body?: unknown;
  headers?: Record<string, string>;
  /**
   * The Response `type`. Only worth setting for `"opaqueredirect"`, which is
   * what the browser hands back when a request under `redirect: "manual"` is
   * redirected. The mutator treats that as the reverse proxy signing us out.
   */
  type?: ResponseType;
}

/** Matched against the request URL; the first match wins. */
export type RouteMatcher = string | RegExp;

interface Handler {
  matcher: RouteMatcher;
  method?: string;
  respond: StubResponse | ((url: string, init: RequestInit) => StubResponse);
}

export interface MockApi {
  /** Register a handler. Later registrations take precedence over earlier ones. */
  on: (
    matcher: RouteMatcher,
    respond: Handler["respond"],
    method?: string,
  ) => MockApi;
  /** The underlying fetch mock, for asserting on calls. */
  fetch: Mock;
  /** Every request made so far, in order. */
  calls: { url: string; method: string; body: unknown }[];
  /** The most recent request matching a matcher, or undefined. */
  lastCall: (
    matcher: RouteMatcher,
    method?: string,
  ) => { url: string; body: unknown } | undefined;
}

function matches(matcher: RouteMatcher, url: string): boolean {
  return typeof matcher === "string"
    ? url.includes(matcher)
    : matcher.test(url);
}

/**
 * Install a stubbed `fetch` with per-route handlers.
 *
 * Handlers are consulted newest-first, so a test can override a default set up
 * by its own `beforeEach`.
 */
export function mockApi(): MockApi {
  const handlers: Handler[] = [];
  const calls: MockApi["calls"] = [];

  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      const method = (init.method ?? "GET").toUpperCase();

      let body: unknown = undefined;
      if (typeof init.body === "string") {
        try {
          body = JSON.parse(init.body);
        } catch {
          body = init.body;
        }
      } else if (init.body instanceof FormData) {
        body = init.body;
      }
      calls.push({ url, method, body });

      const handler = [...handlers]
        .reverse()
        .find(
          (h) => matches(h.matcher, url) && (!h.method || h.method === method),
        );

      if (!handler) {
        throw new Error(
          `Unhandled request: ${method} ${url}. Stub it with mockApi().on()`,
        );
      }

      const stub =
        typeof handler.respond === "function"
          ? handler.respond(url, init)
          : handler.respond;
      const status = stub.status ?? 200;

      return {
        ok: status >= 200 && status < 300,
        status,
        type: stub.type ?? "basic",
        statusText: `Status ${status}`,
        headers: new Headers({
          "content-type": "application/json",
          ...stub.headers,
        }),
        json: () => Promise.resolve(stub.body),
        blob: () =>
          Promise.resolve(new Blob([JSON.stringify(stub.body ?? "")])),
      } as unknown as Response;
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  const api: MockApi = {
    fetch: fetchMock,
    calls,
    on(matcher, respond, method) {
      handlers.push({ matcher, respond, method: method?.toUpperCase() });
      return api;
    },
    lastCall(matcher, method) {
      const wanted = method?.toUpperCase();
      return [...calls]
        .reverse()
        .find(
          (call) =>
            matches(matcher, call.url) && (!wanted || call.method === wanted),
        );
    },
  };
  return api;
}

// ── Rendering ─────────────────────────────────────────────────────────────────

/**
 * A client with retries and caching off.
 *
 * Retries would make a test asserting an error state wait through two extra
 * attempts; a shared cache would leak one test's data into the next.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

interface ProvidersOptions extends Omit<RenderOptions, "wrapper"> {
  /** Initial history entry, for pages that read route params. */
  route?: string;
  queryClient?: QueryClient;
  /**
   * The language to render in. Defaults to English, and is *forced* rather
   * than detected: left to resolve normally it would follow the machine's
   * browser language, so the same assertions would pass here and fail on a
   * German laptop.
   */
  locale?: Locale;
}

export function renderWithProviders(
  ui: ReactElement,
  {
    route = "/",
    queryClient,
    locale = Locale.en,
    ...options
  }: ProvidersOptions = {},
): RenderResult & { queryClient: QueryClient } {
  const client = queryClient ?? createTestQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <ThemeProvider initialPreference="light" initialPattern={PATTERNS[0]}>
          <LocaleProvider initialLocale={locale}>
            <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
          </LocaleProvider>
        </ThemeProvider>
      </QueryClientProvider>
    );
  }

  return {
    ...render(ui, { wrapper: Wrapper, ...options }),
    queryClient: client,
  };
}

/** Put a signed-in account in localStorage, as the app expects to find it. */
export function signIn(user: {
  id: number;
  username: string;
  is_admin: boolean;
}): void {
  localStorage.setItem("token", "test-token");
  localStorage.setItem("user", JSON.stringify(user));
}

/** Assert a request was made, and return its parsed body. */
export function expectRequest(
  api: MockApi,
  matcher: RouteMatcher,
  method?: string,
): { url: string; body: unknown } {
  const call = api.lastCall(matcher, method);
  expect(
    call,
    `expected a ${method ?? "matching"} request to ${String(matcher)}`,
  ).toBeDefined();
  return call!;
}

interface LocalisedOptions extends Omit<RenderOptions, "wrapper"> {
  locale?: Locale;
  route?: string;
}

/**
 * Render a presentational component with only the context it needs.
 *
 * Dumb components take props and render text; they do not fetch. Giving them
 * a query client in a test would blur exactly the line the structure exists to
 * draw, so they get the locale (their text is translated) and a router (some
 * render a Link), and nothing else. Use `renderWithProviders` for a page.
 */
export function renderLocalised(
  ui: ReactElement,
  { locale = Locale.en, route = "/", ...options }: LocalisedOptions = {},
): RenderResult {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ThemeProvider initialPreference="light" initialPattern={PATTERNS[0]}>
        <LocaleProvider initialLocale={locale}>
          <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
        </LocaleProvider>
      </ThemeProvider>
    );
  }
  return render(ui, { wrapper: Wrapper, ...options });
}

/**
 * Render a hook with the context a page hook expects.
 *
 * A query client and a router: several page hooks read the URL (Home seeds its
 * ownership filter from `?ownership=`), so a bare QueryClientProvider is no
 * longer enough to render one.
 */
export function renderHookWithProviders<TResult>(
  hook: () => TResult,
  {
    route = "/",
    queryClient,
  }: { route?: string; queryClient?: QueryClient } = {},
): RenderHookResult<TResult, unknown> & { queryClient: QueryClient } {
  const client = queryClient ?? createTestQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <ThemeProvider initialPreference="light" initialPattern={PATTERNS[0]}>
          <LocaleProvider initialLocale={Locale.en}>
            <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
          </LocaleProvider>
        </ThemeProvider>
      </QueryClientProvider>
    );
  }

  return { ...renderHook(hook, { wrapper: Wrapper }), queryClient: client };
}
