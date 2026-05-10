export type ChatSource = {
  type: string;
  title: string;
  snippet: string;
  company?: string | null;
  location?: string | null;
  work_type?: string | null;
  posted_at?: string | null;
  url?: string | null;
};

export type ChatResponse = {
  contract_version: "chat.v1";
  answer: string;
  stage: string;
  memory_used: boolean;
  sources: ChatSource[];
  tool_used?: string | null;
  tool_trace: string[];
};

export type ResumeImageParseResponse = {
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

export type SavedParsedResumeResponse = {
  resume_id: number;
  candidate_id: number;
  title: string;
  version: string;
  content: string;
};

export type Message = {
  id: number;
  role: "user" | "agent";
  content: string;
  response?: ChatResponse;
};

export type ViewMode = "query" | "chat";

export type SessionMeta = {
  session_id: string;
  title: string;
  created_at: string;
  turn_count: number;
};
