import React, { FormEvent, useMemo, useRef, useState } from "react";
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
  memory_used: boolean;
  sources: ChatSource[];
  tool_used?: string | null;
  plan?: ChatPlan | null;
  tool_trace: string[];
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

async function sendChat(userId: string, message: string): Promise<ChatResponse> {
  const response = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, message }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }

  return response.json();
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

function App() {
  const [view, setView] = useState<ViewMode>("chat");
  const [userId, setUserId] = useState("demo-user");
  const [chatInput, setChatInput] = useState("帮我找一些 Python backend 岗位");
  const [queryInput, setQueryInput] = useState("结合我的投递和面试反馈，我下一步该准备什么？");
  const [messages, setMessages] = useState<Message[]>([]);
  const [queryResult, setQueryResult] = useState<ChatResponse | null>(null);
  const [resumeImageResult, setResumeImageResult] = useState<ResumeImageParseResponse | null>(null);
  const [savedResume, setSavedResume] = useState<SavedParsedResumeResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isVisionLoading, setIsVisionLoading] = useState(false);
  const [isSavingResume, setIsSavingResume] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(1);

  const latestResponse = useMemo(() => {
    if (view === "query") return queryResult;
    return [...messages].reverse().find((message) => message.response)?.response ?? null;
  }, [messages, queryResult, view]);

  async function handleChatSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = chatInput.trim();
    if (!trimmed || isLoading) return;
    setError(null);
    setIsLoading(true);
    const userMessage: Message = { id: nextId.current++, role: "user", content: trimmed };
    setMessages((current) => [...current, userMessage]);
    setChatInput("");

    try {
      const response = await sendChat(userId.trim() || "demo-user", trimmed);
      setMessages((current) => [
        ...current,
        { id: nextId.current++, role: "agent", content: response.answer, response },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleQuerySubmit(event?: FormEvent) {
    event?.preventDefault();
    const trimmed = queryInput.trim();
    if (!trimmed || isLoading) return;
    setError(null);
    setIsLoading(true);
    try {
      const response = await sendChat(userId.trim() || "demo-user", trimmed);
      setQueryResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setIsLoading(false);
    }
  }

  function useStarter(prompt: string) {
    if (view === "query") {
      setQueryInput(prompt);
      return;
    }
    setChatInput(prompt);
  }

  async function handleResumeImageParse(file: File) {
    if (isVisionLoading) return;
    setError(null);
    setIsVisionLoading(true);
    try {
      const response = await parseResumeImage(file);
      setResumeImageResult(response);
      setSavedResume(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setIsVisionLoading(false);
    }
  }

  async function handleSaveParsedResume() {
    if (!resumeImageResult || isSavingResume) return;

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
            onChange={(event) => setUserId(event.target.value)}
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
      </aside>

      <main className="workspace">
        <section className="primary-pane">
          <header className="pane-header">
            <div>
              <span className="eyebrow">{view === "chat" ? "continuous context" : "single task"}</span>
              <h1>{view === "chat" ? "Chat" : "Query"}</h1>
            </div>
            <StatusPill isLoading={isLoading} response={latestResponse} />
          </header>

          {view === "chat" ? (
            <ChatView
              messages={messages}
              input={chatInput}
              setInput={setChatInput}
              isLoading={isLoading}
              onSubmit={handleChatSubmit}
            />
          ) : (
            <QueryView
              input={queryInput}
              setInput={setQueryInput}
              isLoading={isLoading}
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

function StatusPill({ isLoading, response }: { isLoading: boolean; response: ChatResponse | null }) {
  if (isLoading) {
    return (
      <span className="status-pill loading">
        <Loader2 size={15} />
        Running
      </span>
    );
  }
  return (
    <span className="status-pill">
      <Activity size={15} />
      {response?.plan?.planner_source ?? "Ready"}
    </span>
  );
}

function ChatView({
  messages,
  input,
  setInput,
  isLoading,
  onSubmit,
}: {
  messages: Message[];
  input: string;
  setInput: (value: string) => void;
  isLoading: boolean;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <div className="chat-view">
      <div className="message-list">
        {messages.length === 0 ? (
          <div className="empty-state">
            <MessageSquareText size={30} />
            <strong>Start with a job search, career diagnosis, or history question.</strong>
          </div>
        ) : (
          messages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <span>{message.role === "user" ? "You" : "Agent"}</span>
              <p>{message.content}</p>
              {message.response ? <MessageDiagnostics response={message.response} /> : null}
            </article>
          ))
        )}
      </div>

      <form className="composer" onSubmit={onSubmit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask about jobs, applications, interviews, or next steps"
          rows={3}
        />
        <button
          type="submit"
          disabled={isLoading || !input.trim()}
          aria-label="Send message"
          className={isLoading ? "is-loading" : ""}
        >
          {isLoading ? <Loader2 size={19} /> : <Send size={19} />}
        </button>
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

  const parsed = resumeImageResult?.parsed;
  return (
    <div className="query-view">
      <form className="query-form" onSubmit={onSubmit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={5}
          placeholder="Run a single task through /chat"
        />
        <button
          type="submit"
          disabled={isLoading || !input.trim()}
          className={isLoading ? "is-loading" : ""}
        >
          {isLoading ? <Loader2 size={18} /> : <FileSearch size={18} />}
          Run
        </button>
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
        <label className="field-label" htmlFor="resume-image-upload">Upload Resume Image</label>
        <input
          id="resume-image-upload"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={onFileChange}
          disabled={isVisionLoading}
        />
        {isVisionLoading ? <p>Parsing image...</p> : null}
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
              disabled={isSavingResume}
            >
              {isSavingResume ? "Saving..." : "Save as Resume"}
            </button>
            {savedResume ? (
              <p>Saved resume #{savedResume.resume_id} as {savedResume.version}</p>
            ) : null}
          </div>
        ) : (
          <p>Upload one resume screenshot/image to parse structured fields.</p>
        )}
      </div>
    </div>
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
