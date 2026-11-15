import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "../api/client";
import { RepositoryBrowsePanel } from "./RepositoryBrowsePanel";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  apiClient.setCsrfToken(null);
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  apiClient.setCsrfToken(null);
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("RepositoryBrowsePanel", () => {
  it("navigates directories, renders text files, and shows history", async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/tree")) {
        return Promise.resolve(
          jsonResponse({
            repository_id: "repo-1",
            commit_id: "c".repeat(40),
            path: "",
            entries: [
              { name: "README.md", type: "blob", mode: "100644", object_id: "b".repeat(40) },
              { name: "docs", type: "tree", mode: "40000", object_id: "d".repeat(40) },
            ],
          }),
        );
      }
      if (url.endsWith("/refs")) {
        return Promise.resolve(
          jsonResponse({
            repository_id: "repo-1",
            refs: [
              {
                name: "main",
                ref: "refs/heads/main",
                object_id: "c".repeat(40),
                kind: "branch",
                current: true,
              },
              {
                name: "v1.0.0",
                ref: "refs/tags/v1.0.0",
                object_id: "c".repeat(40),
                kind: "tag",
                current: false,
              },
            ],
          }),
        );
      }
      if (url.includes("/tree?path=docs")) {
        return Promise.resolve(
          jsonResponse({
            repository_id: "repo-1",
            commit_id: "c".repeat(40),
            path: "docs",
            entries: [
              { name: "guide.txt", type: "blob", mode: "100644", object_id: "e".repeat(40) },
            ],
          }),
        );
      }
      if (url.includes("/blob?path=README.md")) {
        return Promise.resolve(
          jsonResponse({
            repository_id: "repo-1",
            commit_id: "c".repeat(40),
            path: "README.md",
            object_id: "b".repeat(40),
            size: 18,
            is_binary: false,
            content: "Hello CommitVerse\n",
          }),
        );
      }
      if (url.includes("/commits?limit=50")) {
        return Promise.resolve(
          jsonResponse({
            repository_id: "repo-1",
            limit: 50,
            truncated: false,
            commits: [
              {
                object_id: "c".repeat(40),
                parent_ids: [],
                author_name: "Developer",
                author_email: "developer@example.test",
                author_timestamp: 1_700_000_000,
                message: "Initial snapshot",
              },
            ],
          }),
        );
      }
      if (url.includes("/commits/")) {
        if (url.includes("/diff")) {
          return Promise.resolve(
            jsonResponse({
              repository_id: "repo-1",
              base_commit_id: null,
              head_commit_id: "c".repeat(40),
              files: [],
            }),
          );
        }
        return Promise.resolve(
          jsonResponse({
            repository_id: "repo-1",
            object_id: "c".repeat(40),
            tree_id: "t".repeat(40),
            parent_ids: [],
            author_name: "Developer",
            author_email: "developer@example.test",
            author_timestamp: 1_700_000_000,
            author_timezone_offset: 0,
            committer_name: "Developer",
            committer_email: "developer@example.test",
            committer_timestamp: 1_700_000_000,
            committer_timezone_offset: 0,
            message: "Initial browser snapshot\nDetails",
          }),
        );
      }
      throw new Error(`Unexpected API request: ${url}`);
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <RepositoryBrowsePanel repositoryId="repo-1" />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("button", { name: /README\.md/ })).toBeInTheDocument();
    expect(await screen.findByRole("combobox", { name: "Ref" })).toHaveValue("HEAD");
    expect(screen.getByText("Initial snapshot")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Initial snapshot/ }));
    expect(await screen.findByText("Initial browser snapshot")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /README\.md/ }));
    expect(await screen.findByText("Hello CommitVerse")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /docs/ }));
    expect(await screen.findByRole("button", { name: /guide\.txt/ })).toBeInTheDocument();
  });
});
