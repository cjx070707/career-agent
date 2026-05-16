import React, { useEffect, useState } from "react";
import type { Application } from "../types";
import { fetchApplications, createApplication, updateApplicationStatus, fetchCandidate } from "../api";

interface Props {
  userId: string;
}

const ALL_STATUSES = ["关注中", "已投递", "一面", "二面", "Offer", "淘汰"];
const FILTER_TABS = ["全部", "关注中", "已投递", "面试中", "Offer"];

function statusStyle(status: string): React.CSSProperties {
  switch (status) {
    case "关注中": return { color: "#0284c7", background: "#f0f9ff", border: "1px solid #bae6fd" };
    case "已投递": return { color: "#16a34a", background: "#f0fdf4", border: "1px solid #bbf7d0" };
    case "一面":
    case "二面": return { color: "#9333ea", background: "#fdf4ff", border: "1px solid #e9d5ff" };
    case "Offer": return { color: "#d97706", background: "#fef3c7", border: "1px solid #fde68a" };
    case "淘汰": return { color: "#6b7280", background: "#f3f4f6", border: "1px solid #e5e7eb" };
    default: return { color: "#6b7280", background: "#f3f4f6", border: "1px solid #e5e7eb" };
  }
}

function filterApps(apps: Application[], tab: string) {
  if (tab === "全部") return apps;
  if (tab === "面试中") return apps.filter(a => a.status === "一面" || a.status === "二面");
  return apps.filter(a => a.status === tab);
}

export function JobTrackingPage({ userId }: Props) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("全部");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [addForm, setAddForm] = useState({ company: "", job_title: "", status: "关注中" });
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchApplications(userId)
      .then(setApplications)
      .catch(() => setApplications([]))
      .finally(() => setLoading(false));
  }, [userId]);

  async function handleStatusChange(id: number, newStatus: string) {
    await updateApplicationStatus(id, newStatus);
    setApplications(prev => prev.map(a => a.id === id ? { ...a, status: newStatus } : a));
    setSelectedId(null);
  }

  async function handleAdd() {
    if (!addForm.company.trim() || !addForm.job_title.trim()) return;
    setAddLoading(true);
    setAddError(null);
    try {
      const candidate = await fetchCandidate(userId);
      if (!candidate) {
        setAddError("未找到候选人档案，请先在 AI 对话中上传简历");
        return;
      }
      const newApp = await createApplication({
        candidate_id: candidate.id,
        company: addForm.company.trim(),
        job_title: addForm.job_title.trim(),
        status: addForm.status,
      });
      setApplications(prev => [newApp, ...prev]);
      setAddForm({ company: "", job_title: "", status: "关注中" });
      setShowAddForm(false);
    } catch (e) {
      setAddError(e instanceof Error ? e.message : "添加失败");
    } finally {
      setAddLoading(false);
    }
  }

  const filtered = filterApps(applications, activeTab);

  if (loading) return <div className="page-loading">加载中...</div>;

  return (
    <div className="tracking-page">
      <div className="page-header">
        <div>
          <h2>求职追踪</h2>
          <p className="page-subtitle">管理你的投递进度</p>
        </div>
        <button className="btn-primary" type="button" onClick={() => setShowAddForm(v => !v)}>
          + 添加岗位
        </button>
      </div>

      {showAddForm && (
        <div className="add-form-card">
          <h4>添加新岗位</h4>
          {addError && <div className="form-error">{addError}</div>}
          <div className="add-form-fields">
            <input
              placeholder="公司名称"
              value={addForm.company}
              onChange={e => setAddForm(f => ({ ...f, company: e.target.value }))}
            />
            <input
              placeholder="岗位名称"
              value={addForm.job_title}
              onChange={e => setAddForm(f => ({ ...f, job_title: e.target.value }))}
            />
            <select value={addForm.status} onChange={e => setAddForm(f => ({ ...f, status: e.target.value }))}>
              {ALL_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <div className="add-form-actions">
              <button className="btn-primary" type="button" onClick={handleAdd} disabled={addLoading}>
                {addLoading ? "添加中..." : "确认添加"}
              </button>
              <button className="btn-ghost" type="button" onClick={() => setShowAddForm(false)}>取消</button>
            </div>
          </div>
        </div>
      )}

      <div className="filter-tabs">
        {FILTER_TABS.map(tab => (
          <button
            key={tab}
            type="button"
            className={`filter-tab${activeTab === tab ? " active" : ""}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
            <span className="filter-tab-count">
              {tab === "全部" ? applications.length : filterApps(applications, tab).length}
            </span>
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state-page">
          <div className="empty-state-icon">📋</div>
          <p>暂无{activeTab === "全部" ? "" : activeTab}岗位</p>
        </div>
      ) : (
        <div className="job-cards">
          {filtered.map(app => (
            <div key={app.id} className="job-card">
              <div className="job-card-header">
                <div>
                  <div className="job-company">{app.company}</div>
                  <div className="job-title">{app.job_title}</div>
                </div>
                <span className="status-badge" style={statusStyle(app.status)}>{app.status}</span>
              </div>
              {app.note && <div className="job-note">{app.note}</div>}
              <div className="job-card-footer">
                <span className="job-date">投递时间: {app.applied_at ? new Date(app.applied_at).toLocaleDateString("zh-CN") : "-"}</span>
                <button
                  type="button"
                  className="btn-ghost-sm"
                  onClick={() => setSelectedId(selectedId === app.id ? null : app.id)}
                >
                  更新状态
                </button>
              </div>
              {selectedId === app.id && (
                <div className="status-picker">
                  {ALL_STATUSES.map(s => (
                    <button
                      key={s}
                      type="button"
                      className={`status-option${app.status === s ? " current" : ""}`}
                      style={statusStyle(s)}
                      onClick={() => handleStatusChange(app.id, s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
