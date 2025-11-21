# ERP Consultant AI Agent - User Guide

## Table of Contents
1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
3. [Usage Examples](#usage-examples)
4. [Command Reference](#command-reference)
5. [Understanding Outputs](#understanding-outputs)
6. [Best Practices](#best-practices)
7. [Troubleshooting](#troubleshooting)

---

## Introduction

The ERP Consultant AI Agent is your AI-powered assistant for ERP implementation projects. It automates the entire consulting lifecycle:

✅ **Requirements Gathering** - Transform stakeholder inputs into structured requirements  
✅ **Process Mapping** - Create detailed business process maps  
✅ **Solution Design** - Design ERP solutions with best practices  
✅ **QA Testing** - Generate comprehensive test cases  
✅ **UAT Testing** - Create user acceptance test scenarios  
✅ **Training** - Produce training materials and documentation  

**Time Savings:** Reduce documentation time by 50-70%  
**Consistency:** Standardized, high-quality deliverables  
**Coverage:** Comprehensive testing and documentation  

---

## Getting Started

### Prerequisites

- Python 3.10 or higher
- Google Gemini API key
- 500MB free disk space

### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/James-Muguro/erp-consultant-agent.git
cd erp-consultant-agent
```

2. **Create virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Configure API key:**
```bash
cp .env.example .env
# Edit .env and add your Gemini API key
```

### Quick Start

Run the demo to see the system in action:

```bash
python demo.py
```

This will execute a complete Accounts Payable implementation project from start to finish.

---

## Usage Examples

### Example 1: Complete Workflow

Execute a full ERP consulting project:

```bash
python src/main.py workflow \
  --project-name "ABC Corp AP Implementation" \
  --module "FI" \
  --input "We need to automate accounts payable with invoice processing, approval workflows, and automated payments. Integration with procurement is required."
```

**What happens:**
1. Creates new project session
2. Generates requirements document
3. Creates process maps
4. Designs solution architecture
5. Generates QA test cases
6. Creates UAT scenarios
7. Produces training materials

**Output:** All documents saved to `output/documents/`

### Example 2: Step-by-Step Execution

Execute phases individually for more control:

**Step 1: Start project and gather requirements**
```bash
python src/main.py workflow \
  --project-name "Inventory Management" \
  --module "MM" \
  --input "Implement inventory management with real-time stock tracking, reorder point alerts, and cycle counting."

# Note the session ID from output
```

**Step 2: Execute process mapping**
```bash
python src/main.py phase \
  --session-id prj_inventory_management \
  --phase process_mapping \
  --process-name "Inventory Management Process"
```

**Step 3: Continue with other phases**
```bash
python src/main.py phase \
  --session-id prj_inventory_management \
  --phase solution_design
```

### Example 3: Check Project Status

Monitor project progress:

```bash
python src/main.py status --session-id prj_inventory_management
```

**Output:**
```
📊 Project Status
==============================================================
Project: Inventory Management
Module: MM
Current Phase: solution_design
Progress: 33.3%

Completed Phases:
  ✅ Requirements Gathering
  ✅ Process Mapping

Next Phase: Solution Design
```

### Example 4: List All Projects

View all active projects:

```bash
python src/main.py list
```

### Example 5: View Memory Statistics

See system learning and memory usage:

```bash
python src/main.py memory
```

---

## Command Reference

### Workflow Command

Execute complete consulting workflow.

```bash
python src/main.py workflow [OPTIONS]
```

**Required Options:**
- `--project-name TEXT` - Name of the project
- `--module TEXT` - ERP module code (FI, MM, SD, PP, CO, HR)
- `--input TEXT` - Initial stakeholder requirements

**Optional Options:**
- `--erp-system TEXT` - ERP system (default: "SAP S/4HANA")
- `--process-name TEXT` - Business process name
- `--user-roles TEXT` - Comma-separated user roles for UAT/training

**Example:**
```bash
python src/main.py workflow \
  --project-name "Sales Order Processing" \
  --module "SD" \
  --input "Automate sales order creation with credit checking and ATP" \
  --process-name "Order to Cash" \
  --user-roles "Sales Rep,Order Processor,Credit Manager"
```

### Phase Command

Execute a single project phase.

```bash
python src/main.py phase [OPTIONS]
```

**Required Options:**
- `--session-id TEXT` - Session identifier
- `--phase CHOICE` - Phase to execute
  - `requirements`
  - `process_mapping`
  - `solution_design`
  - `qa_testing`
  - `uat_testing`
  - `training`

**Phase-Specific Options:**
- `--input TEXT` - Required for requirements phase
- `--process-name TEXT` - Optional for process_mapping and training

**Example:**
```bash
python src/main.py phase \
  --session-id prj_my_project \
  --phase qa_testing
```

### Status Command

Check project status and progress.

```bash
python src/main.py status --session-id TEXT
```

### List Command

List all active sessions.

```bash
python src/main.py list
```

### Memory Command

View memory bank statistics.

```bash
python src/main.py memory
```

---

## Understanding Outputs

### Directory Structure

All outputs are saved to organized directories:

```
output/
├── documents/          # Generated documentation
│   ├── requirements_*.md
│   ├── test_cases_*.md
│   ├── user_manual_*.md
│   └── solution_design_*.md
├── sessions/           # Session state files
│   └── prj_*.json
└── memory_bank/        # Long-term memory
    └── *.json

logs/                   # System logs
└── agent_*.log
```

### Document Formats

#### Requirements Document
```
# Requirements Document

## Project Information
- Project Name: ...
- Module: ...
- Date: ...

## Executive Summary
...

## Functional Requirements
### Category 1
- REQ-001: Description
  - Priority: High
  - Acceptance Criteria: ...

## Technical Requirements
...

## Integration Requirements
...
```

#### Test Cases Document
```
# QA Test Cases Document

## Test Summary
- Total Test Cases: 15
- Critical: 5
- High: 7

## Test Cases

### Test Case 1: Scenario Name
**Test Case ID:** TC-001
**Priority:** High

#### Test Steps
1. Step one
2. Step two

#### Expected Results
...
```

### Session Data

Session files (JSON) contain:
- Project metadata
- Current phase
- Completed phases
- All phase outputs
- Conversation history
- Decision log

Access via: `output/sessions/prj_*.json`

---

## Best Practices

### 1. Stakeholder Input Quality

**Good Input:**
```
We need to implement Purchase Order management with:
- Create and approve purchase orders
- Three-way matching (PO, GR, Invoice)
- Vendor management and evaluation
- Budget checking and approvals
- Integration with inventory management
- Email notifications for approvals
```

**Poor Input:**
```
Need PO system
```

**Tips:**
- Be specific about requirements
- Mention integration points
- Include business rules
- Specify user roles
- Note pain points with current process

### 2. Module Selection

Choose the correct SAP module code:
- **FI** - Financial Accounting (G/L, AP, AR, Asset Accounting)
- **CO** - Controlling (Cost Centers, Internal Orders, Product Costing)
- **MM** - Materials Management (Purchasing, Inventory, Warehouse)
- **SD** - Sales and Distribution (Sales, Shipping, Billing)
- **PP** - Production Planning (MRP, Production Orders, BOMs)
- **HR** - Human Resources (Personnel, Payroll, Time Management)

### 3. Iterative Approach

For complex projects, use step-by-step execution:
1. Review requirements before proceeding
2. Adjust process mapping if needed
3. Validate solution design
4. Review test cases for completeness

### 4. Naming Conventions

Use clear, descriptive project names:
- ✅ "ABC Corp AP Automation Phase 1"
- ✅ "XYZ Manufacturing Inventory Management"
- ❌ "Project 1"
- ❌ "Test"

### 5. Regular Evaluation

Run evaluation on completed projects:
```bash
python tests/run_tests.py evaluate --session-id prj_your_project
```

This provides quality metrics and identifies improvement areas.

---

## Troubleshooting

### Common Issues

#### Issue: "Session not found"
**Cause:** Invalid session ID or session was deleted  
**Solution:** Run `python src/main.py list` to see available sessions

#### Issue: "Requirements not found"
**Cause:** Trying to execute a phase before completing requirements  
**Solution:** Execute phases in order, starting with requirements

#### Issue: API Rate Limiting
**Cause:** Too many API calls in short time  
**Solution:** Wait a few minutes between runs

#### Issue: Empty or Poor Quality Output
**Cause:** Insufficient input details or API issues  
**Solution:** 
- Provide more detailed stakeholder input
- Check API key is valid
- Review logs in `logs/` directory

### Getting Help

1. **Check Logs:** Review `logs/agent_*.log` for error details
2. **Session Data:** Examine `output/sessions/prj_*.json`
3. **Evaluation:** Run evaluation to identify quality issues
4. **Documentation:** Review architecture.md for system design

### Performance Tips

- **Cold Start:** First run may be slower due to initialization
- **Parallel Projects:** Run one project at a time for best performance
- **Large Projects:** Break into smaller modules if workflow times out

---

## Advanced Usage

### Custom ERP Knowledge

Add your organization's specific knowledge to the Memory Bank:

```python
from src.memory import memory_bank

memory_bank.store_memory(
    entry_id="custom_001",
    category="best_practice",
    content="Our company policy: All POs over $50k require VP approval",
    tags=["company-policy", "approval"],
    importance=1.0
)
```

### Batch Processing

Process multiple projects programmatically:

```python
from src.orchestrator import orchestrator

projects = [
    {"name": "Project A", "module": "FI", "input": "..."},
    {"name": "Project B", "module": "MM", "input": "..."},
]

for project in projects:
    result = orchestrator.execute_full_workflow(
        project_name=project["name"],
        module=project["module"],
        stakeholder_input=project["input"]
    )
    print(f"Project {project['name']}: {'✅' if result['success'] else '❌'}")
```

### Custom Evaluation Criteria

Extend evaluation metrics for your needs:

```python
from tests.evaluation_metrics import AgentEvaluator

evaluator = AgentEvaluator()

# Add custom evaluation
def evaluate_company_standards(requirements):
    # Your custom logic
    return score

# Use in evaluation workflow
```

---

## Next Steps

1. **Run the demo:** `python demo.py`
2. **Try your first project:** Use the workflow command
3. **Review outputs:** Check generated documents
4. **Run evaluation:** Assess quality with evaluation tool
5. **Customize:** Add your organization's knowledge and standards

For technical details, see [Architecture Documentation](architecture.md).