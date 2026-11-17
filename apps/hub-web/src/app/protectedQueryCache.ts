import type { QueryClient } from "@tanstack/react-query";

export const protectedQueryKeys = {
  all: ["protected"] as const,
  forUser: (userId: string) => ["protected", userId] as const,
};

export function protectedQueryKey(userId: string, ...scope: readonly unknown[]) {
  return [...protectedQueryKeys.forUser(userId), ...scope] as const;
}

export interface ProtectedQueryIdentity {
  userId: string | null;
  generation: number;
}

const activeUsers = new WeakMap<QueryClient, ProtectedQueryIdentity>();

export function getProtectedQueryIdentity(queryClient: QueryClient): ProtectedQueryIdentity {
  return activeUsers.get(queryClient) ?? { userId: null, generation: 0 };
}

export function getProtectedQueryIdentityGeneration(
  queryClient: QueryClient,
  userId: string,
): number | null {
  const identity = getProtectedQueryIdentity(queryClient);
  return identity?.userId === userId ? identity.generation : null;
}

export function isProtectedQueryIdentity(
  queryClient: QueryClient,
  userId: string,
  generation?: number,
): boolean {
  const identity = getProtectedQueryIdentity(queryClient);
  return (
    identity?.userId === userId && (generation === undefined || identity.generation === generation)
  );
}

export async function transitionProtectedQueryIdentity(
  queryClient: QueryClient,
  nextUserId: string | null,
  forceClear = false,
): Promise<boolean> {
  const previousIdentity = getProtectedQueryIdentity(queryClient);
  const identityChanged = previousIdentity.userId !== nextUserId;
  const shouldClear = identityChanged || forceClear;
  activeUsers.set(queryClient, {
    userId: nextUserId,
    generation: previousIdentity.generation + (shouldClear ? 1 : 0),
  });

  if (!shouldClear) return false;

  const cancellation = queryClient.cancelQueries({ queryKey: protectedQueryKeys.all });
  queryClient.removeQueries({ queryKey: protectedQueryKeys.all });
  queryClient.getMutationCache().clear();
  await cancellation;
  return true;
}
