import React, { useEffect, useState } from "react";
import type { NavPage, ResumeData } from "../types";
import { fetchUserResume } from "../api";

interface Props {
  userId: string;
  onNavigate: (page: NavPage) => void;
}

const AI_TIPS = [
  "在简历中添加量化的项目成果（如：提升性能30%）",
  "针对目标岗位的JD关键词优化技能描述",
  "补充开源项目或个人博客链接增加可信度",
];

export function ResumePage({ userId, onNavigate }: Props) {
  const [resume, setResume] = useState<ResumeData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchUserResume(userId)
      .then(setResume)
      .catch(() => setResume(null))
      .finally(() => setLoading(false));
  }, [userId]);

  if (loading) return <div className="page-loading">加载中...</div>;

  if (!resume) {
    return (
      <div className="resume-page">
        <div className="page-header">
          <div>
            <h2>我的简历</h2>
            <p className="page-subtitle">AI 解析与优化建议</p>
          </div>
        </div>
        <div className="resume-empty">
          <div className="resume-empty-icon">📄</div>
          <h3>还没有上传简历</h3>
          <p>去 AI 对话页上传简历图片，AI 将自动解析并保存</p>
          <button className="btn-primary" type="button" onClick={() => onNavigate("chat")}>
            去上传简历
          </button>
        </div>
      </div>
    );
  }

  const p = resume.parsed;
  const edu = p?.education;
  const eduStr = Array.isArray(edu)
    ? edu.map((e: unknown) => {
        if (typeof e === "string") return e;
        if (typeof e === "object" && e !== null) {
          const ed = e as Record<string, string>;
          return [ed.school, ed.degree, ed.dates].filter(Boolean).join(" · ");
        }
        return String(e);
      }).join(" / ")
    : typeof edu === "string" ? edu : "";

  return (
    <div className="resume-page">
      <div className="page-header">
        <div>
          <h2>我的简历</h2>
          <p className="page-subtitle">AI 解析与优化建议</p>
        </div>
        <button className="btn-ghost" type="button" onClick={() => onNavigate("chat")}>
          重新上传
        </button>
      </div>

      <div className="resume-layout">
        <div className="resume-main">
          {/* Header card */}
          <div className="resume-header-card">
            <div className="resume-avatar">{p?.name ? p.name[0] : "?"}</div>
            <div className="resume-identity">
              <h3>{p?.name || "未知姓名"}</h3>
              <div className="resume-contact">
                {p?.email && <span>✉ {p.email}</span>}
                {p?.phone && <span>📱 {p.phone}</span>}
              </div>
              {eduStr && <div className="resume-edu">🎓 {eduStr}</div>}
            </div>
          </div>

          {/* Summary */}
          {p?.summary && (
            <div className="resume-section">
              <h4 className="resume-section-title">个人简介</h4>
              <p className="resume-summary">{p.summary}</p>
            </div>
          )}

          {/* Skills */}
          {p?.skills && p.skills.length > 0 && (
            <div className="resume-section">
              <h4 className="resume-section-title">技能</h4>
              <div className="skill-tags">
                {p.skills.map((skill, i) => (
                  <span key={i} className="skill-tag">{skill}</span>
                ))}
              </div>
            </div>
          )}

          {/* Experience */}
          {p?.experience && p.experience.length > 0 && (
            <div className="resume-section">
              <h4 className="resume-section-title">工作经历</h4>
              <div className="exp-list">
                {p.experience.map((exp, i) => (
                  <div key={i} className="exp-item">
                    <div className="exp-header">
                      <div>
                        <span className="exp-role">{exp.role || "职位未知"}</span>
                        {exp.company && <span className="exp-company"> @ {exp.company}</span>}
                      </div>
                      {exp.dates && <span className="exp-dates">{exp.dates}</span>}
                    </div>
                    {(exp.description || exp.summary) && (
                      <p className="exp-desc">{exp.description || exp.summary}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Projects */}
          {p?.projects && p.projects.length > 0 && (
            <div className="resume-section">
              <h4 className="resume-section-title">项目经历</h4>
              <div className="exp-list">
                {p.projects.map((proj, i) => (
                  <div key={i} className="exp-item">
                    <div className="exp-role">{proj.name || "项目"}</div>
                    {(proj.description || proj.summary) && (
                      <p className="exp-desc">{proj.description || proj.summary}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right sidebar */}
        <div className="resume-sidebar">
          <div className="score-card">
            <h4>AI 评分</h4>
            <div className="score-circle">
              <span className="score-num">78</span>
              <span className="score-denom">/100</span>
            </div>
            <div className="score-bar-wrap">
              <div className="score-bar" style={{ width: "78%" }} />
            </div>
            <div className="score-tips">
              <h5>优化建议</h5>
              {AI_TIPS.map((tip, i) => (
                <div key={i} className="score-tip">
                  <span className="tip-num">{i + 1}</span>
                  <span>{tip}</span>
                </div>
              ))}
            </div>
          </div>
          <button className="btn-primary full-width" type="button" onClick={() => onNavigate("chat")}>
            AI 优化简历
          </button>
        </div>
      </div>
    </div>
  );
}
