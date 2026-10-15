import pytest

from calc import Box, add, extend, fails, gen, many, ordered, recurse, threaded, with_kw


@pytest.fixture
def three():
    return add(1, 2)


def test_add():
    assert add(1, 2) == 3
    assert add("a", "b") == "ab"


def test_raise():
    with pytest.raises(ValueError):
        fails(3)


def test_generator():
    assert list(gen(3)) == [0, 2, 4]


def test_abandoned_generator():
    values = gen(5)
    assert next(values) == 0


def test_recursion():
    assert recurse(5) == 5


def test_budget():
    assert many(250) == sum(range(1, 251))


def test_threads():
    assert threaded(4) == [0, 2, 4, 6]


def test_keywords():
    assert with_kw(1, 2, 3, b=4, c={"x", "y", "z"}) == (1, (2, 3), 4, {"c": {"x", "y", "z"}})


def test_method():
    assert Box("abc").size() == 3


def test_setup_phase(three):
    assert three == 3


def test_dict_order():
    assert ordered(["bb", "a"]) == {"a": 1, "bb": 2}


def test_mutation():
    items = [1]
    assert extend(items, [2, 3]) == 3
