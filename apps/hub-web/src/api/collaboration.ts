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

export async function listPullRequests(
  repositoryId: string,
  state: "open" | "closed" | "merged" | "all" = "open",
) {
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
    {
      title: string;
      body: string | null;
      source_branch: string;
      target_branch: string;
      draft: boolean;
    }
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

export interface Execution {
  id: string;
  workflow_id: string | null;
  trigger_type: string;
  commit_id: string;
  status:
    | "pending"
    | "scheduled"
    | "starting"
    | "running"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "timed_out";
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
  logs?: Array<{ sequence: number; stream: string; content: string; created_at: string }>;
  artifacts?: Array<{
    id: string;
    name: string;
    storage_path: string;
    size_bytes: number;
    created_at: string;
  }>;
}

export async function listExecutions(repositoryId: string) {
  return apiClient.get<Execution[]>(
    `${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/executions`,
  );
}

export async function getExecution(repositoryId: string, executionId: string) {
  return apiClient.get<Execution>(
    `${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/executions/${encodeURIComponent(executionId)}`,
  );
}

export async function cancelExecution(repositoryId: string, executionId: string) {
  return apiClient.post<Execution>(
    `${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/executions/${encodeURIComponent(executionId)}/cancel`,
  );
}

export interface AITask {
  id: string;
  kind: string;
  status: string;
  provider: string;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown> | null;
}

export async function createAITask(
  repositoryId: string,
  kind: string,
  query: string,
  provider: "deterministic" | "ollama" = "deterministic",
) {
  return apiClient.post<
    AITask,
    { kind: string; query: string; provider: "deterministic" | "ollama" }
  >(`${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/ai/tasks`, {
    kind,
    query,
    provider,
  });
}

export interface ReviewComment {
  id: string;
  review_id: string;
  author_user_id: string;
  path: string;
  line: number | null;
  body: string;
  created_at: string;
  updated_at: string;
}

export async function listReviewComments(repositoryId: string, pullRequestId: string) {
  return apiClient.get<ReviewComment[]>(
    `${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/pull-requests/${encodeURIComponent(pullRequestId)}/review-comments`,
  );
}

export interface IndexStatus {
  repository_id: string;
  indexed_files: number;
  python_files: number;
  total_text_bytes: number;
}

export async function getIndexStatus(repositoryId: string) {
  return apiClient.get<IndexStatus>(
    `${API_BASE_PATH}/repositories/${encodeURIComponent(repositoryId)}/index/status`,
  );
}
