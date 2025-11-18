
from pydantic import BaseModel, Field
from typing import Type
import subprocess

from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

class CodeExecutionInput(BaseModel):
    """Input model for the Code Execution tool"""
    code: str = Field(..., description="The Python code to execute")

class CodeExecutionTool:
    """A tool for executing Python code."""
    name: str = "code_execution"
    description: str = "Executes Python code in a sandboxed environment."
    args_schema: Type[BaseModel] = CodeExecutionInput
    
    def __call__(self, code: str) -> str:
        """
        Executes the given Python code.
        
        Args:
            code: The Python code to execute.
            
        Returns:
            A string containing the output of the code execution.
        """
        try:
            # This is a placeholder implementation
            # In a real implementation, this should be done in a sandboxed
            # environment to prevent security risks.
            
            result = subprocess.run(
                ["python", "-c", code],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return result.stdout
            else:
                return result.stderr
                
        except Exception as e:
            logger.error(f"Error during code execution: {e}", exc_info=True)
            return "An error occurred during code execution."

