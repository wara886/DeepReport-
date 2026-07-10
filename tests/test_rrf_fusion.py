from src.rag.rrf_fusion import reciprocal_rank_fusion


def test_rrf_fusion_promotes_hits_seen_by_multiple_retrievers():
    bm25 = [
        {"evidence_id": "ev_a", "score": 9, "bm25_score": 9},
        {"evidence_id": "ev_b", "score": 8, "bm25_score": 8},
    ]
    dense = [
        {"evidence_id": "ev_b", "score": 0.9, "vector_score": 0.9},
        {"evidence_id": "ev_c", "score": 0.8, "vector_score": 0.8},
    ]

    fused = reciprocal_rank_fusion([bm25, dense], topk=3, k=60)

    assert [item["evidence_id"] for item in fused] == ["ev_b", "ev_a", "ev_c"]
    assert fused[0]["rank_sources"] == ["bm25", "dense"]
    assert fused[0]["component_ranks"] == {"bm25": 2, "dense": 1}
    assert fused[0]["final_score"] == fused[0]["rrf_score"]
