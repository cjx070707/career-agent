const form = document.getElementById("chat-form");
const statusNode = document.getElementById("status");
const answerNode = document.getElementById("answer");
const planNode = document.getElementById("plan");
const sourcesNode = document.getElementById("sources");
const toolTraceNode = document.getElementById("tool-trace");
const llmTraceNode = document.getElementById("llm-trace");
const submitButton = document.getElementById("submit-button");

function renderPlan(plan) {
  if (!plan) {
    return "No plan returned.";
  }

  const lines = [
    `task_type: ${plan.task_type}`,
    `planner_source: ${plan.planner_source ?? "not_set"}`,
    `reason: ${plan.reason}`,
    `steps: ${(plan.steps ?? []).join(" -> ") || "(none)"}`,
    `needs_more_context: ${String(plan.needs_more_context)}`,
  ];

  if (plan.missing_context?.length) {
    lines.push(`missing_context: ${plan.missing_context.join(", ")}`);
  }
  if (plan.follow_up_question) {
    lines.push(`follow_up_question: ${plan.follow_up_question}`);
  }

  return lines.join("\n");
}

function renderSources(sources) {
  sourcesNode.innerHTML = "";
  if (!sources?.length) {
    const emptyItem = document.createElement("li");
    emptyItem.textContent = "No sources.";
    sourcesNode.appendChild(emptyItem);
    return;
  }

  for (const source of sources) {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `${source.title} `;
    const meta = document.createElement("span");
    meta.className = "muted";
    meta.textContent = `[${source.type}]`;
    const snippet = document.createElement("p");
    snippet.textContent = source.snippet;
    item.appendChild(title);
    item.appendChild(meta);
    item.appendChild(snippet);
    sourcesNode.appendChild(item);
  }
}

async function submitChat(event) {
  event.preventDefault();

  const formData = new FormData(form);
  const payload = {
    user_id: String(formData.get("user_id") || "").trim(),
    message: String(formData.get("message") || "").trim(),
  };

  if (!payload.user_id || !payload.message) {
    statusNode.textContent = "user_id and message are required.";
    return;
  }

  submitButton.disabled = true;
  statusNode.textContent = "Calling /chat...";

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const body = await response.json();

    if (!response.ok) {
      throw new Error(body.detail || "Request failed.");
    }

    answerNode.textContent = body.answer || "";
    planNode.textContent = renderPlan(body.plan);
    renderSources(body.sources || []);
    toolTraceNode.textContent = JSON.stringify(body.tool_trace || [], null, 2);
    llmTraceNode.textContent = JSON.stringify(body.llm_trace || {}, null, 2);
    statusNode.textContent = "Success.";
  } catch (error) {
    answerNode.textContent = "";
    planNode.textContent = "";
    sourcesNode.innerHTML = "";
    toolTraceNode.textContent = "";
    llmTraceNode.textContent = "";
    statusNode.textContent = error instanceof Error ? error.message : "Request failed.";
  } finally {
    submitButton.disabled = false;
  }
}

form.addEventListener("submit", submitChat);
