"""
Main entry point for ERP Consultant AI Agent
"""
import argparse
import json
from pathlib import Path

from src.orchestrator import orchestrator
from src.memory import agent_memory
from src.utils.logger import metrics_collector, setup_logging
from src.config.settings import settings


def print_banner():
    """Print application banner"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║          ERP CONSULTANT AI AGENT                             ║
║          Multi-Agent System for ERP Projects                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def run_full_workflow(args):
    """Run complete ERP consulting workflow"""
    
    print(f"\n🚀 Starting ERP Consulting Project: {args.project_name}")
    print(f"📦 Module: {args.module}")
    print(f"🔧 ERP System: {args.erp_system}")
    print(f"\n{'='*60}\n")
    
    # Execute full workflow
    result = orchestrator.execute_full_workflow(
        project_name=args.project_name,
        module=args.module,
        stakeholder_input=args.input,
        erp_system=args.erp_system,
        process_name=args.process_name,
        user_roles=args.user_roles.split(',') if args.user_roles else None
    )
    
    if result['success']:
        print("\n✅ Workflow completed successfully!")
        print(f"\n📊 Session ID: {result['session_id']}")
        print(f"⏱️  Total Duration: {result['total_duration']:.2f} seconds")
        
        # Print phase results
        print("\n📋 Phase Results:")
        for phase, phase_result in result['workflow_results']['phases'].items():
            status = "✅" if phase_result.get('success') else "❌"
            print(f"  {status} {phase.replace('_', ' ').title()}")
            
            # Print document path if available
            doc_path = phase_result.get('document_path')
            if doc_path:
                print(f"     📄 Document: {doc_path}")
        
        # Print summary
        summary = result.get('summary', {})
        if summary:
            print(f"\n📈 Project Summary:")
            print(f"  Phases Completed: {len(summary.get('phases_completed', []))}/6")
            
            deliverables = summary.get('deliverables', {})
            if deliverables:
                print(f"\n  📂 Deliverables:")
                for phase, path in deliverables.items():
                    print(f"    - {phase}: {path}")
        
        # Print metrics
        print(f"\n{metrics_collector.get_summary()}")
        
        # Save results to file
        output_file = Path(settings.output_dir) / f"project_{result['session_id']}_results.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\n💾 Full results saved to: {output_file}")
        
    else:
        print(f"\n❌ Workflow failed: {result.get('error')}")
        if 'partial_results' in result:
            print("\n⚠️  Partial results available")


def run_single_phase(args):
    """Run a single project phase"""
    
    print(f"\n🎯 Executing Phase: {args.phase}")
    print(f"📊 Session ID: {args.session_id}")
    print(f"\n{'='*60}\n")
    
    phase_methods = {
        'requirements': orchestrator.execute_requirements_phase,
        'process_mapping': orchestrator.execute_process_mapping_phase,
        'solution_design': orchestrator.execute_solution_design_phase,
        'qa_testing': orchestrator.execute_qa_testing_phase,
        'uat_testing': orchestrator.execute_uat_testing_phase,
        'training': orchestrator.execute_training_phase
    }
    
    method = phase_methods.get(args.phase)
    if not method:
        print(f"❌ Unknown phase: {args.phase}")
        return
    
    # Execute phase
    if args.phase == 'requirements':
        if not args.input:
            print("❌ --input required for requirements phase")
            return
        result = method(session_id=args.session_id, stakeholder_input=args.input)
    elif args.phase == 'process_mapping':
        result = method(session_id=args.session_id, process_name=args.process_name)
    else:
        result = method(session_id=args.session_id)
    
    if result['success']:
        print(f"\n✅ Phase completed successfully!")
        print(f"⏱️  Duration: {result['duration']:.2f} seconds")
        
        doc_path = result.get('document_path')
        if doc_path:
            print(f"📄 Document: {doc_path}")
    else:
        print(f"\n❌ Phase failed: {result.get('error')}")


def show_project_status(args):
    """Show project status"""
    
    status = orchestrator.get_project_status(args.session_id)
    
    if 'error' in status:
        print(f"❌ {status['error']}")
        return
    
    print(f"\n📊 Project Status")
    print(f"{'='*60}")
    print(f"Project: {status['project_name']}")
    print(f"Module: {status['module']}")
    print(f"Current Phase: {status['current_phase']}")
    print(f"Progress: {status['progress_percentage']:.1f}%")
    print(f"\nCompleted Phases:")
    for phase in status['completed_phases']:
        print(f"  ✅ {phase.replace('_', ' ').title()}")
    print(f"\nNext Phase: {status['next_phase'].replace('_', ' ').title()}")
    print(f"\nCreated: {status['created_at']}")
    print(f"Last Updated: {status['last_updated']}")


def list_sessions(args):
    """List all sessions"""
    
    sessions = agent_memory.session_service.list_sessions()
    
    print(f"\n📋 Active Sessions ({len(sessions)})")
    print(f"{'='*60}")
    
    for session_id in sessions:
        summary = agent_memory.session_service.get_session_summary(session_id)
        if summary:
            print(f"\n🔹 {session_id}")
            print(f"   Project: {summary['project_name']}")
            print(f"   Module: {summary['module']}")
            print(f"   Phase: {summary['current_phase']}")
            print(f"   Progress: {summary['phases_completed']}/6 phases")


def show_memory_stats(args):
    """Show memory statistics"""
    
    stats = agent_memory.get_memory_stats()
    
    print(f"\n🧠 Memory Statistics")
    print(f"{'='*60}")
    
    print(f"\nSessions:")
    print(f"  Active: {stats['sessions']['active']}")
    
    print(f"\nMemory Bank:")
    print(f"  Total Memories: {stats['memory_bank']['total_memories']}")
    
    print(f"\n  By Category:")
    for category, count in stats['memory_bank']['categories'].items():
        print(f"    - {category}: {count}")
    
    if stats['memory_bank']['top_tags']:
        print(f"\n  Top Tags:")
        for tag, count in stats['memory_bank']['top_tags'][:5]:
            print(f"    - {tag}: {count}")


def main():
    """Main entry point"""
    
    # Initialize logging
    setup_logging()
    settings.init_directories()
    
    print_banner()
    
    parser = argparse.ArgumentParser(
        description='ERP Consultant AI Agent - Multi-Agent System for ERP Projects'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Full workflow command
    workflow_parser = subparsers.add_parser('workflow', help='Run complete workflow')
    workflow_parser.add_argument('--project-name', required=True, help='Project name')
    workflow_parser.add_argument('--module', required=True, help='ERP module (FI, MM, SD, etc.)')
    workflow_parser.add_argument('--input', required=True, help='Initial stakeholder input/requirements')
    workflow_parser.add_argument('--erp-system', default='SAP S/4HANA', help='ERP system')
    workflow_parser.add_argument('--process-name', help='Business process name')
    workflow_parser.add_argument('--user-roles', help='Comma-separated user roles')
    
    # Single phase command
    phase_parser = subparsers.add_parser('phase', help='Run single phase')
    phase_parser.add_argument('--session-id', required=True, help='Session ID')
    phase_parser.add_argument('--phase', required=True, 
                             choices=['requirements', 'process_mapping', 'solution_design', 
                                    'qa_testing', 'uat_testing', 'training'],
                             help='Phase to execute')
    phase_parser.add_argument('--input', help='Input for the phase')
    phase_parser.add_argument('--process-name', help='Process name (for process_mapping)')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show project status')
    status_parser.add_argument('--session-id', required=True, help='Session ID')
    
    # List sessions command
    subparsers.add_parser('list', help='List all sessions')
    
    # Memory stats command
    subparsers.add_parser('memory', help='Show memory statistics')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Execute command
    if args.command == 'workflow':
        run_full_workflow(args)
    elif args.command == 'phase':
        run_single_phase(args)
    elif args.command == 'status':
        show_project_status(args)
    elif args.command == 'list':
        list_sessions(args)
    elif args.command == 'memory':
        show_memory_stats(args)


if __name__ == '__main__':
    main()