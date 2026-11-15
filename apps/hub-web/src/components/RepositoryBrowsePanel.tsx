import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import {
  getRepositoryBlob,
  getRepositoryCommits,
  getRepositoryCommit,
  getRepositoryDiff,
  getRepositoryRefs,
  getRepositoryTree,
  type RepositoryTreeEntry,
} from "../api/browse";

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError("Repository contents could not be loaded.", {
        status: null,
        code: "unexpected_error",
        requestId: null,
        cause: error,
      });
}

function formatCommitDate(timestamp: number): string {
  const value = new Date(timestamp * 1000);
  return Number.isNaN(value.getTime())
    ? "Unknown date"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(value);
}

export function RepositoryBrowsePanel({ repositoryId }: { repositoryId: string }) {
  const [path, setPath] = useState("");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [selectedRef, setSelectedRef] = useState("HEAD");
  const [selectedCommit, setSelectedCommit] = useState<string | null>(null);
  const refsQuery = useQuery({
    queryKey: ["repository-browse", repositoryId, "refs"],
    queryFn: ({ signal }) => getRepositoryRefs(repositoryId, { signal }),
    enabled: Boolean(repositoryId),
  });
  const treeQuery = useQuery({
    queryKey: ["repository-browse", repositoryId, "tree", selectedRef, path],
    queryFn: ({ signal }) => getRepositoryTree(repositoryId, path, { signal, ref: selectedRef }),
    enabled: Boolean(repositoryId),
  });
  const commitsQuery = useQuery({
    queryKey: ["repository-browse", repositoryId, "commits", selectedRef],
    queryFn: ({ signal }) => getRepositoryCommits(repositoryId, { signal, ref: selectedRef }),
    enabled: Boolean(repositoryId),
  });
  const blobQuery = useQuery({
    queryKey: ["repository-browse", repositoryId, "blob", selectedRef, selectedFile],
    queryFn: ({ signal }) =>
      getRepositoryBlob(repositoryId, selectedFile ?? "", { signal, ref: selectedRef }),
    enabled: Boolean(repositoryId && selectedFile),
  });
  const commitQuery = useQuery({
    queryKey: ["repository-browse", repositoryId, "commit", selectedRef, selectedCommit],
    queryFn: ({ signal }) =>
      getRepositoryCommit(repositoryId, selectedCommit ?? "", {
        signal,
        ref: selectedRef,
      }),
    enabled: Boolean(repositoryId && selectedCommit),
  });
  const diffQuery = useQuery({
    queryKey: ["repository-browse", repositoryId, "diff", selectedRef, selectedCommit],
    queryFn: ({ signal }) =>
      getRepositoryDiff(repositoryId, selectedCommit ?? "", {
        signal,
        ref: selectedRef,
      }),
    enabled: Boolean(repositoryId && selectedCommit),
  });
  const tree = treeQuery.data;
  const treeError = treeQuery.error ? asApiError(treeQuery.error) : null;
  const blobError = blobQuery.error ? asApiError(blobQuery.error) : null;

  function selectEntry(entry: RepositoryTreeEntry) {
    const nextPath = path ? `${path}/${entry.name}` : entry.name;
    if (entry.type === "tree") {
      setSelectedFile(null);
      setPath(nextPath);
    } else {
      setSelectedFile(nextPath);
    }
  }

  return (
    <section className="repository-browse-section" aria-labelledby="repository-browse-title">
      <div className="repository-section-heading">
        <p className="eyebrow">Repository contents</p>
        <h2 id="repository-browse-title">Browse the latest snapshot</h2>
        <p>Read-only browsing follows a selected local branch or tag.</p>
      </div>
      {refsQuery.data?.refs.length ? (
        <label className="repository-browse-ref-picker">
          <span>Ref</span>
          <select
            value={selectedRef}
            onChange={(event) => {
              setSelectedRef(event.target.value);
              setPath("");
              setSelectedFile(null);
              setSelectedCommit(null);
            }}
          >
            <option value="HEAD">HEAD</option>
            {refsQuery.data.refs.map((item) => (
              <option key={item.ref} value={item.ref}>
                {item.kind}: {item.name}
                {item.current ? " (current)" : ""}
              </option>
            ))}
          </select>
        </label>
      ) : refsQuery.isPending ? (
        <p className="repository-state" role="status">
          Loading branches and tags…
        </p>
      ) : null}
      {treeQuery.isPending ? (
        <p className="repository-state" role="status">
          Loading repository contents…
        </p>
      ) : null}
      {treeError ? (
        <div className="repository-form-error" role="alert">
          <p>{treeError.message}</p>
          <button
            className="repository-secondary-action"
            type="button"
            onClick={() => void treeQuery.refetch()}
          >
            Try again
          </button>
        </div>
      ) : null}
      {tree ? (
        <>
          <div className="repository-browse-toolbar">
            <button
              className="repository-secondary-action"
              type="button"
              disabled={!path}
              onClick={() => {
                setSelectedFile(null);
                setPath(path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
              }}
            >
              ← Up
            </button>
            <code>{tree.path || "/"}</code>
            {tree.commit_id ? (
              <span>{tree.entries.length} entries</span>
            ) : (
              <span>Empty repository</span>
            )}
          </div>
          {tree.entries.length ? (
            <ul className="repository-browse-list">
              {tree.entries.map((entry) => (
                <li key={`${entry.type}-${entry.name}`}>
                  <button type="button" onClick={() => selectEntry(entry)}>
                    <span aria-hidden="true">{entry.type === "tree" ? "▸" : "·"}</span>
                    {entry.name}
                  </button>
                  <span>{entry.type === "tree" ? "directory" : "file"}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="repository-state">No committed entries in this directory.</p>
          )}
        </>
      ) : null}
      {selectedFile ? (
        <section className="repository-file-viewer" aria-labelledby="repository-file-title">
          <div className="repository-section-heading">
            <p className="eyebrow">File</p>
            <h3 id="repository-file-title">{selectedFile}</h3>
          </div>
          {blobQuery.isPending ? (
            <p className="repository-state" role="status">
              Loading file…
            </p>
          ) : null}
          {blobError ? (
            <p className="repository-state-error" role="alert">
              {blobError.message}
            </p>
          ) : null}
          {blobQuery.data?.is_binary ? (
            <p className="repository-state">This binary file is not rendered in the browser.</p>
          ) : blobQuery.data ? (
            <pre className="repository-file-content">
              <code>{blobQuery.data.content}</code>
            </pre>
          ) : null}
        </section>
      ) : null}
      <section className="repository-history-section" aria-labelledby="repository-history-title">
        <div className="repository-section-heading">
          <p className="eyebrow">History</p>
          <h3 id="repository-history-title">Recent commits</h3>
        </div>
        {commitsQuery.isPending ? (
          <p className="repository-state" role="status">
            Loading history…
          </p>
        ) : null}
        {commitsQuery.error ? (
          <p className="repository-state-error" role="alert">
            {asApiError(commitsQuery.error).message}
          </p>
        ) : null}
        {commitsQuery.data?.commits.length ? (
          <ol className="repository-history-list">
            {commitsQuery.data.commits.map((commit) => (
              <li key={commit.object_id}>
                <button
                  className="repository-history-commit"
                  type="button"
                  onClick={() => setSelectedCommit(commit.object_id)}
                  aria-pressed={selectedCommit === commit.object_id}
                >
                  <code>{commit.object_id.slice(0, 10)}</code>
                  <span>{commit.message || "No commit message"}</span>
                </button>
                <time dateTime={new Date(commit.author_timestamp * 1000).toISOString()}>
                  {formatCommitDate(commit.author_timestamp)}
                </time>
              </li>
            ))}
          </ol>
        ) : null}
      </section>
      {commitQuery.data ? (
        <section
          className="repository-commit-detail"
          aria-labelledby="repository-commit-detail-title"
        >
          <div className="repository-section-heading">
            <p className="eyebrow">Commit detail</p>
            <h3 id="repository-commit-detail-title">
              {commitQuery.data.message.split("\n", 1)[0] || "No commit message"}
            </h3>
          </div>
          <p>
            <code>{commitQuery.data.object_id}</code> · {commitQuery.data.author_name} ·{" "}
            {formatCommitDate(commitQuery.data.author_timestamp)}
          </p>
          <pre className="repository-file-content">
            <code>{commitQuery.data.message}</code>
          </pre>
          <p>
            {commitQuery.data.parent_ids.length} parent commit
            {commitQuery.data.parent_ids.length === 1 ? "" : "s"}
          </p>
        </section>
      ) : null}
      {commitQuery.error ? (
        <p className="repository-state-error" role="alert">
          {asApiError(commitQuery.error).message}
        </p>
      ) : null}
      {diffQuery.isPending && selectedCommit ? (
        <p className="repository-state" role="status">
          Loading commit changes…
        </p>
      ) : null}
      {diffQuery.data ? (
        <section className="repository-diff-section" aria-labelledby="repository-diff-title">
          <div className="repository-section-heading">
            <p className="eyebrow">Changes</p>
            <h3 id="repository-diff-title">Files changed</h3>
          </div>
          {diffQuery.data.files.length ? (
            <ul className="repository-diff-list">
              {diffQuery.data.files.map((file) => (
                <li key={file.path}>
                  <div>
                    <code>{file.path}</code>
                    <span>{file.status}</span>
                  </div>
                  {file.is_binary ? (
                    <p className="repository-state">Binary file changed.</p>
                  ) : file.patch ? (
                    <pre className="repository-file-content">
                      <code>{file.patch}</code>
                    </pre>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="repository-state">No file changes in this commit.</p>
          )}
        </section>
      ) : null}
      {diffQuery.error ? (
        <p className="repository-state-error" role="alert">
          {asApiError(diffQuery.error).message}
        </p>
      ) : null}
    </section>
  );
}
