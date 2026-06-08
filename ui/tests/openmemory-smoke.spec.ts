import { expect, test } from "@playwright/test";

const apiURL = process.env.MCORE_API_URL || "http://127.0.0.1:8318";

test.describe("MemoryCore UI smoke", () => {
  test("lists, searches, opens, filters, shows stats, and archives a memory", async ({ page, request }) => {
    const marker = `MEMORYCORE-UI-${Date.now()}`;
    const imageErrors: string[] = [];
    page.on("console", (message) => {
      if (
        message.type() === "error" &&
        /empty string.*src|missing required "src"/i.test(message.text())
      ) {
        imageErrors.push(message.text());
      }
    });
    const created = await request.post(`${apiURL}/api/v1/memories`, {
      data: {
        text: `${marker} Playwright smoke memory for MemoryCore UI.`,
        tags: ["playwright", "memorycore-ui"],
        source_agent: "memorycore-smoke-test",
        atomize: false,
      },
    });
    expect(created.ok()).toBeTruthy();
    const memory = await created.json();

    await page.goto("/");
    await expect(page.getByText("Total Memories").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Memory Operations" })).toBeVisible();
    await expect(page.getByText("Curator Schedule")).toBeVisible();
    await expect(page.getByRole("button", { name: /run curator now/i })).toBeVisible();
    await expect(page.getByText("Manual run")).toBeVisible();

    await page.goto("/apps");
    await expect(page.getByRole("heading", { name: "Agents & Clients" })).toBeVisible();
    await expect(page.getByText("Agent Activity")).toBeVisible();
    await expect(page.getByText("Connected Agents")).toBeVisible();

    await page.goto("/settings");
    await expect(page.getByLabel("API URL")).toHaveValue(apiURL);
    await page.getByLabel("API URL").fill(apiURL);
    await page.getByRole("button", { name: /save configuration/i }).click();
    await expect
      .poll(() => page.evaluate(() => window.localStorage.getItem("memorycore.apiUrl")))
      .toBe(apiURL);

    await page.goto(`/memories?search=${encodeURIComponent(marker)}`);
    await expect(page.getByPlaceholder("Search memories...")).toBeVisible();
    await expect(page.getByText(marker)).toBeVisible();

    await page.getByRole("button", { name: /filter/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByText(/apps/i).first()).toBeVisible();
    await page.keyboard.press("Escape");

    await page.goto(`/memory/${memory.id}`);
    await expect(page.getByText(marker)).toBeVisible();
    await page.goto(`/apps/memorycore-smoke-test`);
    await expect(page.getByText(marker)).toBeVisible();
    expect(imageErrors).toEqual([]);

    await page.goto(`/memories?search=${encodeURIComponent(marker)}`);
    const row = page.getByRole("row").filter({ hasText: marker });
    await expect(row).toBeVisible();
    const archived = await request.post(`${apiURL}/api/v1/memories/actions/pause`, {
      data: { memory_ids: [memory.id], state: "archived" },
    });
    expect(archived.ok()).toBeTruthy();

    const detail = await request.get(`${apiURL}/api/v1/memories/${memory.id}`);
    expect(detail.ok()).toBeTruthy();
    expect((await detail.json()).state).toBe("archived");
  });

  test("switches UI language and persists the selected locale", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Language").click();
    await page.getByRole("option", { name: "中文" }).click();

    await expect(page.getByRole("button", { name: "刷新" })).toBeVisible();
    await expect(page.getByRole("link", { name: /记忆/ }).first()).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => window.localStorage.getItem("memorycore.locale")))
      .toBe("zh");

    await page.getByLabel("语言").click();
    await page.getByRole("option", { name: "English" }).click();
    await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
  });
});
