import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { CaseStudyResponse } from "../types";


export function CaseStudyPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [data, setData] = useState<CaseStudyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);


  // Defer setState past the effect's synchronous phase.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled || !sessionId) return;
      try {
        const result = await api.getCaseStudy(sessionId);
        if (!cancelled) setData(result);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Not available.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);


  if (!data) {
    return (
      <div className="mx-auto max-w-3xl p-6 text-sm text-ink-muted">
        {error ?? "Loading…"}
      </div>
    );
  }


  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
        <p className="text-xs">
        <Link
          to="/opportunities"
          className="text-accent-strong underline"
        >
          ← Back to opportunities
        </Link>
      </p>
      <header>
        <h1 className="font-display text-lg text-ink">{data.project_name}</h1>
        <p className="mt-1 text-xs text-ink-muted">
          {data.module} · {data.erp_system} · Current phase:{" "}
          {data.current_phase}
        </p>
      </header>


      <div className="rounded-md border border-border bg-surface p-4">
        <h2 className="text-sm font-medium text-ink">Requirements</h2>
        <p className="mt-1 text-xs text-ink-muted">
          {data.requirements.total} requirement(s) recorded
        </p>
        {Object.keys(data.requirements.by_status).length > 0 && (
          <ul className="mt-2 space-y-1 text-xs text-ink-muted">
            {Object.entries(data.requirements.by_status).map(([k, v]) => (
              <li key={k}>
                {k}: {v}
              </li>
            ))}
          </ul>
        )}
      </div>


      <div className="rounded-md border border-border bg-surface p-4">
        <h2 className="text-sm font-medium text-ink">Deliverables</h2>
        {data.deliverables.length === 0 ? (
          <p className="mt-1 text-xs text-ink-muted">
            No deliverables generated yet.
          </p>
        ) : (
          <ul className="mt-2 space-y-1 text-xs text-ink-muted">
            {data.deliverables.map((d, idx) => (
              <li key={idx}>
                {d.phase} — {d.filename}
              </li>
            ))}
          </ul>
        )}
      </div>


      <p className="text-xs text-ink-faint">
        This is a read-only outcome view. Implementation workspace and
        testing surfaces are not available here.
      </p>
    </div>
  );
}