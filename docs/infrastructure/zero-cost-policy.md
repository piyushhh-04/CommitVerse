# CommitVerse Strict Zero-Cost Infrastructure Policy

## Status

This is a permanent project constraint. CommitVerse must not require or incur
any payment.

The policy applies to development, testing, deployment, hosting, storage, and
application services. Planned infrastructure remains unimplemented until the
relevant development stage and must not be represented as currently provisioned.

## Non-negotiable constraints

CommitVerse must not use:

- credit cards or payment methods
- pay-as-you-go billing
- paid subscriptions or paid add-ons
- automatic upgrades
- trial credits or promotional credits as a required dependency

When a free quota is exhausted, the affected feature must pause, degrade
gracefully, or be migrated. It must never incur a charge.

No credential, billing, or infrastructure configuration should be added solely
to prepare for a future service.

## Approved planned infrastructure

The approved zero-cost direction is:

| Area | Approved plan | Status |
|---|---|---|
| Frontend | Cloudflare Pages Free | Planned, not provisioned |
| Lightweight API endpoints | Cloudflare Workers Free only | Planned, not provisioned |
| Application database | Neon PostgreSQL Free | Planned, not provisioned |
| Core objects and repository data | Local filesystem during development | Current development approach |
| Source and collaboration | GitHub | Current project hosting |

Cloudflare Workers must not run the full Python CommitVerse Git engine.
CommitVerse Core remains a local Python package during its current development
stages.

## Explicitly excluded

- Cloudflare R2, unless a genuinely no-billing configuration becomes possible
- AWS
- Render
- Fly.io
- Railway
- Supabase; Neon is the selected PostgreSQL service

These exclusions apply to the strict zero-billing architecture and are not
reopened by a future feature request without an explicit architecture decision.

## Deferral rule

Hosting, deployment, database provisioning, and cloud storage implementation
are deliberately deferred until their appropriate development stage. Product
logic and Core repository behavior must not acquire cloud dependencies merely
because a service is planned.

