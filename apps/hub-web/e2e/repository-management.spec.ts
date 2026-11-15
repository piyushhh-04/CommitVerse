import { expect, test, type Page } from "@playwright/test";

const authenticatedUser = {
  id: "browser-user",
  email: "browser@example.test",
  username: "browser",
  display_name: "Browser Developer",
};

const repositoryId = "6f577861-febc-4c87-8949-e92014711401";

function repository(name: string, description: string | null, visibility: "private" | "public") {
  return {
    id: repositoryId,
    name,
    description,
    visibility,
    created_at: "2026-11-15T10:00:00Z",
    updated_at: "2026-11-15T10:00:00Z",
  };
}

async function installRepositoryApi(page: Page) {
  let currentRepository: ReturnType<typeof repository> | null = null;
  let deleteRequests = 0;
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "X-CSRF-Token": "browser-csrf" },
      body: JSON.stringify(authenticatedUser),
    }),
  );
  await page.route("**/api/v1/repositories**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/v1/repositories") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: currentRepository ? [currentRepository] : [],
          total: currentRepository ? 1 : 0,
          limit: 50,
          offset: 0,
        }),
      });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/v1/repositories") {
      expect(request.postDataJSON()).toEqual({
        name: "browser-project",
        description: null,
        visibility: "private",
      });
      currentRepository = repository("browser-project", null, "private");
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(currentRepository),
      });
      return;
    }
    if (url.pathname === `/api/v1/repositories/${repositoryId}`) {
      if (request.method() === "GET" && currentRepository) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(currentRepository),
        });
        return;
      }
      if (request.method() === "PATCH" && currentRepository) {
        expect(request.postDataJSON()).toEqual({
          name: "renamed-project",
          visibility: "public",
        });
        currentRepository = repository("renamed-project", null, "public");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(currentRepository),
        });
        return;
      }
      if (request.method() === "DELETE") {
        deleteRequests += 1;
        if (deleteRequests === 1) {
          await route.fulfill({
            status: 503,
            contentType: "application/json",
            body: JSON.stringify({
              error: {
                code: "repository_unavailable",
                message: "Repository deletion is pending safe storage cleanup; retry the request.",
              },
              request_id: "browser-delete-retry",
            }),
          });
          return;
        }
        currentRepository = null;
        await route.fulfill({ status: 204 });
        return;
      }
    }
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "repository_not_found", message: "Repository not found." },
        request_id: "browser-not-found",
      }),
    });
  });
  return () => deleteRequests;
}

test("repository create, edit, responsive layout, and delete retry work in the browser", async ({
  page,
}) => {
  const getDeleteRequests = await installRepositoryApi(page);
  await page.goto("/app/repositories/new");
  await page.getByLabel("Repository name").fill("Browser-Project");
  await page.getByRole("button", { name: "Create repository" }).click();

  await expect(page).toHaveURL(new RegExp(`/app/repositories/${repositoryId}$`));
  await expect(page.getByRole("heading", { name: "browser-project" })).toBeVisible();
  await expect(page.getByText(/anonymous repository access is not available/i)).toBeVisible();

  await page.getByLabel("Repository name").fill("renamed-project");
  await page.getByLabel("Description (optional)").fill("");
  await page.getByRole("radio", { name: /Public/ }).check();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status")).toContainText("Changes saved.");
  await expect(page.getByRole("heading", { name: "renamed-project" })).toBeVisible();

  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);

  const deleteButton = page.getByRole("button", { name: "Delete repository" });
  await deleteButton.click();
  await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(deleteButton).toBeFocused();
  await deleteButton.click();
  await page.getByRole("button", { name: "Confirm deletion" }).click();
  await expect(page.getByRole("alert")).toContainText("deletion may still be pending");
  await page.getByRole("button", { name: "Retry deletion" }).click();

  await expect(page).toHaveURL(/\/app\/repositories$/);
  await expect(
    page.getByRole("heading", { name: "Your repositories will live here." }),
  ).toBeVisible();
  expect(getDeleteRequests()).toBe(2);
});
