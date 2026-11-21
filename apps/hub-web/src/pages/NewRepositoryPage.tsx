import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { RepositoryForm, type RepositoryFormValues } from "../components/RepositoryForm";
import { useAuth } from "../auth/AuthContext";
import {
  personalRepositoryMutationClient,
  personalRepositoryMutationOptions,
} from "../repositories/queries";

export function NewRepositoryPage() {
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const mutations = personalRepositoryMutationOptions(queryClient, userId);
  const createMutation = useMutation(
    mutations.create,
    personalRepositoryMutationClient(queryClient),
  );

  if (!userId) return null;

  function handleSubmit(values: RepositoryFormValues) {
    createMutation.mutate(
      {
        name: values.name,
        description: values.description || null,
        visibility: values.visibility,
      },
      {
        onSuccess: (repository) => {
          void navigate(`/app/repositories/${repository.id}`, {
            state: { focusDestinationHeading: true },
          });
        },
      },
    );
  }

  return (
    <main className="repository-page repository-form-page">
      <Link className="repository-back-link" to="/app/repositories">
        <span aria-hidden="true">←</span> All repositories
      </Link>
      <header className="repository-page-header repository-form-header">
        <div>
          <h1 id="foundation-title" tabIndex={-1}>
            New repository
          </h1>
          <p className="repository-page-intro">
            Start with a name and a few details. Your repository will be created as an empty Core
            repository.
          </p>
        </div>
      </header>
      <section className="repository-form-section" aria-labelledby="repository-create-form-title">
        <h2 className="sr-only" id="repository-create-form-title">
          Repository details
        </h2>
        <RepositoryForm
          pending={createMutation.isPending}
          submitLabel="Create repository"
          pendingLabel="Creating repository…"
          error={createMutation.error ?? null}
          onSubmit={handleSubmit}
        />
      </section>
    </main>
  );
}
