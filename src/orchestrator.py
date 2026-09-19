"""
Orchestrator Agent - Coordinates all specialized agents and manages workflow.

This is the pipeline driver: it sequences the six phases, threads state
between them, applies the phase-level timeout, and assembles the final
project state.

Design notes on this revision:

  * Pipeline gating. Previously every phase failure was logged and the
    workflow continued anyway, producing a cascade of "X not found"
    errors from downstream phases. Now failures on critical phases
    (requirements_gathering, solution_design) stop the pipeline with a
    clear error, and non-critical failures are surfaced in the summary.

  * Diagnostics aggregation. Every agent now returns enriched keys
    (warnings, open_questions, degraded, repaired, validation). The
    orchestrator previously dropped all of them. It now collects them
    per-phase and aggregates them at the workflow level, so the
    epistemic discipline the agents enforce reaches the caller.

  * Correlation binding. Each phase binds session_id and phase_name onto
    the log context via AgentLogger.bound(), so log lines from
    concurrent phases on different sessions are distinguishable.

  * Terminal 'completed' phase. AgentMemory.advance_phase rejects any
    phase outside the six-entry PHASES sequence, so calling it with
    'completed' silently fails. The _advance_to_phase helper handles the
    terminal case by going through the session service directly.

  * Defensive result handling. _call_agent_safely normalizes non-dict
    results from agents into a structured failure, so a return-value
    mistake in one agent can't crash the orchestrator.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from src.utils.llm import get_llm
from src.config.settings import settings
from src.utils.logger import AgentLogger, metrics_collector
from src.utils.resilience import run_with_timeout, OperationTimeoutError
from src.utils.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from src.memory import agent_memory
from src.memory.session_manager import PHASES
from src.agents import (
    requirements_agent,
    process_mapping_agent,
    solution_design_agent,
    qa_testing_agent,
    uat_testing_agent,
    training_agent,
)


class ProjectPhase(Enum):
    """ERP project phases. COMPLETED is a terminal state, not part of the
    six-phase work sequence - see PHASES in src/memory/session_manager.py."""
    REQUIREMENTS_GATHERING = "requirements_gathering"
    PROCESS_MAPPING = "process_mapping"
    SOLUTION_DESIGN = "solution_design"
    QA_TESTING = "qa_testing"
    UAT_TESTING = "uat_testing"
    TRAINING = "training"
    COMPLETED = "completed"


# Phases whose failure means the pipeline cannot meaningfully continue.
# Requirements is the ground truth for everything downstream; solution
# design is the ground truth for QA, UAT, and training. Failing on
# either one and continuing would produce a chain of downstream phases
# running on empty inputs.
_CRITICAL_PHASES = frozenset({
    ProjectPhase.REQUIREMENTS_GATHERING.value,
    ProjectPhase.SOLUTION_DESIGN.value,
})

# Which earlier phases each phase consumes. Single source of truth for
# both _select_phase_context's inputs and the pipeline's precondition
# checks. Kept as a module constant so the two consumers can't drift.
_PHASE_PREREQUISITES: Dict[str, List[str]] = {
    ProjectPhase.REQUIREMENTS_GATHERING.value: [],
    ProjectPhase.PROCESS_MAPPING.value: [ProjectPhase.REQUIREMENTS_GATHERING.value],
    ProjectPhase.SOLUTION_DESIGN.value: [
        ProjectPhase.REQUIREMENTS_GATHERING.value,
        ProjectPhase.PROCESS_MAPPING.value,
    ],
    ProjectPhase.QA_TESTING.value: [ProjectPhase.SOLUTION_DESIGN.value],
    ProjectPhase.UAT_TESTING.value: [ProjectPhase.PROCESS_MAPPING.value],
    ProjectPhase.TRAINING.value: [ProjectPhase.SOLUTION_DESIGN.value],
}


def _select_phase_context(
    session,
    phase: str,
    current_request: Optional[str] = None,
    process_name: Optional[str] = None,
    current_state: Optional[str] = None,
    user_roles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Select the minimum session context required by one workflow phase.

    The set of required upstream phases is read from _PHASE_PREREQUISITES
    (single source of truth) rather than a locally-redeclared dict, so a
    change to the dependency graph can't leave one consumer out of date.
    """
    context: Dict[str, Any] = {
        'project': {
            'project_name': session.project_name,
            'module': session.module,
            'erp_system': session.erp_system,
        },
        'request': current_request if phase == ProjectPhase.REQUIREMENTS_GATHERING.value else None,
        'phase_outputs': {},
        'phase_inputs': {},
    }

    if phase == ProjectPhase.PROCESS_MAPPING.value:
        context['phase_inputs'] = {
            'process_name': process_name,
            'current_state': current_state,
        }
    elif phase == ProjectPhase.UAT_TESTING.value:
        context['phase_inputs'] = {'user_roles': user_roles}
    elif phase == ProjectPhase.TRAINING.value:
        context['phase_inputs'] = {
            'process_name': process_name,
            'user_roles': user_roles,
        }

    required_outputs = _PHASE_PREREQUISITES.get(phase, [])
    context['phase_outputs'] = {
        upstream: agent_memory.get_phase_output(session.session_id, upstream)
        for upstream in required_outputs
    }
    return context


class ERPOrchestratorAgent:
    """
    Orchestrator agent that manages the complete ERP consulting workflow.
    """

    def __init__(self):
        self.logger = AgentLogger("OrchestratorAgent")

        # Singleton model instance (unused directly by the orchestrator,
        # but retained because CLI/API code inspects it for provider
        # configuration).
        self.model = get_llm()

        self.phase_workflow = {
            ProjectPhase.REQUIREMENTS_GATHERING: {
                'agent': requirements_agent,
                'method': 'gather_requirements',
                'next_phase': ProjectPhase.PROCESS_MAPPING,
                'description': 'Gather and document requirements',
            },
            ProjectPhase.PROCESS_MAPPING: {
                'agent': process_mapping_agent,
                'method': 'map_process',
                'next_phase': ProjectPhase.SOLUTION_DESIGN,
                'description': 'Create business process maps',
            },
            ProjectPhase.SOLUTION_DESIGN: {
                'agent': solution_design_agent,
                'method': 'design_solution',
                'next_phase': ProjectPhase.QA_TESTING,
                'description': 'Design ERP solution',
            },
            ProjectPhase.QA_TESTING: {
                'agent': qa_testing_agent,
                'method': 'generate_test_cases',
                'next_phase': ProjectPhase.UAT_TESTING,
                'description': 'Generate QA test cases',
            },
            ProjectPhase.UAT_TESTING: {
                'agent': uat_testing_agent,
                'method': 'generate_uat_scenarios',
                'next_phase': ProjectPhase.TRAINING,
                'description': 'Create UAT scenarios',
            },
            ProjectPhase.TRAINING: {
                'agent': training_agent,
                'method': 'create_training_materials',
                'next_phase': ProjectPhase.COMPLETED,
                'description': 'Generate training materials',
            },
        }

        self.logger.info("Orchestrator Agent initialized")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _advance_to_phase(self, session_id: str, phase: str) -> bool:
        """Advance the session's current_phase to `phase`.

        Handles the terminal 'completed' state, which is not part of the
        six-entry PHASES sequence and would be rejected by
        AgentMemory.advance_phase. For 'completed', goes through the
        session service directly (which records the previous phase in
        completed_phases and sets current_phase to the terminal value).

        Returns True if the transition succeeded, False otherwise.
        """
        if phase == ProjectPhase.COMPLETED.value:
            try:
                agent_memory.session_service.advance_phase(session_id, phase)
                return True
            except Exception as e:  # noqa: BLE001
                self.logger.warning(
                    f"Failed to advance session to terminal 'completed' state: {e}",
                    session_id=session_id,
                )
                return False
        return bool(agent_memory.advance_phase(session_id, phase))

    def _check_prerequisites(self, session_id: str, phase: str) -> Optional[str]:
        """Return an error string if the required upstream phase outputs
        for `phase` are missing, or None if the phase is ready to run.

        This is a fast-fail guard so a phase that would run against empty
        inputs returns a clear error instead of an agent-specific
        "requirements not found" message."""
        for upstream in _PHASE_PREREQUISITES.get(phase, []):
            if not agent_memory.get_phase_output(session_id, upstream):
                return (
                    f"Cannot run '{phase}': required upstream phase "
                    f"'{upstream}' has no output yet. Run that phase first."
                )
        return None

    def _collect_phase_diagnostics(
        self, phase_name: str, result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Extract the enriched keys every agent now returns so the
        workflow summary can aggregate them. Preserves the shape of the
        underlying result via the individual fields (not the whole dict)
        - the raw result is still available to callers via workflow_results."""
        validation = result.get('validation')
        return {
            'phase': phase_name,
            'success': bool(result.get('success')),
            'error': result.get('error'),
            'document_path': result.get('document_path'),
            'duration': result.get('duration'),
            'warnings': list(result.get('warnings') or []),
            'open_questions': list(result.get('open_questions') or []),
            'assumptions': list(result.get('assumptions') or []),
            'degraded': bool(result.get('degraded')),
            'repaired': bool(result.get('repaired')),
            'validation_valid': (
                bool(validation.get('is_valid'))
                if isinstance(validation, dict) else None
            ),
        }

    def _call_agent_safely(self, phase_name: str, agent_fn: Callable[..., Any], **kwargs) -> Dict[str, Any]:
        """Runs one agent's phase method with a hard time ceiling and turns
        any exception into a structured failure result instead of letting
        it propagate. Also records execution metadata for every phase.

        The timeout bounds the *whole* phase call (tool use plus however
        many LLM calls the agent makes). Several LLM calls with retries
        and provider fallback can happen inside one phase; all must fit
        inside this outer ceiling. See src/utils/resilience.py for the
        timeout semantics.

        Non-dict results from agents are normalized into a structured
        failure - previously they would crash the caller when it did
        result['success']. This is defensive against a future agent that
        forgets to return a dict, or a mocked agent in a test."""
        start_time = time.time()
        result: Any = None
        try:
            result = run_with_timeout(
                agent_fn, timeout=settings.timeout_seconds, **kwargs,
            )
        except OperationTimeoutError:
            duration = time.time() - start_time
            self.logger.error(
                f"{phase_name} phase timed out after {settings.timeout_seconds}s"
            )
            metrics_collector.record_task(phase_name, False, duration)
            return {
                'success': False,
                'error': (
                    f"This step took longer than expected "
                    f"({settings.timeout_seconds}s) and was stopped. "
                    f"Please try again."
                ),
                'warnings': [],
                'duration': duration,
            }
        except Exception as e:  # noqa: BLE001 - boundary; orchestration must not crash
            duration = time.time() - start_time
            self.logger.log_agent_error(phase_name, e)
            metrics_collector.record_task(phase_name, False, duration)
            return {
                'success': False,
                'error': (
                    f"An unexpected error occurred during "
                    f"{phase_name.replace('_', ' ')}: {e}"
                ),
                'warnings': [],
                'duration': duration,
            }

        duration = time.time() - start_time

        if not isinstance(result, dict):
            # An agent returned None or a non-dict. Normalize rather than
            # crash. This is the same failure class as an agent that
            # raises - the pipeline should see a structured failure.
            self.logger.error(
                f"{phase_name} returned non-dict result of type "
                f"{type(result).__name__}; normalizing to a failure result."
            )
            metrics_collector.record_task(phase_name, False, duration)
            return {
                'success': False,
                'error': (
                    f"{phase_name} returned an unexpected result type "
                    f"({type(result).__name__}); treating as failure."
                ),
                'warnings': [],
                'duration': duration,
            }

        if 'duration' not in result:
            result['duration'] = duration
        metrics_collector.record_task(
            phase_name, bool(result.get('success')), duration,
        )
        return result

    # ------------------------------------------------------------------ #
    # Project lifecycle
    # ------------------------------------------------------------------ #
    def start_project(
        self,
        project_name: str,
        module: str,
        erp_system: str = "SAP S/4HANA",
        initial_input: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Start a new ERP consulting project.

        The returned `current_phase` reflects the session's actual phase
        after any auto-run requirements work, not a hardcoded
        'requirements_gathering' - previously the value was wrong
        whenever initial_input was supplied and requirements succeeded.
        """
        start_time = time.time()

        self.logger.log_agent_start(
            "start_project",
            {
                'project': project_name,
                'module': module,
                'erp_system': erp_system,
            },
        )

        try:
            session_id = agent_memory.create_project(
                project_name=project_name,
                module=module,
                erp_system=erp_system,
                user_id=user_id,
            )

            self.logger.info(
                "Project created",
                session_id=session_id,
                project=project_name,
            )

            result_extra: Dict[str, Any] = {}
            if initial_input:
                with self.logger.bound(session_id=session_id, phase="requirements_gathering"):
                    req_result = self.execute_requirements_phase(
                        session_id=session_id,
                        stakeholder_input=initial_input,
                    )
                result_extra['requirements_result'] = req_result

            # Read the actual current phase from the session (which will
            # have been advanced by the requirements run if it succeeded).
            session = agent_memory.session_service.get_session(session_id)
            current_phase = (
                getattr(session, 'current_phase', None)
                or ProjectPhase.REQUIREMENTS_GATHERING.value
            )

            duration = time.time() - start_time
            metrics_collector.record_task("OrchestratorAgent", True, duration)

            return {
                'success': True,
                'session_id': session_id,
                'project_name': project_name,
                'module': module,
                'current_phase': current_phase,
                'duration': duration,
                **result_extra,
            }

        except Exception as e:  # noqa: BLE001
            duration = time.time() - start_time
            self.logger.log_agent_error("start_project", e)
            metrics_collector.record_task("OrchestratorAgent", False, duration)
            return {
                'success': False,
                'error': str(e),
                'duration': duration,
            }

    # ------------------------------------------------------------------ #
    # Phases
    # ------------------------------------------------------------------ #
    def execute_requirements_phase(
        self, session_id: str, stakeholder_input: str,
    ) -> Dict[str, Any]:
        """Execute the requirements gathering phase."""
        self.logger.info("Executing requirements phase", session_id=session_id)

        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found', 'warnings': []}

        context = _select_phase_context(
            session, ProjectPhase.REQUIREMENTS_GATHERING.value,
            current_request=stakeholder_input,
        )
        project = context['project']

        with self.logger.bound(session_id=session_id, phase="requirements_gathering"):
            result = self._call_agent_safely(
                'requirements_gathering',
                requirements_agent.gather_requirements,
                session_id=session_id,
                project_name=project['project_name'],
                module=project['module'],
                stakeholder_input=context['request'],
                erp_system=project['erp_system'],
            )

        if result.get('success'):
            # Ensure phase output is available even if the agent wrote it
            # through a path the orchestrator can't see (e.g. in tests).
            phase_output = agent_memory.get_phase_output(session_id, 'requirements_gathering')
            if not phase_output:
                structured = (
                    result.get('requirements')
                    or result.get('structured_requirements')
                    or {}
                )
                agent_memory.save_phase_output(
                    session_id,
                    'requirements_gathering',
                    {
                        'structured_requirements': structured,
                        'document_path': result.get('document_path'),
                        'raw_text': result.get('raw_text', ''),
                        'validation': result.get('validation'),
                        'warnings': result.get('warnings') or [],
                        'degraded': result.get('degraded', False),
                    },
                )

            self._advance_to_phase(session_id, ProjectPhase.PROCESS_MAPPING.value)
            self.logger.info("Requirements phase completed", session_id=session_id)

        return result

    def execute_process_mapping_phase(
        self,
        session_id: str,
        process_name: Optional[str] = None,
        current_state: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute the process mapping phase."""
        self.logger.info("Executing process mapping phase", session_id=session_id)

        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found', 'warnings': []}

        pre_err = self._check_prerequisites(
            session_id, ProjectPhase.PROCESS_MAPPING.value,
        )
        if pre_err:
            return {'success': False, 'error': pre_err, 'warnings': []}

        context = _select_phase_context(
            session, ProjectPhase.PROCESS_MAPPING.value,
            process_name=process_name,
            current_state=current_state,
        )
        project = context['project']
        requirements_output = context['phase_outputs']['requirements_gathering']
        requirements = (requirements_output or {}).get('structured_requirements', {}) or {}

        selected_process_name = (
            context['phase_inputs']['process_name']
            or f"{project['module']} Standard Process"
        )

        with self.logger.bound(
            session_id=session_id, phase="process_mapping",
            process_name=selected_process_name,
        ):
            result = self._call_agent_safely(
                'process_mapping',
                process_mapping_agent.map_process,
                session_id=session_id,
                process_name=selected_process_name,
                requirements=requirements,
                current_state=context['phase_inputs']['current_state'],
                module=project['module'],
                erp_system=project['erp_system'],
            )

        if result.get('success'):
            self._advance_to_phase(session_id, ProjectPhase.SOLUTION_DESIGN.value)
            self.logger.info("Process mapping phase completed", session_id=session_id)

        return result

    def execute_solution_design_phase(self, session_id: str) -> Dict[str, Any]:
        """Execute the solution design phase."""
        self.logger.info("Executing solution design phase", session_id=session_id)

        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found', 'warnings': []}

        pre_err = self._check_prerequisites(
            session_id, ProjectPhase.SOLUTION_DESIGN.value,
        )
        if pre_err:
            return {'success': False, 'error': pre_err, 'warnings': []}

        context = _select_phase_context(session, ProjectPhase.SOLUTION_DESIGN.value)
        project = context['project']
        requirements_output = context['phase_outputs']['requirements_gathering']

        # Copy the structured requirements so adding the module hint doesn't
        # mutate the persisted phase output. Previously this modified the
        # stored dict in place.
        requirements = dict(
            (requirements_output or {}).get('structured_requirements', {}) or {}
        )
        requirements['module'] = session.module

        # Process mapping output is {process_name: {...}} - pass it through
        # as-is; the design agent handles both shapes.
        process_maps = context['phase_outputs'].get('process_mapping') or {}

        with self.logger.bound(session_id=session_id, phase="solution_design"):
            result = self._call_agent_safely(
                'solution_design',
                solution_design_agent.design_solution,
                session_id=session_id,
                requirements=requirements,
                process_maps=process_maps,
                erp_system=project['erp_system'],
            )

        if result.get('success'):
            self._advance_to_phase(session_id, ProjectPhase.QA_TESTING.value)
            self.logger.info("Solution design phase completed", session_id=session_id)

        return result

    def execute_qa_testing_phase(
        self, session_id: str, scope: str = "comprehensive",
    ) -> Dict[str, Any]:
        """Execute the QA testing phase."""
        self.logger.info("Executing QA testing phase", session_id=session_id)

        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found', 'warnings': []}

        pre_err = self._check_prerequisites(
            session_id, ProjectPhase.QA_TESTING.value,
        )
        if pre_err:
            return {'success': False, 'error': pre_err, 'warnings': []}

        context = _select_phase_context(session, ProjectPhase.QA_TESTING.value)
        project = context['project']
        design_output = context['phase_outputs']['solution_design']
        solution_design = (design_output or {}).get('structured_design', {}) or {}

        with self.logger.bound(session_id=session_id, phase="qa_testing"):
            result = self._call_agent_safely(
                'qa_testing',
                qa_testing_agent.generate_test_cases,
                session_id=session_id,
                solution_design=solution_design,
                module=project['module'],
                scope=scope,
            )

        if result.get('success'):
            self._advance_to_phase(session_id, ProjectPhase.UAT_TESTING.value)
            self.logger.info("QA testing phase completed", session_id=session_id)

        return result

    def execute_uat_testing_phase(
        self, session_id: str, user_roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Execute the UAT testing phase."""
        self.logger.info("Executing UAT testing phase", session_id=session_id)

        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found', 'warnings': []}

        pre_err = self._check_prerequisites(
            session_id, ProjectPhase.UAT_TESTING.value,
        )
        if pre_err:
            return {'success': False, 'error': pre_err, 'warnings': []}

        context = _select_phase_context(
            session, ProjectPhase.UAT_TESTING.value,
            user_roles=user_roles,
        )
        process_maps = context['phase_outputs'].get('process_mapping') or {}

        resolved_roles = context['phase_inputs'].get('user_roles') or [
            "Business User", "Power User", "Administrator",
        ]

        with self.logger.bound(session_id=session_id, phase="uat_testing"):
            result = self._call_agent_safely(
                'uat_testing',
                uat_testing_agent.generate_uat_scenarios,
                session_id=session_id,
                business_processes=process_maps,
                user_roles=resolved_roles,
            )

        if result.get('success'):
            self._advance_to_phase(session_id, ProjectPhase.TRAINING.value)
            self.logger.info("UAT testing phase completed", session_id=session_id)

        return result

    def execute_training_phase(
        self,
        session_id: str,
        process_name: Optional[str] = None,
        user_roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Execute the training and documentation phase."""
        self.logger.info("Executing training phase", session_id=session_id)

        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'success': False, 'error': 'Session not found', 'warnings': []}

        pre_err = self._check_prerequisites(
            session_id, ProjectPhase.TRAINING.value,
        )
        if pre_err:
            return {'success': False, 'error': pre_err, 'warnings': []}

        context = _select_phase_context(
            session, ProjectPhase.TRAINING.value,
            process_name=process_name,
            user_roles=user_roles,
        )
        project = context['project']
        design_output = context['phase_outputs']['solution_design']
        solution_design = (design_output or {}).get('structured_design', {}) or {}

        resolved_process_name = (
            context['phase_inputs'].get('process_name')
            or f"{project['module']} Business Process"
        )
        resolved_roles = context['phase_inputs'].get('user_roles') or [
            "End User", "Process Owner", "System Administrator",
        ]

        with self.logger.bound(
            session_id=session_id, phase="training",
            process_name=resolved_process_name,
        ):
            result = self._call_agent_safely(
                'training',
                training_agent.create_training_materials,
                session_id=session_id,
                process_name=resolved_process_name,
                user_roles=resolved_roles,
                solution_design=solution_design,
            )

        if result.get('success'):
            # Terminal transition - handled by _advance_to_phase because
            # 'completed' is outside the PHASES sequence.
            self._advance_to_phase(session_id, ProjectPhase.COMPLETED.value)
            self.logger.info(
                "Training phase completed - Project finished!", session_id=session_id,
            )
            agent_memory.learn_from_project(session_id)

        return result

    # ------------------------------------------------------------------ #
    # Full workflow
    # ------------------------------------------------------------------ #
    def execute_full_workflow(
        self,
        project_name: str,
        module: str,
        stakeholder_input: str,
        erp_system: str = "SAP S/4HANA",
        process_name: Optional[str] = None,
        user_roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute the complete ERP consulting workflow from start to finish.

        Phase failures on critical phases (requirements_gathering,
        solution_design) stop the pipeline with a clear error rather than
        continuing into a cascade of downstream "not found" errors.
        Non-critical phase failures are recorded and the pipeline
        continues where the remaining phases can still produce output.
        """
        start_time = time.time()

        self.logger.info(
            "Starting full workflow execution",
            project=project_name,
            module=module,
        )

        workflow_results: Dict[str, Any] = {
            'project_name': project_name,
            'module': module,
            'phases': {},
        }
        diagnostics: List[Dict[str, Any]] = []

        try:
            # 1. Start project (without auto-running requirements here).
            self.logger.info("Phase 1/6: Requirements Gathering")
            project_result = self.start_project(
                project_name=project_name,
                module=module,
                erp_system=erp_system,
                initial_input=None,
            )

            if not project_result.get('success'):
                return {
                    'success': False,
                    'error': project_result.get('error', 'Project creation failed'),
                    'workflow_results': workflow_results,
                    'stopped_at': 'start_project',
                    'total_duration': time.time() - start_time,
                }

            session_id = project_result['session_id']
            workflow_results['session_id'] = session_id

            # 1a. Requirements gathering.
            req_result = self.execute_requirements_phase(
                session_id=session_id,
                stakeholder_input=stakeholder_input,
            )
            workflow_results['phases']['requirements'] = req_result
            diagnostics.append(self._collect_phase_diagnostics('requirements_gathering', req_result))

            if not req_result.get('success'):
                # Critical: everything downstream reads requirements.
                return {
                    'success': False,
                    'session_id': session_id,
                    'error': (
                        "Requirements gathering failed: "
                        f"{req_result.get('error', 'unknown error')}. "
                        "Cannot continue - all later phases depend on requirements."
                    ),
                    'stopped_at': 'requirements_gathering',
                    'workflow_results': workflow_results,
                    'diagnostics': diagnostics,
                    'total_duration': time.time() - start_time,
                }

            # 2. Process mapping (non-critical - design can run without it).
            self.logger.info("Phase 2/6: Process Mapping")
            process_result = self.execute_process_mapping_phase(
                session_id=session_id,
                process_name=process_name,
            )
            workflow_results['phases']['process_mapping'] = process_result
            diagnostics.append(self._collect_phase_diagnostics('process_mapping', process_result))

            if not process_result.get('success'):
                self.logger.warning(
                    "Process mapping failed; solution design will proceed "
                    "with reduced process context"
                )

            # 3. Solution design (critical).
            self.logger.info("Phase 3/6: Solution Design")
            design_result = self.execute_solution_design_phase(session_id=session_id)
            workflow_results['phases']['solution_design'] = design_result
            diagnostics.append(self._collect_phase_diagnostics('solution_design', design_result))

            if not design_result.get('success'):
                return {
                    'success': False,
                    'session_id': session_id,
                    'error': (
                        "Solution design failed: "
                        f"{design_result.get('error', 'unknown error')}. "
                        "Cannot continue - QA, UAT, and training all depend "
                        "on the solution design."
                    ),
                    'stopped_at': 'solution_design',
                    'workflow_results': workflow_results,
                    'diagnostics': diagnostics,
                    'total_duration': time.time() - start_time,
                }

            # 4. QA testing (non-critical for later phases).
            self.logger.info("Phase 4/6: QA Testing")
            qa_result = self.execute_qa_testing_phase(session_id=session_id)
            workflow_results['phases']['qa_testing'] = qa_result
            diagnostics.append(self._collect_phase_diagnostics('qa_testing', qa_result))

            # 5. UAT testing (non-critical for later phases).
            self.logger.info("Phase 5/6: UAT Testing")
            uat_result = self.execute_uat_testing_phase(
                session_id=session_id,
                user_roles=user_roles,
            )
            workflow_results['phases']['uat_testing'] = uat_result
            diagnostics.append(self._collect_phase_diagnostics('uat_testing', uat_result))

            # 6. Training (non-critical - project can still finish without it).
            self.logger.info("Phase 6/6: Training & Documentation")
            training_result = self.execute_training_phase(
                session_id=session_id,
                process_name=process_name,
                user_roles=user_roles,
            )
            workflow_results['phases']['training'] = training_result
            diagnostics.append(self._collect_phase_diagnostics('training', training_result))

            duration = time.time() - start_time

            # Aggregate diagnostics across every phase.
            aggregated = self._aggregate_diagnostics(diagnostics)
            workflow_results['diagnostics'] = diagnostics
            workflow_results['aggregated'] = aggregated

            summary = self.generate_project_summary(session_id)

            self.logger.info(
                "Full workflow completed",
                session_id=session_id,
                duration=duration,
                failed_phases=aggregated['failed_phases'],
                total_open_questions=aggregated['open_questions_count'],
            )

            # Success means the pipeline reached completion without a
            # critical failure - individual non-critical phase failures
            # are surfaced in `aggregated` and in `workflow_results` but
            # do not make the overall call fail. Callers that need strict
            # behavior should inspect `aggregated['failed_phases']`.
            return {
                'success': True,
                'session_id': session_id,
                'workflow_results': workflow_results,
                'summary': summary,
                'diagnostics': diagnostics,
                'aggregated': aggregated,
                'total_duration': duration,
                'metrics': metrics_collector.get_summary(),
            }

        except Exception as e:  # noqa: BLE001 - top-level boundary
            duration = time.time() - start_time
            self.logger.log_agent_error("execute_full_workflow", e)
            return {
                'success': False,
                'error': str(e),
                'partial_results': workflow_results,
                'diagnostics': diagnostics,
                'duration': duration,
            }

    # ------------------------------------------------------------------ #
    # Summaries
    # ------------------------------------------------------------------ #
    @staticmethod
    def _aggregate_diagnostics(diagnostics: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate per-phase diagnostic records into a single summary.
        The `open_questions` and `warnings` lists are the caller-facing
        outputs of the epistemic discipline the agents enforce; this is
        where they finally surface above the phase level."""
        failed = [d['phase'] for d in diagnostics if not d['success']]
        degraded = [d['phase'] for d in diagnostics if d.get('degraded')]
        repaired = [d['phase'] for d in diagnostics if d.get('repaired')]

        all_questions: List[Dict[str, Any]] = []
        for d in diagnostics:
            for q in d.get('open_questions') or []:
                all_questions.append({
                    'phase': d['phase'],
                    'question': q,
                })

        all_warnings: List[Dict[str, Any]] = []
        for d in diagnostics:
            for w in d.get('warnings') or []:
                all_warnings.append({
                    'phase': d['phase'],
                    'warning': w,
                })

        return {
            'failed_phases': failed,
            'degraded_phases': degraded,
            'repaired_phases': repaired,
            'open_questions_count': len(all_questions),
            'open_questions': all_questions,
            'warnings_count': len(all_warnings),
            'warnings': all_warnings,
        }

    def generate_project_summary(self, session_id: str) -> Dict[str, Any]:
        """Generate comprehensive project summary."""
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {}

        summary: Dict[str, Any] = {
            'project_info': {
                'name': session.project_name,
                'module': session.module,
                'erp_system': session.erp_system,
                'created_at': session.created_at.isoformat(),
                'completed_at': session.updated_at.isoformat(),
            },
            'phases_completed': list(session.completed_phases),
            'deliverables': {},
            'metrics': {},
        }

        for phase in session.completed_phases:
            phase_output = agent_memory.get_phase_output(session_id, phase)
            if not phase_output:
                continue
            # Phase outputs have varied shapes across phases - tolerate
            # both the dict-with-document_path shape (requirements,
            # solution design, training) and the process-maps shape
            # (mapping, where each process entry carries its own path).
            if isinstance(phase_output, dict):
                doc_path = phase_output.get('document_path')
                if doc_path:
                    summary['deliverables'][phase] = doc_path
                elif phase == 'process_mapping':
                    for process_name, entry in phase_output.items():
                        if isinstance(entry, dict) and entry.get('document_path'):
                            summary['deliverables'][f"process_mapping:{process_name}"] = (
                                entry['document_path']
                            )

        summary['metrics'] = metrics_collector.get_summary()
        return summary

    def get_project_status(self, session_id: str) -> Dict[str, Any]:
        """Get current project status."""
        session = agent_memory.session_service.get_session(session_id)
        if not session:
            return {'error': 'Session not found'}

        completed = list(session.completed_phases or [])
        total = len(PHASES) or 1

        return {
            'session_id': session_id,
            'project_name': session.project_name,
            'module': session.module,
            'current_phase': session.current_phase,
            'completed_phases': completed,
            'progress_percentage': round(len(completed) / total * 100, 1),
            'next_phase': self._get_next_phase(session.current_phase),
            'created_at': session.created_at.isoformat(),
            'last_updated': session.updated_at.isoformat(),
        }

    def _get_next_phase(self, current_phase: str) -> str:
        """Get next phase in workflow."""
        try:
            phase_enum = ProjectPhase(current_phase)
        except ValueError:
            return "unknown"
        # Terminal state has no next phase.
        if phase_enum == ProjectPhase.COMPLETED:
            return ProjectPhase.COMPLETED.value
        workflow_info = self.phase_workflow.get(phase_enum)
        if workflow_info:
            return workflow_info['next_phase'].value
        return "unknown"


# Global orchestrator instance
orchestrator = ERPOrchestratorAgent()