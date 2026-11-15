import { useRef, useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import type { RepositoryVisibility } from "../api/repositories";

export interface RepositoryFormValues {
  name: string;
  description: string;
  visibility: RepositoryVisibility;
}

interface RepositoryFormProps {
  initialValues?: RepositoryFormValues;
  pending: boolean;
  submitLabel: string;
  pendingLabel: string;
  error?: ApiError | null;
  successMessage?: string | null;
  onValuesChange?: () => void;
  onSubmit: (values: RepositoryFormValues) => void;
}

interface RepositoryFormErrors {
  name?: string;
  description?: string;
}

const REPOSITORY_NAME_PATTERN = /^(?!.*\.$)[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;

function getApiFieldError(error: ApiError | null | undefined, field: string): string | undefined {
  return error?.details?.find((detail) => detail.field.split(".").at(-1) === field)?.message;
}

function getApiErrorMessage(error: ApiError): string {
  if (error.code === "repository_conflict") {
    return "A repository with that name already exists. Choose a different name.";
  }
  return error.message;
}

export function RepositoryForm({
  initialValues = { name: "", description: "", visibility: "private" },
  pending,
  submitLabel,
  pendingLabel,
  error,
  successMessage,
  onValuesChange,
  onSubmit,
}: RepositoryFormProps) {
  const [name, setName] = useState(initialValues.name);
  const [description, setDescription] = useState(initialValues.description);
  const [visibility, setVisibility] = useState<RepositoryVisibility>(initialValues.visibility);
  const [fieldErrors, setFieldErrors] = useState<RepositoryFormErrors>({});
  const nameInputRef = useRef<HTMLInputElement>(null);
  const descriptionInputRef = useRef<HTMLTextAreaElement>(null);
  const serverNameError = getApiFieldError(error, "name");
  const serverDescriptionError = getApiFieldError(error, "description");
  const nameError = fieldErrors.name ?? serverNameError;
  const descriptionError = fieldErrors.description ?? serverDescriptionError;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim().toLowerCase();
    const normalizedDescription = description.trim();
    const nextErrors: RepositoryFormErrors = {};

    if (!normalizedName) {
      nextErrors.name = "Enter a repository name.";
    } else if (!REPOSITORY_NAME_PATTERN.test(normalizedName)) {
      nextErrors.name =
        "Use 1–100 letters, numbers, dots, underscores or hyphens; start with a letter or number and do not end with a dot.";
    }
    if (Array.from(normalizedDescription).length > 1000) {
      nextErrors.description = "Description must be 1,000 characters or fewer.";
    }

    setFieldErrors(nextErrors);
    if (nextErrors.name) {
      nameInputRef.current?.focus();
      return;
    }
    if (nextErrors.description) {
      descriptionInputRef.current?.focus();
      return;
    }

    onSubmit({
      name: normalizedName,
      description: normalizedDescription,
      visibility,
    });
  }

  function updateName(value: string) {
    setName(value);
    setFieldErrors((current) => {
      const next = { ...current };
      delete next.name;
      return next;
    });
    onValuesChange?.();
  }

  function updateDescription(value: string) {
    setDescription(value);
    setFieldErrors((current) => {
      const next = { ...current };
      delete next.description;
      return next;
    });
    onValuesChange?.();
  }

  function updateVisibility(value: RepositoryVisibility) {
    setVisibility(value);
    onValuesChange?.();
  }

  return (
    <form className="repository-form" aria-busy={pending} noValidate onSubmit={handleSubmit}>
      {error ? (
        <div className="repository-form-error" role="alert">
          <p>{getApiErrorMessage(error)}</p>
          {error.details?.length ? (
            <ul>
              {error.details.map((detail, index) => (
                <li key={`${detail.field}-${detail.code}-${index}`}>
                  {detail.field ? `${detail.field}: ` : ""}
                  {detail.message}
                </li>
              ))}
            </ul>
          ) : null}
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
        <label htmlFor="repository-name">Repository name</label>
        <input
          ref={nameInputRef}
          id="repository-name"
          name="name"
          type="text"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          required
          maxLength={100}
          value={name}
          disabled={pending}
          aria-invalid={Boolean(nameError)}
          aria-describedby={`repository-name-hint${nameError ? " repository-name-error" : ""}`}
          onChange={(event) => updateName(event.currentTarget.value)}
        />
        <p className="repository-field-hint" id="repository-name-hint">
          Lowercase names are used in Hub. Surrounding whitespace is trimmed.
        </p>
        {nameError ? (
          <p className="repository-field-error" id="repository-name-error">
            {nameError}
          </p>
        ) : null}
      </div>

      <div className="repository-field">
        <label htmlFor="repository-description">
          Description <span className="repository-optional">(optional)</span>
        </label>
        <textarea
          ref={descriptionInputRef}
          id="repository-description"
          name="description"
          rows={4}
          value={description}
          disabled={pending}
          aria-invalid={Boolean(descriptionError)}
          aria-describedby={
            descriptionError
              ? "repository-description-hint repository-description-error"
              : "repository-description-hint"
          }
          onChange={(event) => updateDescription(event.currentTarget.value)}
        />
        <p className="repository-field-hint" id="repository-description-hint">
          Up to 1,000 characters.
        </p>
        {descriptionError ? (
          <p className="repository-field-error" id="repository-description-error">
            {descriptionError}
          </p>
        ) : null}
      </div>

      <fieldset className="repository-visibility">
        <legend>Visibility</legend>
        <div className="repository-visibility-options">
          <label>
            <input
              type="radio"
              name="visibility"
              value="private"
              checked={visibility === "private"}
              disabled={pending}
              onChange={() => updateVisibility("private")}
            />
            <span>
              <strong>Private</strong>
              <small>Only you can manage this repository.</small>
            </span>
          </label>
          <label>
            <input
              type="radio"
              name="visibility"
              value="public"
              checked={visibility === "public"}
              disabled={pending}
              onChange={() => updateVisibility("public")}
            />
            <span>
              <strong>Public</strong>
              <small>Marks metadata as public; anonymous access is not available.</small>
            </span>
          </label>
        </div>
      </fieldset>

      <button className="repository-primary-action" type="submit" disabled={pending}>
        {pending ? pendingLabel : submitLabel}
      </button>
    </form>
  );
}
