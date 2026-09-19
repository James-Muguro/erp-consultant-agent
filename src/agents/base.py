"""
Generic agent base class.

Status: legacy
--------------
This class predates the six specialized ERP agents
(RequirementsAgent, ProcessMappingAgent, SolutionDesignAgent,
QATestingAgent, UATTestingAgent, TrainingAgent). Those agents do not
inherit from it — each defines its own __init__ and uses AgentLogger
and get_llm() directly. The class is retained because:

  * `from src.agents import Agent` is a name that may be consumed by
    code outside the reviewed repository scope.
  * Removing it is a breaking change; keeping it is cheap.

If you confirm nothing imports `Agent` (grep for "from src.agents
import Agent", "src.agents.Agent", "from .base import Agent"), the
class, its module, and its entry in src/agents/__init__.py can be
deleted in a single commit.

If you keep it, the fixes below correct three bugs that would bite
the first caller who actually used this class:

  1. `run` used to be `async` but called a blocking HTTP routine
     in-line, stalling the event loop. It now offloads to a worker
     thread via asyncio.to_thread.
  2. `run` used to return the LLMResponse object despite a `-> str`
     annotation. It now returns the response text.
  3. Progress was emitted via termcolor.cprint (a stdout write with
     ANSI escape codes), which bypasses the structured logger and
     produces non-JSON lines in production. It now uses the shared
     structlog logger.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional

from src.utils.llm import get_llm, reload_llm
from src.config.settings import settings
from src.utils.logger import get_logger
from src.utils.model_selection import TaskCategory
from src.utils.resilience import run_with_timeout, OperationTimeoutError

logger = get_logger(__name__)


# Bound the whole LLM call. The hybrid wrapper bounds each provider
# attempt (settings.llm_call_timeout_seconds) but the aggregate across
# retries and tiers can be longer; this is the outer ceiling a caller
# of Agent.run can rely on.
_DEFAULT_RUN_TIMEOUT_SECONDS = 120.0


class Agent:
    """Base class for a generic query → text-response agent.

    NOT the base class of the six specialized ERP agents. Those use
    AgentLogger and get_llm() directly and share no inheritance with
    this class. See the module docstring for the full status note.

    The class is useful as a thin wrapper when a caller wants to send
    a query to the LLM with a system-role description and get back
    plain text. It does not implement iterative tool use, structured
    output, or schema validation — use the specialized agents for
    those.
    """

    def __init__(
        self,
        name: str,
        description: str,
        tools: Optional[List[Any]] = None,
        temperature: float = 0.7,
        max_iterations: int = 5,
    ):
        self.name = name
        self.description = description
        self.tools = tools or []
        self.temperature = temperature
        # `max_iterations` is accepted for API compatibility with
        # earlier consumers but is not used by this class — the current
        # run() is a single-shot LLM call, not an iterative loop.
        self.max_iterations = max_iterations

        # Shared singleton (see src/utils/llm.py). Each instance shares
        # the process-wide HybridLLMClient.
        self.model = get_llm()

    # ------------------------------------------------------------------ #
    # Model lifecycle
    # ------------------------------------------------------------------ #
    def reload_model(self) -> None:
        """Re-initialize the shared LLM client. Consistent with the
        specialized agents' reload_model; calls reload_llm() (which
        constructs a fresh HybridLLMClient) rather than get_llm()
        (which returns the existing singleton)."""
        self.model = reload_llm()

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    async def run(
        self,
        query: str,
        context: Optional[str] = None,
        *,
        response_schema: Optional[type] = None,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        """Send a query to the LLM and return the response text.

        Runs the blocking LLM call in a worker thread (via
        asyncio.to_thread) so the async event loop is not stalled
        while the call is in flight.

        Args:
            query: the user's message.
            context: optional reference context inserted into the
                prompt between the system-role description and the
                query. Plain string.
            response_schema: optional pydantic model to constrain the
                response as structured JSON. When provided, the return
                value is the raw JSON string; the caller validates it
                against the schema. When None (default), the LLM
                returns free-form text.
            timeout_seconds: outer time bound for the whole call
                (across provider retries and fallback tiers). Defaults
                to _DEFAULT_RUN_TIMEOUT_SECONDS.

        Returns:
            The response text. Empty string if the LLM returned no
            content (blocked, filtered, or empty).

        Raises:
            OperationTimeoutError: the call exceeded timeout_seconds.
            RuntimeError: the LLM client reported a failure for every
                configured provider.
        """
        if not query or not query.strip():
            return ""

        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else _DEFAULT_RUN_TIMEOUT_SECONDS
        )

        logger.info(
            "Agent run started",
            agent_name=self.name,
            query_length=len(query),
            has_context=bool(context),
            has_schema=response_schema is not None,
        )

        try:
            text = await asyncio.to_thread(
                self._run_sync,
                query,
                context,
                response_schema,
                timeout,
            )
        except OperationTimeoutError:
            logger.warning(
                "Agent run timed out",
                agent_name=self.name,
                timeout_seconds=timeout,
            )
            raise
        except Exception:
            logger.exception(
                "Agent run failed",
                agent_name=self.name,
            )
            raise

        logger.info(
            "Agent run completed",
            agent_name=self.name,
            response_length=len(text) if text else 0,
        )
        return text

    # ------------------------------------------------------------------ #
    # Internal: the synchronous work
    # ------------------------------------------------------------------ #
    def _run_sync(
        self,
        query: str,
        context: Optional[str],
        response_schema: Optional[type],
        timeout: float,
    ) -> str:
        """Synchronous implementation. Called from run() in a worker
        thread; kept separate so the async wrapper is a thin shim."""
        prompt = self._build_prompt(query, context)

        generation_config: dict = {
            "temperature": self.temperature,
            "max_output_tokens": settings.max_tokens,
            "task": TaskCategory.STANDARD_AGENT,
        }
        if response_schema is not None:
            generation_config["response_schema"] = response_schema

        response = run_with_timeout(
            self.model.generate_content,
            prompt,
            timeout=timeout,
            generation_config=generation_config,
        )

        # generate_content returns an LLMResponse (see src/utils/llm.py).
        # Extract text explicitly — the previous version returned the
        # object despite a `-> str` annotation.
        text = getattr(response, "text", None) or ""
        return text

    def _build_prompt(
        self,
        query: str,
        context: Optional[str] = None,
    ) -> str:
        """Compose the LLM prompt.

        Kept deliberately simple: a system-role line, an optional
        context block, and the query. Callers that need richer
        prompting (epistemic guardrails, delimited untrusted content,
        structured-output instructions) should build the prompt
        themselves and call the LLM wrapper directly — the specialized
        agents do exactly that.
        """
        parts: List[str] = [
            f"You are {self.name}, {self.description}.",
        ]
        if context:
            parts.append(f"Relevant context:\n{context}")
        parts.append(f"User query: {query}")
        parts.append("Please provide a detailed and helpful response.")
        return "\n\n".join(parts)