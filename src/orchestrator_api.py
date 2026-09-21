"""
FastAPI wrapper for ERP Orchestrator with hybrid LLM support
(Gemini + Groq + GPT-4 + Claude fallback).

"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid as uuid_lib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import structlog
import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.orchestrator import orchestrator
from src.config.settings import settings
import src.utils.llm as llm_mod
from src.agents import requirements_agent, training_agent
from src.memory import agent_memory
from src.tools.info_retriever import info_retriever
from src.utils.logger import (
    get_logger,
    metrics_collector,
    bind_log_context,
    unbind_log_context,
    log_context,
)
from src.utils.prompts import get_synthesis_prompt
from src.models.chat_intent_schema import ChatIntent, ChatIntentDecision
from src.auth.dependencies import get_current_user, get_db
from src.auth.schemas import (
    SignupRequest, LoginRequest, TokenResponse, UserOut,
    ProfileUpdateRequest, PasswordChangeRequest,
)
from src.auth.security import create_access_token
from src.auth import service as auth_service
from src.db.base import engine as db_engine, SessionLocal
from src.db.models import User, Feedback, SessionRecord, ProjectDocument
from src.utils.model_selection import TaskCategory
from src.storage import object_storage
from src.tools.document_extractor import (
    extract_text as extract_document_text,
    UnsupportedFileType,
    SUPPORTED_EXTENSIONS,
)
from src.tools.document_generator import doc_generator
from src.storage.object_storage import ObjectStorageNotConfigured, ObjectStorageError


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks.

    Startup: create directories and emit a single structured log line
    summarizing effective LLM routing, sanitizer availability, and the
    environment. Without this, the first evidence that a provider tier
    is misconfigured comes from production traffic.

    Shutdown: release the shared thread pool used by run_with_timeout so
    a graceful redeploy doesn't hang on in-flight calls longer than
    necessary. Calls that are still running are not forcibly killed
    (Python can't), but the process stops accepting new work cleanly."""
    settings.init_directories()

    startup_logger = get_logger(__name__)

    startup_logger.info(
        "Starting ERP Orchestrator API",
        environment=getattr(settings, "environment", "unknown"),
        log_level=settings.log_level,
        log_format=settings.log_format,
    )

    # LLM routing summary - which providers are configured and which
    # models each tier will use.
    try:
        summary = settings.describe_llm_configuration()
        startup_logger.info("LLM routing configured", **summary)
    except Exception as e:  # noqa: BLE001
        startup_logger.warning("Could not summarize LLM configuration", error=str(e))

    # Sanitizer availability - a missing ftfy silently disables mojibake
    # repair; make that visible at boot.
    try:
        from src.utils.text_sanitize import is_ftfy_available
        if not is_ftfy_available():
            startup_logger.warning(
                "ftfy is not installed; Unicode mojibake repair is disabled. "
                "Install ftfy to enable."
            )
    except Exception:  # noqa: BLE001 - sanitizer module missing entirely
        startup_logger.warning("text_sanitize module unavailable")

    # Object storage configuration status - uploads return 503 if unset.
    try:
        if not getattr(settings, "object_storage_configured", False):
            startup_logger.warning(
                "Object storage is not configured; file uploads will return 503."
            )
    except Exception:  # noqa: BLE001
        pass

    yield

    # Shutdown
    try:
        from src.utils.resilience import shutdown_executor
        shutdown_executor(wait=False)
    except Exception as e:  # noqa: BLE001
        startup_logger.warning("Executor shutdown failed", error=str(e))
    startup_logger.info("ERP Orchestrator API shutting down")


app = FastAPI(title="ERP Orchestrator API", lifespan=lifespan)

logger = get_logger(__name__)

_TESTING = "pytest" in sys.modules

# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------
# Auth endpoints are tight everywhere (brute force surface). Chat and
# phase execution are moderately tight per authenticated user because
# each call costs real LLM spend. Everything else gets a generous default
# suitable for SPA page loads (a single page can hit a dozen endpoints).
AUTH_RATE_LIMIT = "10000/minute" if _TESTING else "5/minute"
DEFAULT_RATE_LIMIT = "100000/minute" if _TESTING else "120/minute"
CHAT_RATE_LIMIT = "100000/minute" if _TESTING else "30/minute"
PHASE_RATE_LIMIT = "100000/minute" if _TESTING else "10/minute"
UPLOAD_RATE_LIMIT = "100000/minute" if _TESTING else "15/minute"
REPORT_RATE_LIMIT = "100000/minute" if _TESTING else "10/minute"


def _client_ip_for_rate_limit(request: Request) -> str:
    """Rate-limit key function.

    `get_remote_address` returns `request.client.host`, which behind a
    load balancer is the LB's address - every user ends up sharing one
    bucket. When `settings.trusted_proxy_hops` is greater than zero, we
    trust the X-Forwarded-For chain from the right, taking the
    Nth-from-last entry (N = trusted_proxy_hops), which is the client
    address as seen by the outermost trusted proxy.

    Set trusted_proxy_hops to the number of proxies you control in front
    of the app (typically 1 for a single LB, 2 for CDN + LB). Do NOT set
    it higher than the number of trusted proxies, or a client can spoof
    its own IP via a forged X-Forwarded-For header."""
    hops = int(getattr(settings, "trusted_proxy_hops", 0) or 0)
    if hops > 0:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                idx = max(0, len(parts) - hops)
                return f"ip:{parts[idx]}"
    # Fallback to the direct peer. Prefix by category so a client IP and
    # a session id can never collide in the limiter's key space.
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=_client_ip_for_rate_limit,
    default_limits=[DEFAULT_RATE_LIMIT],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
# Ordering (outermost first):
#   request_id -> body_size -> security_headers -> CORS -> SlowAPI -> app
# Request id outermost so every response - including early 413s and
# CORS preflight - carries it. Body size before security headers so an
# oversized request fails fast without going through the rest of the
# stack. Security headers outside CORS so the response gains them
# regardless of how CORS short-circuits.

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Bind a request_id for log correlation. Uses the log_context
    context manager (bind + unbind of exactly the keys we add) instead
    of clear_contextvars(), which would wipe any outer context bound by
    the ASGI layer or a future tenant middleware."""
    request_id = request.headers.get("X-Request-ID", str(uuid_lib.uuid4()))
    request.state.request_id = request_id

    start = time.time()
    with log_context(request_id=request_id):
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "Request completed",
            path=request.url.path,
            method=request.method,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


@app.middleware("http")
async def body_size_limit_middleware(request: Request, call_next):
    """Reject oversized request bodies before they are read.

    Bounds the declared Content-Length. Chunked-encoded requests without
    a Content-Length header bypass this check; the upload endpoints have
    their own per-upload cap that reads in bounded chunks regardless."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            size = int(content_length)
        except ValueError:
            size = 0
        max_mb = int(getattr(settings, "max_request_body_mb", 25) or 25)
        max_bytes = max_mb * 1024 * 1024
        if size > max_bytes:
            return JSONResponse(
                status_code=413,
                content=_error_envelope(
                    request, 413, f"Request body exceeds the {max_mb}MB limit.",
                ),
            )
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # HSTS is meaningful only when the response is actually served over
    # HTTPS - setting it on plain-HTTP responses is ignored by browsers
    # and mildly misleading in logs. Set it only when the request came in
    # via HTTPS (either directly or via a trusted proxy forwarding the
    # original scheme).
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    is_https = request.url.scheme == "https" or forwarded_proto == "https"
    if is_https:
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )
    return response


def _error_envelope(request: Request, status_code: int, message: str) -> Dict[str, Any]:
    return {
        "error": {
            "code": status_code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        }
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_envelope(request, exc.status_code, str(exc.detail)),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content=_error_envelope(
            request, 500,
            "Internal server error. If this persists, please contact support "
            "with the request ID above.",
        ),
    )


if os.path.isdir("frontend/dist/assets"):
    app.mount(
        "/assets",
        StaticFiles(directory="frontend/dist/assets"),
        name="frontend_assets",
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------
_MAX_MESSAGE_CHARS = 50_000      # enough for a pasted questionnaire
_MAX_NAME_CHARS = 200
_MAX_COMMENT_CHARS = 5_000
_MAX_SESSION_ID_CHARS = 128
_MAX_ROLES = 50
_MAX_ROLE_CHARS = 100


class ProjectStart(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=_MAX_NAME_CHARS)
    module: str = Field(..., min_length=1, max_length=32)
    erp_system: Optional[str] = Field("SAP S/4HANA", max_length=64)
    initial_input: Optional[str] = Field(None, max_length=_MAX_MESSAGE_CHARS)


class ProjectRename(BaseModel):
    project_name: str = Field(..., min_length=1, max_length=_MAX_NAME_CHARS)


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = Field(None, max_length=_MAX_SESSION_ID_CHARS)
    rating: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=_MAX_COMMENT_CHARS)


class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(None, max_length=_MAX_SESSION_ID_CHARS)
    message: str = Field(..., min_length=1, max_length=_MAX_MESSAGE_CHARS)
    agent_hint: Optional[str] = Field(None, max_length=64)
    prefer_web: Optional[bool] = False


class SolutionActualRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=10_000)
    component: Optional[str] = Field(None, max_length=256)
    rationale: Optional[str] = Field(None, max_length=10_000)


class ProcessStepReviseRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = Field(None, max_length=10_000)
    responsible_role: Optional[str] = Field(None, max_length=256)
    step_number: Optional[int] = Field(None, ge=1, le=10_000)


class ReviewActionRequest(BaseModel):
    object_type: str = Field(..., max_length=64)
    object_id: str = Field(..., max_length=_MAX_SESSION_ID_CHARS)
    action: str = Field(..., max_length=32)
    note: Optional[str] = Field(None, max_length=2_000)


class RequirementReviseRequest(BaseModel):
    description: Optional[str] = Field(None, max_length=20_000)
    priority: Optional[str] = Field(None, max_length=32)
    category: Optional[str] = Field(None, max_length=128)
    acceptance_criteria: Optional[str] = Field(None, max_length=10_000)


class TestFailureRequest(BaseModel):
    classification: str = Field(..., max_length=64)
    description: str = Field(..., min_length=1, max_length=10_000)


class BaselineCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    notes: Optional[str] = Field(None, max_length=5_000)
    decision_ids: Optional[List[str]] = Field(None, max_length=2_000)


class PhaseExecuteRequest(BaseModel):
    """Phase-specific parameters. Not all fields apply to every phase;
    unused fields are ignored. The endpoint validates that the required
    fields for the requested phase are present."""
    stakeholder_input: Optional[str] = Field(None, max_length=_MAX_MESSAGE_CHARS)
    process_name: Optional[str] = Field(None, max_length=_MAX_NAME_CHARS)
    current_state: Optional[str] = Field(None, max_length=_MAX_MESSAGE_CHARS)
    user_roles: Optional[List[str]] = Field(None, max_length=_MAX_ROLES)
    scope: Optional[str] = Field("comprehensive", max_length=32)


# ---------------------------------------------------------------------------
# Endpoint helpers
# ---------------------------------------------------------------------------
def extract_text(response: Any) -> str:
    if response is None:
        return "No response from LLM."
    if hasattr(response, "text"):
        return response.text
    if isinstance(response, dict):
        for key in ("text", "output_text", "answer"):
            if key in response:
                return str(response[key])
        return str(response)
    if isinstance(response, str):
        return response
    return str(response)


def _reference_data_fallback(data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Compose a fallback answer from already-retrieved reference data.

    Used when every LLM provider has failed: rather than discarding the
    knowledge-base/web results that info_retriever already returned (and
    returning a generic "trouble summarizing" message), we surface the
    retrieved reference material directly.

    Constraints honored:
      * Does NOT call any LLM.
      * Does NOT fabricate facts - only reuses what retrieval produced.
      * Preserves source attribution when the retrieval response carries
        a `sources` field.
      * Returns None when there is no usable reference content, so the
        caller can fall through to an explicit failure message.

    The shape of `data` matches what src.tools.info_retriever.info_retriever
    returns: a dict that may carry `kb_results`, `web_results`, and
    `sources`. This helper is intentionally defensive about the concrete
    shape of individual entries (str vs. dict vs. other)."""
    if not isinstance(data, dict):
        return None

    def _as_text(item: Any) -> Optional[str]:
        if item is None:
            return None
        if isinstance(item, str):
            stripped = item.strip()
            return stripped or None
        if isinstance(item, dict):
            for key in ("content", "text", "snippet", "answer", "summary", "body"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    title = (
                        item.get("title")
                        or item.get("source")
                        or item.get("url")
                    )
                    if isinstance(title, str) and title.strip():
                        return f"{title.strip()}: {value.strip()}"
                    return value.strip()
            return None
        try:
            return str(item).strip() or None
        except Exception:  # noqa: BLE001
            return None

    def _iter_bucket(bucket: Any) -> List[Any]:
        if bucket is None:
            return []
        if isinstance(bucket, dict):
            return list(bucket.values())
        if isinstance(bucket, (list, tuple)):
            return list(bucket)
        return [bucket]

    parts: List[str] = []
    for key in ("kb_results", "web_results"):
        for entry in _iter_bucket(data.get(key)):
            text = _as_text(entry)
            if text:
                parts.append(text)

    if not parts:
        return None

    source_labels: List[str] = []
    for entry in _iter_bucket(data.get("sources")):
        if isinstance(entry, str) and entry.strip():
            source_labels.append(entry.strip())
        elif isinstance(entry, dict):
            label = (
                entry.get("title")
                or entry.get("url")
                or entry.get("source")
            )
            if isinstance(label, str) and label.strip():
                source_labels.append(label.strip())

    header = (
        "I wasn't able to synthesize a full answer right now, but here is "
        "the reference material I retrieved for your question:"
    )
    body = "\n\n".join(parts)
    if source_labels:
        body = body + "\n\nSources: " + "; ".join(source_labels)
    return header + "\n\n" + body


def _derive_chat_title(message: str) -> str:
    words = message.strip().split()
    if not words:
        return "New chat"
    title = " ".join(words[:6])
    if len(title) > 60:
        title = title[:57].rstrip() + "..."
    return title[0].upper() + title[1:]


def _attachment_headers(filename: str) -> Dict[str, str]:
    """Build a Content-Disposition header that is safe for both ASCII and
    non-ASCII filenames. Includes an RFC 5987 `filename*` form for
    non-ASCII and a sanitized ASCII fallback for legacy clients.
    Previously a filename containing `"` would break the header, and
    non-ASCII names were passed through unencoded."""
    raw = filename or "document"
    # ASCII fallback: strip quotes, replace non-ASCII with '_'.
    ascii_name = "".join(c if 32 <= ord(c) < 127 and c != '"' else "_" for c in raw)
    if not ascii_name:
        ascii_name = "document"
    encoded = quote(raw, safe="")
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'
        ),
    }


async def _read_upload_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in bounded chunks, rejecting as soon as the running
    total exceeds max_bytes. Previously the entire body was read into
    memory before the size check ran, so a 200MB upload was fully
    received before being rejected."""
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File exceeds the {max_bytes // (1024 * 1024)}MB limit."
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


PHASE_ORDER = [
    'requirements_gathering', 'process_mapping', 'solution_design',
    'qa_testing', 'uat_testing', 'training', 'completed',
]

PHASE_LABELS = {
    'process_mapping': 'Map the business process',
    'solution_design': 'Design the ERP solution',
    'qa_testing': 'Generate QA test cases',
    'uat_testing': 'Prepare UAT scenarios',
    'training': 'Create training material',
}

# Single source of truth for phase -> orchestrator method. Referenced by
# both the REST endpoint and the chat dispatch, so they can't drift.
_PHASE_EXECUTORS: Dict[str, Callable[..., Dict[str, Any]]] = {
    'requirements': orchestrator.execute_requirements_phase,
    'process_mapping': orchestrator.execute_process_mapping_phase,
    'solution_design': orchestrator.execute_solution_design_phase,
    'qa_testing': orchestrator.execute_qa_testing_phase,
    'uat_testing': orchestrator.execute_uat_testing_phase,
    'training': orchestrator.execute_training_phase,
}

# Which phases require which parameters - checked before dispatch so a
# missing input returns a specific 422 rather than a generic failure.
_PHASE_REQUIRED_PARAMS: Dict[str, List[str]] = {
    'requirements': ['stakeholder_input'],
}


def _map_phase_error_to_status(error_text: str) -> int:
    """Map an orchestrator failure to an HTTP status.

    Uses string matching on the orchestrator's error messages as a
    stopgap; a follow-up pass should have the orchestrator return a
    structured `error_code` on failure. Until then, this at least
    distinguishes "you called this wrong" from "the system is broken." """
    lower = (error_text or "").lower()
    if "took longer than expected" in lower or "timed out" in lower:
        return 504
    if (
        "required upstream" in lower
        or "run that phase first" in lower
        or "not found" in lower
    ):
        return 409
    if "unknown phase" in lower or "is not one of" in lower:
        return 400
    return 500


# ---------------------------------------------------------------------------
# Requirements intake - plain per-session state
# ---------------------------------------------------------------------------
INTAKE_QUESTIONS = [
    {"key": "industry", "text": "What industry is the client in?"},
    {"key": "company_size", "text": "Roughly how large is the organization (employee count or revenue range)?"},
    {"key": "primary_goal", "text": "What's the primary business problem or goal driving this ERP initiative?"},
    {"key": "scope_areas", "text": "Which business areas are in scope for this phase (e.g. Finance, Supply Chain, HR)?"},
]

MIN_STAKEHOLDER_ANSWER_LENGTH = 40


def _get_intake_state(session) -> dict:
    metadata = session.metadata or {}
    return dict(metadata.get("intake") or {"stage": "not_started", "answers": {}})


def _save_intake_state(session_id: str, intake_state: dict) -> None:
    session = agent_memory.session_service.get_session(session_id)
    if not session:
        return
    metadata = dict(session.metadata or {})
    metadata["intake"] = intake_state
    agent_memory.session_service.update_session(session_id, {"metadata": metadata})


def _next_action_for(session) -> Optional[Dict[str, Any]]:
    if session is None or session.is_casual:
        return None

    has_requirements = bool(
        agent_memory.get_phase_output(session.session_id, 'requirements_gathering')
    )

    if session.current_phase == 'requirements_gathering' and not has_requirements:
        if _intake_is_pending(session.session_id):
            return None
        if not _intake_is_complete(session.session_id):
            return {'label': 'Start requirements intake', 'agent_hint': 'start_intake'}
        return None

    if session.current_phase in PHASE_LABELS:
        return {
            'label': PHASE_LABELS[session.current_phase],
            'agent_hint': session.current_phase,
        }

    return None


def _intake_is_pending(session_id: str) -> bool:
    session = agent_memory.session_service.get_session(session_id)
    if not session:
        return False
    state = _get_intake_state(session)
    return state.get("stage") in ("collecting", "awaiting_stakeholder_answers")


def _intake_is_complete(session_id: str) -> bool:
    session = agent_memory.session_service.get_session(session_id)
    if not session:
        return False
    state = _get_intake_state(session)
    return state.get("stage") == "complete"


def _run_intake_step(session_id: str, user_input: Optional[str], resume: bool) -> Dict[str, Any]:
    session = agent_memory.session_service.get_session(session_id)
    if not session:
        return {'success': False, 'error': 'Session not found.'}

    if not resume:
        state = {"stage": "collecting", "answers": {}}
        _save_intake_state(session_id, state)
        return {'success': True, 'answer': INTAKE_QUESTIONS[0]['text']}

    state = _get_intake_state(session)
    stage = state.get("stage")

    if stage == "collecting":
        answers = dict(state.get("answers") or {})
        pending_question = next(
            (q for q in INTAKE_QUESTIONS if q["key"] not in answers), None,
        )
        if pending_question is None:
            return {
                'success': False,
                'error': 'Intake questions already answered; unexpected state.',
            }

        answers[pending_question["key"]] = user_input
        state["answers"] = answers

        next_question = next(
            (q for q in INTAKE_QUESTIONS if q["key"] not in answers), None,
        )
        if next_question is not None:
            _save_intake_state(session_id, state)
            return {'success': True, 'answer': next_question['text']}

        result = requirements_agent.generate_requirements_template(
            project_name=session.project_name,
            module=session.module,
            erp_system=session.erp_system,
            context=answers,
            session_id=session_id,
        )
        if not result.get("success"):
            return {
                'success': False,
                'error': result.get('error', 'Failed to generate requirements template'),
            }

        state["stage"] = "awaiting_stakeholder_answers"
        _save_intake_state(session_id, state)
        return {
            'success': True,
            'answer': (
                "Thanks - I've put together a requirements questionnaire based "
                "on your answers. Download it, work through it with your "
                "stakeholders, then come back and paste their answers in so I "
                "can turn them into a formal requirements document."
            ),
            'document_path': result['document_path'],
        }

    if stage == "awaiting_stakeholder_answers":
        if not user_input or len(user_input.strip()) < MIN_STAKEHOLDER_ANSWER_LENGTH:
            return {
                'success': True,
                'answer': (
                    "I don't see enough stakeholder input to work with yet. "
                    "Please paste the completed questionnaire answers as a "
                    "message, and I'll take it from there."
                ),
            }

        result = requirements_agent.gather_requirements(
            session_id=session_id,
            project_name=session.project_name,
            module=session.module,
            stakeholder_input=user_input,
            erp_system=session.erp_system,
        )
        if not result.get("success"):
            return {
                'success': False,
                'error': result.get('error', 'Failed to structure requirements'),
            }

        agent_memory.advance_phase(session_id, "process_mapping")
        state["stage"] = "complete"
        _save_intake_state(session_id, state)
        summary = (
            result.get('requirements', {}).get('executive_summary')
            or 'Requirements captured.'
        )
        return {
            'success': True,
            'answer': f"Requirements structured and saved: {summary}",
            'document_path': result.get('document_path'),
        }

    return {
        'success': False,
        'error': f"Intake already complete or in an unexpected stage: {stage}",
    }


def _get_owned_session(session_id: str, current_user: User):
    """Return the session if it exists and belongs to current_user.
    Binds session_id and user_id onto the log context for the rest of
    the request - every subsequent log line is greppable by either."""
    session = agent_memory.session_service.get_session(session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    bind_log_context(session_id=session_id, user_id=current_user.id)
    return session


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.post("/api/auth/signup", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
def signup(request: Request, req: SignupRequest, db: Session = Depends(get_db)):
    try:
        user = auth_service.create_user(db, req.email, req.password)
    except auth_service.EmailAlreadyRegistered:
        raise HTTPException(status_code=409, detail="Email already registered")

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.access_token_expire_minutes,
    )


@app.post("/api/auth/login", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    user = auth_service.authenticate_user(db, req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.access_token_expire_minutes,
    )


@app.get("/api/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@app.get("/api/auth/settings", response_model=UserOut)
def account_settings(current_user: User = Depends(get_current_user)):
    return current_user


@app.patch("/api/auth/settings", response_model=UserOut)
def update_account_settings(
    req: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return auth_service.update_profile(
        db, current_user, req.name, current_user.profile_picture_url,
    )


@app.post("/api/auth/profile-picture", response_model=UserOut)
def upload_profile_picture(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
        raise HTTPException(status_code=415, detail="Profile picture must be a supported image")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        raise HTTPException(status_code=415, detail="Profile picture must be a supported image")

    # Bounded read: profile pictures are small, cap at 5MB.
    content = file.file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Profile picture exceeds the 5MB limit")

    picture_dir = Path(settings.output_dir) / "profile_pictures"
    picture_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid_lib.uuid4().hex}{suffix}"
    picture_path = picture_dir / filename
    with picture_path.open("wb") as destination:
        destination.write(content)

    return auth_service.update_profile(
        db, current_user, current_user.name, f"/api/auth/profile-picture/{filename}",
    )


@app.get("/api/auth/profile-picture/{filename}")
def get_profile_picture(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Profile picture not found")
    picture_path = Path(settings.output_dir) / "profile_pictures" / filename
    if not picture_path.is_file():
        raise HTTPException(status_code=404, detail="Profile picture not found")
    return FileResponse(path=str(picture_path))


@app.post("/api/auth/password")
def change_account_password(
    req: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not auth_service.change_password(
        db, current_user, req.current_password, req.new_password,
    ):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    return {"success": True}


@app.delete("/api/auth/account")
def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete the account and everything it owns.

    Sessions are removed via session_service.delete_session so the full
    cascade runs: object-storage cleanup for uploaded documents,
    ProjectMemory removal, and in-memory cache invalidation. Previously
    this bulk-deleted SessionRecord rows, which bypassed storage cleanup
    and left orphaned files behind. Profile pictures are removed
    explicitly - they are not referenced by any DB row."""
    owned_session_ids = agent_memory.session_service.list_sessions_for_user(
        current_user.id, include_archived=True,
    )
    for session_id in owned_session_ids:
        try:
            agent_memory.session_service.delete_session(session_id)
        except Exception as e:  # noqa: BLE001 - continue cleaning up the rest
            logger.warning(
                "Failed to fully clean up session during account deletion",
                session_id=session_id, error=str(e),
            )

    # Profile picture on disk is not tracked in the DB.
    if current_user.profile_picture_url:
        pic_filename = current_user.profile_picture_url.rsplit("/", 1)[-1]
        if pic_filename:
            pic_path = Path(settings.output_dir) / "profile_pictures" / pic_filename
            try:
                pic_path.unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Failed to delete profile picture during account deletion",
                    error=str(e),
                )

    # Any Feedback rows still present (the cascade may already have taken
    # care of them) plus the user row itself.
    db.query(Feedback).filter(Feedback.user_id == current_user.id).delete(
        synchronize_session=False,
    )
    db.delete(current_user)
    db.commit()

    return {"deleted": True}


# ---------------------------------------------------------------------------
# Health & readiness
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Liveness probe. Deliberately lightweight - does not touch the DB
    or the LLM wrapper's initialization path. Reports the configured
    provider tiers so an operator can see at a glance which fallbacks
    are active."""
    serpapi_installed = True
    try:
        import serpapi  # type: ignore
    except ImportError:
        serpapi_installed = False

    providers: List[str] = []
    try:
        llm_instance = llm_mod.get_llm()
        if getattr(llm_instance, "use_gemini", False):
            providers.append("gemini")
        if getattr(llm_instance, "groq_client", None):
            providers.append("groq")
        if getattr(llm_instance, "openai_client", None):
            providers.append("openai")
        if getattr(llm_instance, "anthropic_client", None):
            providers.append("anthropic")
    except Exception as e:  # noqa: BLE001 - health must not fail
        logger.warning("Could not inspect LLM providers in /health", error=str(e))

    return {
        "status": "ok",
        "llm_providers_configured": providers,
        "llm_mode": "+".join(providers) if providers else "none",
        "serpapi_installed": serpapi_installed,
        "gemini_key_present": bool(settings.gemini_api_key),
        "serpapi_key_present": bool(settings.serpapi_api_key),
    }


@app.get("/ready")
def ready():
    """Readiness probe. Verifies DB reachability; returns 503 if the DB
    is unreachable so a load balancer removes the instance from rotation."""
    try:
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001
        logger.error("Readiness check failed", error=str(e))
        raise HTTPException(status_code=503, detail="Database is not reachable")
    return {"status": "ready"}


@app.get("/metrics")
def metrics(current_user: User = Depends(get_current_user)):
    """Process-wide metrics summary - cumulative counters and per-agent
    breakdown. Authenticated because the per-agent breakdown reveals
    operational scale. Intended for the SPA's admin view or for grepping
    by an on-call engineer; a real Prometheus exporter is a follow-up."""
    return metrics_collector.get_summary()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
@app.get("/api/projects")
def list_projects(
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
):
    session_ids = agent_memory.session_service.list_sessions_for_user(
        current_user.id, include_archived=include_archived,
    )
    summaries = [
        agent_memory.session_service.get_session_summary(sid) for sid in session_ids
    ]
    return {"projects": [s for s in summaries if s]}


@app.post("/api/projects/start")
def start_project(
    req: ProjectStart,
    current_user: User = Depends(get_current_user),
):
    result = orchestrator.start_project(
        project_name=req.project_name,
        module=req.module,
        erp_system=req.erp_system,
        initial_input=req.initial_input,
        user_id=current_user.id,
    )
    if not result.get('success'):
        raise HTTPException(
            status_code=500, detail=result.get('error', 'Unknown error'),
        )
    session = agent_memory.session_service.get_session(result['session_id'])
    result['next_action'] = _next_action_for(session) if session else None
    return result


@app.patch("/api/projects/{session_id}")
def rename_project(
    session_id: str,
    req: ProjectRename,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    session = agent_memory.session_service.rename_session(session_id, req.project_name)
    return {"session_id": session_id, "project_name": session.project_name}


@app.delete("/api/projects/{session_id}")
def archive_project(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    archived = agent_memory.session_service.archive_session(session_id)
    if not archived:
        raise HTTPException(status_code=409, detail="Project is already archived")
    return {"session_id": session_id, "archived": True}


@app.delete("/api/projects/{session_id}/permanent")
def delete_project_permanently(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    deleted = agent_memory.session_service.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "deleted": True}


from src.services import project_intelligence
from src.services import consistency_checker


# ---------------------------------------------------------------------------
# Requirements / issues / review
# ---------------------------------------------------------------------------
@app.get("/api/projects/{session_id}/requirements")
def list_requirements(
    session_id: str,
    include_history: bool = False,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {
        "session_id": session_id,
        "requirements": project_intelligence.get_requirements(
            session_id, include_history=include_history,
        ),
    }


@app.post("/api/projects/{session_id}/review")
def submit_review_action(
    session_id: str,
    req: ReviewActionRequest,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    action_id = project_intelligence.record_review_action(
        session_id, current_user.id, req.object_type, req.object_id,
        req.action, req.note,
    )
    return {"action_id": action_id, "success": True}


@app.get("/api/projects/{session_id}/issues")
def list_issues(
    session_id: str,
    status: Optional[str] = "open",
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {
        "session_id": session_id,
        "issues": project_intelligence.get_issues(session_id, status),
    }


@app.get("/api/projects/{session_id}/health")
def project_health(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return project_intelligence.get_project_health(session_id)


@app.post("/api/projects/{session_id}/consistency-check")
def run_consistency_check(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    findings = consistency_checker.run_consistency_checks(session_id)
    return {
        "session_id": session_id,
        "findings_count": len(findings),
        "findings": findings,
    }


@app.post("/api/feedback")
def submit_feedback(
    req: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if req.session_id:
        _get_owned_session(req.session_id, current_user)

    feedback = Feedback(
        id=uuid_lib.uuid4().hex,
        user_id=current_user.id,
        session_id=req.session_id,
        rating=req.rating,
        comment=req.comment,
    )
    db.add(feedback)
    db.commit()
    return {"success": True, "feedback_id": feedback.id}


# ---------------------------------------------------------------------------
# Phase execution
# ---------------------------------------------------------------------------
@app.post("/api/projects/{session_id}/phase/{phase_name}/execute")
@limiter.limit(PHASE_RATE_LIMIT)
def execute_phase(
    request: Request,
    session_id: str,
    phase_name: str,
    body: Optional[PhaseExecuteRequest] = None,
    current_user: User = Depends(get_current_user),
):
    """Execute a named phase on the session.

    Accepts phase parameters in the body. Previously the endpoint had no
    body, so the requirements phase (which needs stakeholder_input)
    could not be run through it. Phase-specific required parameters are
    validated up front and return a specific 422 if missing.

    Failures map to HTTP statuses based on the orchestrator's error
    category: 504 for timeouts, 409 for missing prerequisites, 400 for
    unknown phases, 500 for anything else."""
    _get_owned_session(session_id, current_user)

    if phase_name not in _PHASE_EXECUTORS:
        raise HTTPException(status_code=400, detail=f"Unknown phase: {phase_name}")

    body = body or PhaseExecuteRequest()

    required = _PHASE_REQUIRED_PARAMS.get(phase_name, [])
    for field_name in required:
        value = getattr(body, field_name, None)
        if not value or (isinstance(value, str) and not value.strip()):
            raise HTTPException(
                status_code=422,
                detail=f"'{field_name}' is required to execute the {phase_name} phase.",
            )

    kwargs: Dict[str, Any] = {'session_id': session_id}
    if phase_name == 'requirements':
        kwargs['stakeholder_input'] = body.stakeholder_input
    elif phase_name == 'process_mapping':
        kwargs['process_name'] = body.process_name
        kwargs['current_state'] = body.current_state
    elif phase_name == 'qa_testing':
        kwargs['scope'] = body.scope or "comprehensive"
    elif phase_name == 'uat_testing':
        kwargs['user_roles'] = body.user_roles
    elif phase_name == 'training':
        kwargs['process_name'] = body.process_name
        kwargs['user_roles'] = body.user_roles

    result = _PHASE_EXECUTORS[phase_name](**kwargs)

    if not result.get('success'):
        error_text = result.get('error', 'Unknown error')
        status = _map_phase_error_to_status(error_text)
        raise HTTPException(status_code=status, detail=error_text)

    return result


@app.get("/api/projects/{session_id}/status")
def project_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return orchestrator.get_project_status(session_id)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def _collect_session_documents(session_id: str) -> List[Dict[str, str]]:
    db = SessionLocal()
    try:
        from src.db.models import GeneratedDocument
        records = (
            db.query(GeneratedDocument)
            .filter(GeneratedDocument.session_id == session_id)
            .all()
        )
        return [
            {'phase': r.phase, 'label': r.label, 'path': r.filename}
            for r in records
        ]
    finally:
        db.close()


@app.get("/api/projects/{session_id}/documents")
def list_documents(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    docs = _collect_session_documents(session_id)
    return {
        'session_id': session_id,
        'documents': [
            {
                'phase': d['phase'],
                'label': d['label'],
                'filename': os.path.basename(d['path']),
            }
            for d in docs
        ],
    }


@app.post("/api/projects/{session_id}/report")
@limiter.limit(REPORT_RATE_LIMIT)
def generate_project_report(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    try:
        filepath = doc_generator.generate_project_report(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"session_id": session_id, "filename": os.path.basename(filepath)}


@app.get("/api/projects/{session_id}/messages")
def get_messages(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    session = _get_owned_session(session_id, current_user)
    return {"session_id": session_id, "messages": session.conversation_history}


@app.get("/api/projects/{session_id}/documents/{filename}")
def download_document(
    session_id: str,
    filename: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)

    db = SessionLocal()
    try:
        from src.db.models import GeneratedDocument
        record = (
            db.query(GeneratedDocument)
            .filter(
                GeneratedDocument.session_id == session_id,
                GeneratedDocument.filename == filename,
            )
            .first()
        )
    finally:
        db.close()

    if not record:
        raise HTTPException(status_code=404, detail="Document not found for this session")

    return Response(
        content=record.content,
        media_type=record.content_type,
        headers=_attachment_headers(record.filename),
    )


# ---------------------------------------------------------------------------
# Uploaded project documents
# ---------------------------------------------------------------------------
@app.post("/api/projects/{session_id}/uploads")
@limiter.limit(UPLOAD_RATE_LIMIT)
async def upload_project_document(
    request: Request,
    session_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)

    if not settings.object_storage_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "File upload isn't available yet - object storage isn't "
                "configured on this server."
            ),
        )

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    # Bounded read: the previous version read the entire body into memory
    # before checking size, so a 200MB upload was fully received before
    # being rejected.
    content = await _read_upload_bounded(file, max_bytes)

    try:
        extracted = extract_document_text(file.filename, content)
    except UnsupportedFileType as e:
        raise HTTPException(status_code=415, detail=str(e))

    doc_id = uuid_lib.uuid4().hex
    storage_key = object_storage.make_storage_key(session_id, doc_id, file.filename)

    try:
        object_storage.upload_bytes(
            storage_key, content, file.content_type or "application/octet-stream",
        )
    except ObjectStorageError as e:
        raise HTTPException(status_code=502, detail=f"Upload to storage failed: {e}")

    # Persist metadata. If this fails we best-effort delete the storage
    # object so we don't leave orphans behind.
    db = SessionLocal()
    try:
        record = ProjectDocument(
            id=doc_id,
            session_id=session_id,
            user_id=current_user.id,
            filename=file.filename,
            storage_key=storage_key,
            content_type=file.content_type or "application/octet-stream",
            size_bytes=len(content),
            extracted_text_chars=len(extracted),
        )
        db.add(record)
        db.commit()
    except Exception:
        try:
            object_storage.delete_object(storage_key)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to roll back storage object after DB failure",
                storage_key=storage_key,
            )
        raise
    finally:
        db.close()

    if extracted:
        agent_memory.remember(
            session_id,
            key=f"upload_{doc_id}",
            content=extracted,
            category="uploaded_document",
            tags=["uploaded", file.filename.rsplit(".", 1)[-1].lower()],
            importance=1.0,
        )

    return {
        "id": doc_id,
        "filename": file.filename,
        "size_bytes": len(content),
        "extracted_text_chars": len(extracted),
    }


@app.get("/api/projects/{session_id}/uploads")
def list_project_documents(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)

    db = SessionLocal()
    try:
        records = (
            db.query(ProjectDocument)
            .filter(ProjectDocument.session_id == session_id)
            .order_by(ProjectDocument.uploaded_at.desc())
            .all()
        )
        return {
            "session_id": session_id,
            "documents": [
                {
                    "id": r.id,
                    "filename": r.filename,
                    "content_type": r.content_type,
                    "size_bytes": r.size_bytes,
                    "extracted_text_chars": r.extracted_text_chars,
                    "uploaded_at": r.uploaded_at.isoformat(),
                }
                for r in records
            ],
        }
    finally:
        db.close()


@app.get("/api/projects/{session_id}/uploads/{document_id}/download")
def download_project_document(
    session_id: str,
    document_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)

    db = SessionLocal()
    try:
        record = (
            db.query(ProjectDocument)
            .filter(
                ProjectDocument.session_id == session_id,
                ProjectDocument.id == document_id,
            )
            .first()
        )
    finally:
        db.close()

    if not record:
        raise HTTPException(status_code=404, detail="Document not found for this session")

    try:
        content = object_storage.download_bytes(record.storage_key)
    except ObjectStorageError as e:
        raise HTTPException(status_code=502, detail=f"Download from storage failed: {e}")

    return Response(
        content=content,
        media_type=record.content_type,
        headers=_attachment_headers(record.filename),
    )


@app.delete("/api/projects/{session_id}/uploads/{document_id}")
def delete_project_document(
    session_id: str,
    document_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)

    db = SessionLocal()
    try:
        record = (
            db.query(ProjectDocument)
            .filter(
                ProjectDocument.session_id == session_id,
                ProjectDocument.id == document_id,
            )
            .first()
        )
        if not record:
            raise HTTPException(status_code=404, detail="Document not found for this session")

        storage_key = record.storage_key
        db.delete(record)
        db.commit()
    finally:
        db.close()

    try:
        object_storage.delete_object(storage_key)
    except ObjectStorageError as e:
        logger.warning(
            "Failed to delete object from storage after DB row removed",
            storage_key=storage_key, error=str(e),
        )

    try:
        agent_memory.project_memory.delete_memory(session_id, f"upload_{document_id}")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Failed to delete memory entry for deleted upload",
            document_id=document_id, error=str(e),
        )

    return {"id": document_id, "deleted": True}


# ---------------------------------------------------------------------------
# Structured project data (process steps, decisions, tests, training)
# ---------------------------------------------------------------------------
@app.get("/api/projects/{session_id}/process-steps")
def list_process_steps(
    session_id: str,
    process_name: Optional[str] = None,
    include_history: bool = False,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {
        "session_id": session_id,
        "process_steps": project_intelligence.get_process_steps(
            session_id, process_name, include_history,
        ),
    }


@app.get("/api/projects/{session_id}/solution-decisions")
def list_solution_decisions(
    session_id: str,
    decision_type: Optional[str] = None,
    stage: Optional[str] = None,
    include_history: bool = False,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {
        "session_id": session_id,
        "solution_decisions": project_intelligence.get_solution_decisions(
            session_id, decision_type, stage=stage, include_history=include_history,
        ),
    }


@app.get("/api/projects/{session_id}/test-cases")
def list_test_cases(
    session_id: str,
    test_type: Optional[str] = None,
    include_history: bool = False,
    needs_retest: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {
        "session_id": session_id,
        "test_cases": project_intelligence.get_test_cases(
            session_id, test_type, needs_retest,
        ),
    }


@app.post("/api/projects/{session_id}/test-cases/{test_case_id}/mark-retested")
def mark_test_case_retested(
    session_id: str,
    test_case_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    ok = project_intelligence.mark_test_case_retested(session_id, test_case_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Test case not found for this session")
    return {"success": True}


@app.get("/api/projects/{session_id}/training-steps")
def list_training_steps(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {
        "session_id": session_id,
        "training_steps": project_intelligence.get_training_steps(session_id),
    }


@app.get("/api/projects/{session_id}/coverage-gaps")
def coverage_gaps(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {
        "session_id": session_id,
        **project_intelligence.get_coverage_gaps(session_id),
    }


# ---------------------------------------------------------------------------
# Revisions & baselines
# ---------------------------------------------------------------------------
@app.post("/api/projects/{session_id}/requirements/{requirement_id}/revise")
def revise_requirement(
    session_id: str,
    requirement_id: str,
    req: RequirementReviseRequest,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    try:
        new_id = project_intelligence.revise_requirement(
            session_id, requirement_id, req.model_dump(exclude_none=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"new_requirement_id": new_id}


@app.get("/api/projects/{session_id}/requirements/{lineage_id}/history")
def requirement_history(
    session_id: str,
    lineage_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {"history": project_intelligence.get_requirement_history(session_id, lineage_id)}


@app.post("/api/projects/{session_id}/solution-decisions/{decision_id}/actual")
def record_actual_solution(
    session_id: str,
    decision_id: str,
    req: SolutionActualRequest,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    try:
        new_id = project_intelligence.record_actual_solution(
            session_id, decision_id, req.description, req.component, req.rationale,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"new_decision_id": new_id}


@app.get("/api/projects/{session_id}/solution-decisions/{lineage_id}/history")
def solution_decision_history(
    session_id: str,
    lineage_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {"history": project_intelligence.get_solution_decision_history(session_id, lineage_id)}


@app.post("/api/projects/{session_id}/process-steps/{step_id}/revise")
def revise_process_step(
    session_id: str,
    step_id: str,
    req: ProcessStepReviseRequest,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    try:
        new_id = project_intelligence.revise_process_step(
            session_id, step_id, req.model_dump(exclude_none=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"new_step_id": new_id}


@app.get("/api/projects/{session_id}/process-steps/{lineage_id}/history")
def process_step_history(
    session_id: str,
    lineage_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {"history": project_intelligence.get_process_step_history(session_id, lineage_id)}


@app.post("/api/projects/{session_id}/test-cases/{test_case_id}/report-failure")
def report_test_failure(
    session_id: str,
    test_case_id: str,
    req: TestFailureRequest,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    issue_id = project_intelligence.record_test_failure(
        session_id, test_case_id, req.classification, req.description,
    )
    return {"issue_id": issue_id}


@app.get("/api/projects/{session_id}/test-failures")
def list_test_failures(
    session_id: str,
    classification: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {"test_failures": project_intelligence.get_test_failures(session_id, classification)}


@app.post("/api/projects/{session_id}/baselines")
def create_baseline(
    session_id: str,
    req: BaselineCreateRequest,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    baseline_id = project_intelligence.create_baseline(
        session_id, current_user.id, req.label, req.notes, req.decision_ids,
    )
    return {"baseline_id": baseline_id}


@app.get("/api/projects/{session_id}/baselines")
def list_baselines(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    return {"baselines": project_intelligence.get_baselines(session_id)}


@app.get("/api/projects/{session_id}/baselines/active")
def active_baseline(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _get_owned_session(session_id, current_user)
    baseline = project_intelligence.get_active_baseline(session_id)
    if not baseline:
        raise HTTPException(status_code=404, detail="No active baseline for this project")
    return baseline


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
def _chat_response(
    answer: str,
    llm_mode: str,
    success: bool = True,
    session_id: Optional[str] = None,
):
    return {
        'success': success,
        'answer': answer,
        'llm_mode': llm_mode,
        'session_id': session_id,
    }


# Obvious greetings and acknowledgments - skip the intent-classification
# LLM call for these. Saves latency and cost on casual chatter.
_GREETING_PATTERN = re.compile(
    r"^(?:hi|hello|hey|good (?:morning|afternoon|evening)|"
    r"thanks|thank you|thx|ok|okay|sure|got it|cool|nice)[.!?]?$",
    re.IGNORECASE,
)


def classify_intent(
    llm_instance, message: str, has_session: bool,
) -> ChatIntentDecision:
    stripped = (message or "").strip()
    if not stripped or _GREETING_PATTERN.match(stripped):
        return ChatIntentDecision(intent=ChatIntent.ASK_QUESTION)

    prompt = f"""Classify this user message into exactly one intent.

Message: "{message}"
User currently has an active project session: {has_session}

Intents:
- start_project: user explicitly wants to begin a new ERP project (e.g. "start a new project called X", "let's begin implementation for Y"). If they mention a specific ERP system (SAP, Oracle, Dynamics 365, NetSuite, Odoo, Infor, Workday) or module (e.g. FI, MM, SD, HCM, financials), extract them into module/erp_system. Leave them unset if not mentioned.
- run_phase: user explicitly wants to execute a specific workflow phase on their CURRENT project. Only valid if a session already exists. Phase must be one of: requirements, process_mapping, solution_design, qa_testing, uat_testing, training
- generate_training: user explicitly wants training materials or a user guide generated as a document
- ask_question: anything else - general questions, discussion, or requests for information, even if they mention topics like "training" or "requirements" without asking to generate or run something

Default to ask_question whenever the message is ambiguous, conversational, or informational rather than a direct command."""

    try:
        response = llm_instance.generate_content(
            prompt,
            generation_config={
                'response_schema': ChatIntentDecision,
                'temperature': 0.0,
                'task': TaskCategory.LIGHTWEIGHT,
            },
        )
        return ChatIntentDecision.model_validate_json(response.text)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Intent classification failed, defaulting to ask_question",
            error=str(e),
        )
        return ChatIntentDecision(intent=ChatIntent.ASK_QUESTION)


def _handle_intake_if_pending(
    req: ChatRequest, llm_mode: str,
) -> Optional[Dict[str, Any]]:
    """Returns a chat response dict if the session is mid-intake and the
    message was consumed by intake; returns None if intake is not pending
    or the message should be handled by the usual flow."""
    if not req.session_id or not _intake_is_pending(req.session_id):
        return None

    res = _run_intake_step(req.session_id, req.message, resume=True)
    if not res.get('success'):
        return _chat_response(
            res.get('error', 'Intake failed.'), llm_mode=llm_mode,
            success=False, session_id=req.session_id,
        )
    answer = res['answer']
    agent_memory.session_service.add_to_conversation(
        req.session_id, role="user", content=req.message,
    )
    agent_memory.session_service.add_to_conversation(
        req.session_id, role="assistant", content=answer,
    )
    return _chat_response(answer, llm_mode=llm_mode, session_id=req.session_id)


def _handle_agent_hint(
    req: ChatRequest, llm_mode: str,
) -> Optional[Dict[str, Any]]:
    """Handle messages that carry an explicit agent_hint. Returns a chat
    response dict, or None if the hint isn't recognized (the caller then
    falls through to intent classification)."""
    if not req.agent_hint or not req.session_id:
        return None

    session = agent_memory.session_service.get_session(req.session_id)
    if not session:
        return _chat_response("Session not found.", llm_mode=llm_mode, success=False)

    hint = req.agent_hint.lower()

    if hint == 'requirements':
        res = requirements_agent.gather_requirements(
            session_id=req.session_id,
            project_name=session.project_name,
            module=session.module,
            stakeholder_input=req.message,
            erp_system=session.erp_system,
        )
        summary = (
            res.get('requirements', {}).get('executive_summary')
            or 'No summary available.'
        )
        return _chat_response(
            f"Requirements gathered: {summary}",
            llm_mode=llm_mode, session_id=req.session_id,
        )

    if hint == 'start_intake':
        res = _run_intake_step(req.session_id, None, resume=False)
        if not res.get('success'):
            return _chat_response(
                res.get('error', 'Intake failed.'), llm_mode=llm_mode,
                success=False, session_id=req.session_id,
            )
        answer = res['answer']
        agent_memory.session_service.add_to_conversation(
            req.session_id, role="user", content=req.message,
        )
        agent_memory.session_service.add_to_conversation(
            req.session_id, role="assistant", content=answer,
        )
        return _chat_response(answer, llm_mode=llm_mode, session_id=req.session_id)

    if hint in _PHASE_EXECUTORS:
        result = _PHASE_EXECUTORS[hint](session_id=req.session_id)
        if result.get('success'):
            answer = f"Phase '{hint}' executed successfully."
            agent_memory.session_service.add_to_conversation(
                req.session_id, role="user", content=req.message,
            )
            agent_memory.session_service.add_to_conversation(
                req.session_id, role="assistant", content=answer,
            )
            return _chat_response(answer, llm_mode=llm_mode, session_id=req.session_id)
        return _chat_response(
            f"Failed to execute phase '{hint}': {result.get('error', 'Unknown error')}",
            llm_mode=llm_mode, success=False, session_id=req.session_id,
        )

    # Unrecognized hint - caller falls through to intent classification.
    return None


@app.post("/api/chat")
@limiter.limit(CHAT_RATE_LIMIT)
def chat(
    request: Request,
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    # NOTE: user message content is deliberately not logged - see module
    # docstring. If a support case requires the content, it's available
    # in the session's conversation_history, access-controlled per user.
    logger.info(
        "Chat request received",
        session_id=req.session_id,
        message_length=len(req.message),
        has_agent_hint=bool(req.agent_hint),
        prefer_web=bool(req.prefer_web),
        user_id=current_user.id,
    )

    if req.session_id:
        _get_owned_session(req.session_id, current_user)

    llm_instance = llm_mod.get_llm()
    llm_mode = "gemini" if getattr(llm_instance, "use_gemini", True) else "gpt-4"

    # Intake takes precedence over any other routing.
    intake_response = _handle_intake_if_pending(req, llm_mode)
    if intake_response is not None:
        return intake_response

    hint_response = _handle_agent_hint(req, llm_mode)
    if hint_response is not None:
        return hint_response

    decision = classify_intent(
        llm_instance, req.message, has_session=bool(req.session_id),
    )
    logger.info("Intent classified", intent=decision.intent.value)

    if decision.intent == ChatIntent.START_PROJECT:
        project_name = decision.project_name or 'Chat Project'
        module = decision.module or 'FI'
        erp_system = decision.erp_system or 'SAP S/4HANA'
        res = orchestrator.start_project(
            project_name, module, erp_system=erp_system,
            initial_input=None, user_id=current_user.id,
        )
        if res.get('success'):
            return _chat_response(
                f"Project '{project_name}' started ({module} / {erp_system}). "
                "You can now ask me to gather requirements, run a phase, or "
                "ask any question about it.",
                llm_mode=llm_mode, session_id=res.get('session_id'),
            )
        return _chat_response(
            f"Failed to start project: {res.get('error', 'Unknown error')}",
            llm_mode=llm_mode, success=False,
        )

    if decision.intent == ChatIntent.RUN_PHASE:
        if not req.session_id:
            return _chat_response(
                "session_id is required to run a phase.",
                llm_mode=llm_mode, success=False,
            )

        if decision.phase not in _PHASE_EXECUTORS:
            return _chat_response(
                "Could not determine which phase to run.",
                llm_mode=llm_mode, success=False,
            )

        phase_kwargs: Dict[str, Any] = {'session_id': req.session_id}
        if decision.phase == 'requirements':
            phase_kwargs['stakeholder_input'] = req.message

        result = _PHASE_EXECUTORS[decision.phase](**phase_kwargs)
        if result.get('success'):
            return _chat_response(
                f"Phase '{decision.phase}' executed successfully.",
                llm_mode=llm_mode, session_id=req.session_id,
            )
        return _chat_response(
            f"Failed to execute phase '{decision.phase}': "
            f"{result.get('error', 'Unknown error')}",
            llm_mode=llm_mode, success=False, session_id=req.session_id,
        )

    if decision.intent == ChatIntent.GENERATE_TRAINING and req.session_id is None:
        session_id = agent_memory.create_project(
            project_name='AP Invoice Posting', module='FI',
            user_id=current_user.id,
        )
        result = training_agent.create_training_materials(
            session_id=session_id,
            process_name='AP Invoice Posting',
            user_roles=[
                'AP Clerk', 'Accounts Payable Supervisor', 'Finance Manager',
            ],
            solution_design={},
        )
        if result.get('success'):
            return _chat_response(
                "Training materials for 'AP Invoice Posting' have been generated.",
                llm_mode=llm_mode,
            )
        return _chat_response(
            "Failed to generate training materials.",
            llm_mode=llm_mode, success=False,
        )

    session_id = req.session_id
    if session_id is None:
        title = _derive_chat_title(req.message)
        session_id = agent_memory.create_project(
            project_name=title, module='FI',
            user_id=current_user.id, is_casual=True,
        )

    data = info_retriever(
        req.message, {'summary': ''},
        prefer_web=req.prefer_web, session_id=req.session_id,
    )
    generation_config = {
        'temperature': 0.5,
        'max_output_tokens': settings.max_tokens,
        'task': TaskCategory.LIGHTWEIGHT,
    }

    if data and (data.get('kb_results') or data.get('web_results') or data.get('sources')):
        prompt = get_synthesis_prompt(req.message, data)
    else:
        prompt = (
            'Respond naturally and briefly, as a helpful ERP consulting '
            f'assistant, to this message: "{req.message}"'
        )

    try:
        response = llm_instance.generate_content(prompt, generation_config=generation_config)
        final_answer = extract_text(response)
    except Exception as e:  # noqa: BLE001
        # All LLM providers failed. Do NOT discard the reference data that
        # info_retriever already returned - surface it through the existing
        # fallback path instead. No second LLM request is made, and no
        # facts are invented. If there is no usable reference data, keep an
        # explicit failure message.
        logger.error("Error during final answer synthesis", error=str(e))
        fallback_answer = _reference_data_fallback(data)
        if fallback_answer is not None:
            final_answer = fallback_answer
        else:
            final_answer = "I found some information, but I had trouble summarizing it."

    agent_memory.session_service.add_to_conversation(
        session_id, role="user", content=req.message,
    )
    agent_memory.session_service.add_to_conversation(
        session_id, role="assistant", content=final_answer,
    )

    logger.info("Chat response ready", session_id=session_id)
    return _chat_response(final_answer, llm_mode=llm_mode, session_id=session_id)


# ---------------------------------------------------------------------------
# Streaming chat (SSE)
# ---------------------------------------------------------------------------
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _sse_comment(text: str) -> str:
    """SSE comment line - ignored by clients but keeps intermediaries
    (load balancers, some proxies) from timing out an idle stream.
    Emitted before each potentially long operation."""
    return f": {text}\n\n"


def _stream_chat_events(req: ChatRequest, current_user: User, request_id: Optional[str]):
    """Server-Sent Events generator for the chat endpoint.

    LIMITATION: this is a sync generator iterated in a worker thread. It
    cannot emit keepalives during a blocking LLM call - only between
    operations. The events emitted before each long step (`agent_started`,
    `tool_started`) serve as progress signals and, in practice, produce
    enough traffic that typical 60s LB idle timeouts are not triggered
    (individual LLM calls are bounded by the LLM wrapper). A full async
    rewrite with a producer/consumer queue would be required to keep the
    connection alive during a genuinely slow phase; that's flagged as an
    architectural follow-up, not done here.
    """
    def ev(event_type: str, **data: Any) -> str:
        if request_id:
            data['request_id'] = request_id
        return _sse(event_type, data)

    try:
        yield ev('message_start', session_id=req.session_id)

        llm_instance = llm_mod.get_llm()
        llm_mode = "gemini" if getattr(llm_instance, "use_gemini", True) else "gpt-4"

        # Intake pending takes precedence.
        if req.session_id and _intake_is_pending(req.session_id):
            yield _sse_comment("keepalive")
            yield ev('agent_started', agent='intake', message='Gathering project context')
            res = _run_intake_step(req.session_id, req.message, resume=True)
            if not res.get('success'):
                yield ev('error', message=res.get('error', 'Intake failed.'))
                return
            answer = res['answer']
            agent_memory.session_service.add_to_conversation(
                req.session_id, role="user", content=req.message,
            )
            agent_memory.session_service.add_to_conversation(
                req.session_id, role="assistant", content=answer,
            )
            if res.get('document_path'):
                yield ev(
                    'document_created', phase='requirements_template',
                    filename=os.path.basename(res['document_path']),
                )
            yield ev('text_delta', text=answer)
            yield ev('workflow_completed')
            next_action = _next_action_for(
                agent_memory.session_service.get_session(req.session_id),
            )
            yield ev(
                'message_complete', answer=answer, llm_mode=llm_mode,
                session_id=req.session_id, next_action=next_action,
            )
            return

        # Agent hint.
        if req.agent_hint and req.session_id:
            session = agent_memory.session_service.get_session(req.session_id)
            if not session:
                yield ev('error', message='Session not found.')
                return
            hint = req.agent_hint.lower()

            if hint == 'start_intake':
                yield _sse_comment("keepalive")
                res = _run_intake_step(req.session_id, None, resume=False)
                if not res.get('success'):
                    yield ev('error', message=res.get('error', 'Intake failed.'))
                    return
                answer = res['answer']
                agent_memory.session_service.add_to_conversation(
                    req.session_id, role="user", content=req.message,
                )
                agent_memory.session_service.add_to_conversation(
                    req.session_id, role="assistant", content=answer,
                )
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                next_action = _next_action_for(
                    agent_memory.session_service.get_session(req.session_id),
                )
                yield ev(
                    'message_complete', answer=answer, llm_mode=llm_mode,
                    session_id=req.session_id, next_action=next_action,
                )
                return

            if hint in _PHASE_EXECUTORS:
                yield _sse_comment("keepalive")
                yield ev(
                    'agent_started', agent=hint,
                    message=f"Running {hint.replace('_', ' ')} phase",
                )
                result = _PHASE_EXECUTORS[hint](session_id=req.session_id)
                if not result.get('success'):
                    yield ev(
                        'error',
                        message=(
                            f"Failed to execute phase '{hint}': "
                            f"{result.get('error', 'Unknown error')}"
                        ),
                    )
                    return
                doc_path = result.get('document_path')
                if doc_path:
                    yield ev(
                        'document_created', phase=hint,
                        filename=os.path.basename(doc_path),
                    )
                for label, path in (result.get('documents') or {}).items():
                    if path:
                        yield ev(
                            'document_created', phase=hint, label=label,
                            filename=os.path.basename(path),
                        )
                answer = f"Phase '{hint}' executed successfully."
                agent_memory.session_service.add_to_conversation(
                    req.session_id, role="user", content=req.message,
                )
                agent_memory.session_service.add_to_conversation(
                    req.session_id, role="assistant", content=answer,
                )
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                next_action = _next_action_for(
                    agent_memory.session_service.get_session(req.session_id),
                )
                yield ev(
                    'message_complete', answer=answer, llm_mode=llm_mode,
                    session_id=req.session_id, next_action=next_action,
                )
                return

        # Intent classification.
        yield _sse_comment("keepalive")
        yield ev('agent_started', agent='router', message='Understanding your request')
        decision = classify_intent(
            llm_instance, req.message, has_session=bool(req.session_id),
        )
        logger.info("Intent classified", intent=decision.intent.value)

        if decision.intent == ChatIntent.START_PROJECT:
            project_name = decision.project_name or 'Chat Project'
            module = decision.module or 'FI'
            erp_system = decision.erp_system or 'SAP S/4HANA'
            yield ev(
                'agent_started', agent='orchestrator',
                message=f"Starting project '{project_name}'",
            )
            res = orchestrator.start_project(
                project_name, module, erp_system=erp_system,
                initial_input=None, user_id=current_user.id,
            )
            if res.get('success'):
                answer = (
                    f"Project '{project_name}' started ({module} / {erp_system}). "
                    "You can now ask me to gather requirements, run a phase, or "
                    "ask any question about it."
                )
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                new_session = agent_memory.session_service.get_session(
                    res.get('session_id'),
                )
                next_action = _next_action_for(new_session) if new_session else None
                yield ev(
                    'message_complete', answer=answer, llm_mode=llm_mode,
                    session_id=res.get('session_id'), next_action=next_action,
                )
            else:
                yield ev(
                    'error',
                    message=f"Failed to start project: {res.get('error', 'Unknown error')}",
                )
            return

        if decision.intent == ChatIntent.RUN_PHASE:
            if not req.session_id:
                yield ev('error', message='session_id is required to run a phase.')
                return

            if decision.phase not in _PHASE_EXECUTORS:
                yield ev('error', message='Could not determine which phase to run.')
                return

            yield _sse_comment("keepalive")
            yield ev(
                'agent_started', agent=decision.phase,
                message=f"Running {decision.phase.replace('_', ' ')} phase",
            )
            phase_kwargs: Dict[str, Any] = {'session_id': req.session_id}
            if decision.phase == 'requirements':
                phase_kwargs['stakeholder_input'] = req.message
            result = _PHASE_EXECUTORS[decision.phase](**phase_kwargs)
            if result.get('success'):
                doc_path = result.get('document_path')
                if doc_path:
                    yield ev(
                        'document_created', phase=decision.phase,
                        filename=os.path.basename(doc_path),
                    )
                answer = f"Phase '{decision.phase}' executed successfully."
                agent_memory.session_service.add_to_conversation(
                    req.session_id, role="user", content=req.message,
                )
                agent_memory.session_service.add_to_conversation(
                    req.session_id, role="assistant", content=answer,
                )
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                next_action = _next_action_for(
                    agent_memory.session_service.get_session(req.session_id),
                )
                yield ev(
                    'message_complete', answer=answer, llm_mode=llm_mode,
                    session_id=req.session_id, next_action=next_action,
                )
            else:
                yield ev(
                    'error',
                    message=(
                        f"Failed to execute phase '{decision.phase}': "
                        f"{result.get('error', 'Unknown error')}"
                    ),
                )
            return

        if decision.intent == ChatIntent.GENERATE_TRAINING and req.session_id is None:
            yield _sse_comment("keepalive")
            yield ev(
                'agent_started', agent='training',
                message='Generating training materials',
            )
            session_id = agent_memory.create_project(
                project_name='AP Invoice Posting', module='FI',
                user_id=current_user.id,
            )
            result = training_agent.create_training_materials(
                session_id=session_id, process_name='AP Invoice Posting',
                user_roles=[
                    'AP Clerk', 'Accounts Payable Supervisor', 'Finance Manager',
                ],
                solution_design={},
            )
            if result.get('success'):
                for label, path in (result.get('documents') or {}).items():
                    if path:
                        yield ev(
                            'document_created', phase='training', label=label,
                            filename=os.path.basename(path),
                        )
                answer = "Training materials for 'AP Invoice Posting' have been generated."
                agent_memory.session_service.add_to_conversation(
                    session_id, role="user", content=req.message,
                )
                agent_memory.session_service.add_to_conversation(
                    session_id, role="assistant", content=answer,
                )
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                next_action = _next_action_for(
                    agent_memory.session_service.get_session(session_id),
                )
                yield ev(
                    'message_complete', answer=answer, llm_mode=llm_mode,
                    session_id=session_id, next_action=next_action,
                )
            else:
                yield ev('error', message='Failed to generate training materials.')
            return

        # Fallback: retrieve information and synthesize an answer.
        session_id = req.session_id
        if session_id is None:
            title = _derive_chat_title(req.message)
            session_id = agent_memory.create_project(
                project_name=title, module='FI',
                user_id=current_user.id, is_casual=True,
            )

        yield _sse_comment("keepalive")
        yield ev('tool_started', tool='info_retriever', message='Searching knowledge base and web')
        data = info_retriever(
            req.message, {'summary': ''},
            prefer_web=req.prefer_web, session_id=req.session_id,
        )
        yield ev('tool_completed', tool='info_retriever')

        generation_config = {
            'temperature': 0.5,
            'max_output_tokens': settings.max_tokens,
            'task': TaskCategory.LIGHTWEIGHT,
        }
        if data and (
            data.get('kb_results') or data.get('web_results') or data.get('sources')
        ):
            prompt = get_synthesis_prompt(req.message, data)
        else:
            prompt = (
                'Respond naturally and briefly, as a helpful ERP consulting '
                f'assistant, to this message: "{req.message}"'
            )

        yield _sse_comment("keepalive")
        yield ev('agent_started', agent='synthesis', message='Preparing your answer')
        full_answer_parts: List[str] = []
        try:
            if hasattr(llm_instance, 'generate_content_stream'):
                for chunk in llm_instance.generate_content_stream(
                    prompt, generation_config=generation_config,
                ):
                    full_answer_parts.append(chunk)
                    yield ev('text_delta', text=chunk)
            else:
                response = llm_instance.generate_content(
                    prompt, generation_config=generation_config,
                )
                text = extract_text(response)
                full_answer_parts.append(text)
                yield ev('text_delta', text=text)
        except Exception as e:  # noqa: BLE001
            # Every LLM provider failed before yielding anything. Rather
            # than discard the reference data retrieved above, surface it
            # through the same text_delta/event stream. Guarded by
            # `not full_answer_parts` so we never duplicate or contradict
            # partial output that already reached the client. No second
            # LLM request is made and no facts are invented.
            logger.error("Error during streamed answer synthesis", error=str(e))
            if not full_answer_parts:
                fallback = _reference_data_fallback(data) or (
                    "I found some information, but I had trouble summarizing it."
                )
                full_answer_parts.append(fallback)
                yield ev('text_delta', text=fallback)

        final_answer = "".join(full_answer_parts)
        agent_memory.session_service.add_to_conversation(
            session_id, role="user", content=req.message,
        )
        agent_memory.session_service.add_to_conversation(
            session_id, role="assistant", content=final_answer,
        )

        logger.info("Chat response ready", session_id=session_id)
        yield ev('workflow_completed')
        next_action = _next_action_for(
            agent_memory.session_service.get_session(session_id),
        )
        yield ev(
            'message_complete', answer=final_answer, llm_mode=llm_mode,
            session_id=session_id, next_action=next_action,
        )

    except Exception as e:  # noqa: BLE001
        logger.error("Unhandled error in chat stream", error=str(e), exc_info=True)
        yield ev('error', message='Internal server error while processing your message.')


@app.post("/api/chat/stream")
@limiter.limit(CHAT_RATE_LIMIT)
def chat_stream(
    request: Request,
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    if req.session_id:
        _get_owned_session(req.session_id, current_user)

    request_id = getattr(request.state, "request_id", None)
    return StreamingResponse(
        _stream_chat_events(req, current_user, request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# UI root
# ---------------------------------------------------------------------------
@app.get("/")
def get_ui():
    try:
        with open('frontend/dist/index.html', 'r', encoding='utf-8') as f:
            html = f.read()
        return HTMLResponse(content=html, status_code=200)
    except FileNotFoundError:
        return HTMLResponse(
            content='<h3>ERP Orchestrator API</h3>'
                    '<p>Frontend not built yet - run <code>npm run build</code> in frontend/. '
                    'API docs: <a href="/docs">/docs</a>.</p>',
            status_code=200,
        )


def start_server(host: str = '127.0.0.1', port: int = 8000):
    uvicorn.run(app, host=host, port=port)


if __name__ == '__main__':
    start_server()