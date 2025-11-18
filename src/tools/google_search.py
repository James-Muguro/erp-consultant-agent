from serpapi import GoogleSearch
from pydantic import BaseModel, Field
from typing import Type

from src.config.settings import settings
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

class GoogleSearchToolInput(BaseModel):
    """Input model for the Google Search tool"""
    query: str = Field(..., description="The search query")

class GoogleSearchTool:
    """A tool for performing Google searches."""
    name: str = "google_search"
    description: str = "Performs a Google search and returns the top results."
    args_schema: Type[BaseModel] = GoogleSearchToolInput
    
    def __call__(self, query: str) -> str:
        """
        Executes a Google search.
        
        Args:
            query: The search query.
            
        Returns:
            A string containing the search results.
        """
        try:
            search = GoogleSearch({
                "q": query,
                "api_key": settings.serpapi_api_key  # You need to add SERPAPI_API_KEY to your .env file
            })
            results = search.get_dict()
            
            # Extract relevant information from the results
            if "organic_results" in results:
                return self._format_results(results["organic_results"])
            else:
                return "No organic results found."
                
        except Exception as e:
            logger.error(f"Error during Google search: {e}", exc_info=True)
            return "An error occurred during the Google search."

    def _format_results(self, organic_results: list) -> str:
        """Formats the organic results into a string."""
        formatted_results = []
        for result in organic_results[:5]:  # Limit to top 5 results
            formatted_results.append(
                f"Title: {result.get('title', 'N/A')}\n"
                f"Link: {result.get('link', 'N/A')}\n"
                f"Snippet: {result.get('snippet', 'N/A')}\n"
            )
        return "\n---\n".join(formatted_results)

