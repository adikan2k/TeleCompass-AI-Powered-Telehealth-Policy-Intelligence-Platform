import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { mockApi } from "./fixtures";

test("opens on a worked example that is shown but not saved", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/");

  const medicaid = page.getByRole("listitem").filter({ hasText: "Medicaid payment for this modality" });
  await expect(medicaid).toContainText("Not allowed");
  await expect(page.getByText("A worked example, not saved.")).toBeVisible();
  expect(calls[0].store).toBe(false);

  // The example opens one line, so the first screen already shows a quote from the law.
  await expect(
    medicaid.locator("blockquote").filter({ hasText: "does not reimburse telephone conversations" }),
  ).toBeVisible();
  await expect(page.getByText("Not legal advice.").first()).toBeVisible();
});

test("every verdict is a word, never colour alone", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  for (const word of ["Not allowed", "Silent: no rule found", "Allowed"]) {
    await expect(page.getByText(word, { exact: true }).first()).toBeVisible();
  }
});

test("a line opens to the law and its source, and closes again", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  const line = page.getByRole("listitem").filter({ hasText: "Cross-state licensure" });
  const toggle = line.getByRole("button", { name: /the law \(/ });

  await expect(toggle).toHaveAccessibleName("Show the law (1 rule)");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(line.locator("blockquote")).toContainText("A provider may register.");
  await expect(line.getByRole("link", { name: "example.org" })).toBeVisible();

  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(toggle).toHaveAccessibleName("Show the law (1 rule)");
});

test("jumping to the next change re-runs the check and marks what changed", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/");
  await expect(page.getByText("A worked example, not saved.")).toBeVisible();

  await page.getByRole("button", { name: "Next change" }).click();

  await expect(page.getByRole("slider", { name: "Date of the visit" })).toHaveAttribute(
    "aria-valuetext",
    "January 2028",
  );
  const inPerson = page.getByRole("listitem").filter({ hasText: "Medicare: in-person visit requirement" });
  await expect(inPerson).toContainText("Changed. For December 2026 this line read: Allowed.");
  await expect(inPerson).toContainText("1 Jan 2028");
  expect(calls.at(-1)?.body.visit_date).toBe("2028-01-01");
  expect(calls.at(-1)?.store).toBe(false); // still the example, so nothing is stored
});

test("the date tape moves by keyboard", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  const tape = page.getByRole("slider", { name: "Date of the visit" });
  await tape.focus();
  await page.keyboard.press("ArrowRight");
  await expect(tape).toHaveAttribute("aria-valuetext", "January 2027");
  await page.keyboard.press("Home");
  await expect(tape).toHaveAttribute("aria-valuetext", "January 2026");
});

test("checking a visit saves it and gives a link", async ({ page }) => {
  const calls = await mockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Check this visit" }).click();

  await expect(page.getByRole("link", { name: "/d/Ab3xY9pQ2mZk" })).toBeVisible();
  expect(calls.at(-1)?.store).toBe(true);
  expect(calls.at(-1)?.body).toMatchObject({ profession: "psychiatrist", patient_state: "FL" });
});

test("changing the visit marks the answer as out of date until it is checked again", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByText("A worked example, not saved.")).toBeVisible();

  await page.getByText("Live video", { exact: true }).click();
  await expect(page.getByText("The answer below is for the visit before your changes.")).toBeVisible();
  await page.getByRole("button", { name: "Check the changed visit" }).click();
  await expect(page.getByText("The answer below is for the visit before your changes.")).toBeHidden();
});

test("a failed check says so in an alert", async ({ page }) => {
  await mockApi(page, true);
  await page.goto("/");
  // Next.js keeps its own empty route announcer with role="alert"; ours is the one with text.
  const alert = page.getByRole("alert").filter({ hasText: "That did not work." });
  await expect(alert).toContainText("The check failed on the server.");
});

test("no sideways scrolling", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByText("A worked example, not saved.")).toBeVisible();
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(fits).toBe(true);
});

test("works with reduced motion and forced colours", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
  await mockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Next change" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "in-person visit requirement" })).toContainText(
    "Allowed with conditions",
  );
});

test("no detectable accessibility violations, with all the law open", { tag: "@a11y" }, async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByText("A worked example, not saved.")).toBeVisible();
  await page.getByRole("button", { name: "Show all the law" }).click();

  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .exclude("nextjs-portal")
    .analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.length} node(s)`)).toEqual([]);
});
