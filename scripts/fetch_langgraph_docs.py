"""限速抓取已审核的 LangGraph Markdown 来源；下载正文默认落在被 Git 忽略的 data/ 目录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


def load_sources(manifest_path: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest["documents"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("来源清单中没有文档")
    for source in sources:
        url = source.get("url", "")
        if not url.startswith("https://docs.langchain.com/oss/python/langgraph/") or not url.endswith(".md"):
            raise ValueError(f"拒绝非官方 Markdown 来源：{url}")
    return sources


def fetch_sources(sources: list[dict], output_dir: Path, min_interval_seconds: float) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "EvidenceRAGWorkbench/0.1"}) as client:
        for index, source in enumerate(sources):
            if index:
                time.sleep(min_interval_seconds)
            response = client.get(source["url"])
            response.raise_for_status()
            content = response.content
            if len(content) > 5 * 1024 * 1024:
                raise ValueError(f"来源过大，已停止：{source['url']}")
            destination = output_dir / f"{source['id']}.md"
            destination.write_bytes(content)
            records.append({**source, "downloaded_at": datetime.now(UTC).isoformat(), "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
    result = {"source_manifest": "langgraph_sources.json", "records": records}
    (output_dir / "download_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("evaluation/langgraph_sources.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/demo/langgraph"))
    parser.add_argument("--min-interval-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.min_interval_seconds < 1:
        raise ValueError("限速间隔不得小于 1 秒")
    result = fetch_sources(load_sources(args.manifest), args.output_dir, args.min_interval_seconds)
    print(f"已下载 {len(result['records'])} 篇官方 Markdown 到 {args.output_dir}")


if __name__ == "__main__":
    main()
