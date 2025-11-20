"""
Test Case Generator Tool - Generates comprehensive test cases
"""
from typing import Dict, List, Optional, Any
from datetime import datetime

from src.utils.logger import AgentLogger


class TestCaseGenerator:
    """Generates test cases for ERP implementations"""
    
    def __init__(self):
        self.logger = AgentLogger("TestCaseGenerator")
        self.test_case_counter = 1
    
    def generate_test_case(
        self,
        scenario: str,
        test_type: str,
        priority: str,
        steps: List[str],
        expected_result: str,
        test_data: Optional[Dict] = None,
        preconditions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Generate a single test case"""
        
        test_case = {
            'id': f'TC-{self.test_case_counter:04d}',
            'scenario': scenario,
            'type': test_type,
            'priority': priority,
            'steps': steps,
            'expected_result': expected_result,
            'test_data': test_data or {},
            'preconditions': preconditions or [],
            'status': 'Not Executed',
            'created_date': datetime.now().isoformat(),
            'execution_date': None,
            'tester': None,
            'actual_result': None,
            'comments': None
        }
        
        self.test_case_counter += 1
        
        self.logger.log_tool_usage(
            "generate_test_case",
            {'scenario': scenario, 'type': test_type},
            f"Test case {test_case['id']} created"
        )
        
        return test_case
    
    def generate_functional_test_cases(
        self,
        requirements: List[Dict[str, Any]],
        module: str
    ) -> List[Dict[str, Any]]:
        """Generate functional test cases from requirements"""
        
        test_cases = []
        
        for req in requirements:
            req_id = req.get('id', 'REQ-XXX')
            description = req.get('description', '')
            priority = req.get('priority', 'Medium')
            
            # Positive test case
            positive_tc = self.generate_test_case(
                scenario=f"Verify {description} - Positive Scenario",
                test_type="Functional",
                priority=priority,
                steps=[
                    f"Navigate to the {module} module",
                    "Enter valid test data",
                    "Execute the transaction",
                    "Verify the result"
                ],
                expected_result=f"System processes the transaction successfully and {description}",
                test_data={
                    'requirement_id': req_id,
                    'test_type': 'positive'
                },
                preconditions=[
                    "User has appropriate authorizations",
                    "System is in a stable state",
                    "Master data is configured"
                ]
            )
            test_cases.append(positive_tc)
            
            # Negative test case
            negative_tc = self.generate_test_case(
                scenario=f"Verify {description} - Negative Scenario",
                test_type="Functional",
                priority="Medium",
                steps=[
                    f"Navigate to the {module} module",
                    "Enter invalid test data",
                    "Attempt to execute the transaction",
                    "Verify error handling"
                ],
                expected_result="System displays appropriate error message and prevents invalid data",
                test_data={
                    'requirement_id': req_id,
                    'test_type': 'negative'
                },
                preconditions=[
                    "User has appropriate authorizations",
                    "System is in a stable state"
                ]
            )
            test_cases.append(negative_tc)
        
        return test_cases
    
    def generate_integration_test_cases(
        self,
        integration_points: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Generate integration test cases"""
        
        test_cases = []
        
        for integration in integration_points:
            source = integration.get('source', 'Source System')
            target = integration.get('target', 'Target System')
            description = integration.get('description', 'Data integration')
            
            # End-to-end integration test
            tc = self.generate_test_case(
                scenario=f"Verify data flow from {source} to {target}",
                test_type="Integration",
                priority="High",
                steps=[
                    f"Create transaction in {source}",
                    "Trigger integration process",
                    f"Verify data received in {target}",
                    "Validate data accuracy and completeness",
                    "Check integration logs"
                ],
                expected_result=f"Data flows successfully from {source} to {target} with 100% accuracy",
                test_data={
                    'source': source,
                    'target': target,
                    'integration_type': integration.get('type', 'real-time')
                },
                preconditions=[
                    "Integration interface is configured",
                    "Both systems are accessible",
                    "Test data is prepared"
                ]
            )
            test_cases.append(tc)
            
            # Error handling test
            error_tc = self.generate_test_case(
                scenario=f"Verify error handling for {source} to {target} integration",
                test_type="Integration",
                priority="High",
                steps=[
                    f"Create transaction with invalid data in {source}",
                    "Trigger integration process",
                    "Verify error is caught and logged",
                    "Verify error notification is sent",
                    "Verify transaction can be corrected and reprocessed"
                ],
                expected_result="System handles errors gracefully, logs details, and allows reprocessing",
                test_data={
                    'source': source,
                    'target': target,
                    'test_scenario': 'error_handling'
                },
                preconditions=[
                    "Integration interface is configured",
                    "Error handling is configured"
                ]
            )
            test_cases.append(error_tc)
        
        return test_cases
    
    def generate_performance_test_cases(
        self,
        critical_transactions: List[str]
    ) -> List[Dict[str, Any]]:
        """Generate performance test cases"""
        
        test_cases = []
        
        for transaction in critical_transactions:
            # Response time test
            tc = self.generate_test_case(
                scenario=f"Verify response time for {transaction}",
                test_type="Performance",
                priority="High",
                steps=[
                    f"Execute {transaction} with standard data volume",
                    "Record response time",
                    "Execute multiple times (10 iterations)",
                    "Calculate average response time"
                ],
                expected_result=f"{transaction} completes within acceptable response time (< 3 seconds)",
                test_data={
                    'transaction': transaction,
                    'iterations': 10,
                    'max_response_time': '3 seconds'
                },
                preconditions=[
                    "System is at baseline load",
                    "Performance monitoring tools are active"
                ]
            )
            test_cases.append(tc)
            
            # Load test
            load_tc = self.generate_test_case(
                scenario=f"Verify {transaction} under load",
                test_type="Performance",
                priority="Medium",
                steps=[
                    f"Simulate 50 concurrent users executing {transaction}",
                    "Monitor system performance",
                    "Record response times",
                    "Check for errors or timeouts"
                ],
                expected_result="System handles concurrent users without performance degradation",
                test_data={
                    'transaction': transaction,
                    'concurrent_users': 50,
                    'duration': '15 minutes'
                },
                preconditions=[
                    "Load testing tool is configured",
                    "Test users are set up"
                ]
            )
            test_cases.append(load_tc)
        
        return test_cases
    
    def generate_security_test_cases(
        self,
        roles: List[str],
        sensitive_transactions: List[str]
    ) -> List[Dict[str, Any]]:
        """Generate security and authorization test cases"""
        
        test_cases = []
        
        for transaction in sensitive_transactions:
            for role in roles:
                # Authorization test
                tc = self.generate_test_case(
                    scenario=f"Verify {role} access to {transaction}",
                    test_type="Security",
                    priority="Critical",
                    steps=[
                        f"Log in as user with {role} role",
                        f"Attempt to access {transaction}",
                        "Verify authorization check",
                        "Attempt to execute transaction",
                        "Verify results"
                    ],
                    expected_result=f"User with {role} role has appropriate access based on authorization matrix",
                    test_data={
                        'role': role,
                        'transaction': transaction
                    },
                    preconditions=[
                        f"Test user with {role} role exists",
                        "Authorization matrix is defined"
                    ]
                )
                test_cases.append(tc)
        
        # Audit trail test
        audit_tc = self.generate_test_case(
            scenario="Verify audit trail logging for sensitive transactions",
            test_type="Security",
            priority="High",
            steps=[
                "Execute sensitive transaction",
                "Check audit logs",
                "Verify all required fields are logged",
                "Verify timestamp accuracy",
                "Verify user identification"
            ],
            expected_result="All sensitive transactions are logged with complete audit information",
            test_data={
                'transactions': sensitive_transactions
            },
            preconditions=[
                "Audit logging is enabled",
                "Access to audit tables"
            ]
        )
        test_cases.append(audit_tc)
        
        return test_cases
    
    def generate_uat_scenarios(
        self,
        business_processes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Generate user acceptance test scenarios"""
        
        test_cases = []
        
        for process in business_processes:
            process_name = process.get('name', 'Business Process')
            description = process.get('description', '')
            user_role = process.get('user_role', 'Business User')
            
            # End-to-end business scenario
            tc = self.generate_test_case(
                scenario=f"Execute complete {process_name} process",
                test_type="UAT",
                priority="High",
                steps=process.get('steps', [
                    "Log into the system",
                    "Navigate to the process starting point",
                    "Complete all process steps",
                    "Verify final output"
                ]),
                expected_result=process.get('expected_outcome', f"{process_name} completes successfully with expected business outcome"),
                test_data={
                    'process': process_name,
                    'user_role': user_role,
                    'business_data': process.get('test_data', {})
                },
                preconditions=[
                    f"User with {user_role} role is available",
                    "All system configurations are complete",
                    "Test data is loaded"
                ]
            )
            test_cases.append(tc)
        
        return test_cases
    
    def generate_regression_test_suite(
        self,
        existing_test_cases: List[Dict[str, Any]],
        changes: List[str]
    ) -> List[Dict[str, Any]]:
        """Generate regression test suite based on changes"""
        
        # Filter critical test cases
        regression_suite = [
            tc for tc in existing_test_cases
            if tc.get('priority') in ['Critical', 'High']
        ]
        
        # Add specific tests for areas affected by changes
        for change in changes:
            impact_tc = self.generate_test_case(
                scenario=f"Verify no regression impact from: {change}",
                test_type="Regression",
                priority="High",
                steps=[
                    "Identify processes affected by the change",
                    "Execute existing test cases for affected processes",
                    "Verify no unexpected behavior",
                    "Compare results with baseline"
                ],
                expected_result="No regression issues found; all existing functionality works as before",
                test_data={
                    'change': change,
                    'regression_type': 'impact_analysis'
                },
                preconditions=[
                    "Baseline test results are available",
                    "Change is deployed to test environment"
                ]
            )
            regression_suite.append(impact_tc)
        
        return regression_suite
    
    def generate_test_summary(
        self,
        test_cases: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate test summary statistics"""
        
        summary = {
            'total_test_cases': len(test_cases),
            'by_type': {},
            'by_priority': {},
            'by_status': {},
            'coverage': {
                'requirements_covered': set(),
                'modules_covered': set()
            }
        }
        
        for tc in test_cases:
            # Count by type
            test_type = tc.get('type', 'Unknown')
            summary['by_type'][test_type] = summary['by_type'].get(test_type, 0) + 1
            
            # Count by priority
            priority = tc.get('priority', 'Unknown')
            summary['by_priority'][priority] = summary['by_priority'].get(priority, 0) + 1
            
            # Count by status
            status = tc.get('status', 'Not Executed')
            summary['by_status'][status] = summary['by_status'].get(status, 0) + 1
            
            # Track coverage
            req_id = tc.get('test_data', {}).get('requirement_id')
            if req_id:
                summary['coverage']['requirements_covered'].add(req_id)
        
        # Convert sets to lists for JSON serialization
        summary['coverage']['requirements_covered'] = list(summary['coverage']['requirements_covered'])
        summary['coverage']['modules_covered'] = list(summary['coverage']['modules_covered'])
        
        return summary
    
    def reset_counter(self):
        """Reset test case counter"""
        self.test_case_counter = 1


# Global test case generator instance
test_generator = TestCaseGenerator()