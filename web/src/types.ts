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

export interface Application {
  id: number;
  candidate_id: number;
  company: string;
  job_title: string;
  status: string;
  note: string | null;
  applied_at: string;
  last_updated_at: string;
}

export interface Goal {
  id: number;
  goal_text: string;
  deadline: string | null;
  status: string;
  plan: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ResumeData {
  id: number;
  title: string;
  content: string;
  version: string;
  parsed?: {
    name?: string;
    email?: string;
    phone?: string;
    education?: string[];
    skills?: string[];
    experience?: Array<{ company?: string; role?: string; dates?: string; description?: string; summary?: string }>;
    projects?: Array<{ name?: string; description?: string; summary?: string }>;
    summary?: string;
  };
  created_at?: string;
}

export type NavPage = 'dashboard' | 'chat' | 'track' | 'resume' | 'goals';
