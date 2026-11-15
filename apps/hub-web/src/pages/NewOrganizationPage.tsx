import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  createOrganization,
  type Organization,
  type OrganizationInput,
} from "../api/organizations";
import { OrganizationForm, type OrganizationFormValues } from "../components/OrganizationForm";

export function NewOrganizationPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const mutation = useMutation<Organization, ApiError, OrganizationInput>({
    mutationFn: createOrganization,
    retry: false,
    onSuccess: async (organization) => {
      await queryClient.invalidateQueries({ queryKey: ["organizations"] });
      void navigate(`/app/organizations/${organization.id}`, {
        state: { focusDestinationHeading: true },
      });
    },
  });
  function submit(values: OrganizationFormValues) {
    mutation.mutate(values);
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
