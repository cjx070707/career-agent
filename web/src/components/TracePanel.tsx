import { Activity } from "lucide-react";
import type { ChatResponse } from "../types";

function TraceItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function TracePanel({ response }: { response: ChatResponse | null }) {
  return (
    <section className="trace-section">
      <div className="section-title">
        <Activity size={18} />
        Trace
      </div>
      <div className="trace-grid">
        <TraceItem label="Stage" value={response?.stage ?? "—"} />
        <TraceItem label="Tool" value={response?.tool_used ?? "—"} />
        <TraceItem
          label="Memory"
          value={response ? (response.memory_used ? "used" : "not used") : "—"}
        />
      </div>
      <div className="steps-row">
        {(response?.tool_trace?.length ? response.tool_trace : ["No tools run"]).map((step) => (
          <span key={step}>{step}</span>
        ))}
      </div>
    </section>
  );
}
