import React, { FormEvent, useMemo, useRef, useState } from "react";
import {
  BriefcaseBusiness,
  CheckSquare,
  FileText,
  Home,
  LogOut,
  MessageSquareText,
  Briefcase,
} from "lucide-react";
import type {
  ChatResponse,
  Message,
  NavPage,
  ResumeImageParseResponse,
  SavedParsedResumeResponse,
  SessionMeta,
} from "./types";
import { sendChat, parseResumeImage, saveParsedResume, saveMessage } from "./api";
import {
  getOrCreateSessionId,
  hasParsedResumeContent,
  newSessionId,
  persistSessionId,
  relativeTime,
} from "./utils";
import { StatusPill } from "./components/StatusPill";
import { ChatView } from "./components/ChatView";
import { EvidencePanel } from "./components/EvidencePanel";
import { AuthPage } from "./components/AuthPage";
import { DashboardPage } from "./components/DashboardPage";
import { JobTrackingPage } from "./components/JobTrackingPage";
import { ResumePage } from "./components/ResumePage";
import { GoalsPage } from "./components/GoalsPage";

// ── Auth helpers ──────────────────────────────────────────────────────────────
function getStoredAuth(): { username: string; token: string } | null {
  const username = localStorage.getItem("career-agent-username");
  const token = localStorage.getItem("career-agent-token");
  if (username && token) return { username, token };
  return null;
}

const NAV_ITEMS: { page: NavPage; label: string; icon: React.ElementType }[] = [
  { page: "dashboard", label: "首页", icon: Home },
  { page: "chat", label: "AI 对话", icon: MessageSquareText },
  { page: "track", label: "求职追踪", icon: Briefcase },
  { page: "resume", label: "我的简历", icon: FileText },
  { page: "goals", label: "我的目标", icon: CheckSquare },
];

export function App() {
  const [auth, setAuth] = useState<{ username: string; token: string } | null>(getStoredAuth);
  const [navPage, setNavPage] = useState<NavPage>("dashboard");
  const [sessionId, setSessionId] = useState<string>(getOrCreateSessionId);
  const userId = auth?.username ?? "guest";

  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [resumeVersion, setResumeVersion] = useState(0);
  const [chatInput, setChatInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isVisionLoading, setIsVisionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLabel, setStatusLabel] = useState("就绪");
  const nextId = useRef(1);
  const chatAbortRef = useRef<AbortController | null>(null);
  const userCanceledRef = useRef(false);

  // ── Auth handlers ─────────────────────────────────────────────────────
  function handleAuth(username: string, token: string) {
    localStorage.setItem("career-agent-username", username);
    localStorage.setItem("career-agent-token", token);
    setAuth({ username, token });
    setNavPage("dashboard");
  }

  function handleLogout() {
    localStorage.removeItem("career-agent-username");
    localStorage.removeItem("career-agent-token");
    localStorage.removeItem("career-agent-session-id");
    setAuth(null);
    setMessages([]);
    setSessions([]);
    setChatInput("");
    setError(null);
    setStatusLabel("就绪");
  }

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
    setStatusLabel("就绪");
    setHistoryLoaded(true);
    loadSessions(userId);
  }

  function handleSessionSelect(sid: string) {
    if (sid === sessionId) return;
    persistSessionId(sid);
    setSessionId(sid);
    setMessages([]);
    setError(null);
    setStatusLabel("就绪");
    loadSession(userId, sid);
  }

  const latestResponse = useMemo(() => {
    return [...messages].reverse().find((message) => message.response)?.response ?? null;
  }, [messages]);

  async function handleChatSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = chatInput.trim();
    if (!trimmed || isLoading) return;
    setError(null);
    setStatusLabel("思考中");
    setIsLoading(true);
    userCanceledRef.current = false;
    const userMessage: Message = { id: nextId.current++, role: "user", content: trimmed };
    setMessages((current) => [...current, userMessage]);
    setChatInput("");

    try {
      const controller = new AbortController();
      chatAbortRef.current = controller;
      const timeoutId = window.setTimeout(() => controller.abort(), 120000);

      const streamingId = nextId.current++;
      setMessages((current) => [
        ...current,
        { id: streamingId, role: "agent", content: "", response: undefined },
      ]);

      const response = await sendChat(
        userId,
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
      loadSessions(userId);
      setStatusLabel(response.stage === "tool" ? "已调用工具" : "就绪");
    } catch (err) {
      const isAbort = err instanceof DOMException && err.name === "AbortError";
      if (userCanceledRef.current) {
        // 用户主动停止，不显示错误（无论是 AbortError 还是 buffer 耗尽）
        setError(null);
        setStatusLabel("已取消");
      } else if (isAbort) {
        setError("请求超时，请重试。");
        setStatusLabel("请求超时");
      } else {
        setError(err instanceof Error ? err.message : "请求失败");
        setStatusLabel("请重试");
      }
    } finally {
      chatAbortRef.current = null;
      userCanceledRef.current = false;
      setIsLoading(false);
    }
  }

  function cancelChatRequest() {
    userCanceledRef.current = true;
    if (chatAbortRef.current) {
      chatAbortRef.current.abort();
      chatAbortRef.current = null;
    }
    // Don't setIsLoading(false) here — let catch/finally handle it
    // so the stop button stays visible until streaming truly stops
    setStatusLabel("取消中...");
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

      const saved = await saveParsedResume(userId, parsed.parsed);
      setResumeVersion((v) => v + 1); // force ResumePage to re-fetch
      const name = parsed.parsed.name ? `（${parsed.parsed.name}）` : "";
      const skills = parsed.parsed.skills.slice(0, 5).join("、");
      const skillsLine = skills
        ? `\n- 识别技能：${skills}${parsed.parsed.skills.length > 5 ? " 等" : ""}`
        : "";
      const warnLine =
        parsed.warnings.length > 0
          ? `\n⚠️ 部分字段解析不完整：${parsed.warnings.join("；")}`
          : "";

      const confirmContent = `✅ 简历已解析并保存${name}（ID: ${saved.resume_id}）。${skillsLine}${warnLine}\n\n现在可以问我：\n- "帮我分析和某个 JD 的差距"\n- "我适合哪些 Python 岗位？"`;

      // Persist so the message survives session reloads
      void saveMessage(userId, "assistant", confirmContent, sessionId);

      setMessages((curr) => [
        ...curr,
        {
          id: nextId.current++,
          role: "agent",
          content: confirmContent,
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

  // ── Auth gate ─────────────────────────────────────────────────────────
  if (!auth) {
    return <AuthPage onAuth={handleAuth} />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        {/* Brand */}
        <div className="brand">
          <div className="brand-mark">
            <BriefcaseBusiness size={21} />
          </div>
          <div>
            <strong>CareerHub</strong>
            <span>AI 求职辅导助手</span>
          </div>
        </div>

        {/* User bar */}
        <div className="sidebar-user">
          <div className="sidebar-user-info">
            <div className="user-avatar">{auth.username[0].toUpperCase()}</div>
            <span className="sidebar-username">{auth.username}</span>
          </div>
          <button
            className="sidebar-logout-btn"
            type="button"
            onClick={handleLogout}
            title="退出登录"
          >
            <LogOut size={15} />
          </button>
        </div>

        {/* Nav */}
        <nav className="sidebar-nav">
          {NAV_ITEMS.map(({ page, label, icon: Icon }) => (
            <button
              key={page}
              type="button"
              className={`nav-item${navPage === page ? " active" : ""}`}
              onClick={() => setNavPage(page)}
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        {/* Recent sessions — only visible on chat page */}
        {navPage === "chat" && (
          <>
            <div className="sidebar-divider" />
            <div className="sidebar-section-label">近期对话</div>
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
        )}
      </aside>

      <main className="workspace">
        {navPage === "dashboard" && (
          <div className="full-page">
            <DashboardPage userId={userId} onNavigate={setNavPage} />
          </div>
        )}

        {navPage === "chat" && (
          <>
            <section className="primary-pane">
              <header className="pane-header">
                <div>
                  <span className="eyebrow">持续上下文</span>
                  <h1>AI 对话</h1>
                </div>
                <StatusPill isLoading={isLoading} response={latestResponse} statusLabel={statusLabel} />
              </header>

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

              {error && <div className="error-banner">{error}</div>}
            </section>

            <EvidencePanel response={latestResponse} />
          </>
        )}

        {navPage === "track" && (
          <div className="full-page">
            <JobTrackingPage userId={userId} />
          </div>
        )}

        {navPage === "resume" && (
          <div className="full-page">
            <ResumePage
              key={resumeVersion}
              userId={userId}
              onNavigate={setNavPage}
              onOptimizeResume={() => {
                setChatInput("请帮我分析和优化我的简历，重点提升关键词匹配度和表达清晰度，给出具体修改建议");
                setNavPage("chat");
              }}
            />
          </div>
        )}

        {navPage === "goals" && (
          <div className="full-page">
            <GoalsPage userId={userId} />
          </div>
        )}
      </main>
    </div>
  );
}
