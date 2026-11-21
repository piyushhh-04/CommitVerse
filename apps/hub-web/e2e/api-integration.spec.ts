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
  await expect(page.getByRole("heading", { name: "Welcome, Integration Developer" })).toBeVisible();
  await expect(page.getByText("Integration Developer", { exact: true })).toBeVisible();
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
  await expect(page.getByRole("heading", { name: "Repositories", exact: true })).toBeVisible();
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

test("personal repository creation, editing, and deletion use the real API", async ({ page }) => {
  const suffix = Date.now().toString();
  await page.goto("/register");
  await page.getByLabel("Email address").fill(`repository-${suffix}@example.test`);
  await page.getByLabel("Username").fill(`repository${suffix}`);
  await page.getByRole("textbox", { name: "Password" }).fill("repository integration password");
  await page.getByRole("button", { name: "Create your account" }).click();
  await expect(page).toHaveURL(/\/app$/);

  await page
    .getByRole("navigation", { name: "Application navigation" })
    .getByRole("link", { name: "Repositories" })
    .click();
  await expect(page.getByRole("heading", { name: "Repositories", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "New repository" }).click();
  await expect(page).toHaveURL(/\/app\/repositories\/new$/);
  await expect(page.getByRole("heading", { name: "New repository" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Repository name").pressSequentially(`browser-project-${suffix}`);
  await expect(page.getByLabel("Repository name")).toHaveValue(`browser-project-${suffix}`);
  await page.getByLabel("Description (optional)").fill("A description to clear.");
  await page.getByRole("button", { name: "Create repository" }).click();

  await expect(page).toHaveURL(/\/app\/repositories\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: `browser-project-${suffix}` })).toBeVisible();
  await page.getByLabel("Repository name").fill(`renamed-${suffix}`);
  await page.getByLabel("Description (optional)").fill("");
  await page.getByRole("radio", { name: /Public/ }).check();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status")).toContainText("Changes saved.");
  await expect(page.getByRole("heading", { name: `renamed-${suffix}` })).toBeVisible();
  await expect(page.locator(".repository-detail-header .repository-visibility-tag")).toHaveText(
    "public",
  );
  await expect(page.locator(".repository-detail-description")).toHaveText(
    "No description provided.",
  );

  await page.getByRole("button", { name: "Delete repository" }).click();
  await page.getByRole("button", { name: "Confirm deletion" }).click();
  await expect(page).toHaveURL(/\/app\/repositories$/);
  await expect(
    page.getByRole("heading", { name: "Your repositories will live here." }),
  ).toBeVisible();
});

test("profile settings update the authenticated account through the real API", async ({ page }) => {
  const suffix = Date.now().toString();
  await page.goto("/register");
  await page.getByLabel("Email address").fill(`profile-${suffix}@example.test`);
  await page.getByLabel("Username").fill(`profile${suffix}`);
  await page.getByLabel("Display name (optional)").fill("Profile Developer");
  await page.getByRole("textbox", { name: "Password" }).fill("profile integration password");
  await page.getByRole("button", { name: "Create your account" }).click();
  await expect(page).toHaveURL(/\/app$/);

  await page.getByRole("link", { name: "Profile settings" }).click();
  await expect(page).toHaveURL(/\/app\/settings\/profile$/);
  await page.getByLabel("Username").fill(`updatedprofile${suffix}`);
  await page.getByLabel("Display name").fill("Updated Profile Developer");
  await page.getByLabel(/Bio/).fill("Building a more personal CommitVerse.");
  await page.getByRole("button", { name: "Save profile" }).click();

  await expect(page.getByRole("status")).toHaveText("Profile saved.");
  await expect(page.getByRole("link", { name: "Profile settings" })).toBeVisible();
});

test("repository owners manage direct access and invite a user to browse a private repository", async ({
  browser,
  page,
}) => {
  const suffix = Date.now().toString();
  const ownerEmail = `repository-owner-${suffix}@example.test`;
  const ownerUsername = `repoowner${suffix}`;
  const inviteeEmail = `repository-invitee-${suffix}@example.test`;
  const inviteeUsername = `repoinvitee${suffix}`;

  await page.goto("/register");
  await page.getByLabel("Email address").fill(ownerEmail);
  await page.getByLabel("Username").fill(ownerUsername);
  await page.getByLabel("Display name (optional)").fill("Repository Owner");
  await page
    .getByRole("textbox", { name: "Password" })
    .fill("repository owner integration password");
  await page.getByRole("button", { name: "Create your account" }).click();
  await expect(page).toHaveURL(/\/app$/);

  const inviteeContext = await browser.newContext();
  const inviteePage = await inviteeContext.newPage();
  try {
    await inviteePage.goto("/");
    const registration = await inviteePage.evaluate(
      async ({ email, username }) => {
        const response = await fetch("/api/v1/auth/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email,
            password: "repository invitee integration password",
            username,
            display_name: "Repository Invitee",
          }),
        });
        return { status: response.status, body: await response.json() };
      },
      { email: inviteeEmail, username: inviteeUsername },
    );
    expect(registration.status).toBe(200);

    await page.getByRole("link", { name: "Repositories" }).click();
    await page.getByRole("link", { name: "New repository" }).click();
    await expect(page).toHaveURL(/\/app\/repositories\/new$/);
    await expect(page.getByRole("heading", { name: "New repository" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await page.getByLabel("Repository name").pressSequentially(`shared-${suffix}`);
    await expect(page.getByLabel("Repository name")).toHaveValue(`shared-${suffix}`);
    await page.getByRole("button", { name: "Create repository" }).click();
    await expect(page.getByRole("heading", { name: `shared-${suffix}` })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Repository access" })).toBeVisible();

    const userSearch = page.getByRole("textbox", {
      name: "Search users to grant repository access",
    });
    await userSearch.fill("Repository Invitee");
    await page.getByRole("button", { name: `Repository Invitee (@${inviteeUsername})` }).click();
    await page.getByRole("button", { name: "Grant access" }).click();
    const roleSelector = page.getByRole("combobox", {
      name: `Access role for Repository Invitee (@${inviteeUsername})`,
    });
    await expect(roleSelector).toHaveValue("reader");
    await roleSelector.selectOption("writer");
    await expect(roleSelector).toHaveValue("writer");
    await page.getByRole("button", { name: "Revoke access" }).click();
    await page.getByRole("button", { name: "Confirm revoke" }).click();
    await expect(page.getByText("No direct collaborators have access yet.")).toBeVisible();

    await page.getByRole("textbox", { name: "Invitation email" }).fill(inviteeEmail);
    await page.getByRole("button", { name: "Create invitation" }).click();
    const invitationToken = await page
      .locator(".repository-access-section .organization-invitation-token code")
      .textContent();
    expect(invitationToken).toBeTruthy();

    await inviteePage.goto("/app/repositories/invitations/accept");
    await expect(
      inviteePage.getByRole("heading", { name: "Accept a repository invitation" }),
    ).toBeVisible();
    await inviteePage
      .getByRole("textbox", { name: "Repository invitation token" })
      .fill(invitationToken ?? "");
    await inviteePage.getByRole("button", { name: "Accept invitation" }).click();

    await expect(inviteePage).toHaveURL(/\/app\/repository-browser\/[0-9a-f-]+$/);
    await expect(inviteePage.getByText(/Repository ID:/)).toContainText("Repository ID:");
    await expect(inviteePage.getByText("Empty repository")).toBeVisible();
  } finally {
    await inviteeContext.close();
  }
});
