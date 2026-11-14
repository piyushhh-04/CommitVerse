import { expect, test, type Page } from "@playwright/test";

const authenticatedUser = {
  id: "browser-user",
  email: "browser@example.test",
  username: "browser",
  display_name: "Browser Developer",
};

function installAnonymousSession(page: Page) {
  return page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "authentication_required", message: "Authentication required." },
        request_id: "browser-anonymous",
      }),
    }),
  );
}

test("login submits through the API client and returns to a protected destination", async ({
  page,
}) => {
  await installAnonymousSession(page);
  await page.route("**/api/v1/auth/login", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      email: "browser@example.test",
      password: "browser-password",
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "X-CSRF-Token": "browser-csrf" },
      body: JSON.stringify(authenticatedUser),
    });
  });

  await page.goto("/app/repositories");
  await expect(
    page.getByText("Sign in is required to continue to your requested page."),
  ).toBeVisible();
  await page.getByLabel("Email address").fill("browser@example.test");
  await page.getByRole("textbox", { name: "Password" }).fill("browser-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/app\/repositories$/);
  await expect(page.getByRole("heading", { name: "Repositories" })).toBeVisible();
  if (test.info().project.name === "mobile-chromium") {
    await page.locator(".app-menu-toggle").click();
  }
  await expect(page.getByText("Browser Developer")).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
});

test("registration submits only supported fields and handles backend errors", async ({ page }) => {
  await installAnonymousSession(page);
  await page.route("**/api/v1/auth/register", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      email: "browser@example.test",
      username: "browser",
      display_name: "Browser Developer",
      password: "browser-password",
    });
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "account_exists", message: "An account with this email already exists." },
        request_id: "browser-conflict",
      }),
    });
  });

  await page.goto("/register");
  await page.getByLabel("Email address").fill("browser@example.test");
  await page.getByLabel("Username").fill("browser");
  await page.getByLabel("Display name (optional)").fill("Browser Developer");
  await page.getByRole("textbox", { name: "Password" }).fill("browser-password");
  await page.getByRole("button", { name: "Create your account" }).click();

  await expect(page.getByRole("alert")).toContainText("An account with this email already exists.");
});

test("mobile application navigation is keyboard accessible and logout returns to sign in", async ({
  page,
}) => {
  test.skip(test.info().project.name !== "mobile-chromium");

  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "X-CSRF-Token": "browser-csrf" },
      body: JSON.stringify(authenticatedUser),
    }),
  );
  await page.route("**/api/v1/auth/logout", async (route) => {
    expect(await route.request().headerValue("x-csrf-token")).toBe("browser-csrf");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok" }),
    });
  });

  await page.goto("/app");
  await expect(page.getByRole("heading", { name: "Your workspace" })).toBeVisible();
  const menuButton = page.locator(".app-menu-toggle");
  await menuButton.focus();
  await page.keyboard.press("Enter");
  await expect(menuButton).toHaveAttribute("aria-expanded", "true");

  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  const repositoriesLink = page
    .getByRole("navigation", { name: "Application navigation" })
    .getByRole("link", { name: "Repositories" });
  await expect(repositoriesLink).toBeFocused();
  await page.keyboard.press("Enter");

  const destinationHeading = page.getByRole("heading", { name: "Repositories" });
  await expect(page).toHaveURL(/\/app\/repositories$/);
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");
  await expect(destinationHeading).toBeVisible();
  await expect(destinationHeading).toBeFocused();
  expect(
    await destinationHeading.evaluate((element) => getComputedStyle(element).outlineStyle),
  ).not.toBe("none");
  await expect(page.locator("#app-navigation a:focus")).toHaveCount(0);

  await page.goBack();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByRole("heading", { name: "Your workspace" })).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/\/app\/repositories$/);
  await expect(destinationHeading).toBeVisible();

  await menuButton.click();
  await page.keyboard.press("Escape");
  await expect(menuButton).toBeFocused();
  await menuButton.click();
  await page
    .getByRole("navigation", { name: "Application navigation" })
    .getByRole("button", { name: "Sign out" })
    .click();

  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("modified mobile navigation clicks preserve the open menu and visible focus", async ({
  page,
}) => {
  test.skip(test.info().project.name !== "desktop-chromium");
  await page.setViewportSize({ width: 360, height: 800 });

  await page.context().route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "X-CSRF-Token": "browser-csrf" },
      body: JSON.stringify(authenticatedUser),
    }),
  );

  await page.goto("/app");
  const menuButton = page.locator(".app-menu-toggle");
  await menuButton.focus();
  await page.keyboard.press("Enter");

  const repositoriesLink = page
    .getByRole("navigation", { name: "Application navigation" })
    .getByRole("link", { name: "Repositories" });
  await repositoriesLink.focus();

  const tabModifier = process.platform === "darwin" ? "Meta" : "Control";
  for (const modifier of [tabModifier, "Shift"] as const) {
    const newPagePromise = page.context().waitForEvent("page");
    await repositoriesLink.click({ modifiers: [modifier] });
    const newPage = await newPagePromise;
    try {
      await expect(newPage).toHaveURL(/\/app\/repositories$/);
      await expect(page).toHaveURL(/\/app$/);
      await expect(menuButton).toHaveAttribute("aria-expanded", "true");
      await expect(repositoriesLink).toBeVisible();
      await expect(repositoriesLink).toBeFocused();
      await expect(page.getByRole("heading", { name: "Your workspace" })).not.toBeFocused();
    } finally {
      await newPage.close();
    }
  }
});

test("desktop application navigation remains visible and does not steal focus", async ({
  page,
}) => {
  test.skip(test.info().project.name !== "desktop-chromium");

  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "X-CSRF-Token": "browser-csrf" },
      body: JSON.stringify(authenticatedUser),
    }),
  );

  await page.goto("/app");
  const repositoriesLink = page
    .getByRole("navigation", { name: "Application navigation" })
    .getByRole("link", { name: "Repositories" });
  await expect(repositoriesLink).toBeVisible();
  await repositoriesLink.click();

  await expect(page).toHaveURL(/\/app\/repositories$/);
  await expect(repositoriesLink).toBeVisible();
  await expect(repositoriesLink).toBeFocused();
  await expect(page.getByRole("heading", { name: "Repositories" })).not.toBeFocused();
});
