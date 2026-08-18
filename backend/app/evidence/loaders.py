"""Reconstructs in-memory correlation/evidence structures from persisted rows,
for routes that operate on an already-completed lookup (analysis, hunting,
pivot, copilot) rather than the live SSE stream that originally produced them.
"""
from app.correlation.engine import CorrelationResult, GraphEdge, GraphNode
from app.models.lookup import CorrelationEdgeRecord, IOCLookup


def correlation_from_records(lookup: IOCLookup, edges: list[CorrelationEdgeRecord]) -> CorrelationResult:
    nodes: dict[str, GraphNode] = {}
    graph_edges: list[GraphEdge] = []

    seed_node_id = f"{lookup.ioc_type}:{lookup.ioc_value.strip().lower()}"
    nodes[seed_node_id] = GraphNode(node_id=seed_node_id, ioc_type=lookup.ioc_type, value=lookup.ioc_value)

    for edge in edges:
        source_id = f"{edge.source_type}:{edge.source_value.strip().lower()}"
        target_id = f"{edge.target_type}:{edge.target_value.strip().lower()}"
        nodes.setdefault(source_id, GraphNode(node_id=source_id, ioc_type=edge.source_type, value=edge.source_value))
        nodes.setdefault(target_id, GraphNode(node_id=target_id, ioc_type=edge.target_type, value=edge.target_value))
        graph_edges.append(
            GraphEdge(
                source=source_id,
                target=target_id,
                relationship=edge.relationship_type,
                confidence=edge.confidence,
                provenance=edge.provenance,
                provenance_category=edge.provenance_category,
            )
        )

    return CorrelationResult(
        nodes=list(nodes.values()), edges=graph_edges, deduplicated_facts={}, provider_agreement={}
    )
