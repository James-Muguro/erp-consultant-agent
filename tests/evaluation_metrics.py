"""
Evaluation metrics for ERP Consultant AI Agent
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import json
from pathlib import Path
from datetime import datetime

from src.memory import agent_memory
from src.utils.logger import metrics_collector


@dataclass
class EvaluationResult:
    """Result of evaluation"""
    metric_name: str
    score: float
    max_score: float
    percentage: float
    details: Dict[str, Any]
    passed: bool


class AgentEvaluator:
    """Evaluator for agent performance and output quality"""
    
    def __init__(self):
        self.results = []
    
    def evaluate_requirements_completeness(
        self,
        requirements: Dict[str, Any]
    ) -> EvaluationResult:
        """
        Evaluate completeness of requirements document
        
        Criteria:
        - All required sections present (10 points)
        - Functional requirements documented (10 points)
        - Technical requirements documented (5 points)
        - Integration requirements documented (5 points)
        - Clear acceptance criteria (5 points)
        """
        score = 0
        max_score = 35
        details = {}
        
        # Check required sections
        required_sections = [
            'executive_summary',
            'business_context',
            'functional_requirements',
            'technical_requirements',
            'integration_requirements'
        ]
        
        sections_present = sum(1 for section in required_sections if requirements.get(section))
        score += (sections_present / len(required_sections)) * 10
        details['sections_present'] = f"{sections_present}/{len(required_sections)}"
        
        # Functional requirements
        func_reqs = requirements.get('functional_requirements', {})
        if func_reqs:
            req_count = sum(len(reqs) for reqs in func_reqs.values())
            if req_count >= 10:
                score += 10
            elif req_count >= 5:
                score += 5
            details['functional_requirements_count'] = req_count
        
        # Technical requirements
        tech_reqs = requirements.get('technical_requirements', [])
        if len(tech_reqs) >= 3:
            score += 5
        elif len(tech_reqs) >= 1:
            score += 2
        details['technical_requirements_count'] = len(tech_reqs)
        
        # Integration requirements
        int_reqs = requirements.get('integration_requirements', [])
        if len(int_reqs) >= 2:
            score += 5
        elif len(int_reqs) >= 1:
            score += 2
        details['integration_requirements_count'] = len(int_reqs)
        
        # Acceptance criteria (check if any functional req has it)
        has_acceptance = False
        for reqs in func_reqs.values():
            if any(req.get('acceptance_criteria') for req in reqs):
                has_acceptance = True
                break
        if has_acceptance:
            score += 5
        details['has_acceptance_criteria'] = has_acceptance
        
        percentage = (score / max_score) * 100
        
        result = EvaluationResult(
            metric_name="Requirements Completeness",
            score=score,
            max_score=max_score,
            percentage=percentage,
            details=details,
            passed=percentage >= 70
        )
        
        self.results.append(result)
        return result
    
    def evaluate_process_map_quality(
        self,
        process_map: Dict[str, Any]
    ) -> EvaluationResult:
        """
        Evaluate quality of process map
        
        Criteria:
        - Clear process steps defined (10 points)
        - Roles identified (5 points)
        - Decision points documented (5 points)
        - Integration points identified (5 points)
        - Exception handling covered (5 points)
        """
        score = 0
        max_score = 30
        details = {}
        
        # Process steps
        steps = process_map.get('steps', [])
        if len(steps) >= 8:
            score += 10
        elif len(steps) >= 5:
            score += 7
        elif len(steps) >= 3:
            score += 4
        details['process_steps_count'] = len(steps)
        
        # Roles
        roles = process_map.get('roles', [])
        if len(roles) >= 3:
            score += 5
        elif len(roles) >= 1:
            score += 2
        details['roles_count'] = len(roles)
        
        # Decision points
        decision_points = process_map.get('decision_points', [])
        if len(decision_points) >= 2:
            score += 5
        elif len(decision_points) >= 1:
            score += 3
        details['decision_points_count'] = len(decision_points)
        
        # Integration points
        integration_points = process_map.get('integration_points', [])
        if len(integration_points) >= 2:
            score += 5
        elif len(integration_points) >= 1:
            score += 3
        details['integration_points_count'] = len(integration_points)
        
        # Exception handling
        exceptions = process_map.get('exceptions', [])
        if len(exceptions) >= 2:
            score += 5
        elif len(exceptions) >= 1:
            score += 3
        details['exceptions_count'] = len(exceptions)
        
        percentage = (score / max_score) * 100
        
        result = EvaluationResult(
            metric_name="Process Map Quality",
            score=score,
            max_score=max_score,
            percentage=percentage,
            details=details,
            passed=percentage >= 70
        )
        
        self.results.append(result)
        return result
    
    def evaluate_solution_design_quality(
        self,
        solution_design: Dict[str, Any]
    ) -> EvaluationResult:
        """
        Evaluate quality of solution design
        
        Criteria:
        - Architecture clearly defined (10 points)
        - Configurations documented (10 points)
        - Security design included (5 points)
        - Minimal customizations (10 points)
        - Migration strategy defined (5 points)
        """
        score = 0
        max_score = 40
        details = {}
        
        # Architecture
        if solution_design.get('architecture_overview'):
            score += 10
        details['has_architecture'] = bool(solution_design.get('architecture_overview'))
        
        # Configurations
        configs = solution_design.get('configurations', [])
        if len(configs) >= 5:
            score += 10
        elif len(configs) >= 3:
            score += 7
        elif len(configs) >= 1:
            score += 4
        details['configurations_count'] = len(configs)
        
        # Security
        if solution_design.get('security', {}).get('overview'):
            score += 5
        details['has_security_design'] = bool(solution_design.get('security'))
        
        # Customizations (fewer is better)
        customizations = solution_design.get('customizations', [])
        custom_count = len(customizations)
        if custom_count == 0:
            score += 10
        elif custom_count <= 2:
            score += 7
        elif custom_count <= 5:
            score += 4
        details['customizations_count'] = custom_count
        details['follows_best_practice'] = custom_count <= 2
        
        # Migration
        if solution_design.get('migration', {}).get('strategy'):
            score += 5
        details['has_migration_strategy'] = bool(solution_design.get('migration'))
        
        percentage = (score / max_score) * 100
        
        result = EvaluationResult(
            metric_name="Solution Design Quality",
            score=score,
            max_score=max_score,
            percentage=percentage,
            details=details,
            passed=percentage >= 70
        )
        
        self.results.append(result)
        return result
    
    def evaluate_test_coverage(
        self,
        test_cases: List[Dict[str, Any]],
        requirements_count: int = 10
    ) -> EvaluationResult:
        """
        Evaluate test case coverage
        
        Criteria:
        - Adequate number of test cases (10 points)
        - Mix of positive and negative tests (5 points)
        - Critical functionality covered (10 points)
        - Clear test steps (5 points)
        - Expected results defined (5 points)
        """
        score = 0
        max_score = 35
        details = {}
        
        test_count = len(test_cases)
        
        # Number of test cases (at least 2x requirements)
        expected_min = requirements_count * 2
        if test_count >= expected_min:
            score += 10
        elif test_count >= requirements_count:
            score += 7
        elif test_count >= requirements_count // 2:
            score += 4
        details['test_cases_count'] = test_count
        details['requirements_count'] = requirements_count
        
        # Test types (positive/negative)
        test_types = set(tc.get('type', 'Functional') for tc in test_cases)
        if len(test_types) >= 2:
            score += 5
        details['test_types'] = list(test_types)
        
        # Priority coverage
        critical_count = sum(1 for tc in test_cases if tc.get('priority') == 'Critical')
        high_count = sum(1 for tc in test_cases if tc.get('priority') == 'High')
        
        if critical_count >= 3 or high_count >= 5:
            score += 10
        elif critical_count >= 1 or high_count >= 2:
            score += 5
        details['critical_test_cases'] = critical_count
        details['high_priority_test_cases'] = high_count
        
        # Clear test steps
        avg_steps = sum(len(tc.get('steps', [])) for tc in test_cases) / max(test_count, 1)
        if avg_steps >= 4:
            score += 5
        elif avg_steps >= 2:
            score += 3
        details['avg_steps_per_test'] = round(avg_steps, 2)
        
        # Expected results
        with_expected = sum(1 for tc in test_cases if tc.get('expected_result'))
        if with_expected == test_count:
            score += 5
        elif with_expected >= test_count * 0.8:
            score += 3
        details['tests_with_expected_results'] = f"{with_expected}/{test_count}"
        
        percentage = (score / max_score) * 100
        
        result = EvaluationResult(
            metric_name="Test Coverage",
            score=score,
            max_score=max_score,
            percentage=percentage,
            details=details,
            passed=percentage >= 70
        )
        
        self.results.append(result)
        return result
    
    def evaluate_performance(
        self,
        session_id: str
    ) -> EvaluationResult:
        """
        Evaluate overall system performance
        
        Criteria:
        - Reasonable execution time (10 points)
        - Success rate (10 points)
        - All phases completed (10 points)
        """
        score = 0
        max_score = 30
        details = {}
        
        # Get metrics
        metrics = metrics_collector.get_metrics()
        
        # Execution time (average duration per task)
        total_tasks = metrics.get('total_tasks', 0)
        total_duration = metrics.get('total_duration', 0)
        
        if total_tasks > 0:
            avg_duration = total_duration / total_tasks
            if avg_duration <= 5:
                score += 10
            elif avg_duration <= 10:
                score += 7
            elif avg_duration <= 20:
                score += 4
            details['avg_duration_per_task'] = round(avg_duration, 2)
        
        # Success rate
        successful = metrics.get('successful_tasks', 0)
        if total_tasks > 0:
            success_rate = (successful / total_tasks) * 100
            if success_rate >= 90:
                score += 10
            elif success_rate >= 75:
                score += 7
            elif success_rate >= 50:
                score += 4
            details['success_rate'] = f"{success_rate:.1f}%"
        
        # Phases completed
        session = agent_memory.session_service.get_session(session_id)
        if session:
            phases_completed = len(session.completed_phases)
            if phases_completed == 6:
                score += 10
            elif phases_completed >= 4:
                score += 7
            elif phases_completed >= 2:
                score += 4
            details['phases_completed'] = f"{phases_completed}/6"
        
        percentage = (score / max_score) * 100
        
        result = EvaluationResult(
            metric_name="System Performance",
            score=score,
            max_score=max_score,
            percentage=percentage,
            details=details,
            passed=percentage >= 70
        )
        
        self.results.append(result)
        return result
    
    def generate_evaluation_report(
        self,
        session_id: str,
        output_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """Generate comprehensive evaluation report"""
        
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'error': 'Session not found'}
        
        # Evaluate all phases
        requirements = agent_memory.get_phase_output(session_id, 'requirements_gathering')
        if requirements:
            self.evaluate_requirements_completeness(requirements.get('structured_requirements', {}))
        
        process_maps = session.process_maps or {}
        for process_name, process_data in process_maps.items():
            self.evaluate_process_map_quality(process_data.get('structured', {}))
        
        solution_design = agent_memory.get_phase_output(session_id, 'solution_design')
        if solution_design:
            self.evaluate_solution_design_quality(solution_design.get('structured_design', {}))
        
        qa_tests = agent_memory.get_phase_output(session_id, 'qa_testing')
        if qa_tests:
            req_count = len(requirements.get('structured_requirements', {}).get('functional_requirements', {})) if requirements else 10
            self.evaluate_test_coverage(qa_tests.get('test_cases', []), req_count)
        
        # Performance evaluation
        self.evaluate_performance(session_id)
        
        # Calculate overall score
        total_score = sum(r.score for r in self.results)
        max_total_score = sum(r.max_score for r in self.results)
        overall_percentage = (total_score / max_total_score * 100) if max_total_score > 0 else 0
        
        report = {
            'session_id': session_id,
            'project_name': session.project_name,
            'evaluation_date': datetime.now().isoformat(),
            'overall_score': round(overall_percentage, 2),
            'passed': overall_percentage >= 70,
            'results': [
                {
                    'metric': r.metric_name,
                    'score': r.score,
                    'max_score': r.max_score,
                    'percentage': round(r.percentage, 2),
                    'passed': r.passed,
                    'details': r.details
                }
                for r in self.results
            ]
        }
        
        # Save report if path provided
        if output_path:
            with open(output_path, 'w') as f:
                json.dump(report, f, indent=2)
        
        return report
    
    def print_evaluation_report(self, report: Dict[str, Any]):
        """Print formatted evaluation report"""
        
        print(f"\n{'='*70}")
        print(f"  EVALUATION REPORT")
        print(f"{'='*70}")
        print(f"\nProject: {report['project_name']}")
        print(f"Session ID: {report['session_id']}")
        print(f"Evaluation Date: {report['evaluation_date']}")
        print(f"\nOVERALL SCORE: {report['overall_score']:.2f}%")
        print(f"Status: {'✅ PASSED' if report['passed'] else '❌ FAILED'}")
        
        print(f"\n{'='*70}")
        print("DETAILED RESULTS")
        print(f"{'='*70}\n")
        
        for result in report['results']:
            status = "✅" if result['passed'] else "❌"
            print(f"{status} {result['metric']}")
            print(f"   Score: {result['score']}/{result['max_score']} ({result['percentage']:.1f}%)")
            print(f"   Details:")
            for key, value in result['details'].items():
                print(f"     - {key}: {value}")
            print()


# Global evaluator instance
evaluator = AgentEvaluator()