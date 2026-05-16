import React, { useEffect, useState } from "react";
import type { Goal } from "../types";
import { fetchGoals, createGoal, completeGoal } from "../api";

interface Props {
  userId: string;
}

const DAYS = ["一", "二", "三", "四", "五", "六", "日"];

const AI_WEEKLY_TIPS = [
  "每天复习1个核心算法题，保持手感",
  "周末模拟一次完整面试，训练表达能力",
  "整理面试中被问到的高频问题并记录答案",
  "关注目标公司的技术博客，了解技术栈",
];

export function GoalsPage({ userId }: Props) {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [loading, setLoading] = useState(true);
  const [newGoalText, setNewGoalText] = useState("");
  const [adding, setAdding] = useState(false);
  const [showInput, setShowInput] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchGoals(userId)
      .then(setGoals)
      .catch(() => setGoals([]))
      .finally(() => setLoading(false));
  }, [userId]);

  async function handleComplete(goalId: number) {
    await completeGoal(goalId);
    setGoals(prev => prev.filter(g => g.id !== goalId));
  }

  async function handleAdd() {
    const text = newGoalText.trim();
    if (!text || adding) return;
    setAdding(true);
    try {
      const newGoal = await createGoal(userId, text);
      setGoals(prev => [...prev, newGoal]);
      setNewGoalText("");
      setShowInput(false);
    } finally {
      setAdding(false);
    }
  }

  // Build a simple 7-day bar chart based on goals count
  const today = new Date();
  const dayOfWeek = today.getDay(); // 0=Sun
  // Reorder so Mon=0 ... Sun=6
  const mondayFirst = [1, 2, 3, 4, 5, 6, 0];
  // For simplicity: show active goals count on current day, 0 for others (simplified)
  const barData = mondayFirst.map((d, idx) => {
    const isToday = d === dayOfWeek;
    return { label: DAYS[idx], value: isToday ? goals.length : 0, isToday };
  });
  const maxBar = Math.max(...barData.map(b => b.value), 1);

  if (loading) return <div className="page-loading">加载中...</div>;

  return (
    <div className="goals-page">
      <div className="page-header">
        <div>
          <h2>我的目标</h2>
          <p className="page-subtitle">制定计划，跟踪进度</p>
        </div>
        <button className="btn-primary" type="button" onClick={() => setShowInput(v => !v)}>
          + 添加目标
        </button>
      </div>

      {showInput && (
        <div className="goal-add-form">
          <input
            className="goal-input"
            placeholder="输入目标，如：本周投递5份简历"
            value={newGoalText}
            onChange={e => setNewGoalText(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleAdd()}
            autoFocus
          />
          <div className="goal-add-actions">
            <button className="btn-primary" type="button" onClick={handleAdd} disabled={adding}>
              {adding ? "添加中..." : "确认"}
            </button>
            <button className="btn-ghost" type="button" onClick={() => setShowInput(false)}>取消</button>
          </div>
        </div>
      )}

      <div className="goals-layout">
        <div className="goals-main">
          {/* Today's goals */}
          <div className="goals-section-card">
            <h3 className="goals-section-title">今日目标</h3>
            {goals.length === 0 ? (
              <div className="goals-empty">
                <p>暂无目标，点击右上角添加</p>
              </div>
            ) : (
              <div className="goal-items">
                {goals.map(g => (
                  <div key={g.id} className="goal-item">
                    <label className="goal-check-label">
                      <input
                        type="checkbox"
                        className="goal-checkbox"
                        onChange={() => handleComplete(g.id)}
                      />
                      <span className="goal-text">{g.goal_text}</span>
                    </label>
                    {g.deadline && (
                      <span className="goal-deadline">截止: {new Date(g.deadline).toLocaleDateString("zh-CN")}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Weekly progress bar chart */}
          <div className="goals-section-card">
            <h3 className="goals-section-title">本周进度</h3>
            <div className="week-chart">
              {barData.map((d, i) => (
                <div key={i} className="week-bar-col">
                  <div className="week-bar-wrap">
                    <div
                      className={`week-bar${d.isToday ? " today" : ""}`}
                      style={{ height: `${Math.round((d.value / maxBar) * 80)}px` }}
                      title={`${d.value} 个目标`}
                    />
                  </div>
                  <div className={`week-label${d.isToday ? " today" : ""}`}>周{d.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right: AI weekly tips */}
        <div className="goals-sidebar">
          <div className="ai-tips-card">
            <h4>AI 本周建议</h4>
            <div className="ai-tips-list">
              {AI_WEEKLY_TIPS.map((tip, i) => (
                <div key={i} className="ai-tip-item">
                  <span className="ai-tip-num">{i + 1}</span>
                  <span>{tip}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
