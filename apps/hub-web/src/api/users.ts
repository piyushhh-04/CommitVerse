import { ApiError, apiClient } from "./client";

export interface UserSearchResult {
  id: string;
  username: string;
  display_name: string;
}

export interface UserSearchResponse {
  items: UserSearchResult[];
  query: string;
  limit: number;
}

export async function searchUsers(
  query: string,
  options: { signal?: AbortSignal } = {},
): Promise<UserSearchResponse> {
  const response = await apiClient.get<UserSearchResponse>(
    `/users/search?query=${encodeURIComponent(query)}&limit=20`,
    options,
  );
  if (response !== undefined) return response;
  throw new ApiError("The Hub API returned an empty user search response.", {
    status: 200,
    code: "invalid_response",
    requestId: null,
  });
}
