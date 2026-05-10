import type { ResumeImageParseResponse } from "./types";

// ── Stable user_id via localStorage ──────────────────────────────────────
export function getOrCreateUserId(): string {
  const key = "career-agent-user-id";
  const stored = localStorage.getItem(key);
  if (stored) return stored;
  const id = Array.from(crypto.getRandomValues(new Uint8Array(4)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  localStorage.setItem(key, id);
  return id;
}

// ── Session ID per conversation ───────────────────────────────────────────
export function newSessionId(): string {
  return crypto.randomUUID();
}

export function getOrCreateSessionId(): string {
  const key = "career-agent-session-id";
  const stored = localStorage.getItem(key);
  if (stored) return stored;
  const id = newSessionId();
  localStorage.setItem(key, id);
  return id;
}

export function persistSessionId(id: string): void {
  localStorage.setItem("career-agent-session-id", id);
}

// ── Format a timestamp as relative time ──────────────────────────────────
export function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  return new Date(iso).toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

// ── Guard: has the parsed resume any extractable content? ─────────────────
export function hasParsedResumeContent(parsed: ResumeImageParseResponse["parsed"]): boolean {
  return Boolean(
    parsed.name ||
      parsed.email ||
      parsed.phone ||
      parsed.summary ||
      parsed.skills.length ||
      parsed.projects.length ||
      parsed.experience.length ||
      parsed.education.length,
  );
}
