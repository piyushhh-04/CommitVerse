# CommitVerse Hub Implementation Roadmap

## Status

This roadmap sequences local Hub development without changing Core's completed
scope. Milestones 2 and 3, the backend and database foundations, are
implemented; subsequent milestones remain planned. Each milestone should be
independently reviewable and tested before the next dependent milestone begins.

## Release scope

### Initial MVP

- Local FastAPI modular-monolith foundation and `/api/v1` REST structure.
- PostgreSQL metadata schema with SQLAlchemy and Alembic.
- Accounts, profiles, and revocable opaque browser sessions.
- Personal repository metadata and organization-owned repository metadata.
- Public/private visibility and direct collaborator grants.
- Bare repository creation and lifecycle through the Core adapter.
- Authorization before Core access.
- Supported metadata and repository browsing APIs.
- Basic React authentication, dashboard, repository list, and repository
  overview.

The MVP does **not** include ordinary Git-client network clone, fetch, or push.
Core has local filesystem transport and local fetch/push/clone library
operations, but no Git-over-HTTP, Git-over-SSH, network Git transport,
packfile transfer, or normal remote Git client interoperability.

### Post-MVP

- Organization membership invitations and refined administration workflows.
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
| 3 | Database and migration foundation; depends on 2 — **implemented** | Add optional PostgreSQL settings, bounded SQLAlchemy engine/session utilities, application lifespan disposal, connectivity diagnostic, and Alembic configuration sharing empty SQLAlchemy metadata. | URL validation/redaction, transaction commit/rollback/closure, injected availability/failure checks, lifecycle/disposal, migration wiring, no startup connection, and full Hub/Core suites. Live PostgreSQL interoperability remains unverified unless a dedicated local server is available. | Application tables, automatic migrations, cloud provisioning, or Git object storage in PostgreSQL. |
| 4 | Accounts and authentication; depends on 3 | Add users, password hashing, opaque session issue/lookup/revoke, login/logout, CSRF and auth dependencies. | Password verification/upgrade, expiry/revocation, cookie flags, CSRF, rate-limit, and generic-error tests. | OAuth, JWT, social login. |
| 5 | Profiles; depends on 4 | Add profile model/service/API and username rules. | Case-insensitive uniqueness, validation, privacy, and authorization tests. | Avatar storage service. |
| 6 | Organizations and repository metadata; depends on 3–5 | Add organizations/memberships, repositories, exclusive owner constraint, visibility, opaque storage key, and lifecycle states. | FK/CHECK/unique/index tests; state-transition and ownership tests. | Teams and complex inherited permissions. |
| 7 | Core adapter; depends on 6 and existing Core package | Add narrow in-process adapter, typed Hub outcomes, and Core exception mapping. | Adapter tests against temporary bare repos; assert Core imports without Hub dependencies. | System Git, GitPython, external Git engine, network protocol. |
| 8 | Bare repository provisioning/lifecycle; depends on 6–7 | Implement `provisioning -> ready/error` and `deleting` workflows, safe publication, cleanup, and reconciliation. | Failure injection at each DB/filesystem step; path traversal/symlink tests; idempotency and recovery tests. | Atomic DB/filesystem transaction claims; cloud storage. |
| 9 | Authorization and direct grants; depends on 4, 6, 8 | Add policy service, direct repository grants, and organization owner/admin/member rules. | Matrix tests for public/private, owner/admin/member, direct roles, revocation, and deny-before-adapter. | Invitation workflows, teams, and broad policy customization. |
| 10 | Repository metadata/browse API; depends on 7–9 | Add authorized `/api/v1` repository list/detail and supported Core-backed browse operations. | API tests for status codes, redaction, authorization-first access, malformed objects, bounded work, and no event-loop blocking. | Git-over-HTTP/SSH, ordinary remote Git clients. |
| 11 | Frontend foundation; depends on API contract from 2/10 | Add React/Tailwind app shell, routing, API client, accessible shared controls. | Production build, route checks, API client tests, accessibility and responsive checks. | Deployment configuration and excessive global state. |
| 12 | Authentication/dashboard UI; depends on 4–5 and 11 | Implement sign-in/up, session bootstrap/logout, profile and dashboard. | Browser tests for session expiry, form errors, loading/empty/error states, keyboard navigation. | Social login and unrelated product screens. |
| 13 | Repository UI; depends on 8–10 and 11 | Implement repository list, creation, and overview screens. | Browser/API integration tests for owner/visibility/permission combinations and lifecycle errors. | Network Git clone/fetch/push controls. |
| 14 | MVP security/reliability audit; depends on 1–13 | Review threat model, authorization, concurrency, lifecycle recovery, logs, data retention and backup/restore. | Explicit path/symlink, contention, failure-injection, recovery, redaction, and restore exercises; resolve high-risk findings before release. | Unsupported security guarantees. |
| 15 | Organization invitations; post-MVP, depends on 4, 6, 9 | Add scoped organization invitations and acceptance/revocation workflows using hashed tokens. | Expiry, replay, email match, authorization, duplicate pending invitation, and concurrent acceptance tests. | Teams and complex permission inheritance. |
| 16 | Network Git protocol; separate post-MVP project | Design and implement authenticated network protocol support using Core, including pack/receive limits and isolation. | Protocol interoperability, auth-before-repository access, malformed input/resource exhaustion, concurrency and compatibility tests. | Delegating to GitPython/system Git or assuming local transport is network transport. |
| 17 | Zero-cost deployment readiness; depends on verified MVP and hosting review | Verify a compliant full Python runtime and filesystem-backed repository storage solution, quotas, backups, and recovery before deployment. | Written evidence that no billing activation/payment/trials/pay-as-you-go are required; quota exhaustion safely pauses/degrades. | Deployment until the Python hosting/storage blocker is resolved. |

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
- Run Core tests without regression when integration changes are made; add Hub
  unit, PostgreSQL integration, API, browser, compatibility, security, and
  failure-injection tests at the appropriate milestone.
- Do not add deployment services, dependencies, or infrastructure without a
  concrete milestone and strict ₹0 review.

## Risks and blockers

- **Deployment blocker:** no verified, approved zero-cost host currently
  supports the complete Python FastAPI application and filesystem-backed Core
  repositories. This blocks deployment readiness, not local development.
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

Stop after the approved architecture and roadmap; do not begin implementation
without the user's approval of the next milestone.
