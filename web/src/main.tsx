import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { createRoot } from "react-dom/client";
import {
  Activity,
  BriefcaseBusiness,
  ChevronDown,
  ChevronRight,
  Clock3,
  FileSearch,
  ListChecks,
  Loader2,
  MessageSquareText,
  Paperclip,
  Send,
  Sparkles,
  UserRound,
} from "lucide-react";
import "./styles.css";

type ChatSource = {
  type: string;
  title: string;
  snippet: string;
  company?: string | null;
  location?: string | null;
  work_type?: string | null;
  posted_at?: string | null;
  url?: string | null;
};

type ChatPlan = {
  task_type: string;
  reason: string;
  steps: string[];
  needs_more_context: boolean;
  missing_context: string[];
  follow_up_question?: string | null;
  planner_source?: string | null;
};

type LLMTrace = {
  planner_source: string;
  job_search_summary_source: string;
  generate_source: string;
};

type ChatResponse = {
  contract_version: "chat.v1";
  answer: string;
  stage: string;
  memory_used: boolean;
  sources: ChatSource[];
  tool_used?: string | null;
  plan?: ChatPlan | null;
  tool_trace: string[];
  loop_trace: Record<string, unknown>[];
  llm_trace: LLMTrace;
};

type ResumeImageParseResponse = {
  type: "resume_image";
  model: string;
  parsed: {
    name?: string | null;
    email?: string | null;
    phone?: string | null;
    education: { school?: string | null; degree?: string | null; dates?: string | null }[];
    skills: string[];
    projects: { name?: string | null; summary?: string | null; technologies: string[] }[];
    experience: { company?: string | null; role?: string | null; dates?: string | null; summary?: string | null }[];
    summary?: string | null;
  };
  raw_text: string;
  warnings: string[];
};

type SavedParsedResumeResponse = {
  resume_id: number;
  candidate_id: number;
  title: string;
  version: string;
  content: string;
};

type Message = {
  id: number;
  role: "user" | "agent";
  content: string;
  response?: ChatResponse;
};

type ViewMode = "query" | "chat";

type SessionMeta = {
  session_id: string;
  title: string;
  created_at: string;
  turn_count: number;
};

const queryStarters = [
  {
    label: "Find jobs",
    prompt: "帮我找一些 Python backend 岗位",
    icon: FileSearch,
  },
  {
    label: "Career diagnosis",
    prompt: "结合我的投递和面试反馈，我下一步该准备什么？",
    icon: Sparkles,
  },
  {
    label: "Applications",
    prompt: "我最近投了哪些岗位？",
    icon: ListChecks,
  },
  {
    label: "Interviews",
    prompt: "我最近面试反馈怎么样？",
    icon: MessageSquareText,
  },
];

async function sendChat(
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
    plan: null,
    tool_trace: [],
    loop_trace: [],
    llm_trace: {} as LLMTrace,
  };
}

async function parseResumeImage(file: File): Promise<ResumeImageParseResponse> {
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

async function saveParsedResume(
  userId: string,
  parsed: ResumeImageParseResponse["parsed"]
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

// ── Stable user_id via localStorage ──────────────────────────────────────
function getOrCreateUserId(): string {
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
function newSessionId(): string {
  return crypto.randomUUID();
}

function getOrCreateSessionId(): string {
  const key = "career-agent-session-id";
  const stored = localStorage.getItem(key);
  if (stored) return stored;
  const id = newSessionId();
  localStorage.setItem(key, id);
  return id;
}

function persistSessionId(id: string): void {
  localStorage.setItem("career-agent-session-id", id);
}

// ── Format a timestamp as relative time ──────────────────────────────────
function relativeTime(iso: string): string {
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

function App() {
  const [view, setView] = useState<ViewMode>("chat");
  const [userId, setUserId] = useState<string>(getOrCreateUserId);
  const [sessionId, setSessionId] = useState<string>(getOrCreateSessionId);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [queryInput, setQueryInput] = useState("结合我的投递和面试反馈，我下一步该准备什么？");
  const [messages, setMessages] = useState<Message[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [queryResult, setQueryResult] = useState<ChatResponse | null>(null);
  const [resumeImageResult, setResumeImageResult] = useState<ResumeImageParseResponse | null>(null);
  const [savedResume, setSavedResume] = useState<SavedParsedResumeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isVisionLoading, setIsVisionLoading] = useState(false);
  const [isSavingResume, setIsSavingResume] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLabel, setStatusLabel] = useState("Ready");
  const nextId = useRef(1);
  const chatAbortRef = useRef<AbortController | null>(null);

  // ── Load session list ─────────────────────────────────────────────────
  const loadSessions = (uid: string) => {
    fetch(`/conversations/${encodeURIComponent(uid)}/sessions`)
      .then((r) => r.ok ? r.json() : [])
      .then((data: SessionMeta[]) => setSessions(data))
      .catch(() => {});
  };

  // ── Load messages for a specific session ─────────────────────────────
  const loadSession = (uid: string, sid: string) => {
    setHistoryLoaded(false);
    fetch(`/conversations/${encodeURIComponent(uid)}/sessions/${encodeURIComponent(sid)}`)
      .then((r) => r.ok ? r.json() : [])
      .then((turns: { id: number; role: string; content: string }[]) => {
        setMessages(
          turns.map((t) => ({
            id: t.id,
            role: (t.role === "user" ? "user" : "agent") as "user" | "agent",
            content: t.content,
          }))
        );
        if (turns.length > 0) {
          nextId.current = Math.max(...turns.map((t) => t.id)) + 1;
        }
        setHistoryLoaded(true);
      })
      .catch(() => setHistoryLoaded(true));
  };

  // On mount / userId change: load sessions, then load most recent session
  useEffect(() => {
    const uid = userId.trim();
    if (!uid) return;

    setHistoryLoaded(false);
    fetch(`/conversations/${encodeURIComponent(uid)}/sessions`)
      .then((r) => r.ok ? r.json() : [])
      .then((data: SessionMeta[]) => {
        setSessions(data);
        if (data.length === 0) {
          // Brand-new user — nothing to load
          setHistoryLoaded(true);
          return;
        }
        // Load the session that was open when the user left (localStorage),
        // falling back to the most recent session.
        const storedSid = localStorage.getItem("career-agent-session-id");
        const target = data.find((s) => s.session_id === storedSid) ?? data[0];
        persistSessionId(target.session_id);
        setSessionId(target.session_id);
        loadSession(uid, target.session_id);
      })
      .catch(() => setHistoryLoaded(true));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  function handleNewChat() {
    const newSid = newSessionId();
    persistSessionId(newSid);
    setSessionId(newSid);
    setMessages([]);
    setChatInput("");
    setError(null);
    setStatusLabel("Ready");
    setResumeImageResult(null);
    setSavedResume(null);
    setHistoryLoaded(true);
    loadSessions(userId.trim() || "demo-user");
  }

  function handleSessionSelect(sid: string) {
    if (sid === sessionId) return;
    persistSessionId(sid);
    setSessionId(sid);
    setMessages([]);
    setError(null);
    setStatusLabel("Ready");
    loadSession(userId, sid);
  }

  const latestResponse = useMemo(() => {
    if (view === "query") return queryResult;
    return [...messages].reverse().find((message) => message.response)?.response ?? null;
  }, [messages, queryResult, view]);

  async function handleChatSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = chatInput.trim();
    if (!trimmed || isLoading) return;
    setError(null);
    setStatusLabel("Thinking");
    setIsLoading(true);
    const userMessage: Message = { id: nextId.current++, role: "user", content: trimmed };
    setMessages((current) => [...current, userMessage]);
    setChatInput("");

    try {
      const controller = new AbortController();
      chatAbortRef.current = controller;
      const timeoutId = window.setTimeout(() => controller.abort(), 120000);

      // Add a placeholder message that gets updated token-by-token
      const streamingId = nextId.current++;
      setMessages((current) => [
        ...current,
        { id: streamingId, role: "agent", content: "", response: undefined },
      ]);

      const response = await sendChat(
        userId.trim() || "demo-user",
        trimmed,
        controller.signal,
        sessionId,
        (text) => setStatusLabel(text),
        (tok) => setMessages((current) =>
          current.map((m) =>
            m.id === streamingId ? { ...m, content: m.content + tok } : m
          )
        ),
      );
      window.clearTimeout(timeoutId);
      setMessages((current) =>
        current.map((m) =>
          m.id === streamingId
            ? { ...m, content: response.answer, response }
            : m
        )
      );
      // Refresh session list so new/updated session appears in sidebar
      loadSessions(userId.trim() || "demo-user");
      if (response.stage === "tool") {
        setStatusLabel("Ran tools");
      } else {
        setStatusLabel("Ready");
      }
    } catch (err) {
      const isAbort = err instanceof DOMException && err.name === "AbortError";
      if (isAbort) {
        setError("Request timed out or canceled. Please try again.");
        setStatusLabel("Timed out");
      } else {
        setError(err instanceof Error ? err.message : "Request failed");
        setStatusLabel("Needs retry");
      }
    } finally {
      chatAbortRef.current = null;
      setIsLoading(false);
    }
  }

  async function handleQuerySubmit(event?: FormEvent) {
    event?.preventDefault();
    const trimmed = queryInput.trim();
    if (!trimmed || isLoading) return;
    setError(null);
    setStatusLabel("Planning");
    setIsLoading(true);
    try {
      const controller = new AbortController();
      chatAbortRef.current = controller;
      const timeoutId = window.setTimeout(() => controller.abort(), 120000);
      const response = await sendChat(
        userId.trim() || "demo-user",
        trimmed,
        controller.signal,
        undefined,
        (text) => setStatusLabel(text),
      );
      window.clearTimeout(timeoutId);
      setQueryResult(response);
      if (response.stage === "tool") {
        setStatusLabel("Ran tools");
      } else {
        setStatusLabel("Ready");
      }
    } catch (err) {
      const isAbort = err instanceof DOMException && err.name === "AbortError";
      if (isAbort) {
        setError("Request timed out or canceled. Please try again.");
        setStatusLabel("Timed out");
      } else {
        setError(err instanceof Error ? err.message : "Request failed");
        setStatusLabel("Needs retry");
      }
    } finally {
      chatAbortRef.current = null;
      setIsLoading(false);
    }
  }

  function cancelChatRequest() {
    if (chatAbortRef.current) {
      chatAbortRef.current.abort();
      chatAbortRef.current = null;
    }
    setIsLoading(false);
    setStatusLabel("Canceled");
  }

  function useStarter(prompt: string) {
    if (view === "query") {
      setQueryInput(prompt);
      return;
    }
    setChatInput(prompt);
  }

  // QueryView path: parse only, user manually clicks "Save as Resume"
  async function handleResumeImageParse(file: File) {
    if (isVisionLoading) return;
    setError(null);
    setResumeImageResult(null);
    setSavedResume(null);
    setIsVisionLoading(true);
    try {
      const response = await parseResumeImage(file);
      setResumeImageResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setIsVisionLoading(false);
    }
  }

  // Chat path: parse → auto-save → insert confirmation message in chat
  async function handleChatResumeUpload(file: File) {
    if (isVisionLoading) return;
    setError(null);
    setIsVisionLoading(true);
    try {
      const parsed = await parseResumeImage(file);
      const hasContent = hasParsedResumeContent(parsed.parsed);

      if (!hasContent) {
        setMessages((curr) => [
          ...curr,
          { id: nextId.current++, role: "agent", content: "⚠️ 简历解析结果为空，请确认上传了正确的简历图片。" },
        ]);
        return;
      }

      // Auto-save to DB
      const saved = await saveParsedResume(userId.trim() || "demo-user", parsed.parsed);
      const name = parsed.parsed.name ? `（${parsed.parsed.name}）` : "";
      const skills = parsed.parsed.skills.slice(0, 5).join("、");
      const skillsLine = skills ? `\n- 识别技能：${skills}${parsed.parsed.skills.length > 5 ? " 等" : ""}` : "";
      const warnLine = parsed.warnings.length > 0
        ? `\n⚠️ 部分字段解析不完整：${parsed.warnings.join("；")}` : "";

      setMessages((curr) => [
        ...curr,
        {
          id: nextId.current++,
          role: "agent",
          content:
            `✅ 简历已解析并保存${name}（ID: ${saved.resume_id}）。${skillsLine}${warnLine}\n\n现在可以问我：\n- "帮我分析和某个 JD 的差距"\n- "我适合哪些 Python 岗位？"`,
        },
      ]);
    } catch (err) {
      setMessages((curr) => [
        ...curr,
        {
          id: nextId.current++,
          role: "agent",
          content: `❌ 简历上传失败：${err instanceof Error ? err.message : "未知错误"}，请重试。`,
        },
      ]);
    } finally {
      setIsVisionLoading(false);
    }
  }

  async function handleSaveParsedResume() {
    if (!resumeImageResult || !hasParsedResumeContent(resumeImageResult.parsed) || isSavingResume) return;

    setError(null);
    setIsSavingResume(true);
    try {
      const response = await saveParsedResume(
        userId.trim() || "demo-user",
        resumeImageResult.parsed
      );
      setSavedResume(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setIsSavingResume(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><BriefcaseBusiness size={21} /></div>
          <div>
            <strong>Career Agent</strong>
            <span>USYD coaching workspace</span>
          </div>
        </div>

        <label className="field-label" htmlFor="user-id">User</label>
        <div className="user-field">
          <UserRound size={17} />
          <input
            id="user-id"
            value={userId}
            onChange={(event) => {
              setUserId(event.target.value);
              localStorage.setItem("career-agent-user-id", event.target.value);
            }}
            placeholder="user_id"
          />
        </div>

        <div className="mode-tabs" role="tablist" aria-label="View mode">
          <button
            className={view === "chat" ? "active" : ""}
            onClick={() => setView("chat")}
            type="button"
          >
            <MessageSquareText size={17} />
            Chat
          </button>
          <button
            className={view === "query" ? "active" : ""}
            onClick={() => setView("query")}
            type="button"
          >
            <FileSearch size={17} />
            Query
          </button>
        </div>

        {view === "chat" ? (
          <>
            <button
              className="new-chat-btn"
              type="button"
              onClick={handleNewChat}
            >
              + 新对话
            </button>
            <div className="session-list">
              {sessions.length === 0 ? (
                <div className="session-empty">暂无历史对话</div>
              ) : (
                sessions.map((s) => (
                  <button
                    key={s.session_id}
                    type="button"
                    className={`session-item${s.session_id === sessionId ? " active" : ""}`}
                    onClick={() => handleSessionSelect(s.session_id)}
                    title={s.title}
                  >
                    <span className="session-title">{s.title}</span>
                    <span className="session-meta">{relativeTime(s.created_at)}</span>
                  </button>
                ))
              )}
            </div>
          </>
        ) : (
          <div className="starter-list">
            {queryStarters.map((item) => {
              const Icon = item.icon;
              return (
                <button key={item.label} type="button" onClick={() => useStarter(item.prompt)}>
                  <Icon size={17} />
                  <span>{item.label}</span>
                  <ChevronRight size={16} />
                </button>
              );
            })}
          </div>
        )}
      </aside>

      <main className="workspace">
        <section className="primary-pane">
          <header className="pane-header">
            <div>
              <span className="eyebrow">{view === "chat" ? "continuous context" : "single task"}</span>
              <h1>{view === "chat" ? "Chat" : "Query"}</h1>
            </div>
            <StatusPill isLoading={isLoading} response={latestResponse} statusLabel={statusLabel} />
          </header>

          {view === "chat" ? (
            <ChatView
              messages={messages}
              historyLoaded={historyLoaded}
              input={chatInput}
              setInput={setChatInput}
              isLoading={isLoading}
              isVisionLoading={isVisionLoading}
              onCancel={cancelChatRequest}
              onSubmit={handleChatSubmit}
              onParseResumeImage={handleChatResumeUpload}
            />
          ) : (
            <QueryView
              input={queryInput}
              setInput={setQueryInput}
              isLoading={isLoading}
              onCancel={cancelChatRequest}
              onSubmit={handleQuerySubmit}
              result={queryResult}
              resumeImageResult={resumeImageResult}
              isVisionLoading={isVisionLoading}
              onParseResumeImage={handleResumeImageParse}
              savedResume={savedResume}
              isSavingResume={isSavingResume}
              onSaveParsedResume={handleSaveParsedResume}
            />
          )}

          {error && <div className="error-banner">{error}</div>}
        </section>

        <EvidencePanel response={latestResponse} />
      </main>
    </div>
  );
}

function StatusPill({
  isLoading,
  response,
  statusLabel,
}: {
  isLoading: boolean;
  response: ChatResponse | null;
  statusLabel: string;
}) {
  if (isLoading) {
    return (
      <span className="status-pill loading">
        <Loader2 size={15} />
        {statusLabel}
      </span>
    );
  }
  return (
      <span className="status-pill">
        <Activity size={15} />
        {response?.stage ?? statusLabel}
      </span>
    );
}

function ChatView({
  messages,
  historyLoaded,
  input,
  setInput,
  isLoading,
  isVisionLoading,
  onCancel,
  onSubmit,
  onParseResumeImage,
}: {
  messages: Message[];
  historyLoaded: boolean;
  input: string;
  setInput: (value: string) => void;
  isLoading: boolean;
  isVisionLoading: boolean;
  onCancel: () => void;
  onSubmit: (event: FormEvent) => void;
  onParseResumeImage: (file: File) => Promise<void>;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handlePaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    const imageItem = Array.from(event.clipboardData.items).find((item) =>
      item.type.startsWith("image/")
    );
    if (!imageItem) return; // let normal text paste fall through
    event.preventDefault();
    const file = imageItem.getAsFile();
    if (!file || isVisionLoading) return;
    await onParseResumeImage(
      new File([file], file.name || "pasted-resume.png", {
        type: file.type || "image/png",
      })
    );
  }

  const showEmpty = historyLoaded && messages.length === 0;

  return (
    <div className="chat-view">
      <div className="message-list">
        {!historyLoaded ? (
          <div className="empty-state">
            <Loader2 size={22} className="spin" />
            <span>Loading history...</span>
          </div>
        ) : showEmpty ? (
          <div className="empty-state">
            <MessageSquareText size={30} />
            <strong>你好！我是你的求职助手。</strong>
            <span className="empty-hint">搜岗位、分析简历差距、制定求职目标，都可以直接问我。</span>
            <div className="empty-upload-hint">
              <span>首次使用建议先上传简历，解锁 gap 分析功能</span>
              <label className="resume-upload-btn" aria-disabled={isVisionLoading}>
                <Paperclip size={15} />
                {isVisionLoading ? "解析中..." : "上传简历"}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,application/pdf"
                  disabled={isVisionLoading}
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    await onParseResumeImage(file);
                    e.currentTarget.value = "";
                  }}
                  style={{ display: "none" }}
                />
              </label>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <span>{message.role === "user" ? "You" : "Agent"}</span>
              {message.role === "agent" ? (
                <div className="md-content">
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                </div>
              ) : (
                <p>{message.content}</p>
              )}
              {message.response ? <MessageDiagnostics response={message.response} /> : null}
            </article>
          ))
        )}
        {isVisionLoading && (
          <div className="vision-status">
            <Loader2 size={16} className="spin" />
            <span>正在解析简历图片...</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form className="composer" onSubmit={onSubmit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onPaste={(e) => void handlePaste(e)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit(e as unknown as FormEvent);
            }
          }}
          placeholder="Ask about jobs, or paste a resume image (Cmd+V)…"
          rows={3}
        />
        <div className="composer-actions">
          <label
            className="composer-attach"
            title="上传简历图片"
            aria-disabled={isVisionLoading}
          >
            {isVisionLoading ? <Loader2 size={17} className="spin" /> : <Paperclip size={17} />}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,application/pdf"
              disabled={isVisionLoading}
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                await onParseResumeImage(file);
                e.currentTarget.value = "";
              }}
              style={{ display: "none" }}
            />
          </label>
          {isLoading ? (
            <button type="button" aria-label="Stop request" className="is-loading" onClick={onCancel}>
              <Loader2 size={19} />
            </button>
          ) : (
            <button type="submit" disabled={!input.trim()} aria-label="Send message">
              <Send size={19} />
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

function MessageDiagnostics({ response }: { response: ChatResponse }) {
  const plan = response.plan;
  const traceItems = [
    `task ${plan?.task_type ?? "—"}`,
    `planner ${plan?.planner_source ?? response.llm_trace.planner_source}`,
    `tool ${response.tool_used ?? "—"}`,
    `memory ${response.memory_used ? "used" : "not used"}`,
  ];
  const llmItems = [
    `summary ${response.llm_trace.job_search_summary_source}`,
    `generate ${response.llm_trace.generate_source}`,
  ];
  const sourceCount = response.sources.length;

  return (
    <details className="message-details">
      <summary>
        <Activity size={15} />
        <span>{response.tool_used ?? plan?.planner_source ?? "trace"}</span>
        <span>{sourceCount} sources</span>
        <ChevronDown size={15} />
      </summary>

      <div className="message-detail-body">
        <div className="message-chip-row">
          {traceItems.map((item) => (
            <strong key={item}>{item}</strong>
          ))}
        </div>
        {response.tool_trace.length ? (
          <div className="message-steps">
            {response.tool_trace.map((step) => (
              <code key={step}>{step}</code>
            ))}
          </div>
        ) : null}
        <div className="message-chip-row secondary">
          {llmItems.map((item) => (
            <strong key={item}>{item}</strong>
          ))}
        </div>
        {plan?.reason ? <p className="message-reason">{plan.reason}</p> : null}
        {response.sources.length ? (
          <div className="message-source-list">
            {response.sources.slice(0, 3).map((source, index) => (
              <a
                key={`${source.title}-${index}`}
                href={source.url ?? undefined}
                target={source.url ? "_blank" : undefined}
                rel={source.url ? "noreferrer" : undefined}
                aria-disabled={source.url ? undefined : true}
              >
                <span>{source.type}</span>
                <strong>{source.title}</strong>
              </a>
            ))}
          </div>
        ) : null}
      </div>
    </details>
  );
}

function QueryView({
  input,
  setInput,
  isLoading,
  onCancel,
  onSubmit,
  result,
  resumeImageResult,
  isVisionLoading,
  onParseResumeImage,
  savedResume,
  isSavingResume,
  onSaveParsedResume,
}: {
  input: string;
  setInput: (value: string) => void;
  isLoading: boolean;
  onCancel: () => void;
  onSubmit: (event?: FormEvent) => void;
  result: ChatResponse | null;
  resumeImageResult: ResumeImageParseResponse | null;
  isVisionLoading: boolean;
  onParseResumeImage: (file: File) => Promise<void>;
  savedResume: SavedParsedResumeResponse | null;
  isSavingResume: boolean;
  onSaveParsedResume: () => Promise<void>;
}) {
  async function onFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    await onParseResumeImage(file);
    event.currentTarget.value = "";
  }

  async function onPaste(event: React.ClipboardEvent<HTMLDivElement>) {
    if (isVisionLoading) return;
    const imageItem = Array.from(event.clipboardData.items).find((item) =>
      item.type.startsWith("image/")
    );
    const file = imageItem?.getAsFile();
    if (!file) return;
    event.preventDefault();
    await onParseResumeImage(
      new File([file], file.name || "pasted-resume-image.png", {
        type: file.type || "image/png",
      })
    );
  }

  const parsed = resumeImageResult?.parsed;
  const hasParsedContent = parsed ? hasParsedResumeContent(parsed) : false;
  return (
    <div className="query-view" onPaste={(event) => void onPaste(event)}>
      <form className="query-form" onSubmit={onSubmit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={5}
          placeholder="Run a single task through /chat"
        />
        {isLoading ? (
          <button type="button" className="is-loading" onClick={onCancel}>
            <Loader2 size={18} />
            Stop
          </button>
        ) : (
          <button type="submit" disabled={!input.trim()}>
            <FileSearch size={18} />
            Run
          </button>
        )}
      </form>
      <div className="answer-panel">
        <div className="section-title">
          <Sparkles size={18} />
          Answer
        </div>
        <p>{result?.answer ?? "Run a query to see the agent response."}</p>
      </div>
      <div className="answer-panel">
        <div className="section-title">
          <FileSearch size={18} />
          Resume Image Parse (MVP)
        </div>
        <label className="field-label" htmlFor="resume-image-upload">Upload or Paste Resume Image</label>
        <input
          id="resume-image-upload"
          type="file"
          accept="image/png,image/jpeg,image/webp,application/pdf"
          onChange={onFileChange}
          disabled={isVisionLoading}
        />
        {isVisionLoading ? <p>Parsing image, this may take up to a minute for dense resume screenshots...</p> : null}
        {resumeImageResult ? (
          <div className="source-list">
            <p><strong>Name:</strong> {parsed?.name || "—"}</p>
            <p><strong>Email:</strong> {parsed?.email || "—"}</p>
            <p><strong>Summary:</strong> {parsed?.summary || "—"}</p>
            <div className="steps-row">
              {(parsed?.skills || []).length ? (
                parsed?.skills.map((skill) => <span key={skill}>{skill}</span>)
              ) : (
                <span>No skills extracted</span>
              )}
            </div>
            {parsed?.projects?.length ? (
              <div className="source-list">
                {parsed.projects.map((project, index) => (
                  <article key={`${project.name || "project"}-${index}`} className="source-card">
                    <h2>{project.name || "Unnamed project"}</h2>
                    <p>{project.summary || "No summary"}</p>
                  </article>
                ))}
              </div>
            ) : null}
            {resumeImageResult.warnings.length ? (
              <div className="muted-box">
                {resumeImageResult.warnings.join(" ")}
              </div>
            ) : null}
            <button
              type="button"
              onClick={() => void onSaveParsedResume()}
              disabled={isSavingResume || !hasParsedContent}
            >
              {isSavingResume ? "Saving..." : "Save as Resume"}
            </button>
            {savedResume ? (
              <p>Saved resume #{savedResume.resume_id} as {savedResume.version}</p>
            ) : null}
          </div>
        ) : (
          <p>Upload one resume screenshot/image, or paste an image with Cmd+V / Ctrl+V.</p>
        )}
      </div>
    </div>
  );
}

function hasParsedResumeContent(parsed: ResumeImageParseResponse["parsed"]): boolean {
  return Boolean(
    parsed.name ||
      parsed.email ||
      parsed.phone ||
      parsed.summary ||
      parsed.skills.length ||
      parsed.projects.length ||
      parsed.experience.length ||
      parsed.education.length
  );
}

function EvidencePanel({ response }: { response: ChatResponse | null }) {
  return (
    <aside className="evidence-pane">
      <TracePanel response={response} />
      <section className="sources-section">
        <div className="section-title">
          <BriefcaseBusiness size={18} />
          Sources
        </div>
        <div className="source-list">
          {response?.sources?.length ? (
            response.sources.map((source, index) => <SourceCard key={`${source.title}-${index}`} source={source} />)
          ) : (
            <div className="muted-box">No sources yet.</div>
          )}
        </div>
      </section>
    </aside>
  );
}

function TracePanel({ response }: { response: ChatResponse | null }) {
  const plan = response?.plan;
  return (
    <section className="trace-section">
      <div className="section-title">
        <Activity size={18} />
        Trace
      </div>
      <div className="trace-grid">
        <TraceItem label="Task" value={plan?.task_type ?? "—"} />
        <TraceItem label="Planner" value={plan?.planner_source ?? "—"} />
        <TraceItem label="Tool" value={response?.tool_used ?? "—"} />
        <TraceItem label="Memory" value={response ? (response.memory_used ? "used" : "not used") : "—"} />
      </div>
      <div className="steps-row">
        {(response?.tool_trace?.length ? response.tool_trace : ["No tools run"]).map((step) => (
          <span key={step}>{step}</span>
        ))}
      </div>
      {plan?.reason && <p className="reason-text">{plan.reason}</p>}
      {response?.llm_trace && (
        <div className="llm-trace">
          <Clock3 size={16} />
          <span>planner {response.llm_trace.planner_source}</span>
          <span>summary {response.llm_trace.job_search_summary_source}</span>
          <span>generate {response.llm_trace.generate_source}</span>
        </div>
      )}
    </section>
  );
}

function TraceItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SourceCard({ source }: { source: ChatSource }) {
  const meta = [source.company, source.location, source.work_type, source.posted_at].filter(Boolean);
  return (
    <article className="source-card">
      <div className="source-head">
        <span>{source.type}</span>
        {source.url ? <a href={source.url} target="_blank" rel="noreferrer">Open</a> : null}
      </div>
      <h2>{source.title}</h2>
      {meta.length ? <p className="source-meta">{meta.join(" · ")}</p> : null}
      <p>{source.snippet}</p>
    </article>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
