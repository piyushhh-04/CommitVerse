import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { acceptOrganizationInvitation } from "../api/organizations";

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError("The invitation could not be accepted.", {
        status: null,
        code: "unexpected_error",
        requestId: null,
        cause: error,
      });
}

export function InvitationAcceptancePage() {
  const navigate = useNavigate();
  const [token, setToken] = useState("");
  const mutation = useMutation({
    mutationFn: () => acceptOrganizationInvitation(token.trim()),
    retry: false,
    onSuccess: (result) => {
      void navigate(`/app/organizations/${result.organization_id}`);
    },
  });
  return (
    <main className="repository-page repository-form-page">
      <Link className="repository-back-link" to="/app/organizations">
        <span aria-hidden="true">←</span> All organizations
      </Link>
      <header className="repository-page-header repository-form-header">
        <div>
          <p className="eyebrow">Organizations / Invitation</p>
          <h1 id="foundation-title" tabIndex={-1}>
            Accept an invitation
          </h1>
          <p className="repository-page-intro">
            Paste the one-time token shared by an organization manager.
          </p>
        </div>
      </header>
      <section className="repository-form-section" aria-labelledby="invitation-token-title">
        <div className="repository-section-heading">
          <p className="eyebrow">Secure token</p>
          <h2 id="invitation-token-title">Invitation token</h2>
        </div>
        <div className="organization-inline-form">
          <input
            aria-label="Invitation token"
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
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Accepting…" : "Accept invitation"}
          </button>
        </div>
        {mutation.error ? (
          <p className="repository-state-error" role="alert">
            {asApiError(mutation.error).message}
          </p>
        ) : null}
      </section>
    </main>
  );
}
