from agent.architecture_playbook import ARCHITECTURE_CHECKLIST, build_evidence_bundle


def test_playbook_covers_supplied_ai_and_engineering_principles():
    areas = {area for area, _question in ARCHITECTURE_CHECKLIST}

    assert {
        "platform_boundary",
        "model_strategy",
        "model_lifecycle",
        "data",
        "memory",
        "evaluation",
        "safety_and_security",
        "write_boundary",
        "latency_and_cost",
        "reliability",
        "deployment",
    }.issubset(areas)


def test_evidence_bundle_reuses_one_scenario_retrieval_result():
    chunks = [
        {"chapter": 3, "page_number": 42, "section": "Evaluation", "text": "Measure the system."},
    ]
    bundle = build_evidence_bundle({
        "rag_chunks": chunks,
        "retrieval_relevance": "strong",
        "research_context": "",
    })

    assert len(bundle["book_evidence"]) == 1
    assert bundle["book_evidence"][0]["text"] == "Measure the system."
    assert len(bundle["checklist"]) == len(ARCHITECTURE_CHECKLIST)
