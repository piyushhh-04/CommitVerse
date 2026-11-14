# CommitVerse Hub Security Architecture

## Status and threat model

This document records the approved security architecture and distinguishes
implemented Hub controls from remaining requirements.
Registration/login/logout, session authentication, and owner-only personal
repository lifecycle routes exist, as do organization metadata and membership
routes with membership-scoped reads and role-gated mutations. The shared
repository lifecycle service also supports organization repositories with
current owner/admin membership checks; organization repository HTTP routes,
direct repository grants, and broader repository operations remain
unimplemented. The initial schema alone is not a security guarantee.
The threat model covers unauthenticated and malicious clients, compromised
accounts, abusive repository operations, malformed repository data, path
manipulation, symlink attacks, concurrent requests, partial database/filesystem
failures, and accidental exposure through logs or API errors.

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
credentials. Rate limiting is not currently implemented.

### Implemented authentication workflows

The reusable primitives in `apps/hub-api/src/commitverse_hub/auth/` are
implemented and paired with session-oriented browser auth routes. The current
Hub API includes account registration, login, logout, and current-user
resolution under `/api/v1/auth` and `/api/v1/me`.

Registration requires an exact allow-listed `Origin`. Login requires an
allow-listed `Origin`, and if a session cookie is already present it also
requires the matching session-bound `X-CSRF-Token`. Logout similarly checks
Origin and CSRF for an existing token. Repository mutations require an active
session plus both Origin and CSRF validation. Session cookies use the
configured `Secure`, `HttpOnly`, `SameSite`, path, and expiry attributes; only
the session hash is stored in the database.

- `passwords.py` uses `argon2-cffi` Argon2id with a 64 MiB memory cost,
  three iterations, parallelism four, a 32-byte output, and a 16-byte
  library-generated salt. It rejects empty, non-string, and over-1024-byte
  inputs; verification returns false for incorrect passwords or malformed
  hashes. A rehash check detects outdated or malformed encodings.
- `tokens.py` generates 32-byte (`token_urlsafe(32)`) session secrets,
  validates their canonical encoding, stores their SHA-256 digest, and
  provides constant-time digest comparison. Only the session-issuing caller
  receives the raw token.
- `sessions.py` creates, retrieves, expires, and revokes session records using
  the existing `sessions` table. Retrieval excludes expired, revoked, and
  disabled-user sessions; individual and account-wide revocation use bounded
  SQL updates. Helpers flush or execute within the caller's SQLAlchemy
  transaction and never commit it.
- `cookies.py` centralizes validated cookie attributes and response helpers.
  Defaults are `Secure`, `HttpOnly`, `SameSite=Lax`, path `/`, no domain, and
  a 30-day maximum age. `HttpOnly` cannot be disabled, production rejects an
  insecure cookie, `SameSite=None` requires `Secure`, and wildcard domains are
  rejected.
- `csrf.py` generates a random URL-safe nonce with an HMAC bound to the raw
  session token. Validation uses constant-time comparison and requires an
  exact allow-listed `Origin`; missing/invalid tokens, missing origins, and
  wildcard origin configuration are rejected. Routes pass the current session
  token and an explicit origin allowlist.

Environment-based cookie configuration uses `HUB_SESSION_COOKIE_NAME`,
`HUB_SESSION_COOKIE_SECURE`, `HUB_SESSION_COOKIE_HTTPONLY`,
`HUB_SESSION_COOKIE_SAMESITE`, `HUB_SESSION_COOKIE_PATH`,
`HUB_SESSION_COOKIE_DOMAIN`, and `HUB_SESSION_COOKIE_MAX_AGE`. There is no
default cookie domain or separate CORS middleware configuration. Sessions have
a finite configured expiry, but idle-expiry refresh and password rehashing on
login are not implemented. There is no password reset, email verification,
MFA, account-disable workflow, or rate limiting. Login failures use the same
external message for unknown, disabled, and incorrect-password cases.

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

The implemented repository routes are limited to authenticated personal
owners: list/detail/update/delete queries constrain both repository ID and
`owner_user_id`, require lifecycle state `ready` for normal access, and return
the same not-found response for absent, non-ready, and other-owner records.
Every repository mutation also enforces CSRF/Origin. Public visibility is
metadata only; it does not enable anonymous access.

Use deny-by-default service-level authorization for any added operation. Route
guards and frontend visibility are not sufficient. Organization reads are
scoped to active membership, and organization mutations enforce current
owner/admin restrictions. Direct repository grants and organization-owned
repository HTTP access are not implemented; future behavior must follow the rules in
[`database-design.md`](database-design.md#ownership-and-effective-authorization).
Check lifecycle state and authorization before opening a repository through
Core. Never trust a client-supplied repository path, owner, or role.

Organization members do not automatically gain access to all organization
repositories. The MVP has no teams or complex inherited permission graph.
Document each action's required role and test permission combinations,
revocation, ownership changes, and missing/inconsistent metadata.

## Rate limiting and abuse prevention

Apply limits to login, account creation, invitation issuance/acceptance,
repository creation, and expensive repository reads. These limits are not
implemented. Bound concurrent Core operations and transfer/object sizes. An
in-process counter is not a cross-worker rate limiter; deployment must provide a verified compliant
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

The implemented storage layer creates repositories bare through Core in a
controlled temporary sibling directory, validates before publication, and
publishes only beneath `HUB_REPOSITORY_STORAGE_ROOT`. The root must be a
dedicated path outside the source tree, with private permissions; symlinked
components, unsafe repository paths, and invalid generated keys are rejected.
Deletion verifies the generated key and Core bare-repository structure, and
removes only the exact known repository directory. Failures leave a
recoverable lifecycle state. Storage-root isolation does not defend against a
privileged local attacker or every filesystem race.

Core has supported safe worktree path checks, no-follow tracked reads, atomic
loose-object writes, and single-reference compare-and-swap behavior. These
protections apply to specific Core operations; they do not prove Hub path
isolation, authorize a tenant, prevent every filesystem race, or secure a
hosted multi-user deployment. Hub must validate the storage boundary itself
and test symlink/path traversal attempts.

## Concurrency and bounded execution

The implemented lifecycle operations use synchronous FastAPI handlers so
Core and filesystem work runs outside the ASGI event loop. Database row locks
coordinate lifecycle metadata transitions without relying on process-local
locks. Organization-owned operations always lock the organization before the
repository; personal operations lock the repository. Creation publication and
deletion finalization revalidate state and actor authorization under those
locks. Database transactions are closed before Core or filesystem work.
These locks coordinate database metadata only; shared storage and multi-host
behavior remain deployment-specific and are not verified.

Core's CAS ref update coordinates one reference publication; it is not a
multi-ref/multi-operation transaction and does not coordinate metadata
transactions or every ref writer. PostgreSQL row locks coordinate metadata
transitions across processes, but do not coordinate storage across hosts or
provide multi-host filesystem guarantees. Do not claim safe horizontal scaling
without verifying the shared repository storage and failure behavior.

The current tests cover personal and organization lifecycle behavior,
authorization revalidation, lock ordering, provisioning/publication/cleanup
failures, retry behavior, idempotent cleanup, path/symlink rejection, and
audit transitions. Multi-process database contention, automated stale-state
reconciliation, and bounded execution remain unverified/unimplemented.

## Database and filesystem lifecycle

Repository metadata uses `provisioning`, `ready`, `error`, `deleting`, and
`deleted` states. Exactly one personal-user or organization owner is set.
PostgreSQL and the filesystem do not share an atomic transaction. Creation
reserves metadata and authorizes the current organization role in a committed
transaction, provisions storage outside the transaction, then revalidates
under organization-before-repository locks before publishing `ready` with its
audit event. Deletion similarly commits `deleting` and its audit event before
cleanup, then atomically writes the tombstone, `deleted` state, and final audit
event. Cleanup and finalization have retry paths. An automated reconciler for
abandoned lifecycle records or orphaned directories is not implemented;
reconciliation must compare generated opaque keys, validate paths, and require
explicit policy for ambiguous state; it must never silently delete unknown
data.

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
redaction; backup/restore; and the zero-cost deployment assumptions. Items
explicitly marked unimplemented or unverified above are requirements for a
hosted release, not current evidence.
