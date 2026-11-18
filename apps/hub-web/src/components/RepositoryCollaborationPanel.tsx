import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import {
  closeIssue,
  createIssue,
  createPullRequest,
  listIssues,
  listPullRequests,
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
  const prefix = protectedQueryKey(userId, "repositories", repositoryId, "collaboration");

  const issuesQuery = useQuery({
    queryKey: [...prefix, "issues", "open"],
    queryFn: () => listIssues(repositoryId, "open"),
  });
  const pullRequestsQuery = useQuery({
    queryKey: [...prefix, "pull-requests", "open"],
    queryFn: () => listPullRequests(repositoryId, "open"),
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

  function submitIssue(event: FormEvent) {
    event.preventDefault();
    issueMutation.mutate();
  }

  function submitPullRequest(event: FormEvent) {
    event.preventDefault();
    prMutation.mutate();
  }

  return (
    <section className="repository-form-section" aria-labelledby="repository-collaboration-title">
      <div className="repository-section-heading">
        <p className="eyebrow">Collaboration</p>
        <h2 id="repository-collaboration-title">Issues and pull requests</h2>
        <p>Create persistent engineering work and propose real branch merges.</p>
      </div>

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
            </li>
          ))}
        </ul>
      ) : <p className="repository-state">No open pull requests.</p>}
    </section>
  );
}
