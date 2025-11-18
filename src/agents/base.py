import asyncio
from typing import List, Any, Optional
from pydantic import BaseModel, Field
from termcolor import cprint

import google.generativeai as genai

from src.config.settings import settings
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

# Configure the Gemini API
genai.configure(api_key=settings.gemini_api_key)

class Agent:
    """Base class for all agents"""
    
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
        self.max_iterations = max_iterations
        self.model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            generation_config={
                "temperature": self.temperature,
                "max_output_tokens": settings.max_tokens,
            },
            tools=self.tools,
        )

        async def run(self, query: str, context: Optional[str] = None) -> str:
            """
            Main entry point for the agent.
            
            Args:
                query: The user's query.
                context: Relevant context from memory.
                
            Returns:
                The agent's response.
            """
            cprint(f"Agent '{self.name}' received query: '{query}'", "blue")
            
            # Build the prompt
            prompt = self._build_prompt(query, context)
            
            # Start a chat session
            chat = self.model.start_chat(history=[])
            
            # Send the prompt to the model
            response = await asyncio.to_thread(chat.send_message, prompt)
            
            # Handle the response
            return self._handle_response(chat, response)
    
        def _build_prompt(self, query: str, context: Optional[str] = None) -> str:
            """Builds the prompt for the language model"""
            prompt = f"You are {self.name}, {self.description}.\n\n"
            if context:
                prompt += f"Here is some relevant context:\n{context}\n\n"
            prompt += f"User query: {query}\n\n"
            prompt += "Please provide a detailed and helpful response."
            return prompt
    
        def _handle_response(self, chat: Any, response: Any) -> str:
            """Handles the response from the language model"""
            try:
                # Check for tool calls
                if response.function_calls:
                    for function_call in response.function_calls:
                        tool_name = function_call.name
                        tool_args = function_call.args
                        
                        if tool_name in [tool.name for tool in self.tools]:
                            tool = [tool for tool in self.tools if tool.name == tool_name][0]
                            
                            # Execute the tool
                            tool_result = tool(**tool_args)
                            
                            # Send the tool result back to the model
                            response = chat.send_message(
                                f"Tool {tool_name} returned: {tool_result}",
                                role="tool"
                            )
                            return self._handle_response(chat, response)
                    
                return response.text
            except Exception as e:
                logger.error(f"Error handling response: {e}", exc_info=True)
                return "I'm sorry, but I encountered an error while processing your request."
