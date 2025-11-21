# 🤖 ERP Consultant AI Agent

An intelligent multi-agent system designed to support ERP Functional Consultants throughout the entire project lifecycle - from requirement gathering to user training.

## 🎯 Problem Statement

ERP Functional Consultants spend 60-70% of their time on repetitive documentation tasks, manual requirement gathering, and creating training materials. This reduces billable hours and delays project delivery timelines.

## 💡 Solution

An **ERP Consulting Multi-Agent System** that automates:
- ✅ Requirement gathering and documentation
- ✅ Business process mapping
- ✅ Solution design documentation
- ✅ QA test case generation
- ✅ UAT testing scenarios
- ✅ Training materials and user manuals

**Expected Impact:**
- ⏱️ Save 15-20 hours per week on documentation
- 📊 Standardized, high-quality deliverables
- 🚀 Faster project delivery cycles
- ✅ Consistent testing coverage

## 🏗️ Architecture

Multi-agent system with specialized agents:

```
Orchestrator Agent (Supervisor)
├── Requirements Gathering Agent
├── Process Mapping Agent
├── Solution Design Agent
├── QA Testing Agent
├── UAT Testing Agent
└── Training & Documentation Agent
```

## 🔧 Technical Stack

- **AI Framework:** Google Gemini API + Google ADK
- **Language:** Python 3.10+
- **Memory:** InMemorySessionService + Memory Bank
- **Observability:** Structured logging and tracing
- **Testing:** pytest with evaluation metrics

## 📋 Features

### Multi-Agent System
- Orchestrator with task routing
- Sequential and parallel agent execution
- State management across workflow phases

### Tools & Capabilities
- Google Search integration
- Custom ERP knowledge base
- Document generation
- Process visualization
- Test case generation

### Memory & Context
- Session management for project continuity
- Long-term memory bank for best practices
- Context compaction for large documents

### Observability
- Structured logging
- Agent tracing
- Performance metrics

## 🚀 Quick Start

### 1. Clone Repository
```bash
git clone https://github.com/James-Muguro/erp-consultant-agent.git
cd erp-consultant-agent
```

### 2. Set Up Environment
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure API Keys
```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your Gemini API key
# GEMINI_API_KEY=your_actual_api_key_here
```

### 4. Run the Agent
```bash
python src/main.py
```

## 📖 Usage Examples

### Example 1: Requirements Gathering
```python
from src.orchestrator import ERPOrchestratorAgent

agent = ERPOrchestratorAgent()
result = agent.gather_requirements(
    project="SAP S/4HANA Implementation",
    module="Finance - Accounts Payable"
)
```

### Example 2: Generate Test Cases
```python
result = agent.generate_test_cases(
    requirements_doc="docs/requirements.md",
    test_type="UAT"
)
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/

# Run specific test suite
pytest tests/test_requirements_agent.py
```

## 📊 Evaluation

The system includes automated evaluation metrics:
- Requirements completeness score
- Test case coverage analysis
- Documentation quality metrics
- Agent performance benchmarks

## 📁 Project Structure

```
erp-consultant-agent/
├── src/
│   ├── agents/          # Specialized agents
│   ├── tools/           # Custom tools
│   ├── memory/          # Session & memory management
│   ├── utils/           # Utilities & prompts
│   └── config/          # Configuration
├── tests/               # Test suites
├── examples/            # Sample inputs/outputs
└── docs/                # Documentation
```

---

## 📊 Project Highlights

- **5,000+ lines** of production-quality code
- **9+ course concepts** implemented (multi-agent, tools, memory, evaluation, etc.)
- **6 specialized agents** working in orchestration
- **170-point evaluation system** with 70% pass threshold
- **46-89 second** complete workflow execution
- **50-70% time savings** vs manual process
- **Comprehensive testing** with unit and integration tests
- **Production-ready** with error handling, logging, and documentation

---

## 📂 Repository Structure

```
erp-consultant-agent/
├── src/                    # Source code (5,000+ lines)
│   ├── orchestrator.py     # Main workflow coordinator
│   ├── main.py            # CLI interface
│   ├── agents/            # 6 specialized agents
│   ├── tools/             # Custom tools (ERP KB, Doc Gen, Test Gen)
│   ├── memory/            # Session & memory management
│   ├── utils/             # Logging, prompts, context management
│   └── config/            # Configuration & settings
├── tests/                 # Comprehensive test suite
│   ├── test_requirements_agent.py
│   ├── test_orchestrator.py
│   ├── evaluation_metrics.py
│   └── run_tests.py
├── docs/                  # Full documentation
│   ├── architecture.md    # Technical architecture
│   └── user_guide.md      # User documentation
├── demo.py               # Interactive demo
├── SUBMISSION.md         # Capstone submission writeup
├── VIDEO_SCRIPT.md       # Video recording guide
└── requirements.txt      # Dependencies
```

---

## 🏆 Capstone Project Submission

This project is submitted for the **Enterprise Agents** track of the AI Agent course.

Refer to the [submission document](docs/SUBMISSION.md) for the full project documentation.

---

**Status:** ✅ Complete & Ready for Evaluation
