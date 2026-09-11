import json
from pathlib import Path

from evidence_rag.evaluation import load_gold_cases


ROOT = Path(__file__).resolve().parents[2]


def test_controlled_gold_set_has_40_cases_and_safe_refusals() -> None:
    cases = load_gold_cases(ROOT / "evaluation" / "gold_cases.jsonl")

    assert len(cases) == 40
    assert len({case.id for case in cases}) == 40
    assert sum(case.expect_refusal for case in cases) >= 6


def test_langgraph_manifest_is_bounded_to_official_markdown_sources() -> None:
    manifest = json.loads((ROOT / "evaluation" / "langgraph_sources.json").read_text(encoding="utf-8"))

    assert manifest["captured_at"] == "2026-09-10"
    assert 30 <= len(manifest["documents"]) <= 50
    assert all(item["url"].startswith("https://docs.langchain.com/oss/python/langgraph/") for item in manifest["documents"])
    assert all(item["url"].endswith(".md") for item in manifest["documents"])
