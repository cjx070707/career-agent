import type { ChatResponse, ChatSource, ResumeImageParseResponse, SavedParsedResumeResponse } from "./types";

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
    if (done) break;
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
    tool_trace: [],
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
