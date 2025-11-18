
from pydantic import BaseModel, Field
from typing import Type
from jinja2 import Environment, FileSystemLoader
import os

from src.utils.logger import get_logger
from src.config.settings import settings

# Initialize logger
logger = get_logger(__name__)

class DocumentGeneratorInput(BaseModel):
    """Input model for the Document Generator tool"""
    template_name: str = Field(..., description="The name of the template to use")
    context: dict = Field(..., description="The context to render the template with")
    output_filename: str = Field(..., description="The filename for the output document")

class DocumentGeneratorTool:
    """A tool for generating documents from templates."""
    name: str = "document_generator"
    description: str = "Generates documents from templates."
    args_schema: Type[BaseModel] = DocumentGeneratorInput
    
    def __call__(self, template_name: str, context: dict, output_filename: str) -> str:
        """
        Executes the document generation.
        
        Args:
            template_name: The name of the template to use.
            context: The context to render the template with.
            output_filename: The filename for the output document.
            
        Returns:
            A string containing the path to the generated document.
        """
        try:
            # This is a placeholder implementation
            # In a real implementation, this would involve a more robust
            # template management system.
            
            env = Environment(loader=FileSystemLoader("templates"))
            template = env.get_template(template_name)
            
            rendered_document = template.render(context)
            
            output_path = os.path.join(settings.output_dir, output_filename)
            with open(output_path, "w") as f:
                f.write(rendered_document)
            
            return f"Document saved to {output_path}"
                
        except Exception as e:
            logger.error(f"Error during document generation: {e}", exc_info=True)
            return "An error occurred during document generation."

