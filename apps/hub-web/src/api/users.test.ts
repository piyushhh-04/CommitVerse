import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { searchUsers } from "./users";

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  apiClient.setCsrfToken("csrf-test");
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  apiClient.setCsrfToken(null);
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("user directory API", () => {
  it("encodes bounded profile search queries", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ items: [], query: "Dev Team", limit: 20 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await searchUsers("Dev Team");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/users/search?query=Dev%20Team&limit=20");
  });
});
