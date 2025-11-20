
"""
Custom tools and factory instances for ERP Consultant Agent
"""

# Tool classes
from .google_search import GoogleSearchTool
from .document_analyzer import DocumentAnalyzerTool
from .process_visualizer import ProcessVisualizerTool
from .erp_knowledge_base import ERPKnowledgeBaseTool, ERPKnowledgeBase, erp_kb
from .test_case_generator import (
    TestCaseGeneratorTool,
    TestCaseGenerator,
    test_generator,
)
from .code_execution import CodeExecutionTool
from .document_generator import (
    DocumentGeneratorTool,
    DocumentGenerator,
    doc_generator,
)

__all__ = [
    # Tool classes
    "GoogleSearchTool",
    "DocumentAnalyzerTool",
    "ProcessVisualizerTool",
    "ERPKnowledgeBaseTool",
    "TestCaseGeneratorTool",
    "CodeExecutionTool",
    "DocumentGeneratorTool",

    # Core classes
    "ERPKnowledgeBase",
    "DocumentGenerator",
    "TestCaseGenerator",

    # Pre-built instances
    "erp_kb",
    "doc_generator",
    "test_generator",
]
