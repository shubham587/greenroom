"""Measure the scorer against the hand-scored cases.

    make eval                  # replay cassettes where possible, free
    make eval ARGS=--record    # call the model for real and re-record

What "agreement" means here, because the word is doing a lot of work:

  exact    the scorer produced the same number as the label
  within-1 the scorer was one off - a 3 labelled 4

within-1 is the headline. A 1-5 rubric scored by two careful people
disagrees by one all the time; disagreeing by two means they read the
anchors differently, which is the thing worth catching.

A case the scorer refuses to score at all counts as a miss, not as absent.
Silence is a failure mode, and one that would otherwise flatter the number.
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from greenroom import prompts
from greenroom.llm.client import get_llm
from greenroom.scoring import score

CASES = Path(__file__).parent / "cases.yaml"


async def run_case(llm, case: dict) -> dict:
    scores = await score(llm, case["stage"], case["question"], case["answer"])
    mine = next((s for s in scores if s.dimension == case["dimension"]), None)
    return {
        **case,
        "got": mine.score if mine else None,
        "evidence": mine.evidence_span if mine else "",
    }


async def main(argv: list[str]) -> int:
    # passed as an argument, not an environment variable: settings are read
    # once at import, so setting the variable here would be silently ignored
    # and every "free" run would quietly bill the API
    mode = "record" if "--record" in argv else "replay"

    cases = yaml.safe_load(CASES.read_text())
    llm = get_llm(cassette=mode)

    # sequential on purpose: cassette writes are not worth making concurrent
    results = [await run_case(llm, c) for c in cases]

    per_dim: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        per_dim[r["dimension"]].append(r)

    print(f"scorer prompt {prompts.version('scorer')}   {len(results)} cases\n")
    print(f"{'dim':<5}{'n':>4}{'exact':>8}{'within-1':>10}   worst miss")
    print("-" * 74)

    exact_all = within_all = 0
    for dim in sorted(per_dim):
        rows = per_dim[dim]
        exact = sum(1 for r in rows if r["got"] == r["expected"])
        within = sum(1 for r in rows if r["got"] is not None and abs(r["got"] - r["expected"]) <= 1)
        exact_all += exact
        within_all += within

        misses = [r for r in rows if r["got"] is None or abs(r["got"] - r["expected"]) > 1]
        worst = ""
        if misses:
            m = max(misses, key=lambda r: abs((r["got"] or 0) - r["expected"]))
            worst = f"{m['id']} wanted {m['expected']}, got {m['got']}"
        print(
            f"{dim:<5}{len(rows):>4}{exact / len(rows):>7.0%}{within / len(rows):>10.0%}   {worst}"
        )

    n = len(results)
    print("-" * 74)
    print(f"{'all':<5}{n:>4}{exact_all / n:>7.0%}{within_all / n:>10.0%}")

    unscored = [r["id"] for r in results if r["got"] is None]
    if unscored:
        print(f"\nnot scored at all ({len(unscored)}): {', '.join(unscored)}")

    print("\nevery miss:")
    for r in results:
        if r["got"] is None or abs(r["got"] - r["expected"]) > 1:
            print(f"  {r['id']:<26} wanted {r['expected']}  got {r['got']}")
            print(f"    label: {r['why']}")
            if r["evidence"]:
                print(f"    cited: {r['evidence'][:66]!r}")

    agreement = exact_all / n
    print(f"\ngate: EXACT agreement >= 80%   ->   {agreement:.0%}")
    print(f"      (within-1 is {within_all / n:.0%}; it reads 100% even when sabotaged)")
    print("PASS" if agreement >= 0.80 else "FAIL")
    return 0 if agreement >= 0.80 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
