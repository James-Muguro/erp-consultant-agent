const STARTERS = [
  "Gather requirements for a new implementation",
  "Map a business process",
  "Design an ERP solution",
  "Generate QA test cases",
  "Prepare UAT scenarios",
  "Create training material",
];

export function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <h2 className="font-display text-2xl text-ink">What are we working on?</h2>
      <p className="mt-2 max-w-md text-sm text-ink-muted">
        Describe the task and I'll bring in the right specialist — requirements, process
        mapping, solution design, testing, or training.
      </p>
      <div className="mt-6 flex max-w-lg flex-wrap justify-center gap-2">
        {STARTERS.map((s) => (
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
