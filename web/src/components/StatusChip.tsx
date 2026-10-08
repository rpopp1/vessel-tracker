import { useEffect, useState } from "react";
import { chipModel } from "../liveLogic";
import type { LiveState } from "../types";

const TONE_COLORS = { ok: "#10b981", warn: "#f59e0b", idle: "#9ca3af" };

export default function StatusChip({ live, newestTs, errorDetail }: { live: LiveState; newestTs: string | null; errorDetail?: string | null }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 5000); return () => clearInterval(t); }, []);
  const m = chipModel(live, newestTs, Date.now(), errorDetail);
  return (
    <div className="chip">
      <span className="dot" style={{ background: TONE_COLORS[m.tone] }} />
      {m.label} - newest AIS message {m.ageText}
    </div>
  );
}
