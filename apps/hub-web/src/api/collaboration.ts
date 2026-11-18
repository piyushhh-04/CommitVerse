import { apiClient, API_BASE_PATH } from "./client";

export interface RepositoryIssue {
  id: string;
  number: number;
  title: string;
  body: string | null;
  state: "open" | "closed";
  author_user_id: string;
  assignee_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RepositoryIssueList {
  items: RepositoryIssue[];
  total: number;
}

export interface PullRequest {
  id: string;
  number: number;
  title: string;
  body: string | null;
  source_branch: string;
  target_branch: string;
  state: "open" | "closed" | "merged";
  author_user_id: string;
  merged_at: string | null;
  merged_by_user_id: string | null;
  merge_commit_id: string | null;
  created_at: string;
  updated_at: string;
}

export async function listIssues(repositoryId: string, state: "open" | "closed" | "all" = "open") {
  return apiClient.get<RepositoryIssueList>(
    `${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/issues?state=${state}&limit=100`,
  );
}

export async function createIssue(repositoryId: string, title: string, body: string | null) {
  return apiClient.post<RepositoryIssue, { title: string; body: string | null }>(
    `${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/issues`,
    { title, body },
  );
}

export async function closeIssue(repositoryId: string, issueId: string) {
  return apiClient.patch<RepositoryIssue, { state: "closed" }>(
    `${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/issues/${encodeURIComponent(issueId)}`,
    { state: "closed" },
  );
}

export async function listPullRequests(repositoryId: string, state: "open" | "closed" | "merged" | "all" = "open") {
  return apiClient.get<PullRequest[]>(
    `${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/pull-requests?state=${state}`,
  );
}

export async function createPullRequest(
  repositoryId: string,
  title: string,
  body: string | null,
  sourceBranch: string,
  targetBranch: string,
) {
  return apiClient.post<
    PullRequest,
    { title: string; body: string | null; source_branch: string; target_branch: string; draft: boolean }
  >(`${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/pull-requests`, {
    title,
    body,
    source_branch: sourceBranch,
    target_branch: targetBranch,
    draft: false,
  });
}

export async function mergePullRequest(repositoryId: string, pullRequestId: string) {
  return apiClient.post<PullRequest>(
    `${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/pull-requests/${encodeURIComponent(pullRequestId)}/merge`,
  );
}
