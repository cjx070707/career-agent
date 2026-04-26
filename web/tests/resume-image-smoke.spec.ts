import { Buffer } from "node:buffer";

import { expect, test } from "@playwright/test";

const parseResponse = {
  type: "resume_image" as const,
  model: "qwen3-vl-flash-2026-01-22",
  parsed: {
    name: "Jesse Chen",
    email: "jesse@example.com",
    phone: null,
    education: [
      {
        school: "University of Sydney",
        degree: "Bachelor of Computer Science",
        dates: "2023-2026",
      },
    ],
    skills: ["Python", "FastAPI", "SQL"],
    projects: [
      {
        name: "Career Agent",
        summary: "Built a FastAPI and RAG based job coaching agent.",
        technologies: ["FastAPI", "SQLite", "ChromaDB"],
      },
    ],
    experience: [],
    summary: "Backend-focused CS student.",
  },
  raw_text: "",
  warnings: [],
};

const saveResponse = {
  resume_id: 12,
  candidate_id: 3,
  title: "Resume parsed from image",
  version: "vision-v1",
  content: "# Parsed Resume\n\nName: Jesse Chen",
};

test("query page can parse and save resume image", async ({ page }) => {
  await page.route("**/vision/resume-image", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(parseResponse),
    });
  });

  await page.route("**/vision/resume-image/save", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(saveResponse),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Query" }).click();

  await page.setInputFiles("#resume-image-upload", {
    name: "resume.png",
    mimeType: "image/png",
    buffer: Buffer.from("fake-image"),
  });

  await expect(page.getByText("Jesse Chen")).toBeVisible();
  await expect(page.locator(".source-card").getByRole("heading", { name: "Career Agent" })).toBeVisible();

  await page.getByRole("button", { name: "Save as Resume" }).click();
  await expect(page.getByText("Saved resume #12 as vision-v1")).toBeVisible();
});
