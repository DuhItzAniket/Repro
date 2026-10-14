"""Fixture repository specs. Expected outcomes live next to them as ``<name>.toml``.

``honest-fix`` (A07), ``selection`` and ``untested`` (D05). The other fixtures in TEST_STRATEGY
§3 are added by the phases that need them.
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

ALL_SPECS = {spec.name: spec for spec in (HONEST_FIX, SELECTION, UNTESTED)}
