"""
Info Retriever - Decides between internal KB, memory, or web search and returns aggregated results
"""
from typing import Dict, Any, List
from src.tools import google_search as google_search_tool
from src.tools.erp_knowledge_base import erp_kb
from src.memory.memory_bank import memory_bank
from src.tools.reasoning import reasoning_tool
from src.utils.logger import AgentLogger


logger = AgentLogger("InfoRetriever")


def retrieve(query: str, context: Dict[str, Any] = None, prefer_web: bool = False) -> Dict[str, Any]:
    """Retrieve information about a query using KB, memory, or web.

    Returns aggregated results with source metadata and scores.
    """
    context = context or {}

    # Ask reasoning tool whether to use KB or Web
    if not prefer_web:
        decision = reasoning_tool.assess_source(query, context.get('summary', ''))
    else:
        decision = {'decision': 'web', 'confidence': 0.9, 'reasoning': 'Force web search by caller'}

    results = {
        'query': query,
        'decision': decision,
        'sources': []
    }

    # Use KB if decision is kb or hybrid
    if decision['decision'] in ('kb', 'hybrid'):
        # use ERPKnowledgeBase.search_knowledge for free-text search
        kb_hits = erp_kb.search_knowledge(query)
        if kb_hits:
            results['sources'].append({'type': 'kb', 'items': kb_hits})

        # Memory search
        mem_hits = memory_bank.search_by_keywords(query.lower().split())
        if mem_hits:
            results['sources'].append({'type': 'memory', 'items': [m.to_dict() for m in mem_hits]})

    # Use web if decision is web or hybrid
    if decision['decision'] in ('web', 'hybrid'):
        try:
            web_txt = google_search_tool.GoogleSearchTool()(query)
            results['sources'].append({'type': 'web', 'items': web_txt})
        except Exception as e:
            logger.error("Web search failed", exc_info=True)
            results['sources'].append({'type': 'web', 'items': []})

    return results


# Expose as module API
info_retriever = retrieve
