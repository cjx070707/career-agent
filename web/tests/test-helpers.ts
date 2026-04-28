import { Page } from "@playwright/test";

export async function mockJsonPost(
  page: Page,
  endpointGlob: string,
  body: unknown
): Promise<void> {
  await page.route(endpointGlob, async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

export async function openQueryTab(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: "Query" }).click();
}
