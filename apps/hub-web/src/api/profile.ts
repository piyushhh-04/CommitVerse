import { apiClient } from "./client";
import type { AuthUser } from "../auth/types";

export interface ProfileUpdateInput {
  username?: string;
  display_name?: string;
  bio?: string | null;
}

export function updateProfile(input: ProfileUpdateInput): Promise<AuthUser> {
  return apiClient.patch<AuthUser, ProfileUpdateInput>("/me", input).then((user) => {
    if (!user) throw new Error("The Hub API returned an empty profile response.");
    return user;
  });
}
