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
