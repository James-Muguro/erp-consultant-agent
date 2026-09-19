"""
Custom tools and factory instances for the ERP Consultant Agent.

Package role
------------
This is the aggregation point for every tool the agents, the orchestrator,
and the API layer import. Agents do `from src.tools import erp_kb,
doc_generator`; the API imports individual tools through their submodule
paths (`from src.tools.document_generator import doc_generator`).

Import-coupling contract
------------------------
Every name below is re-exported from a submodule, and every submodule is
imported unconditionally at package load. That means: if ANY submodule in
this package fails to import - a required dependency is missing
(`python-docx`, `pydantic`), a syntax error exists in an ERP data file, a
nested `__init__` raises - then `src.tools` fails to import as a whole,
and every agent that does `from src.tools import ...` fails at its own
import. In practice that takes the entire application down at startup.

That is a deliberate trade-off, not an oversight:

  * Required dependencies should fail loudly. A codebase that starts up
    without `python-docx` and then can't generate documents is worse than
    one that refuses to start and says why.

  * Optional dependencies should degrade within the tool module, not at
    the package boundary. This is why `google_search.py` catches a
    missing `serpapi` at its own import time and exposes
    `_SERPAPI_AVAILABLE = False`, and why `text_sanitize.py` catches a
    missing `ftfy` the same way. Adding a new tool that wraps an optional
    dependency follows that pattern in the tool's own module - it does
    NOT install a silent stub here.

Contributors adding a new tool should be aware that:
  - A new entry in this file's imports extends the coupling above to
    every consumer.
  - A tool that can run without its dependency should handle the missing
    dependency itself (return a clear error on use, do not import-fail).
  - A tool whose dependency is genuinely required should let ImportError
    propagate and take the app down - with a clear message, which Python
    provides for missing modules.

Import order
------------
The order of the imports below is not alphabetical, because
`erp_knowledge_base` triggers the knowledge-base initialization chain:
`erp_knowledge_base` -> `src.tools.knowledge` (the ERP modules and loader)
-> `src.tools.knowledge.base` (the singleton). The shim runs a one-shot
"is the KB populated?" diagnostic at its own import time, and that
diagnostic is only meaningful after the loader has run. Importing
`erp_knowledge_base` after the loader's own package chain has fired keeps
the diagnostic accurate; moving it above the other imports is fine (they
do not depend on it), but moving it around inside the knowledge package
chain is not something this file controls.

Exposure conventions
--------------------
Three kinds of exports live in `__all__`:

  * Tool *classes* (GoogleSearchTool, DocumentAnalyzerTool,
    ProcessVisualizerTool, ERPKnowledgeBaseTool, TestCaseGeneratorTool,
    ERPKnowledgeBase, DocumentGenerator, TestCaseGenerator) - import and
    instantiate as needed. Most consumers should use the pre-built
    instance instead.

  * Pre-built *instances* (erp_kb, erp_kb_tool, doc_generator,
    reasoning_tool, test_generator) - safe to share across threads
    because each instance opens its own resources per call. This is what
    agents import.

  * Function aliases (info_retriever) - `info_retriever` is the module's
    public function, aliased so callers don't have to know it's a
    function rather than an instance. The name is historical.

Deprecation note
----------------
`test_generator` and `TestCaseGeneratorTool` are retained for backward
compatibility but are no longer called by the QA and UAT testing agents.
The agents now refuse to substitute fabricated test cases when LLM output
is unusable (see src/agents/qa_testing_agent.py and
src/agents/uat_testing_agent.py) rather than falling back to generic
placeholders from `test_generator`. New code should not use
`test_generator`; it exists so that any external caller or test that
still references it does not break. It can be removed once nothing in
the repository imports it.
"""

# ---------------------------------------------------------------------------
# Submodule imports
# ---------------------------------------------------------------------------
# See the module docstring for the import-coupling contract and the
# import-order note about erp_knowledge_base.
from .google_search import GoogleSearchTool
from .document_analyzer import DocumentAnalyzerTool
from .process_visualizer import ProcessVisualizerTool
from .info_retriever import info_retriever
from .reasoning import reasoning_tool

# erp_knowledge_base pulls in the entire knowledge package as a side
# effect of its own import (see module docstring, "Import order").
from .erp_knowledge_base import (
    ERPKnowledgeBase,
    ERPKnowledgeBaseTool,
    erp_kb,
    erp_kb_tool,
)

from .test_case_generator import (
    TestCaseGeneratorTool,
    TestCaseGenerator,
    test_generator,
)
from .document_generator import (
    DocumentGenerator,
    doc_generator,
)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------
__all__ = [
    # -- Tool classes -------------------------------------------------------
    "GoogleSearchTool",
    "DocumentAnalyzerTool",
    "ProcessVisualizerTool",
    "ERPKnowledgeBaseTool",
    "TestCaseGeneratorTool",
    "ERPKnowledgeBase",
    "DocumentGenerator",
    "TestCaseGenerator",

    # -- Pre-built instances -----------------------------------------------
    # Shared, thread-safe (each opens its own resources per call).
    "erp_kb",
    "erp_kb_tool",
    "doc_generator",
    "reasoning_tool",
    "test_generator",  # deprecated - see module docstring

    # -- Function aliases --------------------------------------------------
    "info_retriever",
]