# CommitVerse Hub Security Architecture

## Status and threat model

This document specifies **proposed controls** for an unimplemented Hub. They
are design requirements, not current security guarantees. The threat model
covers unauthenticated and malicious clients, compromised accounts, abusive
repository operations, malformed repository data, path manipulation, symlink
attacks, concurrent requests, partial database/filesystem failures, and
accidental exposure through logs or API errors.

Trust boundaries:

- The browser and all request values are untrusted.
- FastAPI authenticates and validates requests but must not be the sole
  authorization boundary.
- PostgreSQL stores Hub metadata and access policy; it is not the Git object
  store.
- The repository filesystem is sensitive tenant data, accessed only through
  the repository service and Core adapter.
- CommitVerse Core provides Git-like operations, not Hub user identity,
  tenant authorization, or complete hosted-operation isolation.

## Authentication and sessions

For the first-party browser client, use server-side opaque sessions rather than
JWT access/refresh pairs. A cryptographically random high-entropy token is
issued at login; persist only its cryptographic hash in the `sessions` table.
Set a finite idle/absolute expiry policy, support per-session and account-wide
revocation, and rotate the session identifier after login and privilege
changes. Logout revokes the record and expires the cookie.

Hash passwords with Argon2id through a maintained password-hashing library
using its current recommended parameters. Keep algorithm/version metadata so
hashes can be upgraded on successful authentication. Use generic login failure
responses, protect registration/login with rate limits, and never log
credentials.

JWTs are deferred: the initial modular monolith has no independent service
consumer that justifies token refresh, key rotation, and revocation complexity.
Revisit only for a concrete client/integration requirement.

## Cookies, CSRF, CORS, and input validation

- Use `Secure`, `HttpOnly`, appropriately scoped cookies and a deliberate
  `SameSite` policy. Do not put session tokens in URLs or browser local storage.
- Protect cookie-authenticated state-changing requests with CSRF tokens and
  strict `Origin` validation. SameSite is defense in depth, not the only CSRF
  control.
- Configure CORS to exact approved frontend origins. Do not use wildcard origins
  with credentialed requests. Re-evaluate cookie/CSRF behavior if deployment
  makes frontend and API cross-site.
- Validate all request bodies, query parameters, identifiers, slugs, lengths,
  and enums at the API boundary and re-check business invariants in services.
- Apply request/body/time limits where operations can consume significant
  resources.

## Authorization

Use deny-by-default service-level authorization on every operation. Route
guards and frontend visibility are not sufficient. Determine public/private
read access, personal ownership, organization owner/admin rights, and direct
repository grants using the rules in
[`database-design.md`](database-design.md#ownership-and-effective-authorization).
Check lifecycle state and authorization before opening a repository through
Core. Never trust a client-supplied repository path, owner, or role.

Organization members do not automatically gain access to all organization
repositories. The MVP has no teams or complex inherited permission graph.
Document each action's required role and test permission combinations,
revocation, ownership changes, and missing/inconsistent metadata.

## Rate limiting and abuse prevention

Apply limits to login, account creation, invitation issuance/acceptance,
repository creation, and expensive repository reads. Bound concurrent Core
operations and transfer/object sizes. An in-process counter is not a
cross-worker rate limiter; deployment must provide a verified compliant
mechanism before relying on distributed limits. Do not add a paid dependency
or billing requirement to satisfy this control.

## Secrets, logging, and audit

Load secrets from local/deployment configuration and keep them out of source,
responses, logs, screenshots, and audit metadata. No secret or billing setup is
added merely in anticipation of deployment. Fail clearly when required
configuration is absent rather than using unsafe defaults.

Use structured logs with request/correlation IDs. Log security-relevant
success/failure outcomes without passwords, session/invitation tokens,
repository content, or unnecessary personal data. Audit account, membership,
permission, invitation, repository lifecycle, and security-sensitive changes
with actor, action, target, time, and an allow-listed metadata set. Restrict
audit access and define retention before production.

Return stable external error codes and generic path-independent messages.
Keep detailed exceptions in access-controlled logs; do not expose local paths,
SQL, stack traces, object contents, or secret values.

## Repository filesystem isolation

Hub assigns a generated opaque storage key per repository. Resolve paths only
under a configured repository root; do not derive paths from usernames,
repository slugs, or untrusted parameters. Validate that the root and all
relevant components are expected directories, reject symlinks and path
escapes, and use the least-privilege service account and filesystem permissions
available.

Initialize repositories bare through Core in a controlled temporary sibling
directory, validate before publication, and only publish beneath the approved
root. Lifecycle deletion must verify the generated key and resolved path,
block new operations, and remove only the exact known repository directory.
Never recursively delete a path assembled from request input. Failures must
leave a recorded, recoverable lifecycle state.

Core has supported safe worktree path checks, no-follow tracked reads, atomic
loose-object writes, and single-reference compare-and-swap behavior. These
protections apply to specific Core operations; they do not prove Hub path
isolation, authorize a tenant, prevent every filesystem race, or secure a
hosted multi-user deployment. Hub must validate the storage boundary itself
and test symlink/path traversal attempts.

## Concurrency and bounded execution

Authorize first, then acquire per-repository operation coordination before
running Core work. Core operations are synchronous and must not block the
ASGI event loop: use bounded worker execution, operation timeouts where safe,
and concurrency limits. Cancellation must not be treated as proof that a
filesystem operation stopped.

Core's CAS ref update coordinates one reference publication; it is not a
multi-ref/multi-operation transaction and does not coordinate metadata
transactions or every ref writer. A process-local keyed lock does not
coordinate multiple server processes. Keep the initial development topology
single-process for repository mutations unless a cross-process locking design
has been implemented and verified. Do not claim safe horizontal scaling by
adding workers.

Add contention tests for same-repository and different-repository operations,
failure-injection around publication and cleanup, stale lifecycle recovery,
and checks that denied requests never invoke the adapter.

## Database and filesystem lifecycle

Repository metadata uses `provisioning`, `ready`, `deleting`, and `error`
states. PostgreSQL and the filesystem do not share an atomic transaction.
Implement idempotent lifecycle steps and a reconciler for abandoned
provisioning/deleting/error records and orphaned directories. Reconciliation
must compare generated opaque keys, validate paths, and require explicit
policy for ambiguous state; it must never silently delete unknown data.

## Backup, recovery, and deployment

Back up metadata and repository storage with a documented consistency and
restore procedure. Test restore and post-restore reconciliation; a database
backup alone cannot restore repository contents, and a repository backup alone
cannot restore ownership/permissions. Define retention, encryption-at-rest
responsibility, access controls, and recovery objectives before real user data
is accepted.

Hub remains local-development-only until a compliant zero-cost Python hosting
and filesystem-storage solution is separately verified. Cloudflare Pages Free
is planned for static assets; Workers Free are only for suitable lightweight
endpoints, never for the Python Git engine; Neon Free is planned for metadata.
Do not activate billing, use paid trials, or recommend excluded providers.
Free-quota exhaustion must pause, degrade, or migrate without charges.

## Required verification

Before any hosted release, test password/session behavior; CSRF/CORS policy;
authorization matrices; input and rate limits; path traversal and symlink
attacks; repository isolation; safe provisioning/deletion; per-repository
contention; worker bounds; failure injection and reconciliation; error/log
redaction; backup/restore; and the zero-cost deployment assumptions. These are
future Hub tests, not current evidence.
