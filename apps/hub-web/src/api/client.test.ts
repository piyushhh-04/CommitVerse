import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "./client";

const fetchMock = vi.fn<typeof fetch>();
let client: ApiClient;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

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
      expect.objectContaining({ credentials: "same-origin", cache: "no-store" }),
    );
    const requestOptions = fetchMock.mock.calls[1]?.[1];
    expect(new Headers(requestOptions?.headers).get("X-CSRF-Token")).toBe("csrf-from-session");
    expect(requestOptions?.credentials).toBe("same-origin");
    expect(client.hasCsrfToken).toBe(true);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("can make a truly anonymous request without sending or updating session state", async () => {
    client.setSessionIdentity({ userId: "user-1", generation: 3 });
    client.setCsrfToken("csrf-user-1");
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ entries: [] }), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": "csrf-from-anonymous-request",
          },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "X-CSRF-Token": "csrf-from-anonymous-mutation" },
        }),
      );

    await client.get("/repositories/public-1/tree", { credentials: "omit" });
    await client.post("/organizations", { name: "Current session" }, { credentials: "omit" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/repositories/public-1/tree",
      expect.objectContaining({ credentials: "omit", cache: "default" }),
    );
    expect(client.hasCsrfToken).toBe(true);
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("X-CSRF-Token")).toBe(null);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
    );
    await client.post("/organizations", { name: "Current session" });
    expect(new Headers(fetchMock.mock.calls[2]?.[1]?.headers).get("X-CSRF-Token")).toBe(
      "csrf-user-1",
    );
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

  it("preserves the current CSRF token after a profile update and sends it on the next mutation", async () => {
    client.setSessionIdentity({ userId: "user-1", generation: 1 });
    client.setCsrfToken("csrf-user-1");
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "user-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    await client.patch("/me", { display_name: "Updated User" });
    expect(client.hasCsrfToken).toBe(true);
    await client.post("/organizations", { name: "Example" });

    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("X-CSRF-Token")).toBe(
      "csrf-user-1",
    );
  });

  it("does not apply an old-session CSRF response to a different user's session", async () => {
    client.setSessionIdentity({ userId: "user-a", generation: 1 });
    client.setCsrfToken("csrf-user-a");
    const pendingResponse = deferred<Response>();
    fetchMock.mockImplementationOnce(() => pendingResponse.promise);

    const profileRequest = client.patch("/me", { display_name: "Stale User A" });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    client.setSessionIdentity({ userId: null, generation: 2 });
    client.setCsrfToken(null);
    client.setSessionIdentity({ userId: "user-b", generation: 3 });
    client.setCsrfToken("csrf-user-b");
    pendingResponse.resolve(
      new Response(JSON.stringify({ id: "user-a" }), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": "csrf-stale-user-a",
        },
      }),
    );

    await profileRequest;

    expect(client.hasCsrfToken).toBe(true);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await client.post("/organizations", { name: "User B organization" });
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("X-CSRF-Token")).toBe(
      "csrf-user-b",
    );
  });

  it("does not clear a same user's new-session CSRF token when an old profile response arrives", async () => {
    client.setSessionIdentity({ userId: "user-a", generation: 7 });
    client.setCsrfToken("csrf-old-session");
    const pendingResponse = deferred<Response>();
    fetchMock.mockImplementationOnce(() => pendingResponse.promise);

    const profileRequest = client.patch("/me", { display_name: "Old session profile" });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    client.setSessionIdentity({ userId: null, generation: 8 });
    client.setCsrfToken(null);
    client.setSessionIdentity({ userId: "user-a", generation: 9 });
    client.setCsrfToken("csrf-new-session");
    pendingResponse.resolve(
      new Response(JSON.stringify({ id: "user-a" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await profileRequest;

    expect(client.hasCsrfToken).toBe(true);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await client.post("/organizations", { name: "New session organization" });
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("X-CSRF-Token")).toBe(
      "csrf-new-session",
    );
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
