import { BriefcaseBusiness } from "lucide-react";
import type { ChatResponse } from "../types";
import { SourceCard } from "./SourceCard";
import { TracePanel } from "./TracePanel";

export function EvidencePanel({ response }: { response: ChatResponse | null }) {
  return (
    <aside className="evidence-pane">
      <TracePanel response={response} />
      <section className="sources-section">
        <div className="section-title">
          <BriefcaseBusiness size={18} />
          Sources
        </div>
        <div className="source-list">
          {response?.sources?.length ? (
            response.sources.map((source, index) => (
              <SourceCard key={`${source.title}-${index}`} source={source} />
            ))
          ) : (
            <div className="muted-box">No sources yet.</div>
          )}
        </div>
      </section>
    </aside>
  );
}
