# CommitVerse Hub Web

The standalone CommitVerse landing page and design system. This app is
informational only: it has no authentication UI, API client, live repository
data, or backend dependency.

## Requirements

- Node.js 26 LTS
- npm 11

From this directory:

```sh
npm ci
npm run dev
```

The Vite server listens on `http://127.0.0.1:5173`. Its development-only
`/api/v1` proxy targets `http://127.0.0.1:8000`; override the target with
`HUB_API_PROXY_TARGET` when needed. The landing page does not currently use
that proxy. Before adding browser API calls, configure the Hub API's exact
origin allow-list for the Vite origin and review the CSRF/session integration.
The proxy is not included in production builds.

## Checks

```sh
npm run typecheck
npm run lint
npm test
npm run test:e2e
npm run build
npm run format:check
```

Playwright uses Chromium at 360px, 768px, and 1440px. Install its browser once
after `npm ci` if it is not already present:

```sh
npx playwright install chromium
```

## Design and assets

- Fraunces for display typography, Inter for interface text, and JetBrains Mono
  for technical labels. The Latin WOFF2 assets are self-hosted under
  `public/fonts/`; their SIL Open Font Licenses are included beside them.
- Theme preference supports light, dark, and system modes. A small head script
  applies the stored preference before the page styles render to reduce theme
  flash.
- The hero SVG is a static illustration of the actual local Core object flow;
  it does not display live repository state.
- Motion is CSS-only, brief, and disabled for reduced-motion preferences.
- Open Graph title/description metadata is included. A canonical URL and
  absolute social preview image should be added after the public site domain is
  selected.
