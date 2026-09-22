/**
 * First-run surface, shown only when the conversation is empty. In the
 * routed app this is the fresh-ad-hoc chat case (`/chat`), because a
 * project chat always loads its history before rendering and therefore
 * never reaches `messages.length === 0`.
 *
 * The starters are deliberately question-shaped, not action-shaped.
 * The previous version offered "Generate QA test cases" and similar on
 * a chat that had no session yet, which the backend rejects with
 * "session_id is required to run a phase" - i.e. the buttons were
 * broken. Phase execution belongs in a project, where the backend
 * already surfaces the correct next action through `next_action` on the
 * message that just completed.
 */
const QUESTION_STARTERS = [
  "What is the difference between SAP S/4HANA and SAP ECC?",
  "What are common pitfalls in an ERP implementation?",
  "How should I structure a fit-gap analysis?",
  "What goes into a typical UAT test plan?",
];

export function EmptyState({
  hasSession,
  onPick,
}: {
  /** True when there is an active session (project chat or resumed
   * ad-hoc chat). Unused today but kept so callers don't need to change
   * when contextual starters are added. */
  hasSession: boolean;
  onPick: (text: string) => void;
}) {
  // Reserved for future contextual starters. Referenced so the linter
  // does not strip the parameter before it is actually used.
  void hasSession;

  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <h2 className="font-display text-2xl text-ink">What are we working on?</h2>
      <p className="mt-2 max-w-md text-sm text-ink-muted">
        Ask a question, or open a project to run a structured phase —
        requirements, process mapping, solution design, testing, or training.
      </p>
      <div className="mt-6 flex max-w-lg flex-wrap justify-center gap-2">
        {QUESTION_STARTERS.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-ink transition-colors hover:border-accent hover:text-accent-strong"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}