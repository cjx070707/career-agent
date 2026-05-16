import React, { useEffect, useState } from "react";
import type { Application, Goal, NavPage, SessionMeta } from "../types";
import { fetchApplications, fetchGoals, completeGoal } from "../api";

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
    case "Offer": return { color: "#d97706", background: "#fef3c7" };
    case "淘汰": return { color: "#6b7280", background: "#f3f4f6" };
    default: return { color: "#6b7280", background: "#f3f4f6" };
  }
}

export function DashboardPage({ userId, onNavigate }: Props) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchApplications(userId).catch(() => []),
      fetchGoals(userId).catch(() => []),
      fetch(`/conversations/${encodeURIComponent(userId)}/sessions`).then(r => r.ok ? r.json() : []).catch(() => []),
    ]).then(([apps, gs, sess]) => {
      setApplications(apps);
      setGoals(gs);
      setSessions(sess);
      setLoading(false);
    });
  }, [userId]);

  async function handleCompleteGoal(goalId: number) {
    await completeGoal(goalId);
    setGoals(prev => prev.filter(g => g.id !== goalId));
  }

  const recentApps = applications.slice(0, 3);
  const doneGoals = 0; // active goals shown, no "done" count from this endpoint
  const totalGoals = goals.length;

  if (loading) {
    return <div className="page-loading">加载中...</div>;
  }

  return (
    <div className="dashboard-page">
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
          <div className="stat-value">78</div>
          <div className="stat-label">简历 AI 评分</div>
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
          <div className="stat-value">{doneGoals}/{totalGoals}</div>
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
                  <input
                    type="checkbox"
                    id={`goal-${g.id}`}
                    onChange={() => handleCompleteGoal(g.id)}
                  />
                  <label htmlFor={`goal-${g.id}`}>{g.goal_text}</label>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* CTA banner */}
      <div className="cta-banner" onClick={() => onNavigate("chat")} role="button" tabIndex={0} onKeyDown={e => e.key === "Enter" && onNavigate("chat")}>
        <div className="cta-banner-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        </div>
        <div className="cta-banner-text">
          <strong>继续 AI 对话</strong>
          <span>和 AI 分析你的简历差距、面试反馈，获取个性化建议</span>
        </div>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
      </div>
    </div>
  );
}
