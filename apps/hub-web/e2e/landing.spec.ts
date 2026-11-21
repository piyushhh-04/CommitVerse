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
  await expect(page.locator("main > section")).toHaveCount(5);
  await expect(
    page.getByRole("img", { name: /Illustrative CommitVerse object and commit graph/ }),
  ).toBeVisible();
  await expect(page.getByText("AI remains future product scope.")).toBeVisible();
  if (await page.getByRole("button", { name: "Open navigation menu" }).isVisible()) {
    await page.getByRole("button", { name: "Open navigation menu" }).click();
  }
  const navigation = page.getByRole("navigation", { name: "Primary navigation" });
  await expect(navigation.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  await expect(navigation.getByRole("link", { name: "Create account" })).toHaveAttribute(
    "href",
    "/register",
  );
  await expect(page.getByText(/Browse authorized trees/)).toBeVisible();
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
      name: "Product",
    })
    .click();
  await expect(page).toHaveURL(/#product$/);
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");
});

test("theme preference persists across reloads", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("commitverse-theme", "light"));
  await page.reload();
  await page.getByRole("radio", { name: "Switch to dark theme" }).click();
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

test("the capability ledger stacks into readable rows at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const rows = page.locator(".capability-row");
  await expect(rows).toHaveCount(3);
  const positions = await rows.evaluateAll((elements) =>
    elements.map((row) => {
      const heading = row.querySelector("h3")?.getBoundingClientRect();
      const copy = row.querySelector("p")?.getBoundingClientRect();
      const status = row.querySelector("span")?.getBoundingClientRect();
      return {
        headingLeft: heading?.left,
        copyLeft: copy?.left,
        statusLeft: status?.left,
        headingTop: heading?.top,
        copyTop: copy?.top,
        statusTop: status?.top,
      };
    }),
  );

  for (const row of positions) {
    expect(row.headingLeft).toBe(row.copyLeft);
    expect(row.copyLeft).toBe(row.statusLeft);
    expect(row.headingTop).toBeLessThan(row.copyTop ?? 0);
    expect(row.copyTop).toBeLessThan(row.statusTop ?? 0);
  }
});

test("reduced-motion preference keeps the hero entrance free of movement", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");

  const animation = await page.locator(".hero-visual").evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      duration: Number.parseFloat(style.animationDuration),
      transform: style.transform,
    };
  });
  expect(animation.duration).toBeLessThanOrEqual(0.12);
  expect(animation.transform).toBe("none");
});
