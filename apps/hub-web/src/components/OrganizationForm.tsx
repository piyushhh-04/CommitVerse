import { useRef, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";

export interface OrganizationFormValues {
  slug: string;
  name: string;
}

interface OrganizationFormProps {
  initialValues?: OrganizationFormValues;
  pending: boolean;
  submitLabel: string;
  pendingLabel: string;
  error?: ApiError | null;
  successMessage?: string | null;
  onValuesChange?: () => void;
  onSubmit: (values: OrganizationFormValues) => void;
}

const SLUG_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

function apiFieldError(error: ApiError | null | undefined, field: string): string | undefined {
  return error?.details?.find((detail) => detail.field.split(".").at(-1) === field)?.message;
}

export function OrganizationForm({
  initialValues = { slug: "", name: "" },
  pending,
  submitLabel,
  pendingLabel,
  error,
  successMessage,
  onValuesChange,
  onSubmit,
}: OrganizationFormProps) {
  const [slug, setSlug] = useState(initialValues.slug);
  const [name, setName] = useState(initialValues.name);
  const [fieldErrors, setFieldErrors] = useState<{ slug?: string; name?: string }>({});
  const slugRef = useRef<HTMLInputElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const slugError = fieldErrors.slug ?? apiFieldError(error, "slug");
  const nameError = fieldErrors.name ?? apiFieldError(error, "name");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedSlug = slug.trim().toLowerCase();
    const normalizedName = name.trim();
    const nextErrors: { slug?: string; name?: string } = {};
    if (!SLUG_PATTERN.test(normalizedSlug)) {
      nextErrors.slug =
        "Use 1–63 lowercase letters, numbers, or hyphens; do not end with a hyphen.";
    }
    if (!normalizedName) nextErrors.name = "Enter an organization name.";
    setFieldErrors(nextErrors);
    if (nextErrors.slug) {
      slugRef.current?.focus();
      return;
    }
    if (nextErrors.name) {
      nameRef.current?.focus();
      return;
    }
    onSubmit({ slug: normalizedSlug, name: normalizedName });
  }

  function changeSlug(value: string) {
    setSlug(value);
    setFieldErrors(({ name }) => (name ? { name } : {}));
    onValuesChange?.();
  }

  function changeName(value: string) {
    setName(value);
    setFieldErrors(({ slug }) => (slug ? { slug } : {}));
    onValuesChange?.();
  }

  return (
    <form className="repository-form" aria-busy={pending} noValidate onSubmit={submit}>
      {error ? (
        <div className="repository-form-error" role="alert">
          <p>{error.message}</p>
          {error.requestId ? (
            <p className="repository-error-reference">Reference: {error.requestId}</p>
          ) : null}
        </div>
      ) : null}
      {successMessage ? (
        <p className="repository-form-success" role="status">
          {successMessage}
        </p>
      ) : null}
      <div className="repository-field">
        <label htmlFor="organization-slug">Organization slug</label>
        <input
          ref={slugRef}
          id="organization-slug"
          value={slug}
          maxLength={63}
          autoCapitalize="none"
          spellCheck={false}
          disabled={pending}
          aria-invalid={Boolean(slugError)}
          onChange={(event) => changeSlug(event.currentTarget.value)}
        />
        <p className="repository-field-hint">The stable URL identifier for this organization.</p>
        {slugError ? <p className="repository-field-error">{slugError}</p> : null}
      </div>
      <div className="repository-field">
        <label htmlFor="organization-name">Organization name</label>
        <input
          ref={nameRef}
          id="organization-name"
          value={name}
          maxLength={120}
          disabled={pending}
          aria-invalid={Boolean(nameError)}
          onChange={(event) => changeName(event.currentTarget.value)}
        />
        {nameError ? <p className="repository-field-error">{nameError}</p> : null}
      </div>
      <button className="repository-primary-action" type="submit" disabled={pending}>
        {pending ? pendingLabel : submitLabel}
      </button>
    </form>
  );
}
