import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ErpUserGrantInfo } from "../types";


export function useArtifactGrants(sessionId: string | undefined) {
  const [grants, setGrants] = useState<ErpUserGrantInfo[]>([]);
  const [loading, setLoading] = useState(Boolean(sessionId));
  const [error, setError] = useState<string | null>(
    sessionId ? null : "missing session",
  );


  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await api.getErpUserArtifacts(sessionId);
        if (cancelled) return;
        setGrants(res.grants);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setGrants([]);
        setError(err instanceof Error ? err.message : "load failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);


  return { grants, loading, error };
}