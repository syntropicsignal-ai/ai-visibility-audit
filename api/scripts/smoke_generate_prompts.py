"""CLI smoke for the query generator (small parameters; writes to
tmp/smoke-<domain>.json).

    PYTHONPATH=. uv run python scripts/smoke_generate_prompts.py \\
        --domain example.com --pages 5 --competitors 2 --queries 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--domain", default="example.com")
    p.add_argument("--pages", type=int, default=5, help="Exa pages to fetch")
    p.add_argument("--competitors", type=int, default=2, help="Similar sites to fetch")
    p.add_argument("--queries", type=int, default=5, help="Final query count")
    p.add_argument(
        "--oversample",
        type=int,
        default=None,
        help="Candidate count to oversample before pruning (default: 2x queries for small runs)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path (default: tmp/smoke-<domain>.json)",
    )
    return p.parse_args()


async def _main() -> int:
    args = _parse_args()

    # Make the `app` package importable whether the user runs us with
    # `PYTHONPATH=.` or directly.
    here = Path(__file__).resolve().parent
    api_root = here.parent
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    from app.config import settings  # noqa: E402
    from app.services.query_generator import generate_prompt_set  # noqa: E402

    missing = [
        name
        for name, val in [
            ("GEMINI_API_KEY", settings.gemini_api_key),
            ("EXA_API_KEY", settings.exa_api_key),
        ]
        if not val
    ]
    if missing:
        print(f"ERROR: missing env vars: {', '.join(missing)}", file=sys.stderr)
        return 2

    print(
        f"Smoke run — domain={args.domain} pages={args.pages} "
        f"competitors={args.competitors} queries={args.queries}",
        flush=True,
    )
    t0 = time.time()
    result = await generate_prompt_set(
        domain=args.domain,
        num_queries=args.queries,
        max_competitors=args.competitors,
        max_pages=args.pages,
        oversample_size=args.oversample,
        db=None,  # smoke test — do not persist
    )
    elapsed = time.time() - t0

    # Summary to stdout
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  domain         : {result.get('domain')}")
    print(f"  pages_found    : {result.get('pages_found')}")
    profile = result.get("profile") or {}
    print(f"  brand_name     : {profile.get('brand_name')}")
    print(f"  language       : {profile.get('language')}")
    print(f"  country        : {profile.get('country')}")
    print(f"  currency       : {profile.get('currency')}")
    print(f"  distribution   : {profile.get('distribution')}")
    print(f"  competitors    : {len(result.get('competitors') or [])}")
    for c in result.get("competitors") or []:
        print(f"     - {c.get('name')} ({c.get('domain')})")
    queries = result.get("queries") or []
    print(f"  queries        : {len(queries)}")
    for i, q in enumerate(queries, 1):
        meta = (
            f"{q.get('intent'):<13} "
            f"{(q.get('length_mode') or '-'):<13} "
            f"{(q.get('buyer_stage') or '-'):<16} "
            f"shape={q.get('shape')}"
        )
        print(f"  [{i:>2}] {meta}")
        print(f"       {q.get('text')}")

    # Dump full JSON
    out_path = args.out
    if out_path is None:
        repo_root = api_root.parent
        out_dir = repo_root / "tmp"
        out_dir.mkdir(exist_ok=True)
        safe = args.domain.replace("/", "_").replace(":", "_")
        out_path = out_dir / f"smoke-{safe}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nFull JSON: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
