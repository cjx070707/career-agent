import type { Application, ChatResponse, ChatSource, Goal, ResumeData, ResumeImageParseResponse, SavedParsedResumeResponse } from "./types";

export async function authRegister(username: string, password: string): Promise<{ token: string; username: string }> {
  const r = await fetch("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const body = await r.json();
  if (!r.ok) throw new Error(body.detail || "注册失败");
  return body;
}

export async function authLogin(username: string, password: string): Promise<{ token: string; username: string }> {
  const r = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const body = await r.json();
  if (!r.ok) throw new Error(body.detail || "登录失败");
  return body;
}

export async function sendChat(
  userId: string,
  message: string,
  signal: AbortSignal,
  sessionId?: string,
  onStatus?: (text: string) => void,
  onToken?: (text: string) => void,
): Promise<ChatResponse> {
  const response = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, message, session_id: sessionId ?? null }),
    signal,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answerEvent: Record<string, unknown> | null = null;
  let streamedText = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done || signal.aborted) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (!raw) continue;
      let event: Record<string, unknown>;
      try {
        event = JSON.parse(raw);
      } catch {
        continue;
      }
      if (event.type === "status") {
        onStatus?.(String(event.text ?? ""));
      } else if (event.type === "token") {
        const tok = String(event.text ?? "");
        streamedText += tok;
        onToken?.(tok);
      } else if (event.type === "answer") {
        answerEvent = event;
      } else if (event.type === "error") {
        throw new Error(String(event.text ?? "Server error"));
      }
    }
  }

  // Flush any remaining buffer content (handles streams that don't end with \n)
  if (buffer.trim()) {
    const raw = buffer.startsWith("data: ") ? buffer.slice(6).trim() : buffer.trim();
    if (raw) {
      try {
        const event = JSON.parse(raw) as Record<string, unknown>;
        if (event.type === "answer") answerEvent = event;
        else if (event.type === "token") streamedText += String(event.text ?? "");
      } catch { /* ignore */ }
    }
  }

  // If aborted by user, throw AbortError regardless of buffered content
  if (signal.aborted) {
    throw new DOMException("Aborted by user", "AbortError");
  }

  if (!answerEvent) {
    throw new Error("No answer received from server");
  }

  // Prefer streamed text; fall back to answer.text for non-streaming clients
  const finalText = streamedText || String(answerEvent.text ?? "");

  return {
    contract_version: "chat.v1",
    answer: finalText,
    stage: String(answerEvent.stage ?? "direct"),
    memory_used: Boolean(answerEvent.memory_used),
    tool_used: (answerEvent.tool_used as string | null) ?? null,
    sources: (answerEvent.sources as ChatSource[]) ?? [],
    tool_trace: (answerEvent.tool_trace as string[]) ?? [],
  };
}

export async function parseResumeImage(file: File): Promise<ResumeImageParseResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch("/vision/resume-image", {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }
  return response.json();
}

export async function fetchApplications(userId: string): Promise<Application[]> {
  const r = await fetch(`/applications?user_id=${encodeURIComponent(userId)}&limit=50`);
  if (!r.ok) return [];
  return r.json();
}

export async function createApplication(data: {
  candidate_id: number; company: string; job_title: string; status: string; note?: string;
}): Promise<Application> {
  const r = await fetch('/applications', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const body = await r.json();
  if (!r.ok) throw new Error(body.detail || 'Failed');
  return body;
}

export async function updateApplicationStatus(id: number, status: string, note?: string): Promise<void> {
  await fetch(`/applications/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, note }) });
}

export async function deleteApplication(id: number): Promise<void> {
  const r = await fetch(`/applications/${id}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`删除失败 (${r.status})`);
}

export async function fetchGoals(userId: string): Promise<Goal[]> {
  const r = await fetch(`/goals?user_id=${encodeURIComponent(userId)}`);
  if (!r.ok) return [];
  return r.json();
}

export async function createGoal(userId: string, goalText: string): Promise<Goal> {
  const r = await fetch('/goals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId, goal_text: goalText }) });
  return r.json();
}

export async function completeGoal(goalId: number): Promise<void> {
  await fetch(`/goals/${goalId}/complete`, { method: 'PATCH' });
}

export async function fetchUserResume(userId: string): Promise<ResumeData | null> {
  const r = await fetch(`/resumes?user_id=${encodeURIComponent(userId)}`);
  if (!r.ok) return null;
  const data = await r.json();
  return Array.isArray(data) ? (data[0] ?? null) : (data ?? null);
}

export async function fetchCandidate(userId: string): Promise<{ id: number } | null> {
  const r = await fetch(`/candidates?user_id=${encodeURIComponent(userId)}`);
  if (!r.ok) return null;
  const data = await r.json();
  return Array.isArray(data) ? (data[0] ?? null) : null;
}

export interface JobMatch {
  job_title: string;
  match_score: number;
  matched_keywords: string[];
  rationale: string;
}

export async function fetchJobMatches(resumeId: number): Promise<JobMatch[]> {
  const r = await fetch('/matches/resume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume_id: resumeId }),
  });
  if (!r.ok) return [];
  const data = await r.json();
  return data.matches ?? [];
}

export async function saveParsedResume(
  userId: string,
  parsed: ResumeImageParseResponse["parsed"],
): Promise<SavedParsedResumeResponse> {
  const response = await fetch("/vision/resume-image/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: userId,
      title: "Resume parsed from image",
      version: "vision-v1",
      parsed,
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }
  return response.json();
}
