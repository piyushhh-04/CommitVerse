import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import {
  getRepositoryBlob,
  getRepositoryCommit,
  getRepositoryCommits,
  getRepositoryDiff,
  getRepositoryTree,
} from "./browse";

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  apiClient.setCsrfToken(null);
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  apiClient.setCsrfToken(null);
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("repository browse API", () => {
  it("encodes repository paths and tree queries", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          repository_id: "repo/1",
          commit_id: "a".repeat(40),
          path: "docs",
          entries: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await getRepositoryTree("repo/1", "docs/spec notes");
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/v1/repositories/repo%2F1/tree?path=docs%2Fspec%20notes",
    );
  });

  it("loads blobs and commit history through the centralized client", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ repository_id: "repo-1", commit_id: "c", path: "README.md" }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ repository_id: "repo-1", commits: [], limit: 50, truncated: false }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ repository_id: "repo-1", object_id: "c".repeat(40) }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ repository_id: "repo-1", files: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    await getRepositoryBlob("repo-1", "README.md");
    await getRepositoryCommits("repo-1");
    await getRepositoryCommit("repo-1", "c".repeat(40), { ref: "refs/heads/main" });
    await getRepositoryDiff("repo-1", "c".repeat(40), { ref: "refs/heads/main" });
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      "/repositories/repo-1/blob?path=README.md",
    );
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("/repositories/repo-1/commits?limit=50");
    expect(String(fetchMock.mock.calls[2]?.[0])).toContain(
      "/repositories/repo-1/commits/" + "c".repeat(40) + "?ref=refs%2Fheads%2Fmain",
    );
    expect(String(fetchMock.mock.calls[3]?.[0])).toContain("/diff?ref=refs%2Fheads%2Fmain");
  });
});
