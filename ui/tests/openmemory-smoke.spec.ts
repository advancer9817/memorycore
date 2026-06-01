import { expect, test } from "@playwright/test";

const apiURL = process.env.LMMCP_API_URL || "http://127.0.0.1:8318";

test.describe("OpenMemory UI compatibility", () => {
  test("lists, searches, opens, filters, shows stats, and archives a memory", async ({ page, request }) => {
    const marker = `LMMCP-OPENMEMORY-UI-${Date.now()}`;
    const created = await request.post(`${apiURL}/api/v1/memories`, {
      data: {
        text: `${marker} Playwright smoke memory for OpenMemory UI.`,
        tags: ["playwright", "openmemory-ui"],
        source_agent: "openmemory",
        atomize: false,
      },
    });
    expect(created.ok()).toBeTruthy();
    const memory = await created.json();

    await page.goto("/");
    await expect(page.getByText("Memories Stats")).toBeVisible();
    await expect(page.getByText("Total Memories")).toBeVisible();

    await page.goto(`/memories?search=${encodeURIComponent(marker)}`);
    await expect(page.getByPlaceholder("Search memories...")).toBeVisible();
    await expect(page.getByText(marker)).toBeVisible();

    await page.getByRole("button", { name: /filter/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByText(/apps/i).first()).toBeVisible();
    await page.keyboard.press("Escape");

    await page.goto(`/memory/${memory.id}`);
    await expect(page.getByText(marker)).toBeVisible();

    await page.goto(`/memories?search=${encodeURIComponent(marker)}`);
    const row = page.getByRole("row").filter({ hasText: marker });
    await expect(row).toBeVisible();
    await row.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /archive/i }).click();

    const detail = await request.get(`${apiURL}/api/v1/memories/${memory.id}`);
    expect(detail.ok()).toBeTruthy();
    expect((await detail.json()).state).toBe("archived");
  });
});
