import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { createOrganizationRepository } from "../api/organizationRepositories";
import { useAuth } from "../auth/AuthContext";
import { RepositoryForm, type RepositoryFormValues } from "../components/RepositoryForm";

export function NewOrganizationRepositoryPage() {
  const { organizationId = "" } = useParams();
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const mutation = useMutation({
    mutationFn: (values: RepositoryFormValues) =>
      createOrganizationRepository(organizationId, {
        ...values,
        description: values.description || null,
      }),
    retry: false,
    onSuccess: async (repository) => {
      await queryClient.invalidateQueries({
        queryKey: ["organization-repositories", userId, organizationId],
      });
      void navigate(`/app/organizations/${organizationId}/repositories/${repository.id}`, {
        state: { focusDestinationHeading: true },
      });
    },
  });
  if (!userId) return null;
  return (
    <main className="repository-page repository-form-page">
      <Link
        className="repository-back-link"
        to={`/app/organizations/${organizationId}/repositories`}
      >
        <span aria-hidden="true">←</span> Organization repositories
      </Link>
      <header className="repository-page-header repository-form-header">
        <div>
          <p className="eyebrow">Organization repositories / New</p>
          <h1 id="foundation-title" tabIndex={-1}>
            New repository
          </h1>
          <p className="repository-page-intro">
            Create a Core-backed repository owned by this organization.
          </p>
        </div>
      </header>
      <section
        className="repository-form-section"
        aria-labelledby="organization-repository-create-title"
      >
        <h2 className="sr-only" id="organization-repository-create-title">
          Repository details
        </h2>
        <RepositoryForm
          pending={mutation.isPending}
          submitLabel="Create repository"
          pendingLabel="Creating repository…"
          error={mutation.error instanceof ApiError ? mutation.error : null}
          onSubmit={(values) => mutation.mutate(values)}
        />
      </section>
    </main>
  );
}
