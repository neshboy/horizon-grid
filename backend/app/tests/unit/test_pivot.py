"""Unit tests for app.evidence.pivot.rank_pivots -- the pure, non-AI ranking
behind GET /lookup/{id}/pivots and the "Recommended pivots" panel.
"""
from app.evidence.pivot import EdgeLike, rank_pivots

SEED = "1.2.3.4"


def edge(**overrides) -> EdgeLike:
    defaults = dict(
        source_value=SEED, source_type="ipv4", target_value="evil.test", target_type="domain",
        relationship_type="resolves_to", confidence=0.7, provenance="virustotal",
    )
    defaults.update(overrides)
    return EdgeLike(**defaults)


def test_only_seed_touching_edges_are_included():
    edges = [
        edge(),  # touches seed
        edge(source_value="other.test", source_type="domain", target_value="another.test", target_type="domain"),  # doesn't touch seed
    ]
    pivots = rank_pivots(SEED, edges)
    assert len(pivots) == 1
    assert pivots[0]["ioc_value"] == "evil.test"


def test_inbound_edge_pivots_to_source_not_target():
    # seed is the TARGET here -- the pivot should be the source.
    e = edge(source_value="185.1.1.1", source_type="ipv4", target_value=SEED, target_type="ipv4", relationship_type="resolves_to")
    pivots = rank_pivots(SEED, [e])
    assert pivots[0]["ioc_value"] == "185.1.1.1"
    assert pivots[0]["ioc_type"] == "ipv4"


def test_multi_provider_corroboration_ranks_above_single_provider_high_confidence():
    corroborated = edge(target_value="a.test", confidence=0.7, provenance="virustotal,otx")
    single_high_conf = edge(target_value="b.test", confidence=0.95, provenance="virustotal")
    pivots = rank_pivots(SEED, [single_high_conf, corroborated])
    assert pivots[0]["ioc_value"] == "a.test"  # corroboration (2 providers) outranks raw confidence


def test_relevance_high_when_multi_provider_or_very_high_confidence():
    multi = edge(target_value="a.test", confidence=0.5, provenance="virustotal,otx")
    high_conf = edge(target_value="b.test", confidence=0.9, provenance="virustotal")
    pivots = rank_pivots(SEED, [multi, high_conf])
    assert {p["ioc_value"]: p["relevance"] for p in pivots} == {"a.test": "high", "b.test": "high"}


def test_relevance_medium_and_low_bands():
    medium = edge(target_value="a.test", confidence=0.65, provenance="virustotal")
    low = edge(target_value="b.test", confidence=0.3, provenance="virustotal")
    pivots = rank_pivots(SEED, [medium, low])
    assert {p["ioc_value"]: p["relevance"] for p in pivots} == {"a.test": "medium", "b.test": "low"}


def test_limit_is_respected_and_clamped():
    edges = [edge(target_value=f"host{i}.test", confidence=0.5 + i * 0.01) for i in range(20)]
    assert len(rank_pivots(SEED, edges, limit=5)) == 5
    assert len(rank_pivots(SEED, edges, limit=1000)) == 20  # clamped to available, but capped internally at 50
    assert len(rank_pivots(SEED, edges, limit=0)) == 1  # clamped to at least 1


def test_case_insensitive_seed_matching():
    e = edge(source_value=SEED.upper())
    pivots = rank_pivots(SEED, [e])
    assert len(pivots) == 1


def test_no_edges_returns_empty_list():
    assert rank_pivots(SEED, []) == []
