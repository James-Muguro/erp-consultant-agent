"""
Interactive demo script for ERP Consultant AI Agent
"""
from src.orchestrator import orchestrator
from src.utils.logger import setup_logging
from src.config.settings import settings


def print_section(title):
    """Print section header"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def demo_simple_workflow():
    """Run a simple demo workflow"""
    
    print_section("🚀 ERP CONSULTANT AI AGENT - DEMO")
    
    print("This demo will run through a complete ERP consulting project")
    print("for implementing Accounts Payable in SAP S/4HANA\n")
    
    # Project parameters
    project_name = "ABC Corp AP Implementation"
    module = "FI"
    erp_system = "SAP S/4HANA"
    
    stakeholder_input = """
    We need to implement Accounts Payable functionality for our Finance department.
    
    Requirements:
    - Process vendor invoices electronically
    - Implement three-way matching (PO, GR, Invoice)
    - Automate payment runs
    - Generate vendor reports and aging analysis
    - Integrate with existing procurement system
    - Support multiple payment methods (check, ACH, wire transfer)
    - Implement approval workflows for invoices over $10,000
    - Track vendor performance and compliance
    
    Current challenges:
    - Manual invoice processing is slow
    - Duplicate payments occurring
    - No visibility into payment status
    - Missing early payment discounts
    """
    
    print(f"📋 Project: {project_name}")
    print(f"📦 Module: {module} (Financial Accounting)")
    print(f"🔧 ERP System: {erp_system}")
    print(f"\n📄 Stakeholder Input:\n{stakeholder_input}\n")
    
    input("Press Enter to start the workflow...")
    
    # Execute full workflow
    print_section("⚙️ EXECUTING FULL WORKFLOW")
    
    result = orchestrator.execute_full_workflow(
        project_name=project_name,
        module=module,
        stakeholder_input=stakeholder_input,
        erp_system=erp_system,
        process_name="Procure to Pay (P2P)",
        user_roles=["AP Clerk", "AP Manager", "Finance Controller"]
    )
    
    # Display results
    if result['success']:
        print_section("✅ WORKFLOW COMPLETED SUCCESSFULLY")
        
        print(f"📊 Session ID: {result['session_id']}")
        print(f"⏱️  Total Duration: {result['total_duration']:.2f} seconds\n")
        
        # Phase results
        print("📋 PHASE RESULTS:")
        print("-" * 70)
        
        phases = result['workflow_results']['phases']
        
        for phase_name, phase_result in phases.items():
            status = "✅" if phase_result.get('success') else "❌"
            phase_title = phase_name.replace('_', ' ').title()
            
            print(f"\n{status} {phase_title}")
            
            if phase_result.get('success'):
                duration = phase_result.get('duration', 0)
                print(f"   ⏱️  Duration: {duration:.2f}s")
                
                # Show specific outputs
                if phase_name == 'requirements':
                    req_count = len(phase_result.get('requirements', {}).get('functional_requirements', {}))
                    print(f"   📝 Requirements Categories: {req_count}")
                
                elif phase_name == 'process_mapping':
                    process_map = phase_result.get('process_map', {})
                    steps = len(process_map.get('steps', []))
                    print(f"   🗺️  Process Steps Mapped: {steps}")
                
                elif phase_name == 'solution_design':
                    design = phase_result.get('design', {})
                    customizations = len(design.get('customizations', []))
                    print(f"   🏗️  Customizations: {customizations}")
                
                elif phase_name == 'qa_testing':
                    test_cases = len(phase_result.get('test_cases', []))
                    print(f"   🧪 QA Test Cases: {test_cases}")
                
                elif phase_name == 'uat_testing':
                    scenarios = len(phase_result.get('uat_scenarios', []))
                    print(f"   ✅ UAT Scenarios: {scenarios}")
                
                elif phase_name == 'training':
                    docs = len(phase_result.get('documents', {}))
                    print(f"   📚 Training Documents: {docs}")
                
                # Document path
                doc_path = phase_result.get('document_path')
                if doc_path:
                    print(f"   📄 Document: {doc_path}")
        
        # Summary
        print_section("📊 PROJECT SUMMARY")
        
        summary = result.get('summary', {})
        project_info = summary.get('project_info', {})
        
        print("Project Information:")
        print(f"  Name: {project_info.get('name')}")
        print(f"  Module: {project_info.get('module')}")
        print(f"  ERP System: {project_info.get('erp_system')}")
        print(f"  Started: {project_info.get('created_at')}")
        print(f"  Completed: {project_info.get('completed_at')}")
        
        phases_completed = summary.get('phases_completed', [])
        print(f"\n  Phases Completed: {len(phases_completed)}/6")
        for phase in phases_completed:
            print(f"    ✅ {phase.replace('_', ' ').title()}")
        
        # Deliverables
        deliverables = summary.get('deliverables', {})
        if deliverables:
            print("\n📂 Deliverables Generated:")
            for phase, path in deliverables.items():
                print(f"  - {phase.replace('_', ' ').title()}: {path}")
        
        # Metrics
        print_section("📈 PERFORMANCE METRICS")
        print(result.get('metrics', 'No metrics available'))
        
        print("\n" + "="*70)
        print("🎉 Demo completed successfully!")
        print("="*70 + "\n")
        
        print(f"💡 Next Steps:")
        print(f"  1. Review generated documents in: {settings.output_dir}/documents/")
        print(f"  2. Check session data in: {settings.output_dir}/sessions/")
        print(f"  3. View logs in: {settings.logs_dir}/")
        print(f"\n  Session ID for future reference: {result['session_id']}")
        
    else:
        print_section("❌ WORKFLOW FAILED")
        print(f"Error: {result.get('error')}")


def main():
    """Main demo function"""
    
    # Initialize logging
    setup_logging()
    
    try:
        demo_simple_workflow()
    except KeyboardInterrupt:
        print("\n\n⚠️  Demo interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Demo failed with error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()