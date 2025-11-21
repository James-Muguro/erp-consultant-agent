# ERP Consultant AI Agent - Architecture Documentation

## Overview

The ERP Consultant AI Agent is a sophisticated multi-agent system designed to automate and enhance ERP consulting workflows from requirements gathering through user training.

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     USER INTERFACE                           │
│                  (CLI / Demo Script)                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                 ORCHESTRATOR AGENT                           │
│          (Workflow Coordination & Management)                │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
┌───────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐
│ Requirements │ │ Process  │ │ Solution   │
│   Gathering  │ │ Mapping  │ │   Design   │
│    Agent     │ │  Agent   │ │   Agent    │
└──────────────┘ └──────────┘ └────────────┘
        │              │              │
┌───────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐
│ QA Testing   │ │   UAT    │ │  Training  │
│    Agent     │ │ Testing  │ │    & Doc   │
│              │ │  Agent   │ │   Agent    │
└──────────────┘ └──────────┘ └────────────┘
        │              │              │
        └──────────────┼──────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  SHARED SERVICES LAYER                       │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   Memory    │  │ Custom Tools │  │  Utilities   │       │
│  │  & Session  │  │   - ERP KB   │  │  - Logger    │       │
│  │ Management  │  │   - Doc Gen  │  │  - Prompts   │       │
│  └─────────────┘  │   - Test Gen │  │  - Context   │       │
│                   └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              EXTERNAL SERVICES                               │
│         - Google Gemini API (LLM)                           │
│         - File System (Persistence)                         │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Orchestrator Agent

**Purpose:** Coordinates all specialized agents and manages the complete ERP consulting workflow.

**Responsibilities:**
- Project lifecycle management
- Task routing to specialized agents
- Workflow state management
- Phase progression control
- Result aggregation and reporting

**Key Methods:**
- `start_project()` - Initialize new project
- `execute_full_workflow()` - Run complete consulting cycle
- `execute_[phase]_phase()` - Execute individual phases
- `get_project_status()` - Retrieve project state
- `generate_project_summary()` - Create comprehensive report

### 2. Specialized Agents

#### Requirements Gathering Agent
- **Purpose:** Analyze stakeholder inputs and generate comprehensive requirement documents
- **LLM Temperature:** 0.5 (balanced creativity and precision)
- **Key Features:**
  - Categorizes requirements by type
  - Identifies dependencies and constraints
  - Validates completeness
  - Generates structured documentation

#### Process Mapping Agent
- **Purpose:** Create detailed business process maps
- **LLM Temperature:** 0.4 (precise mapping)
- **Key Features:**
  - AS-IS and TO-BE process documentation
  - RACI matrix generation
  - Gap analysis
  - Integration point identification

#### Solution Design Agent
- **Purpose:** Design ERP solutions based on requirements
- **LLM Temperature:** 0.6 (creative solutions with structure)
- **Key Features:**
  - Architecture design
  - Module configuration
  - Minimizes customizations (best practice)
  - Integration architecture
  - Security design

#### QA Testing Agent
- **Purpose:** Generate comprehensive QA test cases
- **LLM Temperature:** 0.3 (precise test specifications)
- **Key Features:**
  - Functional test cases
  - Integration tests
  - Performance tests
  - Security tests
  - Test data generation

#### UAT Testing Agent
- **Purpose:** Create user-friendly UAT scenarios
- **LLM Temperature:** 0.4 (clear user instructions)
- **Key Features:**
  - Business-focused scenarios
  - Role-based test scripts
  - End-to-end workflows
  - Sign-off criteria

#### Training & Documentation Agent
- **Purpose:** Produce training materials and documentation
- **LLM Temperature:** 0.5 (clear and engaging)
- **Key Features:**
  - User manuals
  - Training guides
  - Quick reference guides
  - Standard Operating Procedures (SOPs)

### 3. Memory & Session Management

#### Session Manager
- **Purpose:** Maintain state across agent interactions
- **Storage:** In-memory with disk persistence
- **Data Stored:**
  - Project metadata
  - Current phase and completed phases
  - Agent outputs for each phase
  - Conversation history
  - Decision logs

#### Memory Bank
- **Purpose:** Long-term knowledge storage and learning
- **Categories:**
  - Requirements templates
  - Process patterns
  - Solution patterns
  - Test case templates
  - Best practices
  - Lessons learned
- **Features:**
  - Category-based organization
  - Tag-based search
  - Importance weighting
  - Access tracking

### 4. Custom Tools

#### ERP Knowledge Base
- **Purpose:** Provide domain-specific ERP expertise
- **Content:**
  - SAP module information (FI, CO, MM, SD, PP, HR)
  - Transaction codes
  - Best practices
  - Integration points
  - Standard process flows

#### Document Generator
- **Purpose:** Create formatted documentation
- **Output Formats:** Markdown
- **Document Types:**
  - Requirements documents
  - Test case documents
  - User manuals
  - Solution design documents

#### Test Case Generator
- **Purpose:** Programmatic test case generation
- **Test Types:**
  - Functional
  - Integration
  - Performance
  - Security
  - Regression
  - UAT scenarios

### 5. Utilities

#### Logger & Metrics
- **Logging:** Structured logging with JSON output
- **Metrics Tracked:**
  - Task execution times
  - Success/failure rates
  - Agent-specific performance
  - Memory operations

#### Context Manager
- **Purpose:** Manage LLM context windows
- **Features:**
  - Token estimation
  - Document compaction
  - Context summarization
  - Chunking for large documents

## Data Flow

### Complete Workflow Execution

```
1. User Input
   ↓
2. Orchestrator: Create Session
   ↓
3. Requirements Agent: Gather Requirements
   → Uses: ERP KB, Memory Bank
   → Output: Requirements Document
   → Saves to: Session State
   ↓
4. Process Mapping Agent: Map Process
   → Uses: Requirements, ERP KB
   → Output: Process Maps
   → Saves to: Session State
   ↓
5. Solution Design Agent: Design Solution
   → Uses: Requirements, Process Maps, ERP KB
   → Output: Solution Design Document
   → Saves to: Session State
   ↓
6. QA Testing Agent: Generate Test Cases
   → Uses: Solution Design, Test Generator
   → Output: QA Test Cases Document
   → Saves to: Session State
   ↓
7. UAT Testing Agent: Generate UAT Scenarios
   → Uses: Process Maps, Test Generator
   → Output: UAT Scenarios Document
   → Saves to: Session State
   ↓
8. Training Agent: Create Training Materials
   → Uses: Solution Design, Process Maps, Doc Generator
   → Output: User Manuals, Training Guides
   → Saves to: Session State
   ↓
9. Orchestrator: Generate Project Summary
   → Memory Bank: Learn from Project
   ↓
10. Return Complete Results
```

## Technology Stack

### Core Technologies
- **Language:** Python 3.10+
- **LLM:** Google Gemini 2.0 Flash (via google-genai SDK)
- **Framework:** Custom multi-agent orchestration

### Key Libraries
- **google-genai:** Gemini API integration
- **pydantic:** Data validation and settings
- **structlog:** Structured logging
- **pytest:** Testing framework

### Storage
- **Session Data:** JSON files on disk
- **Memory Bank:** JSON files with indexing
- **Documents:** Markdown files
- **Logs:** Structured log files

## Design Principles

### 1. Agent Specialization
Each agent is specialized for a specific phase of ERP consulting, with:
- Dedicated prompts and system instructions
- Appropriate LLM temperature settings
- Specific tool access
- Phase-specific validation

### 2. State Management
- Persistent sessions enable workflow continuity
- Each phase builds on previous outputs
- Decision logging for traceability
- Phase progression tracking

### 3. Memory & Learning
- Short-term: Session-based context
- Long-term: Memory bank for patterns and best practices
- Continuous improvement through project learning

### 4. Observability
- Structured logging for debugging
- Performance metrics collection
- Execution tracing
- Error tracking

### 5. Modularity
- Agents can be executed independently
- Tools are reusable across agents
- Clear separation of concerns
- Easy to extend with new agents

### 6. ERP Best Practices
- Minimize customizations
- Standard processes first
- Configuration over customization
- Integration-aware design

## Scalability Considerations

### Current Implementation
- Single-threaded sequential execution
- In-memory session storage with disk persistence
- Local file-based document storage

### Future Enhancements
- Parallel agent execution for independent tasks
- Database backend for session storage
- Cloud storage integration
- API endpoint exposure
- Web interface
- Multi-user support
- Real-time collaboration

## Security Considerations

### Current Implementation
- API key stored in .env file
- Local file system access only
- No external data transmission (except to Gemini API)

### Production Requirements
- Secure API key management (e.g., secrets manager)
- User authentication and authorization
- Data encryption at rest and in transit
- Audit logging
- Access controls

## Performance Characteristics

### Typical Execution Times
- Requirements Gathering: 5-15 seconds
- Process Mapping: 5-12 seconds
- Solution Design: 8-20 seconds
- QA Testing: 10-15 seconds
- UAT Testing: 8-12 seconds
- Training: 10-15 seconds
- **Total Workflow: 46-89 seconds**

### Resource Usage
- Memory: ~200-500 MB
- Disk: ~10-50 MB per project
- API Calls: 6-12 per complete workflow

## Limitations

### Current Limitations
1. **No real-time collaboration:** Single-user system
2. **Limited ERP coverage:** Primarily SAP-focused
3. **No screenshot generation:** Placeholder only
4. **No diagram generation:** Text-based process maps
5. **English only:** No multi-language support
6. **Static knowledge:** ERP KB requires manual updates

### Mitigation Strategies
- Templates and best practices reduce need for domain updates
- Text-based outputs are easily editable
- Modular design allows easy extension
- Clear documentation enables customization

## Extension Points

### Adding New Agents
1. Create agent class inheriting from base pattern
2. Define agent configuration
3. Implement execute method
4. Add to orchestrator workflow
5. Update phase enum

### Adding New Tools
1. Create tool class in `src/tools/`
2. Implement required methods
3. Register with agents
4. Update tool documentation

### Adding New ERP Systems
1. Extend ERP Knowledge Base
2. Add system-specific modules
3. Update prompts with system terminology
4. Add system-specific best practices

## Evaluation & Quality Metrics

### Automated Evaluation
- Requirements Completeness: 35 points
- Process Map Quality: 30 points
- Solution Design Quality: 40 points
- Test Coverage: 35 points
- System Performance: 30 points
- **Total: 170 points (70% pass threshold)**

### Quality Assurance
- Unit tests for individual agents
- Integration tests for workflow
- Evaluation metrics for outputs
- Performance benchmarks