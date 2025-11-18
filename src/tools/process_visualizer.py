
from pydantic import BaseModel, Field
from typing import Type
from graphviz import Digraph
import os

from src.utils.logger import get_logger
from src.config.settings import settings

# Initialize logger
logger = get_logger(__name__)

class ProcessVisualizerInput(BaseModel):
    """Input model for the Process Visualizer tool"""
    process_description: str = Field(..., description="A textual description of the process to visualize")
    output_filename: str = Field(..., description="The filename for the output diagram (without extension)")

class ProcessVisualizerTool:
    """A tool for creating process diagrams from textual descriptions."""
    name: str = "process_visualizer"
    description: str = "Creates a process diagram from a textual description."
    args_schema: Type[BaseModel] = ProcessVisualizerInput
    
    def __call__(self, process_description: str, output_filename: str) -> str:
        """
        Executes the process visualization.
        
        Args:
            process_description: A textual description of the process.
            output_filename: The filename for the output diagram.
            
        Returns:
            A string containing the path to the generated diagram.
        """
        try:
            dot = Digraph(comment='Business Process')
            
            # This is a placeholder implementation
            # In a real implementation, this would involve using a language model
            # to parse the process description and create the diagram.
            
            # For now, we'll just create a simple diagram based on the description
            steps = process_description.split("->")
            for i in range(len(steps) - 1):
                dot.edge(steps[i].strip(), steps[i+1].strip())
            
            output_path = os.path.join(settings.output_dir, f"{output_filename}.gv")
            dot.render(output_path, view=False)
            
            return f"Process diagram saved to {output_path}.png"
                
        except Exception as e:
            logger.error(f"Error during process visualization: {e}", exc_info=True)
            return "An error occurred during process visualization."

