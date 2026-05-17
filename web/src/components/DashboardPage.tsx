import React, { useEffect, useState } from "react";
import type { Application, Goal, NavPage, ResumeData, SessionMeta } from "../types";
import {
  fetchApplications, fetchGoals, completeGoal,
  fetchUserResume, fetchCandidate, createApplication,
  fetchJobMatches, type JobMatch,
} from "../api";

// Module-level cache: survives re-mounts within the same browser session
const _matchesCache = new Map<number, JobMatch[]>();

interface Props {
  userId: string;
  onNavigate: (page: NavPage) => void;
}

function statusStyle(status: string): React.CSSProperties {
  switch (status) {
    case "关注中": return { color: "#0284c7", background: "#f0f9ff" };
    case "已投递": return { color: "#16a34a", background: "#f0fdf4" };
    case "一面":
    case "二面": return { color: "#9333ea", background: "#fdf4ff" };
    case "Offer":  return { color: "#d97706", background: "#fef3c7" };
    case "淘汰":  return { color: "#6b7280", background: "#f3f4f6" };
    default:       return { color: "#6b7280", background: "#f3f4f6" };
  }
}

// Rule-based resume completeness score (0-92)
function computeResumeScore(resume: ResumeData): number {
  let score = 30; // base: having any resume
  const p = resume.parsed;
  const content = resume.content ?? "";

  if (p) {
    // Structured path: parsed JSON available (vision-uploaded resumes)
    if (p.name) score += 8;
    if (p.email || p.phone) score += 8;
    if (p.summary) score += 5;
    const skillCount = p.skills?.length ?? 0;
    if (skillCount >= 5) score += 18;
    else if (skillCount >= 2) score += 10;
    else if (skillCount >= 1) score += 5;
    const expCount = p.experience?.length ?? 0;
    if (expCount >= 2) score += 20;
    else if (expCount === 1) score += 12;
    if ((p.education?.length ?? 0) > 0) score += 8;
    if ((p.projects?.length ?? 0) > 0) score += 6;
  } else {
    // Fallback: keyword detection in raw text content
    if (/skills?/i.test(content)) score += 15;
    if (/experience|work history|employment/i.test(content)) score += 18;
    if (/education|university|college|degree/i.test(content)) score += 8;
    if (/project/i.test(content)) score += 6;
    if (/@|\bemail\b/i.test(content)) score += 5;
  }

  // Content richness bonus (both paths)
  if (content.length > 800) score += 8;
  else if (content.length > 300) score += 4;

  return Math.min(92, score);
}

// Extract company from job title like "Amazon · SDE" or "Amazon - SDE"
// Falls back gracefully when the title is a plain sentence (no separator)
function parseJobTitle(raw: string): { company: string; role: string } {
  const sep = raw.includes("·") ? "·" : raw.includes(" - ") ? " - " : null;
  if (sep) {
    const idx = raw.indexOf(sep);
    const company = raw.slice(0, idx).trim();
    const role = raw.slice(idx + sep.length).trim();
    if (company && role) return { company, role };
  }
  // No clear separator — treat full string as role, no company
  return { company: "", role: raw };
}

export function DashboardPage({ userId, onNavigate }: Props) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [resume, setResume] = useState<ResumeData | null | undefined>(undefined); // undefined = loading
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [matchesLoading, setMatchesLoading] = useState(false);
  const [trackedIds, setTrackedIds] = useState<Set<string>>(new Set());
  const [candidateId, setCandidateId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [completedCount, setCompletedCount] = useState(0);
  const [trackModal, setTrackModal] = useState<{ key: string; company: string; role: string } | null>(null);
  const [trackSaving, setTrackSaving] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchApplications(userId).catch(() => []),
      fetchGoals(userId).catch(() => []),
      fetch(`/conversations/${encodeURIComponent(userId)}/sessions`).then(r => r.ok ? r.json() : []).catch(() => []),
      fetchUserResume(userId).catch(() => null),
      fetchCandidate(userId).catch(() => null),
    ]).then(([apps, gs, sess, res, cand]) => {
      setApplications(apps as Application[]);
      setGoals(gs as Goal[]);
      setSessions(sess as SessionMeta[]);
      setResume(res as ResumeData | null);
      setCandidateId(cand ? (cand as { id: number }).id : null);
      setLoading(false);

      // If resume exists, fetch matches (with module-level cache to avoid re-fetch on remount)
      if (res && (res as ResumeData).id) {
        const resumeId = (res as ResumeData).id;
        if (_matchesCache.has(resumeId)) {
          setMatches(_matchesCache.get(resumeId)!);
        } else {
          setMatchesLoading(true);
          fetchJobMatches(resumeId)
            .then(m => { const top3 = m.slice(0, 3); _matchesCache.set(resumeId, top3); setMatches(top3); })
            .catch(() => setMatches([]))
            .finally(() => setMatchesLoading(false));
        }
      }
    });
  }, [userId]);

  async function handleCompleteGoal(goalId: number) {
    await completeGoal(goalId);
    setGoals(prev => prev.filter(g => g.id !== goalId));
    setCompletedCount(prev => prev + 1);
  }

  function handleTrack(match: JobMatch) {
    const key = match.job_title;
    if (trackedIds.has(key) || !candidateId) return;
    const { company, role } = parseJobTitle(match.job_title);
    setTrackModal({ key, company: company || "", role });
  }

  async function handleTrackConfirm(company: string, role: string) {
    if (!candidateId || !trackModal) return;
    const finalCompany = company.trim() || "未知公司";
    const finalRole = role.trim() || trackModal.role;
    setTrackSaving(true);
    try {
      await createApplication({ candidate_id: candidateId, company: finalCompany, job_title: finalRole, status: "关注中" });
      setTrackedIds(prev => new Set([...prev, trackModal.key]));
      setApplications(prev => [...prev, {
        id: Date.now(), candidate_id: candidateId,
        company: finalCompany, job_title: finalRole, status: "关注中",
        note: null, applied_at: new Date().toISOString(), last_updated_at: new Date().toISOString(),
      }]);
      setTrackModal(null);
    } catch (e) { console.error("handleTrackConfirm failed:", e); }
    finally { setTrackSaving(false); }
  }

  const recentApps = applications.slice(0, 3);
  const totalGoals = goals.length;
  const hasResume = resume !== undefined && resume !== null;

  if (loading) {
    return <div className="page-loading">加载中...</div>;
  }

  return (
    <div className="dashboard-page">
      {/* Track confirm modal */}
      {trackModal && (
        <TrackModal
          initialCompany={trackModal.company}
          initialRole={trackModal.role}
          saving={trackSaving}
          onConfirm={handleTrackConfirm}
          onCancel={() => setTrackModal(null)}
        />
      )}

      <div className="dashboard-header">
        <h2>首页概览</h2>
        <p className="dashboard-subtitle">欢迎回来，{userId}</p>
      </div>

      {/* Stat cards */}
      <div className="stat-cards">
        <div className="stat-card">
          <div className="stat-icon stat-icon-purple">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </div>
          {hasResume ? (
            <>
              <div className="stat-value">{computeResumeScore(resume!)}</div>
              <div className="stat-label">简历完整度</div>
            </>
          ) : (
            <>
              <div className="stat-value stat-value-muted">N/A</div>
              <div className="stat-label">简历未上传</div>
            </>
          )}
        </div>

        <div className="stat-card">
          <div className="stat-icon stat-icon-blue">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>
          </div>
          <div className="stat-value">{applications.length}</div>
          <div className="stat-label">追踪岗位</div>
        </div>

        <div className="stat-card">
          <div className="stat-icon stat-icon-green">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          </div>
          <div className="stat-value">{completedCount}/{totalGoals}</div>
          <div className="stat-label">今日目标</div>
        </div>

        <div className="stat-card">
          <div className="stat-icon stat-icon-orange">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </div>
          <div className="stat-value">{sessions.length}</div>
          <div className="stat-label">对话记录</div>
        </div>
      </div>

      {/* ── No resume: onboarding guide ── */}
      {!hasResume && (
        <div className="onboarding-card">
          <div className="onboarding-left">
            <div className="onboarding-icon">📄</div>
            <div>
              <h3>上传简历，解锁全部功能</h3>
              <p>上传简历后，AI 将自动解析并为你推荐匹配岗位、分析技能差距、制定求职目标。</p>
              <div className="onboarding-steps">
                <div className="onboarding-step">
                  <span className="step-num">1</span>
                  <span>去 AI 对话页，发送简历图片或截图</span>
                </div>
                <div className="onboarding-step">
                  <span className="step-num">2</span>
                  <span>AI 自动解析技能、经历、教育背景</span>
                </div>
                <div className="onboarding-step">
                  <span className="step-num">3</span>
                  <span>首页立即显示岗位推荐与评分</span>
                </div>
              </div>
            </div>
          </div>
          <button className="onboarding-btn" onClick={() => onNavigate("chat")}>
            去上传简历 →
          </button>
        </div>
      )}

      <div className="dashboard-grid">
        {/* Recent applications */}
        <div className="dashboard-card">
          <div className="dashboard-card-header">
            <h3>近期投递</h3>
            <button className="link-btn" type="button" onClick={() => onNavigate("track")}>查看全部</button>
          </div>
          {recentApps.length === 0 ? (
            <div className="empty-hint">暂无投递记录，<button className="link-btn" type="button" onClick={() => onNavigate("track")}>去添加</button></div>
          ) : (
            <div className="app-list">
              {recentApps.map(app => (
                <div key={app.id} className="app-row">
                  <div className="app-row-info">
                    <span className="app-company">{app.company}</span>
                    <span className="app-title">{app.job_title}</span>
                  </div>
                  <span className="status-badge" style={statusStyle(app.status)}>{app.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Today's goals */}
        <div className="dashboard-card">
          <div className="dashboard-card-header">
            <h3>今日目标</h3>
            <button className="link-btn" type="button" onClick={() => onNavigate("goals")}>管理目标</button>
          </div>
          {goals.length === 0 ? (
            <div className="empty-hint">暂无目标，<button className="link-btn" type="button" onClick={() => onNavigate("goals")}>去添加</button></div>
          ) : (
            <div className="goal-list">
              {goals.map(g => (
                <div key={g.id} className="goal-row">
                  <input type="checkbox" id={`goal-${g.id}`} onChange={() => handleCompleteGoal(g.id)} />
                  <label htmlFor={`goal-${g.id}`}>{g.goal_text}</label>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Has resume: job recommendations ── */}
      {hasResume && (
        <div className="recommendations">
          <div className="recommendations-header">
            <div>
              <h3>为你推荐的岗位</h3>
              <p className="rec-sub">根据你的简历技能栈匹配</p>
            </div>
            <button className="link-btn" type="button" onClick={() => onNavigate("chat")}>
              让 AI 深度分析 →
            </button>
          </div>

          {matchesLoading ? (
            <div className="rec-loading">正在匹配岗位...</div>
          ) : matches.length === 0 ? (
            <div className="rec-empty">暂无推荐，请确认简历已正确解析</div>
          ) : (
            <div className="rec-cards">
              {matches.map((m, i) => {
                const tracked = trackedIds.has(m.job_title);
                const { company, role } = parseJobTitle(m.job_title);
                return (
                  <div key={i} className="rec-card">
                    <div className="rec-card-top">
                      <div className="rec-match-badge">{m.match_score}%</div>
                      <div className="rec-card-info">
                        {company && <div className="rec-company">{company}</div>}
                        <div className="rec-role">{role}</div>
                      </div>
                    </div>
                    <div className="rec-keywords">
                      {m.matched_keywords.slice(0, 4).map(kw => (
                        <span key={kw} className="rec-kw">{kw}</span>
                      ))}
                    </div>
                    <button
                      className={`rec-track-btn${tracked ? " tracked" : ""}`}
                      onClick={() => handleTrack(m)}
                      disabled={tracked || !candidateId}
                    >
                      {tracked ? "✓ 已加入追踪" : "+ 加入追踪"}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* CTA banner — always visible, text adapts to resume state */}
      <div className="cta-banner" onClick={() => onNavigate("chat")} role="button" tabIndex={0} onKeyDown={e => e.key === "Enter" && onNavigate("chat")}>
        <div className="cta-banner-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        </div>
        <div className="cta-banner-text">
          <strong>{hasResume ? "继续 AI 对话" : "开始 AI 求职辅导"}</strong>
          <span>{hasResume
            ? "和 AI 分析你的简历差距、面试反馈，获取个性化建议"
            : "搜岗位、问面试技巧、制定求职计划，AI 全程陪伴"
          }</span>
        </div>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
      </div>
    </div>
  );
}

// ── Track confirm modal ──────────────────────────────────────────────────────
function TrackModal({
  initialCompany, initialRole, saving, onConfirm, onCancel,
}: {
  initialCompany: string; initialRole: string; saving: boolean;
  onConfirm: (company: string, role: string) => void;
  onCancel: () => void;
}) {
  const [company, setCompany] = React.useState(initialCompany);
  const [role, setRole] = React.useState(initialRole);
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <h4 className="modal-title">确认加入追踪</h4>
        <p className="modal-desc">请确认或修改公司名和职位名后加入</p>
        <label className="modal-label">公司名</label>
        <input
          className="modal-input"
          value={company}
          onChange={e => setCompany(e.target.value)}
          placeholder="未知公司"
          autoFocus
        />
        <label className="modal-label">职位名</label>
        <input
          className="modal-input"
          value={role}
          onChange={e => setRole(e.target.value)}
          placeholder="职位名称"
        />
        <div className="modal-actions">
          <button className="btn-ghost" type="button" onClick={onCancel} disabled={saving}>取消</button>
          <button className="btn-primary" type="button" onClick={() => onConfirm(company, role)} disabled={saving}>
            {saving ? "保存中..." : "加入追踪"}
          </button>
        </div>
      </div>
    </div>
  );
}
