import pytest

from exchange_router.exchanges.base import build_step, build_step_from_decimals, count_decimals


NOT_A_STEP  = ["", None, "abc", "0", "-0.1", "NaN", "Infinity", "1e1000000", "1e-400", {}, [1]]
NOT_A_COUNT = ["", None, "abc", "NaN", "Infinity", True, 2.5, float("inf")]
UNCOUNTABLE = ["", None, "abc", "NaN", "Infinity", "1e1000000"]


def test_a_step_built_from_two_venue_numbers_is_their_decimal_product():
    assert build_step("0.1", "0.1") == 0.01
    assert build_step("0.01", "1000") == 10.0
    assert build_step(1, 0.001) == 0.001
    assert build_step(1e-05) == 0.00001


def test_a_step_from_a_count_of_decimals_reaches_both_sides_of_one():
    assert build_step_from_decimals(4) == 0.0001
    assert build_step_from_decimals(0) == 1.0
    assert build_step_from_decimals(-3) == 1000.0


def test_decimals_are_counted_from_the_number_in_whatever_form_it_arrives():
    assert count_decimals("0.10") == 1
    assert count_decimals("100.0000000000") == 0
    assert count_decimals(1e-05) == 5
    assert count_decimals(1e-11) == 11
    assert count_decimals(0.25) == 2


@pytest.mark.parametrize("value", NOT_A_STEP)
def test_anything_but_a_positive_finite_float_gives_no_step(value):
    assert build_step(value) is None
    assert build_step("0.1", value) is None


@pytest.mark.parametrize("value", NOT_A_COUNT)
def test_anything_but_a_whole_count_of_decimals_gives_no_step(value):
    assert build_step_from_decimals(value) is None


@pytest.mark.parametrize("value", UNCOUNTABLE)
def test_an_uncountable_value_gives_no_count_of_decimals(value):
    assert count_decimals(value) is None
