# Agent Protocol & Integration Guide

This document explains the contract and patterns for agent interactions and how the orchestrator should route messages and tasks.

---

## Message Contract

1. Agents are pure functions that accept a typed context and return a structured result and reasoning trace.
   - Input:
     - session_id: string
     - context: Dict[str, Any] (structured requirements, process, or design info)
     - config: Optional configs like erp_system, module
     - instruction: Optional textual instruction
   - Output:
     - success: bool
     - structured result: Dict[str, Any]
     - document_path: Optional str
     - raw_text: Optional str
     - reasoning_trace: Optional str

2. Agents should not directly call web tools; instead, request them via the Info Retriever or orchestrator. This centralizes web usage and auditing.

3. Agents should log decisions and store outputs in memory via `agent_memory.save_phase_output` and `agent_memory.session_service.log_decision`.

---

## Orchestration Patterns

- Command & Control: Orchestrator chooses which agent to call based on the current phase and heuristics.
- Subscription / Event: Agents can emit events (e.g., `found_new_integration`) with payloads, and the orchestrator or other agents can subscribe.
- Replanning / Fallback: When an agent returns `success: False`, orchestrator should use the Reasoning Engine to either retry, escalate, or route to alternative agents.

---

## Example Agent Lifecycle for Requirements

1. Orchestrator calls `requirements_agent.gather_requirements`.
2. Agent queries KB, memory for past templates, calls LLM to structure requirements, and stores output.
3. Agent requests the orchestrator to proceed to Process Mapping.
4. Orchestrator runs Process Mapping or waits for user approval.

---

## Agent Safety & Policies

- Agents must validate inputs and authorize sensitive operations through a central policy engine before taking action (e.g. project deletion).
- Support dry-run mode for actions that would change external systems or create production artifacts.
