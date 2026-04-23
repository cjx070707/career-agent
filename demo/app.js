const form = document.getElementById("chat-form");
const statusNode = document.getElementById("status");
const answerNode = document.getElementById("answer");
const planNode = document.getElementById("plan");
const sourcesNode = document.getElementById("sources");
const toolTraceNode = document.getElementById("tool-trace");
const llmTraceNode = document.getElementById("llm-trace");
const submitButton = document.getElementById("submit-button");
const messageNode = document.getElementById("message");
const sampleButtons = document.querySelectorAll("button.sample");

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
    emptyItem.className = "muted";
    emptyItem.textContent = "本次没有检索到匹配岗位。";
    sourcesNode.appendChild(emptyItem);
    return;
  }

  for (const source of sources) {
    const item = document.createElement("li");
    const title = document.createElement(source.url ? "a" : "strong");
    if (source.url) {
      title.href = source.url;
      title.target = "_blank";
      title.rel = "noopener noreferrer";
      title.textContent = source.title;
    } else {
      title.textContent = source.title;
    }
    const meta = document.createElement("span");
    meta.className = "muted";
    meta.textContent = `[${source.type}]`;
    const subtitle = document.createElement("p");
    subtitle.className = "muted";
    const parts = [source.company, source.location, source.work_type].filter(Boolean);
    subtitle.textContent = parts.length ? parts.join(" · ") : "";
    const snippet = document.createElement("p");
    snippet.textContent = source.snippet;
    item.appendChild(title);
    item.appendChild(document.createTextNode(" "));
    item.appendChild(meta);
    if (subtitle.textContent) {
      item.appendChild(subtitle);
    }
    item.appendChild(snippet);
    sourcesNode.appendChild(item);
  }
}

function clearOutputsOnError() {
  answerNode.textContent = "";
  answerNode.classList.remove("muted");
  planNode.textContent = "";
  planNode.classList.remove("muted");
  sourcesNode.innerHTML = "";
  toolTraceNode.textContent = "";
  toolTraceNode.classList.remove("muted");
  llmTraceNode.textContent = "";
  llmTraceNode.classList.remove("muted");
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

  let response;
  try {
    response = await fetch("/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    clearOutputsOnError();
    statusNode.textContent = "网络异常，请重试";
    submitButton.disabled = false;
    return;
  }

  let body;
  try {
    body = await response.json();
  } catch (error) {
    clearOutputsOnError();
    statusNode.textContent = `HTTP ${response.status}：响应解析失败，请重试`;
    submitButton.disabled = false;
    return;
  }

  if (!response.ok) {
    clearOutputsOnError();
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : JSON.stringify(body?.detail ?? body ?? "Request failed.");
    statusNode.textContent = `HTTP ${response.status}：${detail}`;
    submitButton.disabled = false;
    return;
  }

  answerNode.classList.remove("muted");
  planNode.classList.remove("muted");
  toolTraceNode.classList.remove("muted");
  llmTraceNode.classList.remove("muted");

  answerNode.textContent = body.answer || "";
  planNode.textContent = renderPlan(body.plan);
  renderSources(body.sources || []);
  toolTraceNode.textContent = JSON.stringify(body.tool_trace || [], null, 2);
  llmTraceNode.textContent = JSON.stringify(body.llm_trace || {}, null, 2);
  statusNode.textContent = "Success.";
  submitButton.disabled = false;
}

for (const button of sampleButtons) {
  button.addEventListener("click", () => {
    const sample = button.dataset.sample || "";
    if (!sample) return;
    messageNode.value = sample;
    messageNode.focus();
    statusNode.textContent = "已填入样例，点 Send 发送。";
  });
}

form.addEventListener("submit", submitChat);
