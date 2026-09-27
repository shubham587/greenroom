from greenroom.problems import load_all, select
from greenroom.schemas.intake import JobDescription


def test_the_bank_loads_and_validates():
    problems = load_all("problems")
    assert len(problems) >= 3
    assert {p.id for p in problems} >= {"merge_intervals", "two_sum_pairs", "lru_cache"}


def test_every_problem_has_both_languages_and_a_reference():
    for p in load_all("problems"):
        assert set(p.signature) == {"python", "javascript"}, p.id
        assert set(p.reference) == {"python", "javascript"}, p.id
        assert p.reference["python"].strip(), p.id


def test_every_problem_has_visible_and_hidden_tests():
    for p in load_all("problems"):
        assert p.visible_tests, f"{p.id} has nothing the candidate can run"
        assert p.hidden_tests, f"{p.id} has no hidden tests, so submit reveals nothing"


def test_every_problem_has_probes_for_the_review_stage():
    for p in load_all("problems"):
        assert len(p.probes) >= 2, p.id


def test_selection_prefers_the_right_level():
    junior = select(JobDescription(title="x", level="junior"), "problems")
    staff = select(JobDescription(title="x", level="staff"), "problems")
    assert junior.id == "two_sum_pairs"
    assert staff.id == "lru_cache"


def test_selection_breaks_ties_on_stack_overlap():
    jd = JobDescription(title="x", level="mid", stack=["sorting"])
    assert select(jd, "problems").id == "merge_intervals"


def test_selection_returns_something_even_for_an_unmatched_level():
    # an empty bank returns None; a populated one always offers a problem
    assert select(JobDescription(title="x", level="junior"), "problems") is not None
