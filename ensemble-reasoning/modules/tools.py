import json
import logging
import sys
import time
from collections import deque
from uuid import uuid4

from mcp.types import TextContent

from . import models
from .utils import (
    calculate_consensus,
    identify_tensions,
    compute_convergence_score,
    detect_cycles,
    format_convergence_map,
)

logger = logging.getLogger("ensemble_reasoning.tools")


def _ok(**payload) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"status": "success", "result": payload}))]


def _err(error: str, message: str | None = None, **payload) -> list[TextContent]:
    body: dict = {"status": "error", "error": error}
    if message is not None:
        body["message"] = message
    if payload:
        body["details"] = payload
    return [TextContent(type="text", text=json.dumps(body))]


async def tool_start_collaborative(args: dict) -> list[TextContent]:
    logger.debug("start_collaborative args=%s", args)
    problem = args["problem"]
    agent_lenses = args["agentLenses"]

    invalid = [a for a in agent_lenses if a not in models.AGENT_LENSES]
    if invalid:
        return _err("invalid_agent_lenses", invalid=invalid)

    if len(agent_lenses) < 2:
        return _err("insufficient_agents", message="Need at least 2 agent lenses for collaboration")

    session_id = str(uuid4())
    session = models.EnsembleSession(session_id, problem, agent_lenses)
    models.active_sessions[session_id] = session
    models.current_session_id = session_id
    models.log_session_event(session, "start", {"problem": problem, "agent_lenses": agent_lenses})

    if models.CONSOLE_OUTPUT:
        print(f"\n[mcp] started ensemble session with {len(agent_lenses)} agents", file=sys.stderr)
        print(f"[mcp] problem: {problem[:80]}...", file=sys.stderr)

    lens_info = {lens: models.AGENT_LENSES[lens] for lens in agent_lenses}

    return _ok(sessionId=session_id, problem=problem, agentLenses=agent_lenses, lensDescriptions=lens_info)


async def tool_contribute(args: dict) -> list[TextContent]:
    logger.debug("contribute args=%s", args)
    session_id = args.get("sessionId") or models.current_session_id
    if not session_id or session_id not in models.active_sessions:
        return _err("no_active_session")

    session = models.active_sessions[session_id]
    agent_lens = args["agentLens"]
    if agent_lens not in session.agent_lenses:
        return _err("agent_not_in_session", agentLens=agent_lens)

    # Rate limiter enforcement (scoped per session)
    if models.is_rate_limited(session.session_id, agent_lens):
        return _err("rate_limited", agentLens=agent_lens)

    thought_text = args["thought"]
    if len(thought_text) > models.CONFIG.max_thought_length:
        return _err(
            "thought_too_long",
            message=f"Thought exceeds {models.CONFIG.max_thought_length} characters",
            maxLength=models.CONFIG.max_thought_length,
        )

    builds_on = args.get("buildsOn", [])
    for tid in builds_on:
        if not session.get_thought(tid):
            return _err("invalid_buildsOn", thoughtId=tid)

    weight = max(0.0, min(1.0, args.get("weight", 1.0)))

    thought = models.CollaborativeThought(
        thought_id=0,
        thought=thought_text,
        agent_lens=agent_lens,
        builds_on=builds_on,
        weight=weight
    )

    start = time.perf_counter()
    thought_id = session.add_thought(thought)
    # record operation for rate limiting
    models.record_agent_op(session.session_id, agent_lens)
    models.log_session_event(session, "contribute", {"thought": thought.to_dict()})

    if models.CONSOLE_OUTPUT:
        print(f"\n[mcp] [{agent_lens}] thought #{thought_id}", file=sys.stderr)
        if builds_on:
            print(f"[mcp] buildsOn: {builds_on}", file=sys.stderr)

    return _ok(thoughtId=thought_id, agentLens=agent_lens, buildsOn=builds_on, weight=weight)


async def tool_endorse_challenge(args: dict) -> list[TextContent]:
    logger.debug("endorse_or_challenge args=%s", args)
    session_id = args.get("sessionId") or models.current_session_id
    if not session_id or session_id not in models.active_sessions:
        return _err("no_active_session")

    session = models.active_sessions[session_id]
    thought_id = args["thoughtId"]
    agent_lens = args["agentLens"]
    endorsement_level = max(-1.0, min(1.0, args["endorsementLevel"]))
    note = args.get("note", "")

    thought = session.get_thought(thought_id)
    if not thought:
        return _err("thought_not_found", thoughtId=thought_id)

    if agent_lens not in session.agent_lenses:
        return _err("agent_not_in_session", agentLens=agent_lens)

    # Rate limiter enforcement (scoped per session)
    if models.is_rate_limited(session.session_id, agent_lens):
        return _err("rate_limited", agentLens=agent_lens)

    if note and len(note) > models.CONFIG.max_note_length:
        return _err(
            "note_too_long",
            message=f"Note exceeds {models.CONFIG.max_note_length} characters",
            maxLength=models.CONFIG.max_note_length,
        )

    if agent_lens == thought.agent_lens:
        return _err("self_endorsement_not_allowed")

    if len(thought.endorsements) >= models.CONFIG.max_endorsements_per_thought:
        return _err("max_endorsements_reached", maxEndorsements=models.CONFIG.max_endorsements_per_thought)

    start = time.perf_counter()
    thought.endorsements[agent_lens] = endorsement_level
    if endorsement_level < 0 and note:
        thought.challenges.append({
            "from_agent": agent_lens,
            "concern": note,
            "level": endorsement_level
        })

    if models.CONSOLE_OUTPUT:
        tag = "endorse" if endorsement_level > 0.3 else "challenge" if endorsement_level < -0.3 else "neutral"
        print(f"\n[mcp] [{agent_lens}] {tag} thought #{thought_id}: {endorsement_level:+.2f}", file=sys.stderr)

    models.record_agent_op(session.session_id, agent_lens)
    models.log_session_event(session, "endorse_challenge", {
        "thought_id": thought_id,
        "agent_lens": agent_lens,
        "endorsement_level": endorsement_level,
        "note": note
    })

    return _ok(
        thoughtId=thought_id,
        agentLens=agent_lens,
        endorsementLevel=endorsement_level,
        totalEndorsements=len(thought.endorsements),
    )


async def tool_synthesize(args: dict) -> list[TextContent]:
    logger.debug("synthesize args=%s", args)
    session_id = args.get("sessionId") or models.current_session_id
    if not session_id or session_id not in models.active_sessions:
        return _err("no_active_session")

    session = models.active_sessions[session_id]
    threshold = args.get("threshold", models.CONFIG.default_synthesis_threshold)
    start = time.perf_counter()

    consensus = calculate_consensus(session, threshold)
    tensions = identify_tensions(session)
    convergence = compute_convergence_score(session)
    cycles = detect_cycles(session)

    synthesis = {
        "sessionId": session_id,
        "convergenceScore": round(convergence, 2),
        "consensus": consensus,
        "tensions": tensions,
        "circularReasoning": cycles,
        "totalThoughts": len(session.thoughts),
        "agentContributions": {agent: len(session.get_agent_thoughts(agent)) for agent in session.agent_lenses}
    }

    if models.CONSOLE_OUTPUT:
        print(
            f"\n[mcp] synthesis: convergence={convergence:.2f} consensus={len(consensus['consensus_thoughts'])} tensions={len(tensions)}",
            file=sys.stderr,
        )
    models.log_session_event(session, "synthesize", {"convergence_score": convergence, "tensions": tensions})

    return _ok(**synthesis)


async def tool_propose_integration(args: dict) -> list[TextContent]:
    logger.debug("propose_integration args=%s", args)
    session_id = args.get("sessionId") or models.current_session_id
    if not session_id or session_id not in models.active_sessions:
        return _err("no_active_session")

    session = models.active_sessions[session_id]
    agent_lens = args["agentLens"]
    integration = args["integration"]
    reconciles = args["reconciles"]

    if agent_lens not in session.agent_lenses:
        return _err("agent_not_in_session", agentLens=agent_lens)

    # Rate limiter enforcement (scoped per session)
    if models.is_rate_limited(session.session_id, agent_lens):
        return _err("rate_limited", agentLens=agent_lens)

    if len(integration) > models.CONFIG.max_integration_length:
        return _err(
            "integration_too_long",
            message=f"Integration exceeds {models.CONFIG.max_integration_length} characters",
            maxLength=models.CONFIG.max_integration_length,
        )

    if not isinstance(reconciles, list):
        return _err("invalid_reconciles", message="reconciles must be a list of thought IDs")

    if len(reconciles) > models.CONFIG.max_reconciles_per_integration:
        return _err(
            "too_many_reconciles",
            message=f"Reconciles exceeds {models.CONFIG.max_reconciles_per_integration} items",
            maxItems=models.CONFIG.max_reconciles_per_integration,
        )

    for tid in reconciles:
        if not isinstance(tid, int):
            return _err("invalid_reconciles", message="reconciles must contain integers", thoughtId=tid)

        if not session.get_thought(tid):
            return _err("invalid_reconciles", thoughtId=tid)

    proposal = models.IntegrationProposal(
        proposal_id=0,
        proposing_agent=agent_lens,
        integration=integration,
        reconciles=reconciles
    )

    proposal_id = session.add_integration(proposal)
    # record operation for rate limiting
    models.record_agent_op(session.session_id, agent_lens)
    models.log_session_event(session, "propose_integration", {"proposal": proposal.to_dict()})
    if models.CONSOLE_OUTPUT:
        print(f"\n[mcp] [{agent_lens}] proposes integration #{proposal_id}", file=sys.stderr)
        print(f"[mcp] reconciles: {reconciles}", file=sys.stderr)

    return _ok(proposalId=proposal_id, agentLens=agent_lens, reconciles=reconciles)


async def tool_convergence_map(args: dict) -> list[TextContent]:
    logger.debug("convergence_map args=%s", args)
    session_id = args.get("sessionId") or models.current_session_id
    if not session_id or session_id not in models.active_sessions:
        return _err("no_active_session")

    session = models.active_sessions[session_id]
    consensus = calculate_consensus(session)
    tensions = identify_tensions(session)
    convergence = compute_convergence_score(session)

    map_text = format_convergence_map(session, consensus, tensions, convergence)
    return _ok(
        sessionId=session_id,
        convergenceScore=round(convergence, 2),
        mapText=map_text,
    )


async def tool_get_metrics(args: dict) -> list[TextContent]:
    logger.debug("get_metrics args=%s", args)
    if not models.CONFIG.enable_metrics:
        return _err("metrics_disabled")

    with models._metrics_lock:
        counters = dict(models.METRICS["counters"])
        avg_latencies = {}
        for k, samples in models.METRICS["latencies"].items():
            avg_latencies[k] = (sum(samples) / len(samples)) if samples else None

    return _ok(
        counters=counters,
        avg_latencies_seconds=avg_latencies,
        config={
            "max_thoughts_per_session": models.CONFIG.max_thoughts_per_session,
            "max_endorsements_per_thought": models.CONFIG.max_endorsements_per_thought,
            "default_synthesis_threshold": models.CONFIG.default_synthesis_threshold,
        },
    )


async def tool_get_rate_status(args: dict) -> list[TextContent]:
    """Return current per-agent rate limiter states (counts in window)."""
    logger.debug("get_rate_status args=%s", args)
    status: dict[str, dict[str, int]] = {}

    now = time.time()
    cutoff = now - models.CONFIG.rate_limit_window_seconds
    with models._agent_ops_lock:
        for session_id, per_agent in models._agent_session_ops.items():
            session_status: dict[str, int] = {}
            for agent, dq in per_agent.items():
                while dq and dq[0] < cutoff:
                    dq.popleft()
                session_status[agent] = len(dq)
            status[session_id] = session_status

    return _ok(rateStatus=status)


async def tool_reset_agent_rate(args: dict) -> list[TextContent]:
    """Admin tool: reset/clear the rate window for a given agent lens."""
    logger.debug("reset_agent_rate args=%s", args)
    agent_lens = args.get("agentLens")
    session_id = args.get("sessionId")
    if not agent_lens:
        return _err("missing_agentLens")

    with models._agent_ops_lock:
        if session_id:
            models._agent_session_ops[session_id][agent_lens].clear()
        else:
            for per_agent in models._agent_session_ops.values():
                per_agent[agent_lens].clear()

    if models.CONSOLE_OUTPUT:
        scope = f"session {session_id}" if session_id else "all sessions"
        print(f"[mcp] admin: reset rate window for {agent_lens} ({scope})", file=sys.stderr)

    return _ok(agentLens=agent_lens)


async def tool_get_active_session(args: dict) -> list[TextContent]:
    logger.debug("get_active_session args=%s", args)
    if not models.current_session_id or models.current_session_id not in models.active_sessions:
        return _err("no_active_session")

    session = models.active_sessions[models.current_session_id]
    return _ok(session=session.to_dict())
