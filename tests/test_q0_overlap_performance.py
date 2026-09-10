"""Local overlap prefilter must preserve the original exact decision oracle."""
from difflib import SequenceMatcher
import random

import pytest

from evaluation.q0_pipeline import _has_near_template_overlap, near_template


def original_overlap(values):
    return any(near_template(left, right) for index, left in enumerate(values)
               for right in values[index + 1:])


@pytest.mark.parametrize("values", [
    [], [""], ["", ""], ["", "a"], ["a", "a"], ["ab", "ba"],
    ["tide", "diet"], ["a" * 199, "a" * 198 + "b"],
    ["a" * 200, "a" * 199 + "b"], ["a" * 300 + "b" * 300, "b" * 300 + "a" * 300],
    ["中文数学题", "中文数学题"], ["x<2", "x<=2", "x>2"],
])
def test_empty_identical_unicode_and_autojunk_boundaries_preserve_original(values):
    assert _has_near_template_overlap(values) is original_overlap(values)


def test_quick_ratio_threshold_equality_cannot_be_filtered_out():
    # The common 22-character prefix gives 44/50=0.88 exactly.
    left, right = "a" * 22 + "bbb", "a" * 22 + "ccc"
    assert SequenceMatcher(None, left, right).quick_ratio() == 0.88
    assert near_template(left, right)
    assert _has_near_template_overlap([left, right])
    assert _has_near_template_overlap([right, left])


def test_seeded_edits_keep_bidirectional_predicate_including_near_threshold():
    rng = random.Random(906)
    saw_accepted = saw_rejected = saw_asymmetric = False
    for _ in range(500):
        left = "".join(rng.choice("abcde123") for _ in range(40))
        right = left
        for _ in range(rng.randrange(1, 12)):
            pos = rng.randrange(len(right))
            right = right[:pos] + rng.choice("abcde123") + right[pos + 1:]
        expected = near_template(left, right)
        saw_accepted |= expected
        saw_rejected |= not expected
        saw_asymmetric |= SequenceMatcher(None, left, right).ratio() != SequenceMatcher(None, right, left).ratio()
        assert _has_near_template_overlap([left, right]) is expected
        assert _has_near_template_overlap([right, left]) is expected
    assert saw_accepted and saw_rejected and saw_asymmetric


def test_seeded_multi_item_permutations_match_original_without_retaining_old_values():
    rng = random.Random(204)
    for _ in range(30):
        values = ["".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(100)) for _ in range(8)]
        expected = original_overlap(values)
        assert _has_near_template_overlap(values) is expected
        assert _has_near_template_overlap(values[::-1]) is expected
        values[-1] = values[0]
        assert _has_near_template_overlap(values)
        values[-1] = "distinct fresh value"
        assert _has_near_template_overlap(values) is original_overlap(values)
