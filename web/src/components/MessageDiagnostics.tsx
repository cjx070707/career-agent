import { Activity, ChevronDown } from "lucide-react";
import type { ChatResponse } from "../types";

// 内部工具名 → 用户可读标签
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

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

function stageLabel(stage: string): string {
  if (stage === "direct") return "直接回答";
  if (stage === "tool") return "调用工具";
  return stage;
}

export function MessageDiagnostics({ response }: { response: ChatResponse }) {
  const sourceCount = response.sources.length;
  const displayLabel = response.tool_used
    ? toolLabel(response.tool_used)
    : stageLabel(response.stage);

  return (
    <details className="message-details">
      <summary>
        <Activity size={15} />
        <span>{displayLabel}</span>
        <span>{sourceCount} sources</span>
        <ChevronDown size={15} />
      </summary>

      <div className="message-detail-body">
        <div className="message-chip-row">
          <strong>stage {response.stage}</strong>
          <strong>tool {response.tool_used ? toolLabel(response.tool_used) : "—"}</strong>
          <strong>memory {response.memory_used ? "used" : "not used"}</strong>
        </div>
        {response.tool_trace.length ? (
          <div className="message-steps">
            {response.tool_trace.map((step) => (
              <code key={step}>{step}</code>
            ))}
          </div>
        ) : null}
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
