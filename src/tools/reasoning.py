"""
Reasoning Tool - Higher-level reasoning and decision support for agents and orchestrator
"""
from typing import Dict, Any
from src.utils.llm import get_llm
from src.config.settings import settings
from src.utils.logger import AgentLogger


class ReasoningTool:
    """Wraps the LLM to produce plans, justifications, and route decisions."""

    def __init__(self):
        self.logger = AgentLogger("ReasoningTool")

        # Get the shared LLM instance
        self.model = get_llm()

        # Store generation config separately
        self.generation_config = {
            'temperature': 0.2,
            'max_output_tokens': 512
        }

    def reload_model(self):
        """Reinitialize the reasoning tool's model."""
        self.model = get_llm()

    def assess_source(self, query: str, context: str = "") -> Dict[str, Any]:
        """Decide whether to use KB, web search, or hybrid."""

        prompt = f"""
You are a decision assistant. Given a short query and available internal memory/context, decide whether it's better to use the internal ERP Knowledge Base (KB), perform a web search, or use both.

Query: {query}
Context: {context}

Decide one of: kb, web, hybrid. Explain briefly with confidence (0-1) and short justification.
"""

        self.logger.info("Assessing source decision for query", query=query)

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=self.generation_config
            )
            text = response.text
        except Exception as e:
            self.logger.error("Reasoning assess_source failed", exc_info=True)
            return {
                'decision': 'web',
                'confidence': 0.4,
                'reasoning': f'fallback: {e}'
            }

        # Default values
        decision = 'web'
        confidence = 0.5

        # Basic reasoning extraction
        text_lower = text.lower()
        if 'kb' in text_lower:
            decision = 'kb'
        if 'hybrid' in text_lower:
            decision = 'hybrid'

        # Attempt to extract a confidence float
        for token in text.split():
            try:
                val = float(token)
                if 0 <= val <= 1:
                    confidence = val
                    break
            except ValueError:
                pass

        return {
            'decision': decision,
            'confidence': confidence,
            'reasoning': text
        }

    def make_plan(self, instruction: str, context: str = "") -> Dict[str, Any]:
        """Generate a step-by-step plan and justification."""

        prompt = f"""
You are a planning assistant. Given an instruction and context, produce a concise numbered plan (3-8 steps) to accomplish the instruction. Also provide a short justification.

Instruction: {instruction}
Context: {context}

Output in the format:
Steps:
1. ...
2. ...
...
Justification: ...
"""

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=self.generation_config
            )
            text = response.text
        except Exception as e:
            self.logger.error("Reasoning make_plan failed", exc_info=True)
            return {
                'steps': [],
                'justification': f'fallback: {e}'
            }

        # Parse steps
        steps = []
        lines = text.split('\n')

        for l in lines:
            stripped = l.strip()
            if stripped.startswith(tuple('123456789.')) or stripped.split()[0].isdigit():
                steps.append(stripped.lstrip('0123456789. ').strip())

        if not steps:
            for l in lines:
                if l.strip():
                    steps.append(l.strip())
                    if len(steps) >= 6:
                        break

        # Extract justification
        justification = ''
        for l in reversed(lines):
            if 'justification' in l.lower() or 'reason' in l.lower():
                justification = ' '.join(lines[lines.index(l):])
                break

        return {
            'steps': steps,
            'justification': justification,
            'raw': text
        }


# Global instance
reasoning_tool = ReasoningTool()
