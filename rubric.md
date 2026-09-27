# Scoring rubric

Five dimensions. Every score needs an anchor it matches and a transcript span
that justifies it.

Two rules for any prompt that uses this file:

1. Emit the evidence span **before** the score. An unanchored 1–5 scale makes a
   model cluster everything at 4; forcing evidence first measurably spreads it.
2. Score only the dimensions a stage can speak to. An Approach turn cannot
   score implementation quality.

| Stage | Dimensions it can score |
| --- | --- |
| Intro | D5 |
| Problem | D1, D5 |
| Approach | D1, D2, D5 |
| Coding | D3 |
| Test run | D4, D5 |
| Code review | D2, D3, D5 |
| Deep dive | D5 |

---

## D1 · Problem comprehension

| Score | Anchor |
| --- | --- |
| 1 | Starts solving immediately. No clarifying questions. Misreads what is being asked. |
| 2 | Asks one surface question ("can I use Python?"). Restates the problem inaccurately. |
| 3 | Restates the problem correctly. Asks about one input constraint. |
| 4 | Asks about input size, edge cases, and confirms the expected output shape before starting. |
| 5 | Surfaces an ambiguity the statement genuinely contains. States assumptions explicitly, then proceeds. |

## D2 · Approach and trade-off reasoning

| Score | Anchor |
| --- | --- |
| 1 | No approach stated; starts typing. |
| 2 | Names one approach with no justification. Cannot state its complexity. |
| 3 | States a workable approach and its time complexity. |
| 4 | Compares two approaches, states both complexities, justifies the choice. |
| 5 | Names the constraint that decides between them ("n is 10^6, so O(n²) is out") and says what would change the choice. |

## D3 · Implementation quality

| Score | Anchor |
| --- | --- |
| 1 | Does not run, or abandoned halfway. |
| 2 | Runs but fails most tests. Unclear names, deep nesting. |
| 3 | Passes visible tests. Readable. Some duplication. |
| 4 | Passes all tests. Clear names. Edge cases handled deliberately, not accidentally. |
| 5 | Passes all tests, and the code reads as intentional — guard clauses, no dead paths, structure matches the stated approach. |

## D4 · Debugging and self-diagnosis

| Score | Anchor |
| --- | --- |
| 1 | Cannot say why a test failed. Asks to be shown the answer. |
| 2 | Guesses randomly. Adds try/except to suppress rather than fix. |
| 3 | Reads the failure, forms one hypothesis, tests it. |
| 4 | Predicts the class of failing input before seeing it ("probably empty input or a single element"). |
| 5 | Diagnoses correctly from the failure count alone, and states how they would prevent that class of bug. |

## D5 · Communication and evidence

| Score | Anchor |
| --- | --- |
| 1 | Long silences. Cannot narrate thinking. Answers do not address the question. |
| 2 | Narrates, but vaguely. Claims unquantified ("improved performance"). |
| 3 | Clear narration. Some claims backed. |
| 4 | Concise. Most claims carry a number or a concrete outcome. |
| 5 | Every claim carries evidence. Answers land in two or three sentences. Volunteers the trade-off unprompted. |
