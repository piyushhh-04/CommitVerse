import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) =>
        failureCount < 1 &&
        error instanceof ApiError &&
        (error.status === null || error.status >= 500),
    },
    mutations: {
      retry: false,
    },
  },
});
