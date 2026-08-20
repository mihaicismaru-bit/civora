from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Mapping, Sequence, Set


NODE_TYPES = {"cause", "need", "effect", "intervention", "output", "result", "indicator"}
RELATION_TYPES = {"CAUSES", "LEADS_TO", "TARGETS", "PRODUCES", "CONTRIBUTES_TO", "MEASURED_BY"}
ALLOWED_EDGE_TYPES = {
    "CAUSES": {("cause", "need")},
    "LEADS_TO": {("need", "effect")},
    "TARGETS": {("intervention", "cause"), ("intervention", "need")},
    "PRODUCES": {("intervention", "output")},
    "CONTRIBUTES_TO": {("output", "result")},
    "MEASURED_BY": {("result", "indicator")},
}
EVIDENCE_REQUIRED_RELATIONS = {"CAUSES", "LEADS_TO"}


def _cycle_nodes(adjacency: Mapping[str, Sequence[str]]) -> List[str]:
    state: Dict[str, int] = {}
    stack: List[str] = []
    cycle: List[str] = []

    def visit(node: str) -> bool:
        state[node] = 1
        stack.append(node)
        for nxt in adjacency.get(node, []):
            if state.get(nxt, 0) == 0:
                if visit(nxt):
                    return True
            elif state.get(nxt) == 1:
                start = stack.index(nxt)
                cycle.extend(stack[start:] + [nxt])
                return True
        stack.pop()
        state[node] = 2
        return False

    for node in sorted(adjacency):
        if state.get(node, 0) == 0 and visit(node):
            break
    return cycle


def validate_causal_graph(graph: Mapping[str, Any]) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    node_by_id: Dict[str, Mapping[str, Any]] = {}

    for index, node in enumerate(nodes):
        node_id = str(node.get("id") or "")
        node_type = node.get("type")
        if not node_id:
            failures.append({"node_index": index, "failure": "missing_node_id"})
            continue
        if node_id in node_by_id:
            failures.append({"node_id": node_id, "failure": "duplicate_node_id"})
            continue
        if node_type not in NODE_TYPES:
            failures.append({"node_id": node_id, "failure": "invalid_node_type", "value": node_type})
        node_by_id[node_id] = node

    adjacency: Dict[str, List[str]] = defaultdict(list)
    cause_targets: Set[str] = set()
    indicator_targets: Set[str] = set()

    for index, edge in enumerate(edges):
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        relation = edge.get("relation")
        if source not in node_by_id or target not in node_by_id:
            failures.append({"edge_index": index, "failure": "unknown_node_reference", "source": source, "target": target})
            continue
        if relation not in RELATION_TYPES:
            failures.append({"edge_index": index, "failure": "invalid_relation", "value": relation})
            continue
        source_type = node_by_id[source].get("type")
        target_type = node_by_id[target].get("type")
        if (source_type, target_type) not in ALLOWED_EDGE_TYPES[relation]:
            failures.append({
                "edge_index": index,
                "failure": "invalid_edge_type",
                "relation": relation,
                "source_type": source_type,
                "target_type": target_type,
            })
        if relation in EVIDENCE_REQUIRED_RELATIONS and not edge.get("evidence_ids"):
            failures.append({"edge_index": index, "failure": "causal_edge_without_evidence", "relation": relation})
        adjacency[source].append(target)
        if relation == "CAUSES":
            cause_targets.add(target)
        if relation == "MEASURED_BY":
            indicator_targets.add(target)

    cycle = _cycle_nodes(adjacency)
    if cycle:
        failures.append({"failure": "causal_graph_cycle", "cycle": cycle})

    for node_id, node in node_by_id.items():
        if node.get("type") == "need" and node.get("priority", False) and node_id not in cause_targets:
            if node.get("cause_status") == "not_established":
                warnings.append({"node_id": node_id, "warning": "priority_need_cause_not_established"})
            else:
                failures.append({"node_id": node_id, "failure": "priority_need_without_cause_or_explicit_gap"})
        if node.get("type") == "indicator" and node_id not in indicator_targets:
            warnings.append({"node_id": node_id, "warning": "indicator_not_linked_to_result"})

    return {
        "schema_version": "nf.causal_validation.v0.1",
        "valid": not failures,
        "failures": failures,
        "warnings": warnings,
        "node_count": len(node_by_id),
        "edge_count": len(edges),
    }
