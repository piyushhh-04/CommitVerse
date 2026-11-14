# CommitVerse Hub Web

The CommitVerse landing page and authenticated Hub application. Sign-in,
registration, session restoration, and the authenticated application shell are
implemented. Repository and organization data views remain neutral
placeholders; product-management workflows are not implemented yet.

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
`HUB_API_PROXY_TARGET` when needed. The public landing page does not use that proxy or make session requests.
Authenticated routes use a centralized same-origin API client, the Hub API's
cookie session, and its session-bound CSRF header. Session credentials are not
stored in `localStorage` or `sessionStorage`; the browser manages the session
cookie as an HttpOnly cookie. CSRF tokens remain in memory and are not persisted
in browser storage. The proxy is not included in production builds.

## Frontend foundation

- React Router separates the public landing page from account and protected
  application routes. Protected routes restore `/api/v1/me` before rendering
  and preserve the requested location when redirecting an anonymous user.
- TanStack Query owns the in-memory session cache and provides bounded retries
  for transient query failures. Mutations are not retried automatically.
- The typed API client preserves backend error codes, validation details, and
  request IDs; it sends same-origin cookies and attaches the in-memory CSRF
  token to mutations.
- `/login` and `/register` use the backend's email/password and
  email/password/username/optional-display-name contracts. Credentials are
  submitted through `AuthProvider` and are not written to browser storage.
- Protected `/app/*` routes share a responsive shell with dashboard,
  repository, and organization navigation, current-user information, theme
  control, and logout. Dashboard, repository, and organization content is
  still placeholder-only; no product-management workflow is implemented.

## Checks

```sh
npm run typecheck
npm run lint
npm test
npm run test:e2e
npm run test:api-integration
npm run build
npm run format:check
```

Playwright uses Chromium at 360px, 768px, and 1440px. Install its browser once
after `npm ci` if it is not already present:

```sh
npx playwright install chromium
```

The API integration test starts a disposable FastAPI process and two isolated
Vite origins. It uses a temporary SQLite database, permits only
`http://127.0.0.1:4174` in that test server's Origin allow-list, and verifies
the real browser-to-proxy-to-API session, CSRF, secure-cookie, reload, and
disallowed-Origin behavior. It does not change the Hub API's default or
production configuration. The server and temporary database are stopped and
removed when Playwright exits. Run it from this directory; it requires the
repository-root `.venv` with the Hub API package installed.

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
