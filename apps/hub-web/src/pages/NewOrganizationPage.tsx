import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  getProtectedQueryIdentityGeneration,
  isProtectedQueryIdentity,
  protectedQueryKey,
} from "../app/protectedQueryCache";
import { useAuth } from "../auth/AuthContext";
import {
  createOrganization,
  type Organization,
  type OrganizationInput,
} from "../api/organizations";
import { OrganizationForm, type OrganizationFormValues } from "../components/OrganizationForm";

export function NewOrganizationPage() {
  const auth = useAuth();
  const userId = auth.status === "authenticated" ? auth.user.id : "";
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const mutation = useMutation<
    Organization,
    ApiError,
    { input: OrganizationInput; identityGeneration: number }
  >({
    mutationKey: protectedQueryKey(userId, "organizations", "mutation", "create"),
    mutationFn: ({ input }) => createOrganization(input),
    retry: false,
    onSuccess: async (organization, variables) => {
      if (!isProtectedQueryIdentity(queryClient, userId, variables.identityGeneration)) return;
      await queryClient.invalidateQueries({
        queryKey: protectedQueryKey(userId, "organizations"),
      });
      if (!isProtectedQueryIdentity(queryClient, userId, variables.identityGeneration)) return;
      void navigate(`/app/organizations/${organization.id}`, {
        state: { focusDestinationHeading: true },
      });
    },
  });
  function submit(values: OrganizationFormValues) {
    const identityGeneration = getProtectedQueryIdentityGeneration(queryClient, userId);
    if (identityGeneration !== null) mutation.mutate({ input: values, identityGeneration });
  }
  return (
    <main className="repository-page repository-form-page">
      <Link className="repository-back-link" to="/app/organizations">
        <span aria-hidden="true">←</span> All organizations
      </Link>
      <header className="repository-page-header repository-form-header">
        <div>
          <p className="eyebrow">Organizations / New</p>
          <h1 id="foundation-title" tabIndex={-1}>
            New organization
          </h1>
          <p className="repository-page-intro">
            Create a shared space with explicit membership and ownership boundaries.
          </p>
        </div>
      </header>
      <section className="repository-form-section" aria-labelledby="organization-create-title">
        <h2 className="sr-only" id="organization-create-title">
          Organization details
        </h2>
        <OrganizationForm
          pending={mutation.isPending}
          submitLabel="Create organization"
          pendingLabel="Creating organization…"
          error={mutation.error}
          onSubmit={submit}
        />
      </section>
    </main>
  );
}
