import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_langgraph_live_acceptance_set_is_bounded_and_matches_demo_manifest() -> None:
    cases = [
        json.loads(line)
        for line in (ROOT / "evaluation" / "langgraph_live_acceptance_cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads((ROOT / "evaluation" / "langgraph_sources.json").read_text(encoding="utf-8"))
    official_filenames = {f"{item['id']}.md" for item in manifest["documents"]}

    assert len(cases) == 10
    assert sum(case["expect_refusal"] for case in cases) == 2
    assert len({case["id"] for case in cases}) == 10
    assert all(case["expected_documents"] for case in cases if not case["expect_refusal"])
    assert all(
        set(case["expected_documents"]).issubset(official_filenames)
        for case in cases
        if not case["expect_refusal"]
    )
