import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../context/useAuth";
import type { Opportunity } from "../types";
import { EmptyRow, LoadingRow } from "../components/workspace/shared";


export function OpportunityListPage() {
  const { user } = useAuth();
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [clientName, setClientName] = useState("");

  // Stable reference — memoize so downstream effects don't re-run on
  // every render of this component.
  const orgs = useMemo(
    () => user?.organizations ?? [],
    [user?.organizations],
  );

  // Lazy initialiser: the first render already knows the single-org
  // case, so no effect and no second render are needed for it.
  const [orgId, setOrgId] = useState<string>(
    () => (orgs.length === 1 ? orgs[0].id : ""),
  );


  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listOpportunities();
      setOpportunities(res.opportunities);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load opportunities.");
    } finally {
      setLoading(false);
    }
  }, []);


  // Initial load only; deferred past the effect's sync phase.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled) return;
      setLoading(true);
      setError(null);
      try {
        const res = await api.listOpportunities();
        if (!cancelled) setOpportunities(res.opportunities);
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load opportunities.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Sync orgId when the user switches to a single-org context. Deferred
  // past the effect's sync phase to avoid cascading renders.
  useEffect(() => {
    if (orgs.length !== 1 || orgId === orgs[0].id) return;
    const handle = window.setTimeout(() => setOrgId(orgs[0].id), 0);
    return () => window.clearTimeout(handle);
  }, [orgs, orgId]);


  async function create() {
    if (!title.trim() || !clientName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await api.createOpportunity({
        title: title.trim(),
        client_name: clientName.trim(),
        organization_id: orgId || undefined,
      });
      setTitle("");
      setClientName("");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create opportunity.");
    } finally {
      setCreating(false);
    }
  }


  if (orgs.length === 0) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <EmptyRow label="You are not a member of any organization yet. Create an organization before adding opportunities." />
      </div>
    );
  }


  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <header>
        <h1 className="font-display text-lg text-ink">Opportunities</h1>
        <p className="mt-1 text-xs text-ink-muted">
          Tenders and prospective projects. Upload the TOR, draft fit
          responses with AI assistance, and mark Won to hand off to a
          consultant.
        </p>
      </header>


      <div className="rounded-md border border-border bg-surface p-4 space-y-3">
        <h2 className="text-sm font-medium text-ink">New opportunity</h2>
        {orgs.length > 1 && (
          <select
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
          >
            <option value="">Select organization…</option>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        )}
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Tender title"
          maxLength={200}
          className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
        />
        <input
          type="text"
          value={clientName}
          onChange={(e) => setClientName(e.target.value)}
          placeholder="Client name"
          maxLength={200}
          className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={create}
          disabled={creating || !title.trim() || !clientName.trim() || !orgId}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {creating ? "Creating…" : "Create opportunity"}
        </button>
      </div>


      {error && (
        <p
          role="alert"
          className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}


      {loading ? (
        <LoadingRow label="Loading opportunities…" />
      ) : opportunities.length === 0 ? (
        <EmptyRow label="No opportunities yet." />
      ) : (
        <ul className="space-y-2">
          {opportunities.map((o) => (
            <li
              key={o.id}
              className="rounded-md border border-border bg-surface p-3"
            >
              <Link
                to={`/opportunities/${o.id}`}
                className="block hover:opacity-80"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ink">{o.title}</p>
                    <p className="mt-0.5 text-xs text-ink-muted">
                      {o.client_name}
                    </p>
                  </div>
                  <span className="shrink-0 rounded-full border border-border-strong px-2 py-0.5 text-xs text-ink-muted">
                    {o.status}
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}