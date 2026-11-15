# CommitVerse Hub Implementation Roadmap

## Status

This roadmap sequences local Hub development without changing Core's completed
scope. Milestones 2–5 (backend, database, authentication, and profile editing) and milestone 6
(owner-only personal repository management integrated with Core) are
implemented locally. The organization metadata and membership API scope of
milestone 7 is also implemented. Direct grant management and bounded repository
browsing, including validated local branch/tag selection, are implemented
locally. Organization invitation API and token-based frontend workflows are
implemented; repository invitation APIs are implemented without web workflows
or email delivery. Broader collaboration and deployment remain planned. Authentication,
personal repository management, organization metadata/membership workflows, and
owner/admin organization-repository metadata workflows are implemented.
Each milestone should be independently reviewable and tested before the next
dependent milestone begins.

The table numbers are this roadmap's sequence, not release labels: for
example, the personal repository release commit is titled Milestone 4 while
this table lists that scope as item 6. Do not infer completion from numbering
alone.

## Release scope

### Initial MVP

- Local FastAPI modular-monolith foundation and `/api/v1` REST structure.
- PostgreSQL metadata schema with SQLAlchemy and Alembic.
- Account registration/login/logout and revocable opaque browser sessions.
- Authenticated owner-only personal repository metadata and Core-backed
  lifecycle operations.
- Organization metadata and membership APIs with owner/admin role checks.
- Public/private repository visibility with anonymous read-only browsing for
  ready public repositories.
- Direct grant management, repository invitation APIs, and bounded
  tree/blob/history browsing, reachable
  commit details, and first-parent diffs from HEAD and validated local
  branches/tags and privacy-preserving user discovery are implemented.
  Repository invitation UI, advanced diff operations, and broader
  collaboration remain future work.
  Authentication, personal repository management, organization metadata/membership,
  and owner/admin organization-repository metadata workflows are implemented.
- Basic React authentication, dashboard, repository list, and repository
  overview.

The MVP does **not** include ordinary Git-client network clone, fetch, or push.
Core has local filesystem transport and local fetch/push/clone library
operations, but no Git-over-HTTP, Git-over-SSH, network Git transport,
packfile transfer, or normal remote Git client interoperability.

### Post-MVP

- External email delivery, repository invitation web workflows, and refined
  administration workflows.
- Teams only after their membership and permission inheritance rules are
  designed.
- Network Git protocol work as a separately scoped engineering project.
- Issues, pull requests, reviews, notifications, and broader collaboration.
- More advanced repository policy and recovery workflows.

### Long-term vision

Broader Git compatibility, scalable repository storage and operations,
additional collaboration capabilities, and CommitVerse AI. These remain future
work; this roadmap does not imply implementation.

## Milestones

| # | Milestone / dependencies | Objective and expected modules | Tests and acceptance criteria | Explicit exclusions |
|---|---|---|---|---|
| 1 | Architecture and policy approval; no code dependency | Preserve the accepted modular monolith, ownership/permission model, session design, Core boundary, lifecycle, and ₹0 constraints in docs. | Review diagrams, permission rules, deployment blocker, and Core capability claims. | Application scaffolding or deployment. |
| 2 | Local backend foundation; depends on 1 — **implemented** | Hub API package, FastAPI application factory, validated configuration, `/api/v1/health`, request IDs, safe error mapping, and structured logging. | App construction, invalid config, health route, error redaction, and request logging tests pass. | Auth, database schema, Core operations. |
| 3 | Database foundation and approved schema; depends on 2 — **implemented; initial revision historically PostgreSQL-verified** | Add optional PostgreSQL settings, bounded SQLAlchemy engine/session utilities, lifecycle management, database diagnostic, nine approved metadata models, and initial Alembic revision `40037b3edad7`. | URL validation/redaction, constraints and relationships, migration discovery, SQLite test-database upgrade/downgrade/re-upgrade and metadata comparison, no startup migration, and full Hub/Core suites passed. Historical verification against native Homebrew PostgreSQL 17.11 on macOS/Apple Silicon M2 covered `40037b3edad7` only, which was the head at that time. The current source head is `a7d4d1d1f7ed`; its PostgreSQL application status is not verified. See [database-design.md](database-design.md) for the current migration chain. | Authentication/authorization workflows, application APIs, cloud provisioning, or Git object storage in PostgreSQL. |
| 4 | Authentication; depends on 3 — **implemented** | Implement Argon2id registration/login, opaque server-side sessions, current-user resolution, logout/revocation, secure cookies, and session-bound CSRF/Origin checks. | Password, hash-only persistence, session expiry/revocation, generic login failure, cookie, CSRF, SQLite, and PostgreSQL integration tests. | Password reset, email verification, OAuth, JWT, MFA, and rate limiting. |
| 5 | Profile editing; depends on 4 — **implemented locally** | Add profile update service/API and username rules. | Case-insensitive uniqueness, validation, CSRF, privacy, audit logging, frontend settings, and browser integration tests. | Avatar storage service and account recovery. |
| 6 | Personal repository management; depends on 3–4 and existing Core package — **implemented locally** | Add authenticated owner-only create/list/detail/update/delete, safe storage configuration, bare Core provisioning/deletion, lifecycle recovery, and audit events. | API ownership/CSRF/pagination tests; duplicate-name, Core validation, storage containment, symlink, concurrency, failure/retry, and PostgreSQL lifecycle tests. | Network Git, cross-process locking, automated reconciliation. |
| 7 | Organizations and memberships; depends on 4–6 — **implemented locally** | Add organization metadata, membership, scoped invitation create/list/revoke/accept APIs plus token-based frontend workflows, and bounded privacy-preserving user discovery. Owners and admins can update metadata; only owners can change roles or transfer ownership. Admins can add ordinary members and remove ordinary members; owners can manage admins. Ownership transfer requires current-password reauthentication. The service preserves at least one active owner. Owner/admin organization repository metadata HTTP routes and frontend lifecycle workflows are also implemented; ordinary members do not receive implicit repository access. | Domain and API tests cover role restrictions, membership transitions, invitation hashing, expiry, replay, email binding, revocation, user search privacy/bounds, ownership transfer, disabled-organization mutation behavior, repository lifecycle, repository authorization, and rollback. PostgreSQL owner-leave and cross-organization multi-user lock-order tests require `HUB_TEST_DATABASE_URL`; SQLite does not verify PostgreSQL row-lock concurrency. | Organization disable/enable operations and terminal organization deletion; external email delivery, teams, repository invitation web workflows, repository contents, and complex inherited permissions. |
| 8 | Authorization and direct grants; depends on 4, 6–7 — **implemented locally for current browse operations** | Add manager-controlled direct repository grants with reader/writer/admin roles, revocation, audit events, and effective authorization for supported reads. | Owner/admin authorization, duplicate and inactive-user rejection, role changes, revocation, CSRF, audit, deny-before-manager, and direct-reader browse tests pass. | Teams, broad policy customization. |
| 9 | Repository browsing API; depends on 6–8 — **partially implemented locally** | Add authorized supported Core-backed metadata, tree, bounded text-blob, commit-history, reachable commit-detail, and first-parent diff operations for HEAD and validated local branches/tags. | Redaction, malformed objects, traversal rejection, authorization-first access, bounded execution, empty repository behavior, ref selection, commit detail/diff, frontend detail integration, and browser/API suites pass. | Advanced diff workflows, Git-over-HTTP/SSH, ordinary remote Git clients. |
| 10 | Frontend foundation; depends on API contract from 2/9 — **implemented locally** | Add React/Tailwind app shell, routing, API client, accessible shared controls. | Production build, route checks, API client tests, accessibility and responsive checks. | Deployment configuration and excessive global state. |
| 11 | Authentication/dashboard UI; depends on 4–5 and 10 | Implement sign-in/up, session bootstrap/logout, profile and dashboard. | Browser tests for session expiry, form errors, loading/empty/error states, keyboard navigation. | Social login and unrelated product screens. |
| 12 | Repository UI; depends on 8–10 | Implement repository list, creation, and overview screens. | Browser/API integration tests for owner/visibility/permission combinations and lifecycle errors. | Network Git clone/fetch/push controls. |
| 13 | MVP security/reliability audit; depends on 1–12 | Review threat model, authorization, concurrency, lifecycle recovery, logs, data retention and backup/restore. | Explicit path/symlink, contention, failure-injection, recovery, redaction, and restore exercises; resolve high-risk findings before release. | Unsupported security guarantees. |
| 14 | Organization invitations; post-MVP, depends on 4, 7–8 | Add scoped organization invitations and acceptance/revocation workflows using hashed tokens. | Expiry, replay, email match, authorization, duplicate pending invitation, and concurrent acceptance tests. | Teams and complex permission inheritance. |
| 15 | Network Git protocol; separate post-MVP project | Design and implement authenticated network protocol support using Core, including pack/receive limits and isolation. | Protocol interoperability, auth-before-repository access, malformed input/resource exhaustion, concurrency and compatibility tests. | Delegating to GitPython/system Git or assuming local transport is network transport. |
| 16 | Zero-cost deployment readiness; depends on verified MVP and hosting review | Verify a compliant full Python runtime and filesystem-backed repository storage solution, quotas, backups, and recovery before deployment. | Written evidence that no billing activation/payment/trials/pay-as-you-go are required; quota exhaustion safely pauses/degrades. | Deployment until the Python hosting/storage blocker is resolved. |

## Cross-cutting engineering rules

- Keep Core independently usable and unmodified by Hub-specific business rules.
- Check authorization before invoking Core; deny when metadata is missing,
  inconsistent, or not `ready`.
- Use generated opaque storage identifiers and validate all resolved paths
  beneath the configured root.
- Coordinate operations per repository, execute synchronous Core work through
  bounded workers outside the ASGI event loop, and test failure/cancellation.
- A process-local lock is not cross-process coordination. Do not scale
  repository operations across workers until a cross-process strategy is
  implemented and tested.
- Treat PostgreSQL/filesystem workflows as recoverable state machines, not one
  atomic transaction.
- Mutations on existing organizations lock the organization before
  membership/user rows; multi-user operations lock user rows in ascending
  UUID order; validate the actor and role inside the transaction; and commit
  audit events with their state changes. The active-owner invariant covers
  organization mutations using this lock protocol. Hub has no
  account-deactivation workflow; future deactivation must coordinate with
  organization ownership, and independent account-state writes bypassing the
  protocol are not covered. PostgreSQL concurrency guarantees require the
  conditional PostgreSQL tests, not SQLite-only results.
- PostgreSQL organization concurrency tests require
  `HUB_TEST_DATABASE_URL`; without it, row-lock and last-owner concurrency
  remain unverified.
- Run Core tests without regression when integration changes are made; add Hub
  unit, PostgreSQL integration, API, browser, compatibility, security, and
  failure-injection tests at the appropriate milestone.
- Do not add deployment services, dependencies, or infrastructure without a
  concrete milestone and strict ₹0 review.

## Risks and blockers

- **Deployment blocker:** no verified, approved zero-cost host currently
  supports the complete Python FastAPI application and filesystem-backed Core
  repositories. This blocks deployment readiness, not local development.
- **Local database verification:** historical PostgreSQL 17.11 validation
  covered initial revision `40037b3edad7` via native Homebrew installation on
  macOS/Apple Silicon. Current source head `a7d4d1d1f7ed` is not verified
  against PostgreSQL. Docker is not required for this setup and remains an
  optional future infrastructure tool.
- **Protocol gap:** local transport and library operations are not network Git
  protocols. Normal Git clients cannot yet clone/fetch/push to Hub.
- **Cross-store lifecycle:** database and filesystem partial failure requires
  idempotency, visible error states, and reconciliation.
- **Concurrency:** Core CAS is single-ref publication, not a hosted operation
  transaction. Per-repository coordination and cross-process behavior need
  explicit design and tests.
- **Recovery:** repository and metadata backups must be coordinated and
  restore-tested before valuable user data is accepted.
- **Permission complexity:** keep organization members without a direct grant
  from implicitly seeing every organization repository; test effective access
  after membership, ownership, or grant changes.

Milestones marked implemented above are complete within their stated local
scope. Begin later milestones only after their scope and implementation are
approved.
