"""
Test runner and evaluation script
"""
import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.evaluation_metrics import evaluator
from src.orchestrator import orchestrator
from src.memory import agent_memory
from src.utils.logger import setup_logging


def run_evaluation_on_session(session_id: str):
    """Run evaluation on an existing session"""
    
    print(f"\n🔍 Running evaluation on session: {session_id}\n")
    
    # Generate evaluation report
    report = evaluator.generate_evaluation_report(session_id)
    
    if 'error' in report:
        print(f"❌ Error: {report['error']}")
        return
    
    # Print report
    evaluator.print_evaluation_report(report)
    
    # Save report
    output_dir = Path("output") / "evaluation_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    report_path = output_dir / f"evaluation_{session_id}_{report['evaluation_date'][:10]}.json"
    
    import json
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n💾 Report saved to: {report_path}\n")


def run_test_project():
    """Run a complete test project and evaluate"""
    
    print("\n🧪 Running Test Project\n")
    
    # Create test project
    test_input = """
    We need to implement Material Master Management in SAP:
    
    Requirements:
    - Create and maintain material master records
    - Support multiple material types (raw materials, finished goods, trading goods)
    - Configure material master views (Basic, Purchasing, Sales, Accounting)
    - Implement material valuation
    - Set up material classification
    - Enable batch management for specific materials
    - Configure serial number management
    - Integrate with inventory management
    - Set up material pricing
    - Implement material BOMs
    """
    
    print("Executing full workflow...")
    
    result = orchestrator.execute_full_workflow(
        project_name="Test Material Master Project",
        module="MM",
        stakeholder_input=test_input,
        erp_system="SAP S/4HANA",
        process_name="Material Master Management",
        user_roles=["Material Planner", "Purchasing Manager", "Warehouse Manager"]
    )
    
    if not result['success']:
        print(f"❌ Workflow failed: {result.get('error')}")
        return
    
    print(f"\n✅ Workflow completed!")
    print(f"Session ID: {result['session_id']}\n")
    
    # Run evaluation
    run_evaluation_on_session(result['session_id'])
    
    # Cleanup
    cleanup = input("\nDelete test session? (y/n): ")
    if cleanup.lower() == 'y':
        agent_memory.session_service.delete_session(result['session_id'])
        print("✅ Test session deleted")


def list_evaluable_sessions():
    """List sessions that can be evaluated"""
    
    sessions = agent_memory.session_service.list_sessions()
    
    print(f"\n📋 Available Sessions for Evaluation ({len(sessions)})")
    print(f"{'='*70}\n")
    
    for session_id in sessions:
        summary = agent_memory.session_service.get_session_summary(session_id)
        if summary:
            print(f"🔹 {session_id}")
            print(f"   Project: {summary['project_name']}")
            print(f"   Module: {summary['module']}")
            print(f"   Phases: {summary['phases_completed']}/6")
            print()


def main():
    """Main test runner"""
    
    # Setup logging
    setup_logging()
    
    parser = argparse.ArgumentParser(description='Test Runner and Evaluation Tool')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Run unit tests
    test_parser = subparsers.add_parser('unit', help='Run unit tests')
    test_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    # Run evaluation on session
    eval_parser = subparsers.add_parser('evaluate', help='Evaluate a session')
    eval_parser.add_argument('--session-id', required=True, help='Session ID to evaluate')
    
    # Run test project
    subparsers.add_parser('test-project', help='Run complete test project and evaluate')
    
    # List sessions
    subparsers.add_parser('list', help='List sessions available for evaluation')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == 'unit':
        # Run pytest
        import pytest
        
        pytest_args = ['tests/', '-v'] if args.verbose else ['tests/']
        exit_code = pytest.main(pytest_args)
        sys.exit(exit_code)
    
    elif args.command == 'evaluate':
        run_evaluation_on_session(args.session_id)
    
    elif args.command == 'test-project':
        run_test_project()
    
    elif args.command == 'list':
        list_evaluable_sessions()


if __name__ == '__main__':
    main()