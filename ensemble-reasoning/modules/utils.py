from .models import EnsembleSession, CONFIG


def calculate_consensus(session: EnsembleSession, threshold: float = 0.6) -> dict:
    if len(session.thoughts) < 2:
        return {'consensus_thoughts': [], 'avg_agreement': 0.0}

    consensus_thoughts: list[dict] = []
    sum_endorsements = 0.0
    count_endorsements = 0

    for thought in session.thoughts:
        if not thought.endorsements:
            continue

        values = list(thought.endorsements.values())
        avg_endorsement = sum(values) / len(values)
        sum_endorsements += sum(values)
        count_endorsements += len(values)

        if avg_endorsement >= threshold:
            consensus_thoughts.append({
                'thought_id': thought.thought_id,
                'agent': thought.agent_lens,
                'thought': thought.thought[:100],
                'agreement': round(avg_endorsement, 2)
            })

    avg_agreement = (sum_endorsements / count_endorsements) if count_endorsements else 0.0

    return {
        'consensus_thoughts': consensus_thoughts,
        'avg_agreement': round(avg_agreement, 2)
    }


def identify_tensions(session: EnsembleSession) -> list[dict]:
    tensions = []

    for thought in session.thoughts:
        if not thought.endorsements:
            continue

        positive = [e for e in thought.endorsements.values() if e >= CONFIG.positive_endorsement_threshold]
        negative = [e for e in thought.endorsements.values() if e <= CONFIG.negative_endorsement_threshold]

        if positive and negative:
            tensions.append({
                'thought_id': thought.thought_id,
                'agent': thought.agent_lens,
                'thought': thought.thought[:100],
                'supporters': len(positive),
                'challengers': len(negative),
                'challenges': thought.challenges
            })

    return tensions


def compute_convergence_score(session: EnsembleSession) -> float:
    if len(session.thoughts) < 3:
        return 0.0

    total_endorsements = 0
    positive_endorsements = 0

    for thought in session.thoughts:
        for score in thought.endorsements.values():
            total_endorsements += 1
            if score >= CONFIG.positive_endorsement_threshold:
                positive_endorsements += 1

    if total_endorsements == 0:
        return 0.0

    return positive_endorsements / total_endorsements


def detect_cycles(session: EnsembleSession) -> list[list[int]]:
    """Detect cycles in thought dependencies (directed graph) using an iterative color DFS.

    Graph edges follow `builds_on`: thought_id -> dependency_id.
    Returns a de-duplicated list of cycles as lists of thought IDs.
    """

    # 0=unvisited, 1=visiting, 2=done
    color: dict[int, int] = {}
    parent: dict[int, int] = {}
    cycles_set: set[tuple[int, ...]] = set()

    def _normalize_cycle(cycle: list[int]) -> tuple[int, ...]:
        # normalize by rotation so the smallest id is first
        if not cycle:
            return tuple()
        m = min(cycle)
        i = cycle.index(m)
        rotated = cycle[i:] + cycle[:i]
        return tuple(rotated)

    for start in [t.thought_id for t in session.thoughts]:
        if color.get(start, 0) != 0:
            continue

        color[start] = 1
        parent.pop(start, None)

        # stack holds (node_id, next_child_index)
        stack: list[tuple[int, int]] = [(start, 0)]
        while stack:
            node, idx = stack[-1]
            thought = session.get_thought(node)
            deps = thought.builds_on if thought else []

            if idx >= len(deps):
                color[node] = 2
                stack.pop()
                continue

            dep = deps[idx]
            # advance index for this node
            stack[-1] = (node, idx + 1)

            dep_color = color.get(dep, 0)
            if dep_color == 0:
                parent[dep] = node
                color[dep] = 1
                stack.append((dep, 0))
                continue

            if dep_color == 1:
                # Back-edge found: reconstruct cycle dep -> ... -> node -> dep
                cycle = [dep]
                cur = node
                while cur != dep and cur in parent:
                    cycle.append(cur)
                    cur = parent[cur]
                if cur == dep:
                    # close cycle; current list is [dep, ..., node] (reverse order-ish)
                    cycle = list(reversed(cycle))
                    cycles_set.add(_normalize_cycle(cycle))

    return [list(c) for c in sorted(cycles_set)]


def format_convergence_map(session: EnsembleSession, consensus: dict, tensions: list[dict], convergence: float) -> str:
    lines = [
        "=" * 80,
        "ENSEMBLE CONVERGENCE MAP",
        "=" * 80,
        f"Problem: {session.problem}",
        f"Agents: {', '.join(session.agent_lenses)}",
        f"Thoughts: {len(session.thoughts)}",
        f"Convergence Score: {convergence:.2f}",
        "",
        "--- CONSENSUS AREAS ---"
    ]

    if consensus['consensus_thoughts']:
        for item in consensus['consensus_thoughts']:
            lines.append(f"[CONSENSUS] [{item['agent']}] {item['thought']}... (agreement: {item['agreement']})")
    else:
        lines.append("(No strong consensus yet)")

    lines.append("")
    lines.append("--- PRODUCTIVE TENSIONS ---")

    if tensions:
        for t in tensions:
            lines.append(f"[TENSION] [{t['agent']}] {t['thought']}...")
            lines.append(f"   {t['supporters']} support, {t['challengers']} challenge")
            if t['challenges']:
                for c in t['challenges'][:2]:
                    lines.append(f"   - {c['from_agent']}: {c['concern'][:80]}...")
    else:
        lines.append("(No major disagreements)")

    lines.append("")
    lines.append("--- AGENT CONTRIBUTIONS ---")

    for agent in session.agent_lenses:
        agent_thoughts = session.get_agent_thoughts(agent)
        avg_weight = sum(t.weight for t in agent_thoughts) / len(agent_thoughts) if agent_thoughts else 0
        lines.append(f"{agent}: {len(agent_thoughts)} thoughts, avg weight: {avg_weight:.2f}")

    lines.append("")
    lines.append("=" * 80)

    return "\n".join(lines)
