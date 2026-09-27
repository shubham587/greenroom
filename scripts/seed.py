"""Verify the problem bank. A problem that fails this never reaches a candidate.

Two checks, and the second is the one that matters.

1. The reference solution passes every test. A test the reference fails is a
   wrong test, and a wrong test tells a candidate their correct code is broken.

2. Every deliberate mutation of the reference is caught by at least one test.
   A suite that passes a reference and also passes an off-by-one version of it
   is not testing anything. This is what stops a bank of tests that only
   check the happy path.

    uv run python scripts/seed.py problems/
    uv run python scripts/seed.py problems/ --verify   # same, for CI
"""

from __future__ import annotations

import sys
from pathlib import Path

from greenroom.problems import Problem, Test, load_all

# Each mutation is a plausible bug, not random damage. If no test notices the
# guard clause vanishing, the suite has no edge coverage.
MUTATIONS: list[tuple[str, str, str]] = [
    ("strict-inequality", "<=", "<"),
    ("drop-max", "max(", "min("),
    ("off-by-one-slice", "[1:]", "[:]"),
    ("flip-sort", "sorted(", "reversed("),
    ("drop-empty-guard", "if not intervals:", "if False:"),
    ("drop-dict-default", ".get(n, 0)", ".get(n, 0) * 0"),
    ("skip-move", "move_to_end", "get"),
]


def run_python(source: str, entry: str, test: Test) -> tuple[bool, object]:
    scope: dict = {}
    try:
        exec(source, scope)  # noqa: S102 - our own reference code, not user input
        got = scope[entry](*test.input)
        return got == test.expected, got
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def entry_name(problem: Problem) -> str:
    sig = problem.signature["python"]
    return sig.split("def ", 1)[1].split("(", 1)[0].strip()


def check(problem: Problem) -> list[str]:
    failures: list[str] = []
    ref = problem.reference["python"]
    entry = entry_name(problem)

    # 1. the reference must pass everything
    for t in problem.tests:
        ok, got = run_python(ref, entry, t)
        if not ok:
            failures.append(f"reference fails {t.name}: expected {t.expected!r}, got {got!r}")

    # 2. every applicable mutation must be caught
    applied = 0
    for name, before, after in MUTATIONS:
        if before not in ref or name in problem.equivalent_mutations:
            continue
        applied += 1
        broken = ref.replace(before, after, 1)
        caught = [t.name for t in problem.tests if not run_python(broken, entry, t)[0]]
        if not caught:
            failures.append(f"no test catches mutation '{name}' - the suite is too weak")

    if applied == 0:
        failures.append("no mutation applied; this problem is not being mutation-checked")

    return failures


def main(directory: str, _verify: bool = False) -> int:
    problems = load_all(directory)
    if not problems:
        print(f"no problems found in {directory}")
        return 1

    bad = 0
    for p in problems:
        failures = check(p)
        visible = len(p.visible_tests)
        hidden = len(p.hidden_tests)
        if failures:
            bad += 1
            print(f"FAIL {p.id}")
            for f in failures:
                print(f"       {f}")
        else:
            print(f"ok   {p.id:<18} {visible} visible / {hidden} hidden   [{p.difficulty}]")

    print(f"\n{len(problems) - bad}/{len(problems)} problems usable")
    return 1 if bad else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    raise SystemExit(main(args[0] if args else str(Path("problems"))))
