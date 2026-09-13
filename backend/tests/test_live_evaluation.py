from evidence_rag.live_evaluation import observation_from_events


def test_observation_from_answered_sse_events_keeps_documents_and_timings() -> None:
    events = [
        (
            "sources",
            {
                "sources": [
                    {"label": "S1", "original_filename": "checkpointers.md"},
                    {"label": "S2", "original_filename": "interrupts.md"},
                ]
            },
        ),
        ("delta", {"text": "A checkpoint stores state. [S1]"}),
        (
            "done",
            {
                "citation_labels": ["S1"],
                "retrieval_ms": 18.5,
                "generation_ms": 920.0,
                "total_ms": 941.2,
            },
        ),
    ]

    observation, row = observation_from_events("checkpoint-definition", events)

    assert observation.case_id == "checkpoint-definition"
    assert observation.retrieved_documents == ("checkpointers.md", "interrupts.md")
    assert observation.cited_documents == ("checkpointers.md",)
    assert observation.outcome == "answered"
    assert observation.retrieval_ms == 18.5
    assert observation.generation_ms == 920.0
    assert row["total_ms"] == 941.2
    assert row["answer"] == "A checkpoint stores state. [S1]"


def test_observation_from_refusal_sse_events_uses_empty_citations_and_no_generation_time() -> None:
    events = [
        ("sources", {"sources": []}),
        ("delta", {"text": "知识库中没有足够可靠的依据，无法回答该问题。"}),
        (
            "done",
            {
                "citation_labels": [],
                "retrieval_ms": 12.0,
                "generation_ms": None,
                "total_ms": 13.0,
            },
        ),
    ]

    observation, row = observation_from_events("calendar-refusal", events)

    assert observation.outcome == "refused"
    assert observation.retrieved_documents == ()
    assert observation.cited_documents == ()
    assert observation.generation_ms is None
    assert row["total_ms"] == 13.0
