import { Activity, Loader2 } from "lucide-react";
import type { ChatResponse } from "../types";

export function StatusPill({
  isLoading,
  response,
  statusLabel,
}: {
  isLoading: boolean;
  response: ChatResponse | null;
  statusLabel: string;
}) {
  if (isLoading) {
    return (
      <span className="status-pill loading">
        <Loader2 size={15} />
        {statusLabel}
      </span>
    );
  }
  return (
    <span className="status-pill">
      <Activity size={15} />
      {response?.stage ?? statusLabel}
    </span>
  );
}
