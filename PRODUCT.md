# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers use CommitVerse Core for local version-control workflows. Local users of CommitVerse Hub manage accounts, repository and organization metadata, memberships, and supported read-only repository browsing. The exact audience segment and team size are not specified.

## Product Purpose

CommitVerse is a custom version-control system and developer collaboration platform. Success means making the implemented Core and Hub workflows understandable and usable without presenting planned capabilities as shipped.

## Positioning

CommitVerse Core implements Git-like internals in Python rather than wrapping the Git executable. Hub keeps account, permission, and collaboration metadata separate from Core repository objects and storage.

## Operating Context

Core is used through local Python workflows and the `cv` CLI. Hub is a local FastAPI application with a React web frontend. The frontend is informational when unauthenticated and uses the Hub API for authenticated workflows.

## Capabilities and Constraints

- Core supports local object, tree, index, staging, commit, refs, history, status, diff, checkout, basic merge, and selected local filesystem transport operations.
- Hub supports account sessions, personal and organization repository metadata, memberships, invitations, authorized read-only browsing, issue and pull-request workflows, reviews, and branch protection.
- Local workflow execution and deterministic repository analysis are exposed through separate APIs. They are not an external CI service or hosted assistant.
- Full Git compatibility, network Git transport, packfiles, conflict resolution, repository writes through Hub, advanced collaboration beyond the listed workflows, and CommitVerse AI are not implemented.
- Hub's filesystem lifecycle uses process-local coordination and is not ready for hosted or multi-worker deployment. A compliant hosting path remains unresolved.
- Preserve the project's strict zero-cost policy. Do not incur charges or introduce paid services or assets.

## Brand Commitments

The CommitVerse name and the identity constraints in `COMMITVERSE_DESIGN_MASTER_PROMPT.md` are binding. Keep the existing font assets and shared token system; record the implemented visual system in `DESIGN.md`.

## Evidence on Hand

The implementation and tests in this repository, especially `PROJECT_CONTEXT.md`, are the source of product truth. There are no confirmed customer quotes, benchmarks, case studies, or production integrations to present. Do not fabricate them.

## Product Principles

- Describe implemented behavior and future work distinctly.
- Keep Core repository data separate from Hub application metadata.
- Preserve authorization and privacy boundaries in every authenticated workflow.
- Keep local development and product operation within the zero-cost policy.
- Do not imply hosted deployment or unsupported Git and AI capabilities.

## Accessibility & Inclusion

The frontend targets WCAG 2.2 AA. Preserve keyboard access, visible focus, readable contrast, reduced-motion support, and responsive use.
