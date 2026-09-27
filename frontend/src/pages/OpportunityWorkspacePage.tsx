import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  EligibleConsultant,
  Opportunity,
  OpportunityRequirement,
} from "../types";


const FIT_LABEL: Record<string, string> = {
  meets_out_of_the_box: "Meets out of the box",
  requires_customization: "Requires customization",
  not_supported: "Not supported",
};


export function OpportunityWorkspacePage() {
  const { opportunityId } = useParams<{ opportunityId: string }>();
  const navigate = useNavigate();


  const [opp, setOpp] = useState<Opportunity | null>(null);
  const [requirements, setRequirements] = useState<OpportunityRequirement[]>([]);
  const [consultants, setConsultants] = useState<EligibleConsultant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [draftingId, setDraftingId] = useState<string | null>(null);


  // Initial load only; deferred past the effect's sync phase.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.resolve();
      if (cancelled || !opportunityId) return;
      setLoading(true);
      setError(null);
      try {
        const [o, reqs, cons] = await Promise.all([
          api.getOpportunity(opportunityId),
          api.listOpportunityRequirements(opportunityId),
          api.listEligibleConsultants(opportunityId),
        ]);
        if (cancelled) return;
        setOpp(o);
        setRequirements(reqs.requirements);
        setConsultants(cons.users);
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load opportunity.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [opportunityId]);


  async function onUpload(file: File) {
    if (!opportunityId) return;
    setUploading(true);
    setError(null);
    try {
      const res = await api.uploadTor(opportunityId, file);
      setRequirements(res.requirements);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }


  async function draft(requirementId: string) {
    if (!opportunityId) return;
    setDraftingId(requirementId);
    setError(null);
    try {
      const updated = await api.draftRequirement(opportunityId, requirementId);
      setRequirements((prev) =>
        prev.map((r) => (r.id === updated.id ? updated : r)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI draft failed.");
    } finally {
      setDraftingId(null);
    }
  }


  async function finalize(
    requirementId: string, fitResponse: string, comment: string,
  ) {
    if (!opportunityId) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.finalizeRequirement(
        opportunityId, requirementId,
        { fit_response: fitResponse, comment: comment.trim() || undefined },
      );
      setRequirements((prev) =>
        prev.map((r) => (r.id === updated.id ? updated : r)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Finalize failed.");
    } finally {
      setBusy(false);
    }
  }


  async function markTorFinalized() {
    if (!opportunityId) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.markTorFinalized(opportunityId);
      setOpp(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not finalize TOR.");
    } finally {
      setBusy(false);
    }
  }


  async function generateResponse() {
    if (!opportunityId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.generateTenderResponse(opportunityId);
      await api.downloadTenderResponse(opportunityId, res.filename);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed.");
    } finally {
      setBusy(false);
    }
  }


  async function markWon(consultantId?: string) {
    if (!opportunityId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.markWon(opportunityId, {
        consultant_user_id: consultantId,
      });
      navigate(`/p/${res.session_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Mark as Won failed.");
    } finally {
      setBusy(false);
    }
  }


  if (!opp) {
    return (
      <div className="mx-auto max-w-3xl p-6 text-sm text-ink-muted">
        {loading ? "Loading…" : error ?? "Not available."}
      </div>
    );
  }


  const allFinalized = requirements.length > 0 &&
    requirements.every((r) => r.ai_draft_status === "finalized");


  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <header>
        <h1 className="font-display text-lg text-ink">{opp.title}</h1>
        <p className="mt-1 text-xs text-ink-muted">
          Client: {opp.client_name} · Status: {opp.status}
        </p>
      </header>


      {error && (
        <p
          role="alert"
          className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}


      {opp.status !== "won" && opp.status !== "lost" && opp.status !== "archived" && (
        <div className="rounded-md border border-border bg-surface p-4 space-y-3">
          <h2 className="text-sm font-medium text-ink">TOR</h2>
          <p className="text-xs text-ink-muted">
            Upload the tender's Word (.docx) document. Excel (.xlsx) is
            accepted as a fallback. Each extracted row becomes an editable
            requirement.
          </p>
          <input
            type="file"
            accept=".docx,.doc,.xlsx,.xls"
            disabled={uploading}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
            }}
            className="text-xs"
          />
          {uploading && (
            <p className="text-xs text-ink-faint">Uploading and parsing…</p>
          )}
        </div>
      )}


      {requirements.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-ink">
            Requirements ({requirements.length})
          </h2>
          <ul className="space-y-3">
            {requirements.map((r) => (
              <RequirementRow
                key={`${r.id}:${r.updated_at ?? r.ai_draft_status}`}
                requirement={r}
                busy={busy || draftingId === r.id}
                onDraft={() => draft(r.id)}
                onFinalize={(fit, comment) =>
                  finalize(r.id, fit, comment)
                }
              />
            ))}
          </ul>
        </div>
      )}


      {requirements.length > 0 && opp.status === "draft" && (
        <button
          type="button"
          disabled={busy || !allFinalized}
          onClick={markTorFinalized}
          className="rounded-md bg-accent px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {allFinalized
            ? "Mark TOR finalized"
            : "Finalize every requirement first"}
        </button>
      )}


      {opp.status === "tor_finalized" && (
        <div className="rounded-md border border-border bg-surface p-4 space-y-3">
          <h2 className="text-sm font-medium text-ink">Submission</h2>
          <button
            type="button"
            disabled={busy}
            onClick={generateResponse}
            className="rounded-md border border-accent px-3 py-2 text-sm text-accent-strong"
          >
            Generate tender response
          </button>


          <ConsultantPicker
            consultants={consultants}
            currentConsultantId={opp.assigned_consultant_user_id}
            onSelect={async (id) => {
              if (!opportunityId) return;
              try {
                const updated = await api.assignConsultant(opportunityId, id);
                setOpp(updated);
              } catch (e) {
                setError(
                  e instanceof Error ? e.message : "Could not assign consultant.",
                );
              }
            }}
          />


          <button
            type="button"
            disabled={busy || !opp.assigned_consultant_user_id}
            onClick={() => markWon()}
            className="rounded-md bg-accent px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            Mark as Won
          </button>
          {!opp.assigned_consultant_user_id && (
            <p className="text-xs text-ink-faint">
              Assign a Functional Consultant before marking Won.
            </p>
          )}
        </div>
      )}
    </div>
  );
}


function RequirementRow({
  requirement,
  busy,
  onDraft,
  onFinalize,
}: {
  requirement: OpportunityRequirement;
  busy: boolean;
  onDraft: () => void;
  onFinalize: (fit: string, comment: string) => void;
}) {
  const [fit, setFit] = useState(
    requirement.fit_response ?? requirement.fit_response_ai ?? "",
  );
  const [comment, setComment] = useState(
    requirement.fit_response_comment ?? requirement.fit_response_ai_comment ?? "",
  );


  const finalized = requirement.ai_draft_status === "finalized";


  return (
    <li className="rounded-md border border-border bg-surface p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-mono text-ink-faint">
            {requirement.external_code ?? "—"}
            {requirement.category && ` · ${requirement.category}`}
          </p>
          <p className="mt-1 text-sm text-ink">{requirement.description}</p>
        </div>
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-xs ${
            finalized
              ? "border-accent text-accent-strong"
              : "border-border-strong text-ink-muted"
          }`}
        >
          {requirement.ai_draft_status}
        </span>
      </div>


      {requirement.fit_response_ai && (
        <p className="text-xs text-ink-faint">
          AI suggested:{" "}
          {FIT_LABEL[requirement.fit_response_ai] ?? requirement.fit_response_ai}
          {requirement.fit_response_ai_comment && (
            <> — {requirement.fit_response_ai_comment}</>
          )}
        </p>
      )}


      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy || finalized}
          onClick={onDraft}
          className="rounded-md border border-border px-2 py-1 text-xs text-ink-muted disabled:opacity-50"
        >
          {busy ? "Working…" : requirement.fit_response_ai ? "Re-draft" : "AI draft"}
        </button>
      </div>


      <div className="grid grid-cols-2 gap-2">
        <select
          value={fit}
          onChange={(e) => setFit(e.target.value)}
          disabled={finalized}
          className="rounded-md border border-border bg-surface px-2 py-1 text-xs"
        >
          <option value="">Select response…</option>
          <option value="meets_out_of_the_box">Meets out of the box</option>
          <option value="requires_customization">Requires customization</option>
          <option value="not_supported">Not supported</option>
        </select>
      </div>


      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={2}
        placeholder="Comment (visible in the tender response)…"
        disabled={finalized}
        className="w-full rounded-md border border-border bg-surface px-2 py-1 text-xs"
      />


      <button
        type="button"
        disabled={busy || finalized || !fit}
        onClick={() => onFinalize(fit, comment)}
        className="rounded-md bg-accent px-3 py-1 text-xs text-white disabled:opacity-50"
      >
        {finalized ? "Finalized" : "Finalize"}
      </button>
    </li>
  );
}


function ConsultantPicker({
  consultants,
  currentConsultantId,
  onSelect,
}: {
  consultants: EligibleConsultant[];
  currentConsultantId: string | null;
  onSelect: (id: string) => void;
}) {
  if (consultants.length === 0) {
    return (
      <p className="text-xs text-ink-faint">
        No eligible Functional Consultants in this organization.
      </p>
    );
  }
  return (
    <div className="space-y-1">
      <label className="text-xs text-ink-muted">Functional Consultant</label>
      <select
        value={currentConsultantId ?? ""}
        onChange={(e) => {
          if (e.target.value) onSelect(e.target.value);
        }}
        className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
      >
        <option value="">Select…</option>
        {consultants.map((c) => (
          <option key={c.user_id} value={c.user_id}>
            {c.name ?? c.email} ({c.email})
          </option>
        ))}
      </select>
    </div>
  );
}