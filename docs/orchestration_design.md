# ERP Consultant Agent - Orchestration & Unified Interaction Design

This document provides a design for integrating your existing specialized agents into a coordinated orchestration system with a unified user interface. It covers the architecture, agents orchestration patterns, key components, interactions, and recommended enhancements for reasoning and knowledge retrieval.

---

## Goals
- Provide a single interface (API + UI) for users to chat with agents and trigger workflow phases.
- Keep each agent specialized and re-usable while giving the orchestrator the ability to coordinate flows.
- Add a reasoning layer to enable step-by-step plans, explainability, and routing decisions (KB vs web vs memory).
- Introduce an information retriever that aggregates internal KB, memory, and web results under orchestrator direction.
- Make actions auditable (chain-of-thought, decisions, and trace logs) and safe (configuration & permission checks).
- Provide an MVP UI for chat and project orchestration.

---

## System Architecture (Overview)

- **User Interface (UI):** Lightweight web UI (Prototyped in `ui/`) for chat and project management. Uses REST endpoints or WebSockets to interact with the API server.
- **API Gateway (FastAPI):** Exposes endpoints for chat, project management, phase execution and monitoring (`src/orchestrator_api.py`). Hosts the static UI in POC.
- **Orchestrator (OrchestratorAgent):** Central controller that sequences project phases using agent modules; responsible for progress, session management, and metrics.
- **Agent Modules (`src/agents`):** Specialized agents (requirements, process mapping, solution design, testing, training). Each agent provides typed APIs and uses memory, tools, and the LLM.
- **Reasoning Engine (`src/tools/reasoning.py`):** Wraps the model to produce plans and decisions; outputs plans, confidence, and justification.
- **Retriever (`src/tools/info_retriever.py`):** Aggregates internal KB (`erp_kb`), memory (`memory_bank`), and web search results (via `google_search`) guided by the Reasoning Engine.
- **Memory Bank (`src/memory/memory_bank.py`):** Long-term memory for templates, past projects, designs, and learnings. Supports search and recall.
- **Knowledge Base (`src/tools/erp_knowledge_base.py`):** Domain-specific ERP knowledge for quick retrieval and templates.
- **Tools Layer (`src/tools`):** For web search, test generation, doc generation, code execution, and others.

---

## Key Patterns & Decision Flow

1. User sends a message to the API (chat or project action).
2. API uses the Reasoning Engine to decide if the message should be routed to a specific agent or if the Retriever satisfies the query.
3. If the plan requires agent action(s), the orchestrator runs the agent(s) (synchronously for quick tasks; asynchronously for long-running tasks) and stores deliverables to memory.
4. For content that needs external validation (e.g. missing KB data), the reasoning engine may instruct the Info Retriever to run a web search.
5. All decisions, justification, and generated outputs are saved to `agent_memory` for traceability and downstream retrieval.

---

## Decision Logic for KB vs Web

- Use `info_retriever` to first check internal KB and memory; if it finds high-confidence matches (priority & importance weights), return those results.
- If internal sources are insufficient, reasoning tool chooses `hybrid` or `web` and `info_retriever` performs web search via `google_search` and merges results.
- Reasoning tool returns a decision and confidence score — this can be surfaced in the UI as 'used KB' or 'used web' and list the sources.

---

## Reasoning & Explanation

- The `reasoning_tool` should always return a small structured trace (plan + justification). Each agent and orchestrator action should log a short explanation and the chain-of-thought.
- Save the chain-of-thought and actions to memory for audits and post-hoc learning.

---

## Workflow Orchestration

- Each project is a session in memory, and the Orchestrator tracks the current phase.
- Each phase should be idempotent (safe re-run), and the orchestrator must maintain locks to prevent concurrent conflicting runs for a session.
- Background tasks: For long-running operations, use a queue (Celery) with Redis or a simplified background task runner. The orchestrator can start tasks and poll for status.

---

## UI Recommendations

- Chat view: Users can ask questions, trigger workflows, and see the details (e.g. sources, documents, plans).
- Project Panel: Start projects, run phases, view progress, view deliverables, and see phased logs.
- Visualizations: Show process maps (Graphviz), RACI matrices, and test case overviews. Use `tools/process_visualizer.py` or generate SVG/PNG for the client.
- Attachments: Allow users to download generated documents and view content from memory.

---

## Security & Admin Controls

- Add authentication & authorization for production — ensure only authorized users can create or run project workflows.
- Audit logs: All agent decisions should include what was done, why, and the sources used.

---

## Implementation Roadmap (MVP -> Advanced)

1. MVP (POC) - Implemented in this branch:
  - FastAPI endpoints (UI, chat, start project, run phase, status)
  - Reasoning tool & Info retriever (wrapper around KB, memory, web search)
  - Minimal UI with chat & project operations
  - Keep orchestrator and agents unchanged but add reasoning and info retrieval as helpers

2. v1 - Full orchestration, concurrent, and workflows
  - Add background worker (Celery/RQ) for long-running tasks
  - Add event messaging system (Redis pub/sub) to allow agents to notify orchestrator and each other
  - Implement an audit store for reasoning traces
  - Implement WebSocket-based UI updates

3. v2 - Advanced reasoning & safety
  - Implement RAG (retrieval-augmented generation) patterns inside agents for precise answers
  - Add policy checks for web vs KB or source validations and CRs
  - Add model-agnostic agent plugins for extensibility

---

## Suggested API Endpoints (example)

- POST /api/projects/start
- POST /api/projects/{session_id}/phase/{phase}/execute
- POST /api/chat (routes to reasoning => info retriever => agent(s) if needed)
- GET /api/projects/{session_id}/status
- GET /api/projects/{session_id}/deliverables
- GET /api/memory/search?q=...

---

## Next Steps
- Evaluate whether to keep LLM plan generation inside agents vs a centralized reasoning engine.
- Implement background worker if you expect async or long-running tasks.
- Set confidence threshold for KB vs web to minimize unnecessary web calls.
- Expand the UI with a conversation view, workflow monitor, and reports.

---

This document and the scaffolded files in `src/` and `ui/` provide an initial architecture and small POC. The implementation can be extended into a more robust production-ready system with background tasks, user accounts, and richer UI workflows.
