"""Pure ranking function behind GET /lookup/{id}/pivots -- deliberately NOT
AI-generated (a pure sort over real correlation edges can never hallucinate a
pivot target). Split out from app/api/routes/pivot.py so the ranking logic is
unit-testable without a database.
"""
from dataclasses import dataclass


@dataclass
class EdgeLike:
    """Minimal shape needed from a CorrelationEdgeRecord row to rank pivots."""

    source_value: str
    source_type: str
    target_value: str
    target_type: str
    relationship_type: str
    confidence: float
    provenance: str


def rank_pivots(seed_value: str, edges: list[EdgeLike], limit: int = 10) -> list[dict]:
    seed_lower = seed_value.strip().lower()
    pivots = []
    for edge in edges:
        source_lower = edge.source_value.strip().lower()
        target_lower = edge.target_value.strip().lower()
        # Only surface edges directly touching the seed IOC as one-click
        # pivots -- multi-hop relationships belong in the graph, not this list.
        if source_lower != seed_lower and target_lower != seed_lower:
            continue
        is_outbound = source_lower == seed_lower
        target_type = edge.target_type if is_outbound else edge.source_type
        target_value = edge.target_value if is_outbound else edge.source_value
        provider_count = len([p for p in edge.provenance.split(",") if p])

        pivots.append(
            {
                "ioc_value": target_value,
                "ioc_type": target_type,
                "relationship": edge.relationship_type,
                "confidence": round(edge.confidence * 100, 1),
                "corroborating_providers": provider_count,
                "provenance": edge.provenance,
                "relevance": "high" if provider_count > 1 or edge.confidence >= 0.85 else (
                    "medium" if edge.confidence >= 0.6 else "low"
                ),
            }
        )

    pivots.sort(key=lambda p: (p["corroborating_providers"], p["confidence"]), reverse=True)
    return pivots[: max(1, min(limit, 50))]
