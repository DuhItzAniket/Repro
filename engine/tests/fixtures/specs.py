"""Fixture repository specs. Expected outcomes live next to them as ``<name>.toml``.

``honest-fix`` (A07), ``selection`` and ``untested`` (D05), ``flaky`` and ``test-tamper``
(D06), ``perf-regress`` (D07), ``breaks-one`` (Gate D). The other fixtures in TEST_STRATEGY §3
are added by the phases that need them.
"""

from fixtures.repo_builder import RepoSpec

_DATES_BUGGY = '''"""Date helpers."""

from datetime import datetime


def parse_date(text: str) -> datetime:
    """Parse an ISO-8601 timestamp."""
    return datetime.fromisoformat(text).replace(tzinfo=None)
'''

_DATES_FIXED = '''"""Date helpers."""

from datetime import UTC, datetime


def parse_date(text: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalise it to UTC (naive input is taken as UTC)."""
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
'''

_DATES_TESTS = """from datetime import UTC

from pkg.dates import parse_date


def test_parse_date_with_timezone():
    value = parse_date("2026-03-29T02:30:00+01:00")
    assert value.tzinfo is not None
    assert (value.hour, value.minute) == (1, 30)


def test_parse_date_naive_input_is_utc():
    assert parse_date("2026-01-01T00:00:00").tzinfo == UTC
"""

HONEST_FIX = RepoSpec(
    name="honest-fix",
    description="Bug fix that does exactly what its description claims.",
    base={
        "pyproject.toml": '[project]\nname = "dates-fixture"\nversion = "0.1.0"\n',
        "pkg/__init__.py": "",
        "pkg/dates.py": _DATES_BUGGY,
        "tests/test_dates.py": _DATES_TESTS,
    },
    heads={"fix/parse-date-utc": {"pkg/dates.py": _DATES_FIXED}},
    pr_description={
        "fix/parse-date-utc": (
            "Fix parse_date dropping the UTC offset\n\n"
            "parse_date now returns timezone-aware datetimes normalised to UTC; naive input is "
            "interpreted as UTC. No other behaviour changes."
        )
    },
)

# A small shop: prices, a cart, and a report no test uses. ``selection`` and ``untested``
# change it in ways whose selected tests a person can name (D05).
_PRICES = """\"\"\"Prices, in euros.\"\"\"

TAX_RATE = 0.2


def net(amount):
    return round(amount, 2)


def gross(amount):
    return round(net(amount) * (1 + TAX_RATE), 2)


def discount(amount, percent):
    return round(amount * (1 - percent / 100), 2)
"""

_CART = """\"\"\"A shopping cart.\"\"\"

from shop.prices import gross


class Cart:
    def __init__(self):
        self.items = []

    def add(self, name, amount):
        self.items.append((name, amount))

    def total(self):
        return round(sum(gross(amount) for _, amount in self.items), 2)

    def names(self):
        return sorted(name for name, _ in self.items)
"""

_REPORT = """\"\"\"Reports.\"\"\"


def summary(cart):
    return f"{len(cart.items)} items"
"""

_CONFTEST = """import pytest

from shop.cart import Cart


@pytest.fixture
def cart():
    cart = Cart()
    cart.add("tea", 2.5)
    return cart
"""

_TEST_PRICES = """from shop.prices import discount, gross, net


def test_net():
    assert net(2.499) == 2.5


def test_gross():
    assert gross(10) == 12.0


def test_discount():
    assert discount(50, 10) == 45.0
"""

_TEST_CART = """from shop.cart import Cart


def test_total(cart):
    assert cart.total() == 3.0


def test_names(cart):
    cart.add("Apple", 1.0)
    assert cart.names() == ["Apple", "tea"]


def test_empty_total():
    assert Cart().total() == 0
"""

_SHOP = {
    "pyproject.toml": '[project]\nname = "shop-fixture"\nversion = "0.1.0"\n',
    "shop/__init__.py": "",
    "shop/prices.py": _PRICES,
    "shop/cart.py": _CART,
    "shop/report.py": _REPORT,
    "tests/conftest.py": _CONFTEST,
    "tests/test_prices.py": _TEST_PRICES,
    "tests/test_cart.py": _TEST_CART,
}

SELECTION = RepoSpec(
    name="selection",
    description="Changes whose affected tests a person can name, and one test none affects.",
    base=_SHOP,
    heads={
        "change/prices-and-names": {
            "shop/prices.py": _PRICES.replace(
                "def net(amount):\n",
                'def net(amount):\n    if amount < 0:\n        raise ValueError("amounts are '
                'never negative")\n',
            ).replace(
                "def discount(amount, percent):\n",
                "def discount(amount, percent):\n    percent = min(max(percent, 0), 100)\n",
            ),
            "shop/cart.py": _CART.replace(
                "return sorted(name for name, _ in self.items)",
                "return sorted((name for name, _ in self.items), key=str.casefold)",
            ),
            "tests/test_cart.py": _TEST_CART.replace(
                """    cart.add("Apple", 1.0)
    assert cart.names() == ["Apple", "tea"]""",
                """    cart.add("Banana", 1.0)
    cart.add("apple", 1.0)
    assert cart.names() == ["apple", "Banana", "tea"]""",
            ),
            "tests/test_prices.py": _TEST_PRICES
            + """

def test_discount_is_clamped():
    assert discount(50, 150) == 0.0
    assert discount(50, -5) == 50.0
""",
        }
    },
    pr_description={
        "change/prices-and-names": (
            "Reject negative amounts, clamp discounts, sort names case-insensitively\n\n"
            "net() raises ValueError for negative amounts; discount() clamps its percentage to "
            "0-100; Cart.names() sorts without regard to case."
        )
    },
)

UNTESTED = RepoSpec(
    name="untested",
    description="A change no test reaches.",
    base=_SHOP,
    heads={
        "feat/report-total": {
            "shop/report.py": _REPORT.replace(
                '"""Reports."""\n',
                '"""Reports."""\n\nCURRENCY = "EUR"\n',
            ).replace(
                'return f"{len(cart.items)} items"',
                'return f"{len(cart.items)} items, {cart.total()} {CURRENCY}"',
            ),
            "shop/prices.py": _PRICES
            + """

def rounding(amount):
    return round(amount, 2)
""",
        }
    },
    pr_description={
        "feat/report-total": (
            "Show the cart total in the summary\n\n"
            "summary() now includes the total in euros; adds a rounding helper."
        )
    },
)

_COUNTER = """\"\"\"A counter that remembers what it saw.\"\"\"

SEEN = []


def record(value):
    SEEN.append(value)
    return len(SEEN)


def double(value):
    return value * 2
"""

_TEST_COUNTER = """from counter.core import double, record


def test_record_first():
    assert record("a") >= 1


def test_record_second():
    # Passes only after test_record_first: its outcome depends on the order tests run in.
    assert record("b") == 2


def test_double():
    assert double(2) == 4
"""

FLAKY = RepoSpec(
    name="flaky",
    description="A test whose outcome depends on test order, beside a change it covers.",
    base={
        "pyproject.toml": '[project]\nname = "counter-fixture"\nversion = "0.1.0"\n',
        "counter/__init__.py": "",
        "counter/core.py": _COUNTER,
        "tests/test_counter.py": _TEST_COUNTER,
    },
    heads={
        "change/strip-values": {
            "counter/core.py": _COUNTER.replace(
                "    SEEN.append(value)\n", "    SEEN.append(value.strip())\n"
            )
        }
    },
    pr_description={
        "change/strip-values": (
            "Strip recorded values\n\nrecord() stores values without surrounding whitespace."
        )
    },
)

_OPS = """\"\"\"Arithmetic helpers.\"\"\"


def divide(a, b):
    return a / b


def percent(part, whole):
    return round(100 * part / whole, 1)
"""

_TEST_OPS = """import pytest

from calc.ops import divide, percent


def test_divide():
    assert divide(6, 3) == 2
    assert divide(1, 4) == 0.25


def test_divide_by_zero():
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)


def test_percent():
    assert percent(1, 4) == 25.0
"""

TEST_TAMPER = RepoSpec(
    name="test-tamper",
    description="A change that breaks two tests, then deletes one's assertion and skips the other.",
    base={
        "pyproject.toml": '[project]\nname = "calc-fixture"\nversion = "0.1.0"\n',
        "calc/__init__.py": "",
        "calc/ops.py": _OPS,
        "tests/test_ops.py": _TEST_OPS,
    },
    heads={
        "perf/integer-division": {
            "calc/ops.py": _OPS.replace("return a / b", "return a // b").replace(
                "return round(100 * part / whole, 1)",
                "return round(100 * divide(part, whole), 1)",
            ),
            "tests/test_ops.py": _TEST_OPS.replace("    assert divide(1, 4) == 0.25\n", "").replace(
                "def test_percent():",
                '@pytest.mark.skip(reason="flaky on CI")\ndef test_percent():',
            ),
        }
    },
    pr_description={
        "perf/integer-division": (
            "Faster division\n\ndivide() uses integer division, which is faster. "
            "No behaviour change."
        )
    },
)

_TAGS = """\"\"\"Tags.\"\"\"


def unique_tags(tags):
    return sorted(set(tags))
"""

_TAGS_QUADRATIC = """\"\"\"Tags.\"\"\"


def unique_tags(tags):
    seen = []
    for tag in tags:
        if tag not in seen:
            seen.append(tag)
    return sorted(seen)
"""

_TEST_TAGS = """from tags.core import unique_tags

TAGS = [f"tag{i % 50}" for i in range(50_000)]
VALUES = [(i * 7919) % 100_003 for i in range(200_000)]


def test_unique_tags():
    for _ in range(20):
        assert len(unique_tags(TAGS)) == 50


def test_report_is_sorted():
    assert sorted(VALUES)[0] == 0
    assert unique_tags(["b", "a", "b"]) == ["a", "b"]


def test_unique_tags_small():
    assert unique_tags(["b", "a"]) == ["a", "b"]
"""

PERF_REGRESS = RepoSpec(
    name="perf-regress",
    description="A quadratic loop in a hot path, and a test whose time it does not change.",
    base={
        "pyproject.toml": '[project]\nname = "tags-fixture"\nversion = "0.1.0"\n',
        "tags/__init__.py": "",
        "tags/core.py": _TAGS,
        "tests/test_tags.py": _TEST_TAGS,
    },
    heads={"refactor/no-set": {"tags/core.py": _TAGS_QUADRATIC}},
    pr_description={
        "refactor/no-set": (
            "Keep tags in first-seen order before sorting\n\n"
            "unique_tags() no longer builds a set. No behaviour change."
        )
    },
)

BREAKS_ONE = RepoSpec(
    name="breaks-one",
    description="A change that breaks exactly one test, and touches nothing else.",
    base=_SHOP,
    heads={
        "change/discount-percent": {
            "shop/prices.py": _PRICES.replace(
                "return round(amount * (1 - percent / 100), 2)",
                "return round(amount * percent / 100, 2)",
            )
        }
    },
    pr_description={
        "change/discount-percent": (
            "Simplify discount()\n\ndiscount() computes the discounted price more directly. "
            "No behaviour change."
        )
    },
)

ALL_SPECS = {
    spec.name: spec
    for spec in (
        HONEST_FIX,
        SELECTION,
        UNTESTED,
        FLAKY,
        TEST_TAMPER,
        PERF_REGRESS,
        BREAKS_ONE,
    )
}
