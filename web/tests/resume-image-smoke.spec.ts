import { Buffer } from "node:buffer";

import { expect, test } from "@playwright/test";
import { mockJsonPost, openQueryTab } from "./test-helpers";

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
  await mockJsonPost(page, "**/vision/resume-image", parseResponse);
  await mockJsonPost(page, "**/vision/resume-image/save", saveResponse);
  await openQueryTab(page);

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

test("query page disables saving when resume image parse is empty", async ({ page }) => {
  await mockJsonPost(page, "**/vision/resume-image", {
    ...parseResponse,
    parsed: {
      name: null,
      email: null,
      phone: null,
      education: [],
      skills: [],
      projects: [],
      experience: [],
      summary: null,
    },
    warnings: ["Vision parsing failed. Returned empty parsed payload."],
  });
  await openQueryTab(page);

  await page.setInputFiles("#resume-image-upload", {
    name: "resume.png",
    mimeType: "image/png",
    buffer: Buffer.from("fake-image"),
  });

  await expect(page.getByText("Vision parsing failed. Returned empty parsed payload.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save as Resume" })).toBeDisabled();
});
