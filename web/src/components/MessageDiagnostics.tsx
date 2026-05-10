import { Activity, ChevronDown } from "lucide-react";
import type { ChatResponse } from "../types";

export function MessageDiagnostics({ response }: { response: ChatResponse }) {
  const sourceCount = response.sources.length;

  return (
    <details className="message-details">
      <summary>
        <Activity size={15} />
        <span>{response.tool_used ?? response.stage}</span>
        <span>{sourceCount} sources</span>
        <ChevronDown size={15} />
      </summary>

      <div className="message-detail-body">
        <div className="message-chip-row">
          <strong>stage {response.stage}</strong>
          <strong>tool {response.tool_used ?? "—"}</strong>
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
