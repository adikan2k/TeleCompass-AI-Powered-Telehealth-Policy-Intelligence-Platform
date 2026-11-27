import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { mockChanges } from "./fixtures";

test("shows page changes, approved rule changes and dates ahead", async ({ page }) => {
  const asked = await mockChanges(page);
  await page.goto("/changes");

  await expect(page.getByRole("heading", { name: "What changed for you", level: 1 })).toBeVisible();
  const florida = page.getByRole("article", { name: "Florida" });
  await expect(florida.getByText("21 May 2026")).toBeVisible();
  await expect(florida.getByText("190 days apart")).toBeVisible();
  await expect(florida.getByRole("listitem").filter({ hasText: "Remote Patient Monitoring" })).toContainText(
    "rule added",
  );
  await expect(florida.getByRole("listitem").filter({ hasText: "Store and Forward" })).toContainText(
    "waiting for review",
  );
  await expect(florida.getByText("+ Added")).toBeVisible();
  await expect(florida.locator("blockquote")).toContainText("reimburses remote monitoring");

  const federal = page.getByRole("article", { name: "Federal (Medicare)" });
  await expect(federal).toContainText("30 Jan 2027");
  await expect(federal).toContainText("in 64 days");
  await expect(page.getByText("Not legal advice.").first()).toBeVisible();
  expect(asked[0].get("states")).toBe("FL");
  expect(asked[0].get("care")).toBe("behavioral_health");
});

test("a change of kind is told by its word, not its colour alone", async ({ page }) => {
  await mockChanges(page);
  await page.goto("/changes");
  const florida = page.getByRole("article", { name: "Florida" });
  await expect(florida.getByText("New entry", { exact: false }).first()).toBeVisible();
  await expect(florida.getByText("Entry removed", { exact: false }).first()).toBeVisible();
});

test("choosing another line of care asks again", async ({ page }) => {
  const asked = await mockChanges(page);
  await page.goto("/changes");
  await expect(page.getByRole("article", { name: "Florida" })).toBeVisible();

  await page.getByRole("radio", { name: "Other care" }).check();

  await expect.poll(() => asked.at(-1)?.get("care")).toBe("other");
});

test("the dated law opens on request", async ({ page }) => {
  await mockChanges(page);
  await page.goto("/changes");
  const federal = page.getByRole("article", { name: "Federal (Medicare)" });
  const quote = federal.locator("blockquote");

  await expect(quote).toBeHidden();
  await federal.getByText("The law", { exact: true }).click();
  await expect(quote).toContainText("Through January 30, 2027");
});

test("has no detectable accessibility problems", async ({ page }) => {
  await mockChanges(page);
  await page.goto("/changes");
  await expect(page.getByRole("article", { name: "Florida" })).toBeVisible();
  await page.waitForTimeout(800); // let the rows finish fading in
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .exclude("nextjs-portal")
    .analyze();
  expect(results.violations).toEqual([]);
});
