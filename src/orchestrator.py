
import asyncio
from typing import Dict, Any
from termcolor import cprint

from src.config.settings import settings, AgentConfig, REQUIREMENTS_AGENT_CONFIG, PROCESS_MAPPING_AGENT_CONFIG, SOLUTION_DESIGN_AGENT_CONFIG, QA_TESTING_AGENT_CONFIG, UAT_TESTING_AGENT_CONFIG, TRAINING_AGENT_CONFIG
from src.utils.logger import get_logger
from src.agents.base import Agent  # We will create this base agent soon
from src.memory.in_memory import InMemoryMemory  # We will create this memory soon
from src.tools.google_search import GoogleSearchTool # We will create this tool soon

# Initialize logger
logger = get_logger(__name__)

class Orchestrator:
    """
    The orchestrator manages the overall workflow of the ERP Consultant Agent.
    It receives user requests, selects the appropriate agent, and coordinates
    the execution of tasks.
    """
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.memory = InMemoryMemory(user_id=user_id)
        self.agents: Dict[str, Agent] = self._load_agents()
        self.tools: Dict[str, Any] = self._load_tools()
        
    def _load_agents(self) -> Dict[str, Agent]:
        """Loads all available agents"""
        from src.agents import (
            RequirementsGatheringAgent,
            ProcessMappingAgent,
            SolutionDesignAgent,
            QATestingAgent,
            UATTestingAgent,
            TrainingAgent,
        )
        
        agents = {
            "Requirements Gathering Agent": RequirementsGatheringAgent(
                tools=[self.tools.get(tool_name) for tool_name in REQUIREMENTS_AGENT_CONFIG.tools if self.tools.get(tool_name)]
            ),
            "Process Mapping Agent": ProcessMappingAgent(
                tools=[self.tools.get(tool_name) for tool_name in PROCESS_MAPPING_AGENT_CONFIG.tools if self.tools.get(tool_name)]
            ),
            "Solution Design Agent": SolutionDesignAgent(
                tools=[self.tools.get(tool_name) for tool_name in SOLUTION_DESIGN_AGENT_CONFIG.tools if self.tools.get(tool_name)]
            ),
            "QA Testing Agent": QATestingAgent(
                tools=[self.tools.get(tool_name) for tool_name in QA_TESTING_AGENT_CONFIG.tools if self.tools.get(tool_name)]
            ),
            "UAT Testing Agent": UATTestingAgent(
                tools=[self.tools.get(tool_name) for tool_name in UAT_TESTING_AGENT_CONFIG.tools if self.tools.get(tool_name)]
            ),
            "Training & Documentation Agent": TrainingAgent(
                tools=[self.tools.get(tool_name) for tool_name in TRAINING_AGENT_CONFIG.tools if self.tools.get(tool_name)]
            ),
        }
        return agents

    def _load_tools(self) -> Dict[str, Any]:
        """Loads all available tools"""
        from src.tools import (
            GoogleSearchTool,
            DocumentAnalyzerTool,
            ProcessVisualizerTool,
            ERPKnowledgeBaseTool,
            TestCaseGeneratorTool,
            CodeExecutionTool,
            DocumentGeneratorTool,
        )
        
        tools = {}
        if settings.enable_google_search:
            tools["google_search"] = GoogleSearchTool()
        
        tools["document_analyzer"] = DocumentAnalyzerTool()
        tools["process_visualizer"] = ProcessVisualizerTool()
        tools["erp_knowledge_base"] = ERPKnowledgeBaseTool()
        tools["test_case_generator"] = TestCaseGeneratorTool()
        tools["code_execution"] = CodeExecutionTool()
        tools["document_generator"] = DocumentGeneratorTool()
        
        return tools

    async def run(self, query: str, agent_config: AgentConfig) -> str:
        """
        Main entry point for the orchestrator.
        
        Args:
            query: The user's query.
            agent_config: The configuration for the agent to use.
            
        Returns:
            The agent's response.
        """
        cprint(f"Orchestrator received query for user {self.user_id}: '{query}'", "cyan")
        
        # 1. Select the agent
        agent = self._get_agent(agent_config)
        
        # 2. Retrieve relevant context from memory
        context = await self.memory.get_context(query)
        
        # 3. Execute the agent
        response = await agent.run(query, context)
        
        # 4. Store the interaction in memory
        await self.memory.add_to_history(query, response)
        
        cprint(f"Orchestrator returned response: '{response}'", "green")
        return response

    def _get_agent(self, agent_config: AgentConfig) -> Agent:
        """
        Retrieves an agent based on the provided config.
        """
        agent = self.agents.get(agent_config.name)
        if not agent:
            raise ValueError(f"Agent '{agent_config.name}' not found.")
        return agent

