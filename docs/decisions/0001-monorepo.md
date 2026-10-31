# 0001: Use a modular monorepo

- **Status:** Accepted
- **Date:** 2026-10-31

## Context

CommitVerse is planned as a coordinated product made up of CommitVerse Core,
CommitVerse Hub, and a future CommitVerse AI. At initialization, the project
needs a repository structure that keeps related work discoverable without
coupling component internals.

## Decision

Start with a **modular monorepo**. Keep the product components in one repository
with clear directory and architectural boundaries. Share code only through
intentional, documented interfaces. Keep Core's repository data separate from
Hub's application metadata.

Place the independently installable Core package at
`packages/commitverse-core/`, with Python source under
`packages/commitverse-core/src/commitverse_core/` and tests under
`packages/commitverse-core/tests/{unit,integration,compatibility}/`. Recommend
a package-level `pyproject.toml` for Core configuration and dependency
management. The need and scope of a root-level `pyproject.toml` for
workspace-wide configuration remain undecided.

## Rationale

- A single repository makes project-wide documentation and changes across
  component boundaries easier to coordinate.
- One place for conventions and architectural decisions helps keep the planned
  components consistent.
- Modular boundaries preserve the option to split components into separate
  repositories later if independent ownership, release, or operational needs
  justify doing so.

## Consequences

- Component ownership and interfaces must remain explicit; a monorepo is not a
  reason to share internals indiscriminately.
- Core can be installed and managed as a package without requiring the
  repository root to serve as its Python package configuration.
- Build, test, and dependency management may need to be scoped by component as
  the codebase grows.
- This decision does not prescribe a runtime topology or require every
  component to be deployed together.
- Revisit the decision if the costs of shared repository management exceed its
  coordination benefits.
