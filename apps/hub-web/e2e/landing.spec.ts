import { expect, test } from "@playwright/test";

test("renders the complete informational page without API requests", async ({ page }) => {
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/v1")) {
      apiRequests.push(request.url());
    }
  });

  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1 })).toContainText("Version control");
  await expect(page.locator("main > section")).toHaveCount(9);
  await expect(page.getByText("Static architecture sketch")).toBeVisible();
  await expect(page.getByText("Future scope · not implemented")).toBeVisible();
  expect(apiRequests).toEqual([]);

  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
});

test("the mobile navigation opens, navigates, and closes", async ({ page }) => {
  test.skip(test.info().project.name !== "mobile-chromium");

  await page.goto("/");
  const menuButton = page.locator(".menu-toggle");
  await menuButton.click();
  await expect(menuButton).toHaveAttribute("aria-expanded", "true");

  await page
    .getByRole("navigation", { name: "Primary navigation" })
    .getByRole("link", {
      name: "Hub",
    })
    .click();
  await expect(page).toHaveURL(/#hub$/);
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");
});

test("theme preference persists across reloads", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("commitverse-theme", "light"));
  await page.reload();
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("system theme is applied before the page renders", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("data-theme-mode", "system");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("reduced-motion preference disables the hero entrance animation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");

  const duration = await page
    .locator(".hero-visual")
    .evaluate((element) => Number.parseFloat(getComputedStyle(element).animationDuration));
  expect(duration).toBeLessThanOrEqual(0.00001);
});
