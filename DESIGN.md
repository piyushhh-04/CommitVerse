# CommitVerse Hub design system

## Direction

CommitVerse uses an editorial developer-tool interface: warm paper and ink surfaces,
Fraunces for product and page headlines, Inter for interface text, and JetBrains Mono
for repository identifiers and code. The visual language is deliberately restrained:
hairline borders, ledger rows, small status markers, and peach/sage accents explain
state without turning the product into a card wall.

## Tokens

The source of truth is [apps/hub-web/src/index.css](apps/hub-web/src/index.css).

- Light canvas `#f7f6f2`, surface `#fcfbf8`, sunken surface `#efede6`, ink `#20211f`.
- Dark canvas `#161715`, surface `#1e1f1d`, raised surface `#262826`, ink `#f1efe8`.
- Muted text is `#5a5c55` in light and `#a8aaa2` in dark.
- Peach marks emphasis and current state; sage marks positive or ready state.
- `--cv-border` is the hairline; `--cv-border-strong` is used for controls.
- Spacing uses the existing 4px-based `--space-*` scale.
- Radii are defined by `--radius-xs` through `--radius-pill`; controls use the small end
  of the scale and status chips may use the pill value.
- Motion uses `--cv-ease-out`, `--cv-ease-in-out`, `--cv-ease-drawer`, and the
  `--cv-dur-*` durations. The landing hero uses one staged entrance; application
  navigation and controls use short compositor-safe transitions.

## Type

- Fraunces: landing hero, authenticated page titles, empty-state and closing headlines.
- Inter: body copy, navigation, controls, forms, and dense application content.
- JetBrains Mono: hashes, paths, refs, code, diffs, and technical labels.
- Body text is at least 15px by default; mobile form controls remain at least 16px.

## Layout and interaction

The public page has a single-column mobile composition and a two-column desktop hero.
The authenticated app uses a desktop navigation rail and a full-height mobile navigation
panel below 1024px. The panel traps focus, closes on Escape and route changes, returns
focus to its trigger, and restores body scrolling.

Application data is presented as ledgers and stacked rows at narrow widths. Visibility,
role, and state are communicated with text plus shape or border, never color alone.
Focus rings use `--cv-focus`; hover styles are gated to fine pointers. Reduced motion
removes positional animation while retaining brief opacity and color feedback.

## Product truth

The landing page describes the implemented local Core and Hub capabilities only. It
does not imply hosted deployment, external CI, network Git transport, or a hosted AI
assistant. Product boundaries are maintained in [PRODUCT.md](PRODUCT.md).
