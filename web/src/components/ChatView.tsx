import React, { FormEvent, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import { Loader2, MessageSquareText, Paperclip, Send } from "lucide-react";
import type { Message } from "../types";
import { MessageDiagnostics } from "./MessageDiagnostics";

export function ChatView({
  messages,
  historyLoaded,
  input,
  setInput,
  isLoading,
  isVisionLoading,
  onCancel,
  onSubmit,
  onParseResumeImage,
}: {
  messages: Message[];
  historyLoaded: boolean;
  input: string;
  setInput: (value: string) => void;
  isLoading: boolean;
  isVisionLoading: boolean;
  onCancel: () => void;
  onSubmit: (event: FormEvent) => void;
  onParseResumeImage: (file: File) => Promise<void>;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handlePaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    const imageItem = Array.from(event.clipboardData.items).find((item) =>
      item.type.startsWith("image/"),
    );
    if (!imageItem) return; // let normal text paste fall through
    event.preventDefault();
    const file = imageItem.getAsFile();
    if (!file || isVisionLoading) return;
    await onParseResumeImage(
      new File([file], file.name || "pasted-resume.png", {
        type: file.type || "image/png",
      }),
    );
  }

  const showEmpty = historyLoaded && messages.length === 0;

  return (
    <div className="chat-view">
      <div className="message-list">
        {!historyLoaded ? (
          <div className="empty-state">
            <Loader2 size={22} className="spin" />
            <span>Loading history...</span>
          </div>
        ) : showEmpty ? (
          <div className="empty-state">
            <MessageSquareText size={30} />
            <strong>你好！我是你的求职助手。</strong>
            <span className="empty-hint">搜岗位、分析简历差距、制定求职目标，都可以直接问我。</span>
            <div className="empty-upload-hint">
              <span>
                上传简历后可解锁 <b>gap 分析</b>、<b>岗位匹配</b>等核心功能
              </span>
              <label className="resume-upload-btn" aria-disabled={isVisionLoading}>
                <Paperclip size={15} />
                {isVisionLoading ? "解析中..." : "上传简历（图片 / PDF）"}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,application/pdf"
                  disabled={isVisionLoading}
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    await onParseResumeImage(file);
                    e.currentTarget.value = "";
                  }}
                  style={{ display: "none" }}
                />
              </label>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <article key={message.id} className={`message ${message.role}`}>
              <span>{message.role === "user" ? "You" : "Agent"}</span>
              {message.role === "agent" ? (
                <div className="md-content">
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                </div>
              ) : (
                <p>{message.content}</p>
              )}
              {message.response ? <MessageDiagnostics response={message.response} /> : null}
            </article>
          ))
        )}
        {isVisionLoading && (
          <div className="vision-status">
            <Loader2 size={16} className="spin" />
            <span>正在解析简历图片...</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form className="composer" onSubmit={onSubmit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onPaste={(e) => void handlePaste(e)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit(e as unknown as FormEvent);
            }
          }}
          placeholder="Ask about jobs, or paste a resume image (Cmd+V)…"
          rows={3}
        />
        <div className="composer-actions">
          <label className="composer-attach" title="上传简历图片" aria-disabled={isVisionLoading}>
            {isVisionLoading ? <Loader2 size={17} className="spin" /> : <Paperclip size={17} />}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,application/pdf"
              disabled={isVisionLoading}
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                await onParseResumeImage(file);
                e.currentTarget.value = "";
              }}
              style={{ display: "none" }}
            />
          </label>
          {isLoading ? (
            <button type="button" aria-label="Stop request" className="is-loading" onClick={onCancel}>
              <Loader2 size={19} />
            </button>
          ) : (
            <button type="submit" disabled={!input.trim()} aria-label="Send message">
              <Send size={19} />
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
