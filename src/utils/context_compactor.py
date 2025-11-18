
from typing import List, Tuple
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

class ContextCompactor:
    """
    A simple context compactor that truncates the conversation history
    to fit within a specified token limit.
    """
    
    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        
    def compact(self, history: List[Tuple[str, str]]) -> str:
        """
        Compacts the conversation history to fit within the token limit.
        
        Args:
            history: A list of tuples, where each tuple contains a query and a response.
            
        Returns:
            A string containing the compacted conversation history.
        """
        
        compacted_history = ""
        total_tokens = 0
        
        for query, response in reversed(history):
            # A simple approximation of token count
            query_tokens = len(query.split())
            response_tokens = len(response.split())
            
            if total_tokens + query_tokens + response_tokens > self.max_tokens:
                break
                
            compacted_history = f"User: {query}\nAgent: {response}\n" + compacted_history
            total_tokens += query_tokens + response_tokens
            
        logger.info(f"Compacted context to {total_tokens} tokens.")
        return compacted_history
