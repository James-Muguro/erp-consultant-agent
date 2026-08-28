# KB vs Web Search Policy

This guidance defines how to decide whether to use the internal ERP Knowledge Base (KB), the in-memory Memory Bank, or perform a web search.

## Rules

- Step 1: Query the KB for module-specific content and templates.
- Step 2: Query the Memory Bank for project-specific or pattern-based learnings (search_by_tags/keywords).
- Step 3: If neither KB nor Memory produce high-confidence answers, call the web search (SERP API) - this can be hybridized using RAG.

## Confidence Thresholds
- If KB has direct match (module & matching term), treat as high confidence.
- If Memory Bank returns results with high importance & recency, treat as medium-to-high confidence.
- Else: web search; mark the sources in outputs to ensure traceability.

## Implementation
- Use `reasoning_tool.assess_source(query, context)` to decide which sources to use.
- The `info_retriever.retrieve` function centralizes retrieval logic.
