
from .base import Agent
"""
Specialized ERP Consultant Agents
"""
from .requirements_agent import RequirementsAgent, requirements_agent
from .process_mapping_agent import ProcessMappingAgent, process_mapping_agent
from .solution_design_agent import SolutionDesignAgent, solution_design_agent
from .testing_agents import QATestingAgent, UATTestingAgent, qa_testing_agent, uat_testing_agent
from .training_agent import TrainingAgent, training_agent

__all__ = [
    'RequirementsAgent',
    'requirements_agent',
    'ProcessMappingAgent',
    'process_mapping_agent',
    'SolutionDesignAgent',
    'solution_design_agent',
    'QATestingAgent',
    'qa_testing_agent',
    'UATTestingAgent',
    'uat_testing_agent',
    'TrainingAgent',
    'training_agent'
]
