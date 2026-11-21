import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { acceptRepositoryInvitation } from "../api/repositories";
import {
  getProtectedQueryIdentityGeneration,
  isProtectedQueryIdentity,
  protectedQueryKey,
} from "../app/protectedQueryCache";
import { useAuth } from "../auth/AuthContext";

function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "The repository invitation could not be accepted.";
}

export function RepositoryInvitationAcceptancePage() {
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [token, setToken] = useState("");
  const mutation = useMutation({
    mutationKey: protectedQueryKey(userId, "repository-invitations", "mutation", "accept"),
    mutationFn: ({ invitationToken }: { invitationToken: string; generation: number }) =>
      acceptRepositoryInvitation(invitationToken),
    retry: false,
    onSuccess: async (result, variables: { invitationToken: string; generation: number }) => {
      if (!isProtectedQueryIdentity(queryClient, userId, variables.generation)) return;
      await queryClient.invalidateQueries({
        queryKey: protectedQueryKey(userId, "repositories", "list"),
      });
      if (!isProtectedQueryIdentity(queryClient, userId, variables.generation)) return;
      await navigate(`/app/repository-browser/${result.repository_id}`);
    },
  });

  if (!userId) return null;

  return (
    <main className="repository-page repository-form-page">
      <Link className="repository-back-link" to="/app">
        <span aria-hidden="true">←</span> Workspace
      </Link>
      <header className="repository-page-header repository-form-header">
        <div>
          <h1 id="foundation-title" tabIndex={-1}>
            Accept a repository invitation
          </h1>
          <p className="repository-page-intro">
            Paste the one-time token shared with your account to receive direct repository access.
          </p>
        </div>
      </header>
      <section
        className="repository-form-section"
        aria-labelledby="repository-invitation-token-title"
      >
        <div className="repository-section-heading">
          <h2 id="repository-invitation-token-title">Invitation token</h2>
        </div>
        <div className="organization-inline-form">
          <label className="sr-only" htmlFor="repository-invitation-token">
            Repository invitation token
          </label>
          <input
            id="repository-invitation-token"
            autoComplete="off"
            value={token}
            onChange={(event) => {
              setToken(event.currentTarget.value);
              mutation.reset();
            }}
            placeholder="Paste your invitation token"
          />
          <button
            className="repository-primary-action"
            type="button"
            disabled={!token.trim() || mutation.isPending}
            onClick={() => {
              const generation = getProtectedQueryIdentityGeneration(queryClient, userId);
              if (generation !== null) {
                mutation.mutate({ invitationToken: token.trim(), generation });
              }
            }}
          >
            {mutation.isPending ? "Accepting…" : "Accept invitation"}
          </button>
        </div>
        {mutation.error ? (
          <p className="repository-state-error" role="alert">
            {errorMessage(mutation.error)}
          </p>
        ) : null}
      </section>
    </main>
  );
}
