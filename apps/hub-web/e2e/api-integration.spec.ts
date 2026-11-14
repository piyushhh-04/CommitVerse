import { expect, test } from "@playwright/test";

test("browser sessions survive reload and enforce CSRF and exact Origin", async ({
  browser,
  page,
  context,
}) => {
  const email = `browser-${Date.now()}@example.test`;
  await page.goto("/");

  const registration = await page.evaluate(async (accountEmail) => {
    const response = await fetch("/api/v1/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: accountEmail,
        password: "integration test password",
        username: `browser${Date.now()}`,
      }),
    });
    return {
      status: response.status,
      csrfToken: response.headers.get("X-CSRF-Token"),
      body: await response.json(),
    };
  }, email);

  expect(registration.status).toBe(200);
  expect(registration.csrfToken).toBeTruthy();

  const sessionCookie = (await context.cookies()).find(
    (cookie) => cookie.name === "commitverse_session",
  );
  expect(sessionCookie).toBeDefined();
  expect(sessionCookie?.httpOnly).toBe(true);
  expect(sessionCookie?.secure).toBe(true);
  expect(sessionCookie?.sameSite).toBe("Lax");
  expect(JSON.stringify(registration.body)).not.toContain(sessionCookie?.value);
  expect(await page.evaluate(() => document.cookie)).not.toContain("commitverse_session=");

  const csrfToken = registration.csrfToken;
  if (!csrfToken) {
    throw new Error("Registration did not return a CSRF token.");
  }

  const missingCsrf = await page.evaluate(async () => {
    const response = await fetch("/api/v1/organizations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slug: "missing-csrf",
        name: "Missing CSRF",
      }),
    });
    return { status: response.status, body: await response.json() };
  });
  expect(missingCsrf.status).toBe(403);
  expect(missingCsrf.body.error.code).toBe("csrf_validation_failed");

  const createdOrganization = await page.evaluate(async (token) => {
    const response = await fetch("/api/v1/organizations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
      },
      body: JSON.stringify({
        slug: "browser-org",
        name: "Browser Organization",
      }),
    });
    return { status: response.status, body: await response.json() };
  }, csrfToken);
  expect(createdOrganization.status).toBe(201);
  expect(createdOrganization.body.slug).toBe("browser-org");

  await page.reload();
  const restoredSession = await page.evaluate(async () => {
    const response = await fetch("/api/v1/me");
    return {
      status: response.status,
      csrfToken: response.headers.get("X-CSRF-Token"),
      body: await response.json(),
    };
  });
  expect(restoredSession.status).toBe(200);
  expect(restoredSession.body.email).toBe(email);
  expect(restoredSession.csrfToken).toBeTruthy();

  const disallowedOriginPage = await browser.newPage();
  try {
    await disallowedOriginPage.goto("http://127.0.0.1:4175/");
    const originRejection = await disallowedOriginPage.evaluate(async () => {
      const response = await fetch("/api/v1/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: `disallowed-${Date.now()}@example.test`,
          password: "integration test password",
          username: `disallowed${Date.now()}`,
        }),
      });
      return { status: response.status, body: await response.json() };
    });
    expect(originRejection.status).toBe(403);
    expect(originRejection.body.error.code).toBe("origin_not_allowed");
  } finally {
    await disallowedOriginPage.close();
  }
});

test("the centralized API client uses the Vite proxy, cookie session, and CSRF header", async ({
  page,
}) => {
  await page.goto("/");

  const result = await page.evaluate(async (clientModulePath) => {
    const { apiClient } = await import(clientModulePath);
    const suffix = Date.now().toString();
    const email = `api-client-${suffix}@example.test`;
    const registered = await apiClient.post("/auth/register", {
      email,
      password: "integration test password",
      username: `apiclient${suffix}`,
    });
    const slug = `api-client-${suffix}`;
    const organization = await apiClient.post("/organizations", {
      slug,
      name: "API Client Integration",
    });
    const currentUser = await apiClient.get("/me");

    return {
      registeredEmail: registered?.email,
      organizationSlug: organization?.slug,
      currentUserEmail: currentUser?.email,
      hasCsrfToken: apiClient.hasCsrfToken,
      documentCookie: document.cookie,
    };
  }, "/src/api/client.ts");

  expect(result.registeredEmail).toMatch(/^api-client-.*@example\.test$/);
  expect(result.organizationSlug).toMatch(/^api-client-\d+$/);
  expect(result.currentUserEmail).toBe(result.registeredEmail);
  expect(result.hasCsrfToken).toBe(true);
  expect(result.documentCookie).not.toContain("commitverse_session=");
});

test("authentication screens register, log in, navigate, and revoke real API sessions", async ({
  page,
  context,
}) => {
  const suffix = Date.now().toString();
  const email = `auth-screen-${suffix}@example.test`;
  const username = `authscreen${suffix}`;
  const password = "authentication screen integration password";
  const logoutCsrfTokens: string[] = [];

  page.on("request", (request) => {
    if (request.url().endsWith("/api/v1/auth/logout")) {
      logoutCsrfTokens.push(request.headers()["x-csrf-token"] ?? "");
    }
  });

  await page.goto("/register");
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Display name (optional)").fill("Integration Developer");
  await page.getByRole("textbox", { name: "Password" }).fill(password);
  await page.getByRole("button", { name: "Create your account" }).click();

  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByRole("heading", { name: "Your workspace" })).toBeVisible();
  await expect(page.getByText("Integration Developer")).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Application navigation" }).getByRole("link", {
      name: "Repositories",
    }),
  ).toBeVisible();

  const registrationCookie = (await context.cookies()).find(
    (cookie) => cookie.name === "commitverse_session",
  );
  expect(registrationCookie?.httpOnly).toBe(true);
  expect(registrationCookie?.secure).toBe(true);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await context.cookies()).some((cookie) => cookie.name === "commitverse_session")).toBe(
    false,
  );

  await page.goto("/app/repositories");
  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByText("Sign in is required to continue to your requested page."),
  ).toBeVisible();

  await page.getByLabel("Email address").fill(email);
  await page.getByRole("textbox", { name: "Password" }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/app\/repositories$/);
  await expect(page.getByRole("heading", { name: "Repositories" })).toBeVisible();
  await expect(page.getByText("Integration Developer")).toBeVisible();
  expect((await context.cookies()).some((cookie) => cookie.name === "commitverse_session")).toBe(
    true,
  );

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await context.cookies()).some((cookie) => cookie.name === "commitverse_session")).toBe(
    false,
  );
  expect(logoutCsrfTokens).toHaveLength(2);
  expect(logoutCsrfTokens.every((token) => token.length > 0)).toBe(true);

  await page.goto("/app");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});
