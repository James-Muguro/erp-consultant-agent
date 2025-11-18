from typing import List, Tuple
from collections import deque

from src.config.settings import settings
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

class InMemoryMemory:
    """
    A simple in-memory implementation of the agent's memory.
    It stores conversation history in a deque.
    """
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.history: deque = deque(maxlen=settings.max_memory_items)
        
    async def add_to_history(self, query: str, response: str):
        """Adds a query and response to the conversation history."""
        self.history.append((query, response))
        logger.info(f"Added to memory for user {self.user_id}: Q: {query}, R: {response}")
        
    async def get_context(self, query: str, num_items: int = 5) -> str:
        """
        Retrieves relevant context from the conversation history.
        This is a simple implementation that returns the last `num_items` of the history.
        """
        if not self.history:
            return ""
            
        # Get the last `num_items` from the history
        recent_history = list(self.history)[-num_items:]
        
        # Format the history into a string
        context = "\n".join([f"User: {q}\nAgent: {r}" for q, r in recent_history])
        
        logger.info(f"Retrieved context for user {self.user_id}: {context}")
        return context

    async def clear_history(self):
        """Clears the conversation history."""
        self.history.clear()
        logger.info(f"Cleared memory for user {self.user_id}")
