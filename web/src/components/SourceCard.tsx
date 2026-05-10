import type { ChatSource } from "../types";

export function SourceCard({ source }: { source: ChatSource }) {
  const meta = [source.company, source.location, source.work_type, source.posted_at].filter(Boolean);
  return (
    <article className="source-card">
      <div className="source-head">
        <span>{source.type}</span>
        {source.url ? (
          <a href={source.url} target="_blank" rel="noreferrer">
            Open
          </a>
        ) : null}
      </div>
      <h2>{source.title}</h2>
      {meta.length ? <p className="source-meta">{meta.join(" · ")}</p> : null}
      <p>{source.snippet}</p>
    </article>
  );
}
