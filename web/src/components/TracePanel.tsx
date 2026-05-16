import { Activity } from "lucide-react";
import type { ChatResponse } from "../types";

const TOOL_LABELS: Record<string, string> = {
  search_jobs: "搜索岗位",
  match_resume_to_jobs: "简历匹配",
  analyze_gap: "Gap 分析",
  get_resume_by_id: "查阅简历",
  get_candidate_profile: "查看画像",
  get_career_insights: "职业洞察",
  get_applications: "查投递记录",
  get_interview_feedback: "查面试反馈",
  set_goal: "设定目标",
  update_goal_status: "更新目标",
  get_goals: "查看目标",
  log_progress: "记录进度",
};

function TraceItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function TracePanel({ response }: { response: ChatResponse | null }) {
  const toolTrace = response?.tool_trace ?? [];
  const hasTools = toolTrace.length > 0;

  return (
    <section className="trace-section">
      <div className="section-title">
        <Activity size={18} />
        Trace
      </div>
      <div className="trace-grid">
        <TraceItem label="Stage" value={response?.stage ?? "—"} />
        <TraceItem
          label="Tool"
          value={response?.tool_used
            ? (TOOL_LABELS[response.tool_used] ?? response.tool_used)
            : "—"}
        />
        <TraceItem
          label="Memory"
          value={response ? (response.memory_used ? "used" : "not used") : "—"}
        />
      </div>
      {hasTools && (
        <div className="steps-row">
          {toolTrace.map((step) => (
            <span key={step}>{TOOL_LABELS[step] ?? step}</span>
          ))}
        </div>
      )}
    </section>
  );
}
