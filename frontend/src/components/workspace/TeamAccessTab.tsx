import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { EligibleErpUser, GrantRecord } from "../../types";
import { EmptyRow, ErrorRow, LoadingRow } from "./shared";

const ARTIFACTS: Array<{
  key: string;
  label: string;
  canSignatory?: boolean;
  canParticipant?: boolean;
}> = [
  { key: "requirements_questionnaire", label: "Requirements questionnaire" },
  { key: "frd", label: "FRD", canSignatory: true },
  { key: "uat_scenarios", label: "UAT scenarios", canParticipant: true },
  { key: "training_materials", label: "Training materials" },
];

export function TeamAccessTab({ sessionId }: { sessionId: string }) {
  const [eligible, setEligible] = useState<EligibleErpUser[]>([]);
  const [grants, setGrants] = useState<GrantRecord[]>([]);
  const [history, setHistory] = useState<GrantRecord[]>([]);
  const [loading, setLoading] = useState(true);
  // loadError blocks the view entirely — it means the initial load
  // failed and we have nothing to show. actionError is rendered as an
  // inline banner so a failed toggle does not wipe out the table.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoadError(null);
    try {
      const [e, g, h] = await Promise.all([
        api.getEligibleErpUsers(sessionId),
        api.getGrants(sessionId),
        api.getGrantHistory(sessionId),
      ]);
      setEligible(e.users);
      setGrants(g.grants);
      setHistory(h.grants);
    } catch (err) {
      setLoadError(
        err instanceof Error ? err.message : "Could not load grants.",
      );
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  // Initial load. Deferred past the effect's sync phase; reload above
  // stays for the toggle handlers and the retry button.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled) return;
      setLoadError(null);
      try {
        const [e, g, h] = await Promise.all([
          api.getEligibleErpUsers(sessionId),
          api.getGrants(sessionId),
          api.getGrantHistory(sessionId),
        ]);
        if (cancelled) return;
        setEligible(e.users);
        setGrants(g.grants);
        setHistory(h.grants);
      } catch (err) {
        if (!cancelled) {
          setLoadError(
            err instanceof Error ? err.message : "Could not load grants.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  function findGrant(
    userId: string,
    artifact: string,
  ): GrantRecord | undefined {
    return grants.find(
      (g) => g.user_id === userId && g.artifact_type === artifact,
    );
  }

  async function toggleActive(user: EligibleErpUser, artifact: string) {
    const existing = findGrant(user.user_id, artifact);
    const key = `${user.user_id}:${artifact}`;
    setBusyKey(key);
    setActionError(null);
    try {
      if (existing) {
        await api.revokeGrant(sessionId, user.user_id, artifact);
      } else {
        await api.createGrant(sessionId, {
          user_id: user.user_id,
          artifact_type: artifact,
          is_signatory: false,
          is_uat_participant: false,
        });
      }
      await reload();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Could not update the grant.",
      );
    } finally {
      setBusyKey(null);
    }
  }

  async function toggleDesignation(
    user: EligibleErpUser,
    artifact: string,
    field: "is_signatory" | "is_uat_participant",
  ) {
    const existing = findGrant(user.user_id, artifact);
    if (!existing) return;
    const key = `${user.user_id}:${artifact}:${field}`;
    setBusyKey(key);
    setActionError(null);
    try {
      await api.createGrant(sessionId, {
        user_id: user.user_id,
        artifact_type: artifact,
        is_signatory:
          field === "is_signatory"
            ? !existing.is_signatory
            : existing.is_signatory,
        is_uat_participant:
          field === "is_uat_participant"
            ? !existing.is_uat_participant
            : existing.is_uat_participant,
      });
      await reload();
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : "Could not update the grant.",
      );
    } finally {
      setBusyKey(null);
    }
  }

  if (loading) return <LoadingRow label="Loading team access…" />;
  if (loadError) return <ErrorRow message={loadError} onRetry={reload} />;
  if (eligible.length === 0) {
    return (
      <EmptyRow label="No eligible ERP Users on this project. Invite ERP Users to the organization, then return here to assign artifacts." />
    );
  }

  return (
    <div className="space-y-6">
      {actionError && (
        <p
          role="alert"
          className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          {actionError}
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-faint">
              <th className="py-2 pr-3">User</th>
              {ARTIFACTS.map((a) => (
                <th key={a.key} className="py-2 px-2">
                  {a.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {eligible.map((user) => (
              <tr key={user.user_id} className="border-t border-border">
                <td className="py-2 pr-3">
                  <div className="text-ink">{user.name ?? user.email}</div>
                  <div className="text-xs text-ink-faint">{user.email}</div>
                </td>
                {ARTIFACTS.map((a) => {
                  const g = findGrant(user.user_id, a.key);
                  const active = !!g;
                  const grantKey = `${user.user_id}:${a.key}`;
                  const signatoryKey = `${user.user_id}:${a.key}:is_signatory`;
                  const participantKey = `${user.user_id}:${a.key}:is_uat_participant`;
                  return (
                    <td key={a.key} className="py-2 px-2 align-top">
                      <button
                        type="button"
                        disabled={busyKey === grantKey}
                        onClick={() => toggleActive(user, a.key)}
                        className={`rounded-md border px-2 py-1 text-xs ${
                          active
                            ? "border-accent text-accent-strong"
                            : "border-border text-ink-muted"
                        } disabled:opacity-50`}
                      >
                        {active ? "Granted" : "Grant"}
                      </button>
                      {active && a.canSignatory && g && (
                        <label className="mt-1 flex items-center gap-1 text-xs text-ink-muted">
                          <input
                            type="checkbox"
                            checked={g.is_signatory}
                            disabled={busyKey === signatoryKey}
                            onChange={() =>
                              toggleDesignation(user, a.key, "is_signatory")
                            }
                          />
                          Signatory
                        </label>
                      )}
                      {active && a.canParticipant && g && (
                        <label className="mt-1 flex items-center gap-1 text-xs text-ink-muted">
                          <input
                            type="checkbox"
                            checked={g.is_uat_participant}
                            disabled={busyKey === participantKey}
                            onChange={() =>
                              toggleDesignation(
                                user,
                                a.key,
                                "is_uat_participant",
                              )
                            }
                          />
                          UAT participant
                        </label>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details className="rounded-md border border-border bg-surface p-3">
        <summary className="cursor-pointer text-sm text-ink-muted">
          History ({history.length})
        </summary>
        {history.length === 0 ? (
          <p className="mt-2 text-xs text-ink-faint">No revoked grants.</p>
        ) : (
          <ul className="mt-2 space-y-1 text-xs text-ink-muted">
            {history.map((g) => (
              <li key={g.id}>
                {g.user_email ?? g.user_id} — {g.artifact_type} revoked{" "}
                {g.revoked_at
                  ? new Date(g.revoked_at).toLocaleString()
                  : "—"}
                {g.revoked_by_email ? ` by ${g.revoked_by_email}` : ""}
              </li>
            ))}
          </ul>
        )}
      </details>
    </div>
  );
}