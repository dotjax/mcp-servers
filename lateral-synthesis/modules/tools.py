"""
Lateral Synthesis MCP - Tool Handlers

Implements all tool handlers for the lateral synthesis workflow.
"""

import json
import logging
from datetime import datetime, timezone
from mcp.types import TextContent

from .models import (
    SESSIONS,
    CONNECTION_TYPES,
    ConceptSynthesis,
    SessionReflection,
    LateralSession,
    get_config,
    get_current_session,
    set_current_session,
)
from .divergence import generate_divergent_concepts
from .persistence import save_session_to_history, save_session_snapshot, load_sessions_from_history

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Response Helpers
# -----------------------------------------------------------------------------

def _ok(**payload) -> list[TextContent]:
    """Return a success response (standardized with result wrapper)."""
    return [TextContent(type="text", text=json.dumps({"status": "success", "result": payload}))]


def _err(error: str, message: str | None = None, **details) -> list[TextContent]:
    """Return an error response (standardized with details)."""
    payload: dict = {"status": "error", "error": error}
    if message:
        payload["message"] = message
    if details:
        payload["details"] = details
    return [TextContent(type="text", text=json.dumps(payload))]


# -----------------------------------------------------------------------------
# Tool: start_session
# -----------------------------------------------------------------------------

async def tool_start_session(args: dict) -> list[TextContent]:
    """
    Start a new lateral synthesis session with an origin concept.
    
    Args:
        origin: The starting concept, phrase, or question (max 1000 chars)
        method: Optional divergence method (default: from config)
    """
    logger.debug(f"tool_start_session called with args: {args}")
    
    origin = args.get("origin", "").strip()
    if not origin:
        return _err("missing_origin", "Origin is required")
    
    config = get_config()
    if len(origin) > config.limits.max_origin_chars:
        return _err(
            "origin_too_long",
            f"Origin exceeds maximum length of {config.limits.max_origin_chars} characters",
            length=len(origin),
            max_length=config.limits.max_origin_chars,
        )
    
    method = args.get("method", config.divergence.method)
    
    # Create new session
    session = LateralSession.create(origin=origin, method=method)
    SESSIONS[session.session_id] = session
    set_current_session(session.session_id)
    save_session_snapshot(session, "start")
    
    logger.info(f"Created new session {session.session_id} with origin: {origin[:50]}...")
    
    return _ok(
        session_id=session.session_id,
        origin=session.origin,
        method=session.method,
        created_at=session.created_at,
        next_step="Call generate_divergence to produce divergent concepts",
    )


# -----------------------------------------------------------------------------
# Tool: generate_divergence
# -----------------------------------------------------------------------------

async def tool_generate_divergence(args: dict) -> list[TextContent]:
    """
    Generate divergent concepts for the current session.
    
    Args:
        session_id: Optional session ID (uses current session if not provided)
        count: Optional number of concepts (default: from config)
    """
    logger.debug(f"tool_generate_divergence called with args: {args}")
    
    session_id = args.get("session_id")
    if session_id:
        session = SESSIONS.get(session_id)
    else:
        session = get_current_session()
    
    if not session:
        return _err("no_session", "No active session. Call start_session first.")
    
    if session.divergent_concepts and not args.get("override"):
        return _err(
            "already_generated",
            "Divergent concepts already generated for this session (use override=true to regenerate)",
            concepts=session.divergent_concepts,
        )
    
    config = get_config()
    count_raw = args.get("count", config.divergence.count)
    try:
        count = int(count_raw)
    except (TypeError, ValueError):
        return _err("invalid_count", "count must be an integer between 1 and 50")

    if count < 1 or count > 50:
        return _err("invalid_count", "count must be between 1 and 50", value=count)
    
    # If overriding, clear prior concepts/syntheses/reflection to keep state consistent
    if args.get("override"):
        session.divergent_concepts = []
        session.syntheses = []
        session.reflection = None
        session.completed_at = None

    # Generate divergent concepts
    concepts = generate_divergent_concepts(
        origin=session.origin,
        method=session.method,
        count=count,
    )
    
    session.divergent_concepts = concepts
    
    logger.info(f"Generated {len(concepts)} divergent concepts for session {session.session_id}")
    save_session_snapshot(session, "divergence")
    
    return _ok(
        session_id=session.session_id,
        origin=session.origin,
        divergent_concepts=concepts,
        next_step=f"Call record_synthesis for each of the {len(concepts)} concepts",
        overridden=bool(args.get("override")),
    )


# -----------------------------------------------------------------------------
# Tool: record_synthesis
# -----------------------------------------------------------------------------

async def tool_record_synthesis(args: dict) -> list[TextContent]:
    """
    Record a synthesis for one divergent concept.
    
    Args:
        divergent_concept: The concept being synthesized (must match one from the session)
        connection_type: One of: analogy, contrast, causal, metaphor, structural, arbitrary, other
        connection_type_detail: Required if connection_type is "other"
        confidence: Float 0.0-1.0
        insight: The bridging insight/connection
        session_id: Optional session ID (uses current session if not provided)
    """
    logger.debug(f"tool_record_synthesis called with args: {args}")
    
    session_id = args.get("session_id")
    if session_id:
        session = SESSIONS.get(session_id)
    else:
        session = get_current_session()
    
    if not session:
        return _err("no_session", "No active session. Call start_session first.")
    
    if not session.divergent_concepts:
        return _err("no_divergence", "No divergent concepts generated. Call generate_divergence first.")
    
    # Validate required fields
    divergent_concept = args.get("divergent_concept", "").strip()
    if not divergent_concept:
        return _err("missing_concept", "divergent_concept is required")
    
    if divergent_concept not in session.divergent_concepts:
        return _err(
            "invalid_concept",
            f"'{divergent_concept}' is not one of the divergent concepts for this session",
            valid_concepts=session.divergent_concepts,
        )
    
    # Check if already synthesized
    if divergent_concept in session.get_synthesized_concepts():
        return _err(
            "already_synthesized",
            f"'{divergent_concept}' has already been synthesized",
            remaining=session.get_remaining_concepts(),
        )
    
    connection_type = args.get("connection_type", "").strip()
    if not connection_type:
        return _err("missing_connection_type", f"connection_type is required. Must be one of: {CONNECTION_TYPES}")
    
    connection_type_detail = args.get("connection_type_detail")
    confidence = args.get("confidence")
    insight = args.get("insight", "").strip()
    
    if confidence is None:
        return _err("missing_confidence", "confidence is required (0.0-1.0)")

    # Coerce and validate confidence before creating model instance
    try:
        if isinstance(confidence, (int, float)):
            confidence_val = float(confidence)
        elif isinstance(confidence, str):
            confidence_val = float(confidence.strip())
        else:
            return _err("validation_error", "confidence must be numeric (0.0-1.0)")
    except ValueError:
        return _err("validation_error", "confidence must be numeric (0.0-1.0)")

    if not (0.0 <= confidence_val <= 1.0):
        return _err("validation_error", "confidence must be between 0.0 and 1.0", value=confidence_val)
    
    if not insight:
        return _err("missing_insight", "insight is required")
    
    config = get_config()
    if len(insight) > config.limits.max_insight_chars:
        return _err(
            "insight_too_long",
            f"Insight exceeds maximum length of {config.limits.max_insight_chars} characters",
            length=len(insight),
            max_length=config.limits.max_insight_chars,
        )
    
    # Create and validate synthesis
    synthesis = ConceptSynthesis(
        divergent_concept=divergent_concept,
        connection_type=connection_type,
        connection_type_detail=connection_type_detail,
        confidence=confidence_val,
        insight=insight,
    )
    
    errors = synthesis.validate()
    if errors:
        return _err("validation_error", "Synthesis validation failed", errors=errors)
    
    session.syntheses.append(synthesis)
    remaining = session.get_remaining_concepts()
    save_session_snapshot(session, "synthesis")
    
    logger.info(f"Recorded synthesis for '{divergent_concept}' in session {session.session_id}")
    
    if remaining:
        next_step = f"Record synthesis for remaining concepts: {remaining}"
    else:
        next_step = "All syntheses complete. Call reflect_on_session to finish."
    
    return _ok(
        session_id=session.session_id,
        recorded=divergent_concept,
        connection_type=connection_type,
        confidence=confidence_val,
        syntheses_completed=len(session.syntheses),
        syntheses_required=len(session.divergent_concepts),
        remaining_concepts=remaining,
        next_step=next_step,
    )


# -----------------------------------------------------------------------------
# Tool: reflect_on_session
# -----------------------------------------------------------------------------

async def tool_reflect_on_session(args: dict) -> list[TextContent]:
    """
    Record meta-reflection after all syntheses are complete.
    
    Args:
        most_valuable_insight: Which synthesis was most valuable
        why_valuable: Why it was valuable
        surprising_connections: List of concepts that yielded unexpected links
        overall_rating: Float 0.0-1.0, how productive was this session
        session_id: Optional session ID (uses current session if not provided)
    """
    logger.debug(f"tool_reflect_on_session called with args: {args}")
    
    session_id = args.get("session_id")
    if session_id:
        session = SESSIONS.get(session_id)
    else:
        session = get_current_session()
    
    if not session:
        return _err("no_session", "No active session. Call start_session first.")
    
    if not session.is_synthesis_complete():
        remaining = session.get_remaining_concepts()
        return _err(
            "synthesis_incomplete",
            f"All {len(session.divergent_concepts)} syntheses must be recorded before reflection",
            completed=len(session.syntheses),
            required=len(session.divergent_concepts),
            remaining_concepts=remaining,
        )
    
    if session.reflection:
        return _err("already_reflected", "Session already has a reflection recorded")
    
    # Validate required fields
    most_valuable = args.get("most_valuable_insight", "").strip()
    why_valuable = args.get("why_valuable", "").strip()
    surprising = args.get("surprising_connections", [])
    overall_rating = args.get("overall_rating")
    
    if not most_valuable:
        return _err("missing_most_valuable", "most_valuable_insight is required")
    if not why_valuable:
        return _err("missing_why_valuable", "why_valuable is required")
    if overall_rating is None:
        return _err("missing_rating", "overall_rating is required (0.0-1.0)")

    # Coerce and validate overall_rating early
    try:
        if isinstance(overall_rating, (int, float)):
            overall_rating_val = float(overall_rating)
        elif isinstance(overall_rating, str):
            overall_rating_val = float(overall_rating.strip())
        else:
            return _err("validation_error", "overall_rating must be numeric (0.0-1.0)")
    except ValueError:
        return _err("validation_error", "overall_rating must be numeric (0.0-1.0)")

    if not (0.0 <= overall_rating_val <= 1.0):
        return _err("validation_error", "overall_rating must be between 0.0 and 1.0", value=overall_rating_val)
    
    # Create and validate reflection
    reflection = SessionReflection(
        most_valuable_insight=most_valuable,
        why_valuable=why_valuable,
        surprising_connections=surprising if isinstance(surprising, list) else [surprising],
        overall_rating=overall_rating_val,
    )
    
    errors = reflection.validate()
    if errors:
        return _err("validation_error", "Reflection validation failed", errors=errors)
    
    session.reflection = reflection
    session.completed_at = datetime.now(timezone.utc).isoformat()
    save_session_snapshot(session, "reflection")
    
    # Save to history
    save_session_to_history(session)
    
    logger.info(f"Session {session.session_id} completed with rating {overall_rating_val}")
    
    return _ok(
        session_id=session.session_id,
        completed=True,
        completed_at=session.completed_at,
        overall_rating=overall_rating_val,
        summary={
            "origin": session.origin,
            "divergent_concepts": session.divergent_concepts,
            "syntheses_count": len(session.syntheses),
            "most_valuable": most_valuable,
        },
    )


# -----------------------------------------------------------------------------
# Tool: get_session
# -----------------------------------------------------------------------------

async def tool_get_session(args: dict) -> list[TextContent]:
    """
    Retrieve the current session state.
    
    Args:
        session_id: Optional session ID (uses current session if not provided)
    """
    logger.debug(f"tool_get_session called with args: {args}")
    
    session_id = args.get("session_id")
    if session_id:
        session = SESSIONS.get(session_id)
    else:
        session = get_current_session()
    
    if not session:
        return _err("no_session", "No active session found")
    
    return _ok(
        session=session.to_dict(),
        status={
            "has_divergence": len(session.divergent_concepts) > 0,
            "syntheses_completed": len(session.syntheses),
            "syntheses_required": len(session.divergent_concepts),
            "remaining_concepts": session.get_remaining_concepts(),
            "synthesis_complete": session.is_synthesis_complete(),
            "has_reflection": session.reflection is not None,
            "fully_complete": session.is_complete(),
        },
    )


# -----------------------------------------------------------------------------
# Tool: list_sessions
# -----------------------------------------------------------------------------

async def tool_list_sessions(args: dict) -> list[TextContent]:
    """
    List all sessions (in-memory and from history).
    
    Args:
        include_history: Whether to include completed sessions from disk (default: false)
        limit: Maximum number of sessions to return (default: 20)
    """
    logger.debug(f"tool_list_sessions called with args: {args}")
    
    limit = args.get("limit", 20)
    include_history = args.get("include_history", False)
    
    sessions = []
    
    # Add in-memory sessions
    for session in SESSIONS.values():
        sessions.append({
            "session_id": session.session_id,
            "origin": session.origin[:100] + ("..." if len(session.origin) > 100 else ""),
            "method": session.method,
            "created_at": session.created_at,
            "completed_at": session.completed_at,
            "is_complete": session.is_complete(),
            "source": "memory",
        })
    
    # Load from history if requested
    if include_history:
        history_sessions = load_sessions_from_history(limit=limit)
        # Deduplicate (prefer memory version if exists)
        memory_ids = {s["session_id"] for s in sessions}
        for h_session in history_sessions:
            if h_session.session_id not in memory_ids:
                sessions.append({
                    "session_id": h_session.session_id,
                    "origin": h_session.origin[:100] + ("..." if len(h_session.origin) > 100 else ""),
                    "method": h_session.method,
                    "created_at": h_session.created_at,
                    "completed_at": h_session.completed_at,
                    "is_complete": h_session.is_complete(),
                    "source": "history",
                })
    
    # Sort by created_at descending
    sessions.sort(key=lambda s: s["created_at"], reverse=True)

    current_session = get_current_session()
    return _ok(
        sessions=sessions[:limit],
        total=len(sessions),
        limit=limit,
        current_session_id=current_session.session_id if current_session else None,
    )


# -----------------------------------------------------------------------------
# Tool Registry
# -----------------------------------------------------------------------------

TOOL_HANDLERS = {
    "start_session": tool_start_session,
    "generate_divergence": tool_generate_divergence,
    "record_synthesis": tool_record_synthesis,
    "reflect_on_session": tool_reflect_on_session,
    "get_session": tool_get_session,
    "list_sessions": tool_list_sessions,
}
