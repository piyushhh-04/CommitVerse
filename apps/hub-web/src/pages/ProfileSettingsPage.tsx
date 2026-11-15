import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { updateProfile, type ProfileUpdateInput } from "../api/profile";
import { useAuth } from "../auth/AuthContext";
import type { AuthUser } from "../auth/types";

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError("The profile could not be updated.", {
        status: null,
        code: "unexpected_error",
        requestId: null,
        cause: error,
      });
}

function fieldError(error: ApiError | null, field: string): string | undefined {
  return error?.details?.find((detail) => detail.field.split(".").at(-1) === field)?.message;
}

export function ProfileSettingsPage() {
  const auth = useAuth();
  const user = auth.status === "authenticated" ? auth.user : null;
  const [username, setUsername] = useState(user?.username ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [bio, setBio] = useState(user?.bio ?? "");
  const [formError, setFormError] = useState<string | null>(null);
  const profileMutation = useMutation<AuthUser, ApiError, ProfileUpdateInput>({
    mutationFn: updateProfile,
    retry: false,
    onSuccess: async (updatedUser) => {
      await auth.updateUser(updatedUser);
    },
  });

  if (!user) return null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextUsername = username.trim();
    const nextDisplayName = displayName.trim();
    const nextBio = bio.trim();
    if (!nextUsername) {
      setFormError("Username must not be empty.");
      return;
    }
    if (!nextDisplayName) {
      setFormError("Display name must not be empty.");
      return;
    }
    if (nextUsername.length > 39 || nextDisplayName.length > 120 || nextBio.length > 500) {
      setFormError("One or more profile fields exceed their length limit.");
      return;
    }
    setFormError(null);
    profileMutation.mutate({
      username: nextUsername,
      display_name: nextDisplayName,
      bio: nextBio || null,
    });
  }

  const error = profileMutation.error ? asApiError(profileMutation.error) : null;
  const usernameError = fieldError(error, "username");
  const displayNameError = fieldError(error, "display_name");

  return (
    <main className="repository-page repository-form-page">
      <Link className="repository-back-link" to="/app">
        <span aria-hidden="true">←</span> Your workspace
      </Link>
      <header className="repository-page-header repository-form-header">
        <div>
          <p className="eyebrow">Account / Profile</p>
          <h1 id="foundation-title" tabIndex={-1}>
            Profile settings
          </h1>
          <p className="repository-page-intro">
            Keep the identity attached to your work current. Your email remains private and cannot
            be changed here.
          </p>
        </div>
      </header>
      <section className="repository-form-section" aria-labelledby="profile-form-title">
        <div className="repository-section-heading">
          <p className="eyebrow">Public identity</p>
          <h2 id="profile-form-title">Profile details</h2>
        </div>
        <form
          className="repository-form"
          aria-busy={profileMutation.isPending}
          noValidate
          onSubmit={submit}
        >
          {formError || error ? (
            <div className="repository-form-error" role="alert">
              <p>{formError ?? error?.message}</p>
              {error?.requestId ? (
                <p className="repository-error-reference">Reference: {error.requestId}</p>
              ) : null}
            </div>
          ) : null}
          {profileMutation.isSuccess ? (
            <p className="repository-form-success" role="status">
              Profile saved.
            </p>
          ) : null}
          <div className="repository-field">
            <label htmlFor="profile-username">Username</label>
            <input
              id="profile-username"
              name="username"
              autoComplete="username"
              maxLength={39}
              value={username}
              disabled={profileMutation.isPending}
              aria-invalid={Boolean(usernameError)}
              onChange={(event) => {
                setUsername(event.currentTarget.value);
                profileMutation.reset();
              }}
            />
            {usernameError ? <p className="repository-field-error">{usernameError}</p> : null}
          </div>
          <div className="repository-field">
            <label htmlFor="profile-display-name">Display name</label>
            <input
              id="profile-display-name"
              name="display_name"
              autoComplete="name"
              maxLength={120}
              value={displayName}
              disabled={profileMutation.isPending}
              aria-invalid={Boolean(displayNameError)}
              onChange={(event) => {
                setDisplayName(event.currentTarget.value);
                profileMutation.reset();
              }}
            />
            {displayNameError ? <p className="repository-field-error">{displayNameError}</p> : null}
          </div>
          <div className="repository-field">
            <label htmlFor="profile-bio">
              Bio <span className="repository-optional">(optional)</span>
            </label>
            <textarea
              id="profile-bio"
              name="bio"
              maxLength={500}
              rows={5}
              value={bio}
              disabled={profileMutation.isPending}
              onChange={(event) => {
                setBio(event.currentTarget.value);
                profileMutation.reset();
              }}
            />
          </div>
          <div className="repository-form-actions">
            <button
              className="repository-primary-action"
              type="submit"
              disabled={profileMutation.isPending}
            >
              {profileMutation.isPending ? "Saving profile…" : "Save profile"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
