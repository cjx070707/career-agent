import { FormEvent, useState } from "react";
import { authLogin, authRegister } from "../api";

interface Props {
  onAuth: (username: string, token: string) => void;
}

const FEATURES = [
  { icon: "✦", text: "简历解析与技能差距分析" },
  { icon: "✦", text: "AI 智能岗位匹配推荐" },
  { icon: "✦", text: "求职目标制定与进度追踪" },
  { icon: "✦", text: "面试反馈复盘与改进建议" },
];

export function AuthPage({ onAuth }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setError("");
    setLoading(true);
    try {
      const fn = mode === "login" ? authLogin : authRegister;
      const { token, username: user } = await fn(username.trim(), password);
      onAuth(user, token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败，请重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-shell">
      {/* ── Left: Brand panel ── */}
      <div className="auth-brand">
        <div className="auth-brand-inner">
          <div className="auth-logo">
            <span className="auth-logo-icon">🧭</span>
            <span className="auth-logo-name">CareerHub</span>
          </div>
          <h1 className="auth-tagline">用 AI 加速<br />你的求职之路</h1>
          <p className="auth-sub">专为求职者打造的智能辅导助手，从简历优化到岗位匹配，全程陪你拿到 Offer</p>
          <ul className="auth-features">
            {FEATURES.map((f) => (
              <li key={f.text}>
                <span className="auth-feature-icon">{f.icon}</span>
                <span>{f.text}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="auth-brand-deco" aria-hidden>
          <div className="auth-deco-circle auth-deco-circle-1" />
          <div className="auth-deco-circle auth-deco-circle-2" />
          <div className="auth-deco-circle auth-deco-circle-3" />
        </div>
      </div>

      {/* ── Right: Form panel ── */}
      <div className="auth-form-panel">
        <div className="auth-card">
          <div className="auth-card-header">
            <h2>{mode === "login" ? "欢迎回来" : "创建账号"}</h2>
            <p>{mode === "login" ? "登录以继续你的求职旅程" : "开始你的 AI 求职辅导之旅"}</p>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="auth-field">
              <label htmlFor="auth-username">用户名</label>
              <input
                id="auth-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="输入用户名"
                autoComplete="username"
                autoFocus
                disabled={loading}
              />
            </div>
            <div className="auth-field">
              <label htmlFor="auth-password">密码</label>
              <input
                id="auth-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="输入密码"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                disabled={loading}
              />
            </div>

            {error && <div className="auth-error">{error}</div>}

            <button
              type="submit"
              className="auth-submit"
              disabled={loading || !username.trim() || !password}
            >
              {loading ? (
                <span className="auth-loading-dots">
                  <span /><span /><span />
                </span>
              ) : mode === "login" ? "登录" : "注册"}
            </button>
          </form>

          <div className="auth-switch">
            {mode === "login" ? (
              <>
                还没有账号？
                <button type="button" onClick={() => { setMode("register"); setError(""); }}>
                  立即注册
                </button>
              </>
            ) : (
              <>
                已有账号？
                <button type="button" onClick={() => { setMode("login"); setError(""); }}>
                  去登录
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
