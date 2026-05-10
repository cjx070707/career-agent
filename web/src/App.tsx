import React, { FormEvent, useMemo, useRef, useState } from "react";
import {
  BriefcaseBusiness,
  ChevronRight,
  FileSearch,
  MessageSquareText,
  UserRound,
} from "lucide-react";
import type {
  ChatResponse,
  Message,
  ResumeImageParseResponse,
  SavedParsedResumeResponse,
  SessionMeta,
  ViewMode,
} from "./types";
import { sendChat, parseResumeImage, saveParsedResume } from "./api";
import {
  getOrCreateSessionId,
  getOrCreateUserId,
  hasParsedResumeContent,
  newSessionId,
  persistSessionId,
  relativeTime,
} from "./utils";
import { queryStarters } from "./constants";
import { StatusPill } from "./components/StatusPill";
import { ChatView } from "./components/ChatView";
import { QueryView } from "./components/QueryView";
import { EvidencePanel } from "./components/EvidencePanel";

export function App() {
  const [view, setView] = useState<ViewMode>("chat");
  const [userId, setUserId] = useState<string>(getOrCreateUserId);
  const [sessionId, setSessionId] = useState<string>(getOrCreateSessionId);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [queryInput, setQueryInput] = useState(
    "结合我的投递和面试反馈，我下一步该准备什么？",
  );
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
      .then((r) => (r.ok ? r.json() : []))
      .then((data: SessionMeta[]) => setSessions(data))
      .catch(() => {});
  };

  // ── Load messages for a specific session ─────────────────────────────
  const loadSession = (uid: string, sid: string) => {
    setHistoryLoaded(false);
    fetch(`/conversations/${encodeURIComponent(uid)}/sessions/${encodeURIComponent(sid)}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((turns: { id: number; role: string; content: string }[]) => {
        setMessages(
          turns.map((t) => ({
            id: t.id,
            role: (t.role === "user" ? "user" : "agent") as "user" | "agent",
            content: t.content,
          })),
        );
        if (turns.length > 0) {
          nextId.current = Math.max(...turns.map((t) => t.id)) + 1;
        }
        setHistoryLoaded(true);
      })
      .catch(() => setHistoryLoaded(true));
  };

  // On mount / userId change: load sessions, then resume the last open session
  React.useEffect(() => {
    const uid = userId.trim();
    if (!uid) return;

    setHistoryLoaded(false);
    fetch(`/conversations/${encodeURIComponent(uid)}/sessions`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: SessionMeta[]) => {
        setSessions(data);
        if (data.length === 0) {
          setHistoryLoaded(true);
          return;
        }
        // Resume the session that was open when the user left (localStorage),
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
        (tok) =>
          setMessages((current) =>
            current.map((m) => (m.id === streamingId ? { ...m, content: m.content + tok } : m)),
          ),
      );
      window.clearTimeout(timeoutId);
      setMessages((current) =>
        current.map((m) =>
          m.id === streamingId ? { ...m, content: response.answer, response } : m,
        ),
      );
      // Refresh session list so new/updated session appears in sidebar
      loadSessions(userId.trim() || "demo-user");
      setStatusLabel(response.stage === "tool" ? "Ran tools" : "Ready");
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
      setStatusLabel(response.stage === "tool" ? "Ran tools" : "Ready");
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
          {
            id: nextId.current++,
            role: "agent",
            content: "⚠️ 简历解析结果为空，请确认上传了正确的简历图片。",
          },
        ]);
        return;
      }

      // Auto-save to DB
      const saved = await saveParsedResume(userId.trim() || "demo-user", parsed.parsed);
      const name = parsed.parsed.name ? `（${parsed.parsed.name}）` : "";
      const skills = parsed.parsed.skills.slice(0, 5).join("、");
      const skillsLine = skills
        ? `\n- 识别技能：${skills}${parsed.parsed.skills.length > 5 ? " 等" : ""}`
        : "";
      const warnLine =
        parsed.warnings.length > 0
          ? `\n⚠️ 部分字段解析不完整：${parsed.warnings.join("；")}`
          : "";

      setMessages((curr) => [
        ...curr,
        {
          id: nextId.current++,
          role: "agent",
          content: `✅ 简历已解析并保存${name}（ID: ${saved.resume_id}）。${skillsLine}${warnLine}\n\n现在可以问我：\n- "帮我分析和某个 JD 的差距"\n- "我适合哪些 Python 岗位？"`,
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
    if (!resumeImageResult || !hasParsedResumeContent(resumeImageResult.parsed) || isSavingResume)
      return;

    setError(null);
    setIsSavingResume(true);
    try {
      const response = await saveParsedResume(
        userId.trim() || "demo-user",
        resumeImageResult.parsed,
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
          <div className="brand-mark">
            <BriefcaseBusiness size={21} />
          </div>
          <div>
            <strong>Career Agent</strong>
            <span>USYD coaching workspace</span>
          </div>
        </div>

        <label className="field-label" htmlFor="user-id">
          User
        </label>
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
            <button className="new-chat-btn" type="button" onClick={handleNewChat}>
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
              <span className="eyebrow">
                {view === "chat" ? "continuous context" : "single task"}
              </span>
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
