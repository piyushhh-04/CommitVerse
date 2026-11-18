import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import {
  closeIssue,
  createIssue,
  createPullRequest,
  listIssues,
  listPullRequests,
  mergePullRequest,
  cancelExecution,
  createAITask,
  listExecutions,
  getIndexStatus,
  type AITask,
} from "../api/collaboration";
import { protectedQueryKey } from "../app/protectedQueryCache";

interface Props {
  repositoryId: string;
  userId: string;
}

export function RepositoryCollaborationPanel({ repositoryId, userId }: Props) {
  const queryClient = useQueryClient();
  const [issueTitle, setIssueTitle] = useState("");
  const [issueBody, setIssueBody] = useState("");
  const [prTitle, setPrTitle] = useState("");
  const [sourceBranch, setSourceBranch] = useState("");
  const [targetBranch, setTargetBranch] = useState("main");
  const [aiQuery, setAiQuery] = useState("");
  const [aiResult, setAiResult] = useState<AITask | null>(null);
  const prefix = protectedQueryKey(userId, "repositories", repositoryId, "collaboration");

  const issuesQuery = useQuery({
    queryKey: [...prefix, "issues", "open"],
    queryFn: () => listIssues(repositoryId, "open"),
  });
  const pullRequestsQuery = useQuery({
    queryKey: [...prefix, "pull-requests", "open"],
    queryFn: () => listPullRequests(repositoryId, "open"),
  });
  const executionsQuery = useQuery({
    queryKey: [...prefix, "executions"],
    queryFn: () => listExecutions(repositoryId),
    refetchInterval: 3000,
  });
  const indexQuery = useQuery({
    queryKey: [...prefix, "index-status"],
    queryFn: () => getIndexStatus(repositoryId),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: prefix });
  };
  const issueMutation = useMutation({
    mutationKey: [...prefix, "issue-create"],
    mutationFn: () => createIssue(repositoryId, issueTitle, issueBody || null),
    onSuccess: () => {
      setIssueTitle("");
      setIssueBody("");
      refresh();
    },
  });
  const closeMutation = useMutation({
    mutationKey: [...prefix, "issue-close"],
    mutationFn: (issueId: string) => closeIssue(repositoryId, issueId),
    onSuccess: refresh,
  });
  const prMutation = useMutation({
    mutationKey: [...prefix, "pull-request-create"],
    mutationFn: () => createPullRequest(repositoryId, prTitle, null, sourceBranch, targetBranch),
    onSuccess: () => {
      setPrTitle("");
      setSourceBranch("");
      refresh();
    },
  });
  const mergeMutation = useMutation({
    mutationKey: [...prefix, "pull-request-merge"],
    mutationFn: (pullRequestId: string) => mergePullRequest(repositoryId, pullRequestId),
    onSuccess: refresh,
  });
  const cancelExecutionMutation = useMutation({
    mutationKey: [...prefix, "execution-cancel"],
    mutationFn: (executionId: string) => cancelExecution(repositoryId, executionId),
    onSuccess: refresh,
  });
  const aiMutation = useMutation({
    mutationKey: [...prefix, "ai-task"],
    mutationFn: () => createAITask(repositoryId, "repository-query", aiQuery),
    onSuccess: (task) => {
      setAiResult(task ?? null);
    },
  });

  function submitIssue(event: FormEvent) {
    event.preventDefault();
    issueMutation.mutate();
  }

  function submitPullRequest(event: FormEvent) {
    event.preventDefault();
    prMutation.mutate();
  }

  function submitAI(event: FormEvent) {
    event.preventDefault();
    aiMutation.mutate();
  }

  return (
    <section className="repository-form-section" aria-labelledby="repository-collaboration-title">
      <div className="repository-section-heading">
        <p className="eyebrow">Collaboration</p>
        <h2 id="repository-collaboration-title">Issues and pull requests</h2>
        <p>Create persistent engineering work and propose real branch merges.</p>
      </div>
      {indexQuery.data ? (
        <p className="repository-state">
          Repository index: {indexQuery.data.indexed_files} text files · {indexQuery.data.python_files} Python files · {indexQuery.data.total_text_bytes} bytes
        </p>
      ) : indexQuery.isError ? (
        <p className="repository-state-error" role="alert">Repository index status could not be loaded.</p>
      ) : (
        <p className="repository-state" role="status">Loading repository index status…</p>
      )}

      <form className="repository-form" onSubmit={submitIssue}>
        <label>
          Issue title
          <input value={issueTitle} onChange={(event) => setIssueTitle(event.target.value)} required />
        </label>
        <label>
          Description
          <textarea value={issueBody} onChange={(event) => setIssueBody(event.target.value)} />
        </label>
        <button className="repository-primary-action" type="submit" disabled={issueMutation.isPending || !issueTitle.trim()}>
          {issueMutation.isPending ? "Creating…" : "Create issue"}
        </button>
      </form>

      {issuesQuery.data?.items.length ? (
        <ul className="repository-list" aria-label="Open issues">
          {issuesQuery.data.items.map((issue) => (
            <li key={issue.id}>
              <strong>#{issue.number} {issue.title}</strong>
              {issue.body ? <p>{issue.body}</p> : null}
              <button type="button" onClick={() => closeMutation.mutate(issue.id)}>Close issue</button>
            </li>
          ))}
        </ul>
      ) : <p className="repository-state">No open issues.</p>}

      <form className="repository-form" onSubmit={submitPullRequest}>
        <label>
          Pull request title
          <input value={prTitle} onChange={(event) => setPrTitle(event.target.value)} required />
        </label>
        <label>
          Source branch
          <input value={sourceBranch} onChange={(event) => setSourceBranch(event.target.value)} required />
        </label>
        <label>
          Target branch
          <input value={targetBranch} onChange={(event) => setTargetBranch(event.target.value)} required />
        </label>
        <button className="repository-primary-action" type="submit" disabled={prMutation.isPending || !prTitle.trim() || !sourceBranch.trim()}>
          {prMutation.isPending ? "Creating…" : "Create pull request"}
        </button>
      </form>

      {pullRequestsQuery.data?.length ? (
        <ul className="repository-list" aria-label="Open pull requests">
          {pullRequestsQuery.data.map((pullRequest) => (
            <li key={pullRequest.id}>
              <strong>#{pullRequest.number} {pullRequest.title}</strong>
              <p>{pullRequest.source_branch} → {pullRequest.target_branch}</p>
              <button
                type="button"
                disabled={mergeMutation.isPending}
                onClick={() => mergeMutation.mutate(pullRequest.id)}
              >
                {mergeMutation.isPending ? "Merging…" : "Merge pull request"}
              </button>
            </li>
          ))}
        </ul>
      ) : <p className="repository-state">No open pull requests.</p>}
      <div className="repository-section-heading">
        <p className="eyebrow">CI execution</p>
        <h2>Workflow runs</h2>
      </div>
      {executionsQuery.data?.length ? (
        <ul className="repository-list" aria-label="Workflow executions">
          {executionsQuery.data.map((execution) => (
            <li key={execution.id}>
              <strong>{execution.status}</strong>
              <p>{execution.trigger_type} · {execution.commit_id.slice(0, 12)}</p>
              {execution.error_message ? <p>{execution.error_message}</p> : null}
              {["pending", "scheduled", "starting", "running"].includes(execution.status) ? (
                <button type="button" onClick={() => cancelExecutionMutation.mutate(execution.id)}>
                  Cancel run
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : <p className="repository-state">No workflow executions.</p>}
      <div className="repository-section-heading">
        <p className="eyebrow">Repository AI</p>
        <h2>Evidence-grounded query</h2>
      </div>
      <form className="repository-form" onSubmit={submitAI}>
        <label>
          Question
          <input value={aiQuery} onChange={(event) => setAiQuery(event.target.value)} required />
        </label>
        <button className="repository-primary-action" type="submit" disabled={aiMutation.isPending || !aiQuery.trim()}>
          {aiMutation.isPending ? "Analyzing…" : "Run local analysis"}
        </button>
      </form>
      {aiMutation.error ? (
        <p className="repository-state-error" role="alert">
          {aiMutation.error instanceof Error ? aiMutation.error.message : "AI analysis could not run."}
        </p>
      ) : null}
      {aiResult?.output_data ? (
        <pre className="repository-state" aria-label="AI analysis result">
          {typeof aiResult.output_data.summary === "string"
            ? aiResult.output_data.summary
            : JSON.stringify(aiResult.output_data, null, 2)}
        </pre>
      ) : null}
      {mergeMutation.error ? (
        <p className="repository-state-error" role="alert">
          {mergeMutation.error instanceof Error ? mergeMutation.error.message : "Merge could not be completed."}
        </p>
      ) : null}
    </section>
  );
}
