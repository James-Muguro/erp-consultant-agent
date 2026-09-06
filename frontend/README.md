# Frontend

React + TypeScript + Vite, styled with Tailwind v4. Replaces the old
vanilla-JS demo UI as the default at `/` (the old one is preserved,
unchanged, at `/ui`).

## Local development

Run the backend first (from the repo root):
```
uvicorn src.orchestrator_api:app --reload
```
Then, in this directory:
```
npm install
npm run dev
```
Vite's dev server proxies `/api`, `/health`, and `/ready` to
`http://127.0.0.1:8000` (see `vite.config.ts`) so the app can call the API
with relative paths in both dev and production.

## Tests

```
npm run test
```
Runs Vitest against the SSE parser (`src/api/sse.ts`) and the chat hook
(`src/hooks/useChat.ts`) - the two pieces of real logic in this app, kept
separate from rendering so they're testable without a browser. Component
rendering itself isn't covered by automated tests yet; there's no browser
available in the environment these were built in, so a manual click-through
is worth doing before considering the UI itself fully proven, on top of
these logic tests.

## Production build

```
npm run build
```
Outputs to `dist/` (gitignored - build it as a deploy step, don't commit
it). The backend serves `dist/index.html` at `/` and `dist/assets/*` at
`/assets` automatically once it exists (see `get_ui()` in
`src/orchestrator_api.py`); if `dist/` doesn't exist yet, `/` falls back to
a plain message pointing at `/ui` and `/docs` instead of erroring.

## Structure

- `src/api/client.ts` - all backend calls, JWT storage, and the SSE-streaming
  chat request (uses `fetch` + a manual reader, not `EventSource`, since
  `EventSource` can't send a POST body or an Authorization header).
- `src/api/sse.ts` - pure SSE-chunk parser, decoupled from the fetch/stream
  plumbing so it's unit-testable.
- `src/hooks/useChat.ts` - chat state machine (messages, streaming text,
  agent-activity steps) driven by parsed SSE events.
- `src/context/AuthContext.tsx` - current user + login/signup/logout.
- `src/components/` - Sidebar, ChatPanel, MessageBubble, AgentActivity,
  NewProjectModal, EmptyState.
