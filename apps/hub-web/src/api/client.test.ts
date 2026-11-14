import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "./client";

const fetchMock = vi.fn<typeof fetch>();
let client: ApiClient;

beforeEach(() => {
  client = new ApiClient();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("ApiClient", () => {
  it("uses the same-origin API, captures CSRF in memory, and sends it with mutations", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "user-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json", "X-CSRF-Token": "csrf-from-session" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    await client.get<{ id: string }>("/me");
    await client.post<{ status: string }>("/auth/logout");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/me",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    const requestOptions = fetchMock.mock.calls[1]?.[1];
    expect(new Headers(requestOptions?.headers).get("X-CSRF-Token")).toBe("csrf-from-session");
    expect(requestOptions?.credentials).toBe("same-origin");
    expect(client.hasCsrfToken).toBe(true);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("preserves backend status, error details, and request identifiers", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: {
            code: "validation_error",
            message: "Invalid input.",
            details: [{ field: "email", code: "invalid", message: "Enter a valid email." }],
          },
          request_id: "request-123",
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      ),
    );

    const request = client.post("/auth/register", {
      email: "not-an-email",
      password: "example",
      username: "user",
    });

    await expect(request).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      code: "validation_error",
      requestId: "request-123",
      details: [{ field: "email", code: "invalid", message: "Enter a valid email." }],
    });
  });

  it("sends registration as JSON with the current CSRF token", async () => {
    client.setCsrfToken("csrf-registration");
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "user-2",
          email: "new@example.test",
          username: "new-user",
          display_name: "New User",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await client.post("/auth/register", {
      email: "new@example.test",
      password: "example-password",
      username: "new-user",
    });

    const [url, options] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/auth/register");
    expect(options?.method).toBe("POST");
    expect(new Headers(options?.headers).get("Content-Type")).toBe("application/json");
    expect(new Headers(options?.headers).get("X-CSRF-Token")).toBe("csrf-registration");
    expect(JSON.parse(String(options?.body))).toEqual({
      email: "new@example.test",
      password: "example-password",
      username: "new-user",
    });
  });

  it("returns undefined for a successful empty JSON response", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 200 }));

    await expect(client.get("/health")).resolves.toBeUndefined();
  });

  it("supports DELETE with a CSRF token and a 204 empty response", async () => {
    client.setCsrfToken("csrf-delete");
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(client.delete("/organizations/org-1")).resolves.toBeUndefined();

    const [url, options] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/v1/organizations/org-1");
    expect(options?.method).toBe("DELETE");
    expect(options?.body).toBeUndefined();
    expect(new Headers(options?.headers).get("X-CSRF-Token")).toBe("csrf-delete");
    expect(new Headers(options?.headers).has("Content-Type")).toBe(false);
  });

  it("clears a stale CSRF token when successful session recovery omits the token header", async () => {
    client.setCsrfToken("stale-token");
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "user-1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await client.get("/me");

    expect(client.hasCsrfToken).toBe(false);
  });

  it("represents network failures without disguising them as HTTP responses", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("connection refused"));

    await expect(client.get("/me")).rejects.toMatchObject({
      name: "ApiError",
      status: null,
      code: "network_error",
    } satisfies Partial<ApiError>);
  });

  it("rejects absolute URLs to keep API calls same-origin", async () => {
    await expect(client.get("https://example.test/api/v1/me")).rejects.toThrow(TypeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
