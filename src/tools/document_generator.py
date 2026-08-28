"""
Document Generator Tool - Creates formatted documentation from content
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
import json

from src.config.settings import settings
from src.utils.logger import AgentLogger


class DocumentGenerator:
    """Generates various types of documentation for ERP projects"""
    
    def __init__(self):
        self.logger = AgentLogger("DocumentGenerator")
        self.output_dir = Path(settings.output_dir) / "documents"
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_requirements_document(
        self,
        project_name: str,
        module: str,
        requirements: Dict[str, Any],
        metadata: Optional[Dict] = None
    ) -> str:
        """Generate a formatted requirements document"""
        
        doc_content = f"""# Requirements Document
        
## Project Information
- **Project Name:** {project_name}
- **Module:** {module}
- **Date:** {datetime.now().strftime('%Y-%m-%d')}
- **Version:** 1.0
- **Status:** Draft

---

## Executive Summary

{requirements.get('executive_summary', 'To be completed')}

---

## Business Context and Objectives

{requirements.get('business_context', 'To be completed')}

### Business Objectives
{self._format_list(requirements.get('objectives', []))}

---

## Functional Requirements

"""
        # Add functional requirements by category
        functional_reqs = requirements.get('functional_requirements', {})
        for category, reqs in functional_reqs.items():
            doc_content += f"### {category}\n\n"
            for req in reqs:
                doc_content += f"**{req.get('id', 'REQ-XXX')}:** {req.get('description', '')}\n"
                doc_content += f"- **Priority:** {req.get('priority', 'Medium')}\n"
                doc_content += f"- **Type:** {req.get('type', 'Functional')}\n"
                if req.get('acceptance_criteria'):
                    doc_content += f"- **Acceptance Criteria:** {req['acceptance_criteria']}\n"
                doc_content += "\n"
        
        doc_content += """
---

## Technical Requirements

"""
        technical_reqs = requirements.get('technical_requirements', [])
        doc_content += self._format_requirements_list(technical_reqs)
        
        doc_content += """
---

## Integration Requirements

"""
        integration_reqs = requirements.get('integration_requirements', [])
        doc_content += self._format_requirements_list(integration_reqs)
        
        doc_content += """
---

## Reporting Requirements

"""
        reporting_reqs = requirements.get('reporting_requirements', [])
        doc_content += self._format_requirements_list(reporting_reqs)
        
        doc_content += """
---

## Dependencies and Constraints

### Dependencies
"""
        dependencies = requirements.get('dependencies', [])
        doc_content += self._format_list(dependencies)
        
        doc_content += """
### Constraints
"""
        constraints = requirements.get('constraints', [])
        doc_content += self._format_list(constraints)
        
        doc_content += """
---

## Assumptions

"""
        assumptions = requirements.get('assumptions', [])
        doc_content += self._format_list(assumptions)
        
        doc_content += """
---

## Approval

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Business Owner | | | |
| Project Manager | | | |
| Technical Lead | | | |
| Functional Consultant | | | |

"""
        
        # Save document
        filename = f"requirements_{project_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.md"
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(doc_content)
        
        self.logger.log_tool_usage(
            "generate_requirements_document",
            {'project': project_name, 'module': module},
            f"Document saved to {filepath}"
        )
        
        return str(filepath)
    
    def generate_test_case_document(
        self,
        project_name: str,
        module: str,
        test_cases: List[Dict[str, Any]],
        test_type: str = "QA"
    ) -> str:
        """Generate a formatted test case document"""
        
        doc_content = f"""# {test_type} Test Cases Document

## Project Information
- **Project Name:** {project_name}
- **Module:** {module}
- **Test Type:** {test_type}
- **Date:** {datetime.now().strftime('%Y-%m-%d')}
- **Version:** 1.0

---

## Test Summary

- **Total Test Cases:** {len(test_cases)}
- **Critical:** {sum(1 for tc in test_cases if tc.get('priority') == 'Critical')}
- **High:** {sum(1 for tc in test_cases if tc.get('priority') == 'High')}
- **Medium:** {sum(1 for tc in test_cases if tc.get('priority') == 'Medium')}
- **Low:** {sum(1 for tc in test_cases if tc.get('priority') == 'Low')}

---

## Test Cases

"""
        
        # Group test cases by scenario or module
        for idx, test_case in enumerate(test_cases, 1):
            doc_content += f"""
### Test Case {idx}: {test_case.get('scenario', 'Test Scenario')}

**Test Case ID:** {test_case.get('id', f'TC-{idx:03d}')}  
**Priority:** {test_case.get('priority', 'Medium')}  
**Test Type:** {test_case.get('type', 'Functional')}

#### Objective
{test_case.get('objective', 'Test objective description')}

#### Preconditions
{self._format_list(test_case.get('preconditions', ['None']))}

#### Test Steps

"""
            steps = test_case.get('steps', [])
            for step_num, step in enumerate(steps, 1):
                doc_content += f"{step_num}. {step}\n"
            
            doc_content += f"""

#### Test Data
{self._format_dict(test_case.get('test_data', {}))}

#### Expected Results
{test_case.get('expected_result', 'Expected result description')}

#### Actual Results
_To be filled during testing_

#### Status
- [ ] Pass
- [ ] Fail
- [ ] Blocked

#### Comments
_________________________________

---

"""
        
        doc_content += """
## Test Execution Summary

| Test Case ID | Scenario | Priority | Status | Tester | Date | Comments |
|--------------|----------|----------|--------|--------|------|----------|
"""
        for test_case in test_cases:
            doc_content += f"| {test_case.get('id', 'TC-XXX')} | {test_case.get('scenario', '')} | {test_case.get('priority', 'Medium')} | | | | |\n"
        
        # Save document
        filename = f"test_cases_{test_type}_{project_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.md"
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(doc_content)
        
        self.logger.log_tool_usage(
            "generate_test_case_document",
            {'project': project_name, 'test_type': test_type},
            f"Document saved to {filepath}"
        )
        
        return str(filepath)
    
    def generate_user_manual(
        self,
        process_name: str,
        module: str,
        process_steps: List[Dict[str, Any]],
        screenshots: Optional[List[str]] = None
    ) -> str:
        """Generate a user manual"""
        
        doc_content = f"""# User Manual: {process_name}

## Overview

**Module:** {module}  
**Process:** {process_name}  
**Date:** {datetime.now().strftime('%Y-%m-%d')}  
**Version:** 1.0

---

## Purpose

This manual provides step-by-step instructions for executing the {process_name} process in the ERP system.

---

## Prerequisites

- Access to {module} module
- Required authorizations
- Basic understanding of ERP navigation

---

## Process Steps

"""
        
        for idx, step in enumerate(process_steps, 1):
            doc_content += f"""
### Step {idx}: {step.get('title', 'Process Step')}

**Transaction Code:** {step.get('transaction', 'N/A')}

#### Instructions

{step.get('instructions', 'Step instructions')}

#### Key Fields

"""
            fields = step.get('fields', [])
            if fields:
                doc_content += "| Field | Description | Required | Example |\n"
                doc_content += "|-------|-------------|----------|----------|\n"
                for field in fields:
                    doc_content += f"| {field.get('name', '')} | {field.get('description', '')} | {field.get('required', 'No')} | {field.get('example', '')} |\n"
            
            doc_content += f"""

#### Tips and Best Practices

{self._format_list(step.get('tips', ['Follow standard operating procedures']))}

---

"""
        
        doc_content += """
## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| | | |

---

## FAQs

**Q: Question here?**  
A: Answer here.

---

## Support Contacts

For assistance, please contact:
- **Helpdesk:** [Contact Info]
- **Module Expert:** [Contact Info]

---

## Glossary

| Term | Definition |
|------|------------|
| | |

"""
        
        # Save document
        filename = f"user_manual_{process_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.md"
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(doc_content)
        
        self.logger.log_tool_usage(
            "generate_user_manual",
            {'process': process_name, 'module': module},
            f"Document saved to {filepath}"
        )
        
        return str(filepath)
    
    def generate_solution_design(
        self,
        project_name: str,
        module: str,
        design: Dict[str, Any]
    ) -> str:
        """Generate a solution design document"""
        
        doc_content = f"""# Solution Design Document

## Project Information
- **Project Name:** {project_name}
- **Module:** {module}
- **Date:** {datetime.now().strftime('%Y-%m-%d')}
- **Version:** 1.0
- **Author:** ERP Consultant AI Agent

---

## Executive Summary

{design.get('executive_summary', 'Solution design summary')}

---

## Solution Architecture

### Overview

{design.get('architecture_overview', 'Architecture description')}

### Component Diagram

```
[Diagram placeholder - To be created]
```

---

## Module Configuration

"""
        
        configurations = design.get('configurations', [])
        for config in configurations:
            doc_content += f"### {config.get('component', 'Component')}\n\n"
            doc_content += f"{config.get('description', '')}\n\n"
            doc_content += "**Configuration Steps:**\n"
            doc_content += self._format_list(config.get('steps', []))
            doc_content += "\n"
        
        doc_content += """
---

## Master Data Design

"""
        master_data = design.get('master_data', {})
        for data_type, details in master_data.items():
            doc_content += f"### {data_type}\n\n"
            doc_content += f"{details}\n\n"
        
        doc_content += """
---

## Integration Design

"""
        integrations = design.get('integrations', [])
        for integration in integrations:
            doc_content += f"### {integration.get('name', 'Integration')}\n\n"
            doc_content += f"**Type:** {integration.get('type', 'Real-time')}\n"
            doc_content += f"**Source:** {integration.get('source', '')}\n"
            doc_content += f"**Target:** {integration.get('target', '')}\n"
            doc_content += f"**Description:** {integration.get('description', '')}\n\n"
        
        doc_content += """
---

## Security and Authorization

"""
        security = design.get('security', {})
        doc_content += f"{security.get('overview', 'Security design overview')}\n\n"
        
        doc_content += """
---

## Customizations

"""
        customizations = design.get('customizations', [])
        if customizations:
            doc_content += "| Type | Component | Description | Justification |\n"
            doc_content += "|------|-----------|-------------|---------------|\n"
            for custom in customizations:
                doc_content += f"| {custom.get('type', '')} | {custom.get('component', '')} | {custom.get('description', '')} | {custom.get('justification', '')} |\n"
        else:
            doc_content += "No customizations required. Solution uses standard ERP functionality.\n"
        
        doc_content += """
---

## Migration Strategy

"""
        migration = design.get('migration', {})
        doc_content += f"{migration.get('strategy', 'Migration strategy description')}\n\n"
        
        doc_content += """
---

## Technical Specifications

"""
        tech_specs = design.get('technical_specs', {})
        for spec_name, spec_value in tech_specs.items():
            doc_content += f"**{spec_name}:** {spec_value}\n"
        
        # Save document
        filename = f"solution_design_{project_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.md"
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(doc_content)
        
        self.logger.log_tool_usage(
            "generate_solution_design",
            {'project': project_name, 'module': module},
            f"Document saved to {filepath}"
        )
        
        return str(filepath)
    
    def _format_list(self, items: List[str]) -> str:
        """Format a list of items as markdown"""
        if not items:
            return "- None\n"
        return "\n".join(f"- {item}" for item in items) + "\n"
    
    def _format_requirements_list(self, requirements: List[Dict]) -> str:
        """Format requirements list"""
        if not requirements:
            return "- No requirements specified\n"
        
        result = ""
        for req in requirements:
            result += f"**{req.get('id', 'REQ-XXX')}:** {req.get('description', '')}\n"
            result += f"- Priority: {req.get('priority', 'Medium')}\n\n"
        return result
    
    def _format_dict(self, data: Dict) -> str:
        """Format dictionary as markdown"""
        if not data:
            return "- No data specified\n"
        
        result = ""
        for key, value in data.items():
            result += f"- **{key}:** {value}\n"
        return result


# Global document generator instance
doc_generator = DocumentGenerator()

# -------------------------------------------------------------------
# DocumentGeneratorTool (ADD THIS AT THE VERY BOTTOM OF THE FILE)
# -------------------------------------------------------------------

from typing import Any
try:
    from langchain.tools import BaseTool  # type: ignore
except Exception:
    # Provide a minimal BaseTool fallback for dev mode when langchain is missing
    class BaseTool:
        """Minimal fallback for langchain.tools.BaseTool used for local development.

        This keeps the DocumentGeneratorTool class importable for the POC without adding
        a hard dependency on langchain.
        """
        name: str = "base_tool"
        description: str = "fallback BaseTool for development"

        def _run(self, *args, **kwargs):  # pragma: no cover - dev fallback
            raise NotImplementedError("BaseTool._run not implemented in fallback")

        async def _arun(self, *args, **kwargs):  # pragma: no cover - dev fallback
            raise NotImplementedError("BaseTool._arun not implemented in fallback")

class DocumentGeneratorTool(BaseTool):
    name: str = "document_generator"
    description: str = "Generate ERP documentation: requirements docs, test cases, manuals, solution designs."

    def _run(
        self,
        action: str,
        project_name: str,
        module: str,
        payload: Dict[str, Any],
    ) -> str:
        """
        Runs the document generator.
        action: one of ["requirements", "test_cases", "user_manual", "solution_design"]
        """
        if action == "requirements":
            return doc_generator.generate_requirements_document(
                project_name, module, payload
            )

        elif action == "test_cases":
            return doc_generator.generate_test_case_document(
                project_name, module, payload.get("test_cases", []),
                payload.get("test_type", "QA"),
            )

        elif action == "user_manual":
            return doc_generator.generate_user_manual(
                payload.get("process_name", ""),
                module,
                payload.get("steps", []),
            )

        elif action == "solution_design":
            return doc_generator.generate_solution_design(
                project_name, module, payload
            )

        else:
            return f"Unknown action: {action}"

    async def _arun(self, *args, **kwargs):
        raise NotImplementedError("Async version not implemented.")

