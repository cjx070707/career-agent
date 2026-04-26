import { expect, test } from "@playwright/test";

const chatResponse = {
  contract_version: "chat.v1" as const,
  answer: "Here is a mocked agent answer.",
  memory_used: false,
  sources: [
    {
      type: "job_posting",
      title: "Backend Engineer Intern",
      snippet: "命中关键词：python、backend",
      company: "USYD CareerHub Partner",
      location: "Sydney",
      work_type: "intern",
      posted_at: null,
      url: null,
    },
  ],
  tool_used: "search_jobs",
  plan: {
    task_type: "job_search",
    reason: "Mocked router plan.",
    steps: ["search_jobs"],
    needs_more_context: false,
    missing_context: [],
    follow_up_question: null,
    planner_source: "router",
  },
  tool_trace: ["search_jobs"],
  llm_trace: {
    planner_source: "router",
    job_search_summary_source: "fallback",
    generate_source: "not_used",
  },
};

test("chat flow renders agent answer and expandable trace details", async ({ page }) => {
  await page.route("**/chat", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(chatResponse),
    });
  });

  await page.goto("/");

  await expect(page.getByText("Career Agent")).toBeVisible();

  const input = page.getByPlaceholder(
    "Ask about jobs, applications, interviews, or next steps"
  );
  await input.fill("帮我找悉尼后端实习");

  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes("/chat") &&
        response.request().method() === "POST" &&
        response.status() === 200
    ),
    page.getByRole("button", { name: "Send message" }).click(),
  ]);

  await expect(page.getByText("Here is a mocked agent answer.")).toBeVisible();

  const agentMessage = page.locator(".message.agent").first();
  const details = agentMessage.locator("details.message-details");
  await expect(details).toHaveCount(1);

  await expect(details.getByText("search_jobs").first()).toBeVisible();
  await expect(details.getByText("1 sources")).toBeVisible();

  await details.locator("summary").click();

  await expect(details.getByText("task job_search")).toBeVisible();
  await expect(details.getByText("planner router")).toBeVisible();
  await expect(details.getByText("tool search_jobs")).toBeVisible();
  await expect(details.getByText("summary fallback")).toBeVisible();
  await expect(details.getByText("Backend Engineer Intern")).toBeVisible();
});
