import React, { FormEvent } from "react";
import { FileSearch, Loader2, Sparkles } from "lucide-react";
import type { ChatResponse, ResumeImageParseResponse, SavedParsedResumeResponse } from "../types";
import { hasParsedResumeContent } from "../utils";

export function QueryView({
  input,
  setInput,
  isLoading,
  onCancel,
  onSubmit,
  result,
  resumeImageResult,
  isVisionLoading,
  onParseResumeImage,
  savedResume,
  isSavingResume,
  onSaveParsedResume,
}: {
  input: string;
  setInput: (value: string) => void;
  isLoading: boolean;
  onCancel: () => void;
  onSubmit: (event?: FormEvent) => void;
  result: ChatResponse | null;
  resumeImageResult: ResumeImageParseResponse | null;
  isVisionLoading: boolean;
  onParseResumeImage: (file: File) => Promise<void>;
  savedResume: SavedParsedResumeResponse | null;
  isSavingResume: boolean;
  onSaveParsedResume: () => Promise<void>;
}) {
  async function onFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    await onParseResumeImage(file);
    event.currentTarget.value = "";
  }

  async function onPaste(event: React.ClipboardEvent<HTMLDivElement>) {
    if (isVisionLoading) return;
    const imageItem = Array.from(event.clipboardData.items).find((item) =>
      item.type.startsWith("image/"),
    );
    const file = imageItem?.getAsFile();
    if (!file) return;
    event.preventDefault();
    await onParseResumeImage(
      new File([file], file.name || "pasted-resume-image.png", {
        type: file.type || "image/png",
      }),
    );
  }

  const parsed = resumeImageResult?.parsed;
  const hasParsedContent = parsed ? hasParsedResumeContent(parsed) : false;

  return (
    <div className="query-view" onPaste={(event) => void onPaste(event)}>
      <form className="query-form" onSubmit={onSubmit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          rows={5}
          placeholder="Run a single task through /chat"
        />
        {isLoading ? (
          <button type="button" className="is-loading" onClick={onCancel}>
            <Loader2 size={18} />
            Stop
          </button>
        ) : (
          <button type="submit" disabled={!input.trim()}>
            <FileSearch size={18} />
            Run
          </button>
        )}
      </form>

      <div className="answer-panel">
        <div className="section-title">
          <Sparkles size={18} />
          Answer
        </div>
        <p>{result?.answer ?? "Run a query to see the agent response."}</p>
      </div>

      <div className="answer-panel">
        <div className="section-title">
          <FileSearch size={18} />
          Resume Image Parse (MVP)
        </div>
        <label className="field-label" htmlFor="resume-image-upload">
          Upload or Paste Resume Image
        </label>
        <input
          id="resume-image-upload"
          type="file"
          accept="image/png,image/jpeg,image/webp,application/pdf"
          onChange={onFileChange}
          disabled={isVisionLoading}
        />
        {isVisionLoading ? (
          <p>Parsing image, this may take up to a minute for dense resume screenshots...</p>
        ) : null}
        {resumeImageResult ? (
          <div className="source-list">
            <p>
              <strong>Name:</strong> {parsed?.name || "—"}
            </p>
            <p>
              <strong>Email:</strong> {parsed?.email || "—"}
            </p>
            <p>
              <strong>Summary:</strong> {parsed?.summary || "—"}
            </p>
            <div className="steps-row">
              {(parsed?.skills || []).length ? (
                parsed?.skills.map((skill) => <span key={skill}>{skill}</span>)
              ) : (
                <span>No skills extracted</span>
              )}
            </div>
            {parsed?.projects?.length ? (
              <div className="source-list">
                {parsed.projects.map((project, index) => (
                  <article key={`${project.name || "project"}-${index}`} className="source-card">
                    <h2>{project.name || "Unnamed project"}</h2>
                    <p>{project.summary || "No summary"}</p>
                  </article>
                ))}
              </div>
            ) : null}
            {resumeImageResult.warnings.length ? (
              <div className="muted-box">{resumeImageResult.warnings.join(" ")}</div>
            ) : null}
            <button
              type="button"
              onClick={() => void onSaveParsedResume()}
              disabled={isSavingResume || !hasParsedContent}
            >
              {isSavingResume ? "Saving..." : "Save as Resume"}
            </button>
            {savedResume ? (
              <p>
                Saved resume #{savedResume.resume_id} as {savedResume.version}
              </p>
            ) : null}
          </div>
        ) : (
          <p>Upload one resume screenshot/image, or paste an image with Cmd+V / Ctrl+V.</p>
        )}
      </div>
    </div>
  );
}
