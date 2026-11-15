import { ApiError, apiClient } from "./client";

export interface RepositoryTreeEntry {
  name: string;
  type: "tree" | "blob";
  mode: string;
  object_id: string;
}

export interface RepositoryTree {
  repository_id: string;
  commit_id: string | null;
  path: string;
  entries: RepositoryTreeEntry[];
}

export interface RepositoryRef {
  name: string;
  ref: string;
  object_id: string | null;
  kind: "branch" | "tag";
  current: boolean;
}

export interface RepositoryRefList {
  repository_id: string;
  refs: RepositoryRef[];
}

export interface RepositoryBlob {
  repository_id: string;
  commit_id: string;
  path: string;
  object_id: string;
  size: number;
  is_binary: boolean;
  content: string | null;
}

export interface RepositoryCommit {
  object_id: string;
  parent_ids: string[];
  author_name: string;
  author_email: string;
  author_timestamp: number;
  message: string;
}

export interface RepositoryCommitList {
  repository_id: string;
  commits: RepositoryCommit[];
  limit: number;
  truncated: boolean;
}

export interface RepositoryCommitDetail extends RepositoryCommit {
  repository_id: string;
  tree_id: string;
  author_timezone_offset: number;
  committer_name: string;
  committer_email: string;
  committer_timestamp: number;
  committer_timezone_offset: number;
}

export interface RepositoryDiffFile {
  path: string;
  status: "added" | "deleted" | "modified";
  old_object_id: string | null;
  new_object_id: string | null;
  is_binary: boolean;
  patch: string | null;
}

export interface RepositoryDiff {
  repository_id: string;
  base_commit_id: string | null;
  head_commit_id: string;
  files: RepositoryDiffFile[];
}

function requireResponse<T>(response: T | undefined): T {
  if (response !== undefined) return response;
  throw new ApiError("The Hub API returned an empty repository browse response.", {
    status: 200,
    code: "invalid_response",
    requestId: null,
  });
}

function browsePath(repositoryId: string, suffix: string): string {
  return `/repositories/${encodeURIComponent(repositoryId)}/${suffix}`;
}

export async function getRepositoryTree(
  repositoryId: string,
  path = "",
  options: { signal?: AbortSignal; ref?: string } = {},
): Promise<RepositoryTree> {
  const params: string[] = [];
  if (path) params.push(`path=${encodeURIComponent(path)}`);
  if (options.ref && options.ref !== "HEAD") params.push(`ref=${encodeURIComponent(options.ref)}`);
  const query = params.length ? `?${params.join("&")}` : "";
  return requireResponse(
    await apiClient.get<RepositoryTree>(browsePath(repositoryId, `tree${query}`), options),
  );
}

export async function getRepositoryBlob(
  repositoryId: string,
  path: string,
  options: { signal?: AbortSignal; ref?: string } = {},
): Promise<RepositoryBlob> {
  const params = [`path=${encodeURIComponent(path)}`];
  if (options.ref && options.ref !== "HEAD") params.push(`ref=${encodeURIComponent(options.ref)}`);
  return requireResponse(
    await apiClient.get<RepositoryBlob>(
      `${browsePath(repositoryId, "blob")}?${params.join("&")}`,
      options,
    ),
  );
}

export async function getRepositoryCommits(
  repositoryId: string,
  options: { signal?: AbortSignal; ref?: string } = {},
): Promise<RepositoryCommitList> {
  const params = ["limit=50"];
  if (options.ref && options.ref !== "HEAD") params.push(`ref=${encodeURIComponent(options.ref)}`);
  return requireResponse(
    await apiClient.get<RepositoryCommitList>(
      `${browsePath(repositoryId, "commits")}?${params.join("&")}`,
      options,
    ),
  );
}

export async function getRepositoryCommit(
  repositoryId: string,
  commitId: string,
  options: { signal?: AbortSignal; ref?: string } = {},
): Promise<RepositoryCommitDetail> {
  const params =
    options.ref && options.ref !== "HEAD" ? `?ref=${encodeURIComponent(options.ref)}` : "";
  return requireResponse(
    await apiClient.get<RepositoryCommitDetail>(
      `${browsePath(repositoryId, `commits/${encodeURIComponent(commitId)}`)}${params}`,
      options,
    ),
  );
}

export async function getRepositoryDiff(
  repositoryId: string,
  commitId: string,
  options: { signal?: AbortSignal; ref?: string } = {},
): Promise<RepositoryDiff> {
  const params =
    options.ref && options.ref !== "HEAD" ? `?ref=${encodeURIComponent(options.ref)}` : "";
  return requireResponse(
    await apiClient.get<RepositoryDiff>(
      `${browsePath(repositoryId, `commits/${encodeURIComponent(commitId)}/diff`)}${params}`,
      options,
    ),
  );
}

export async function getRepositoryRefs(
  repositoryId: string,
  options: { signal?: AbortSignal } = {},
): Promise<RepositoryRefList> {
  return requireResponse(
    await apiClient.get<RepositoryRefList>(browsePath(repositoryId, "refs"), options),
  );
}
