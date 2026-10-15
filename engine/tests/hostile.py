"""A corpus of hostile objects for the encoder (E02): each records in ``CALLED`` any of its code
that runs, and the encoder must run none of it, raise nothing, and finish.

Test data, not a test module: the encoder's tests build values from it.
"""

from collections.abc import Callable, Iterator
from typing import Any

CALLED: list[str] = []


def _called(name: str) -> Any:
    def method(*_args: Any, **_kwargs: Any) -> Any:
        CALLED.append(name)
        raise RuntimeError(f"{name} was called")

    return method


class Dunders:
    """Every dunder an encoder might be tempted to call."""

    __eq__ = _called("__eq__")
    __hash__ = _called("__hash__")
    __repr__ = _called("__repr__")
    __str__ = _called("__str__")
    __format__ = _called("__format__")
    __iter__ = _called("__iter__")
    __len__ = _called("__len__")
    __bool__ = _called("__bool__")
    __lt__ = _called("__lt__")
    __getstate__ = _called("__getstate__")
    __reduce__ = _called("__reduce__")
    __reduce_ex__ = _called("__reduce_ex__")
    __getitem__ = _called("__getitem__")
    __contains__ = _called("__contains__")
    __index__ = _called("__index__")
    __float__ = _called("__float__")

    def __init__(self) -> None:
        self.kept = 1


class Attributes:
    """Attribute access itself is user code."""

    def __init__(self) -> None:
        object.__setattr__(self, "kept", 2)

    __getattribute__ = _called("__getattribute__")
    __getattr__ = _called("__getattr__")


class Property:
    def __init__(self) -> None:
        self.kept = 3

    @property
    def value(self) -> int:
        CALLED.append("property")
        return 0


class LyingClass:
    """``__class__`` answers something else: isinstance() would ask it."""

    @property  # type: ignore[misc]
    def __class__(self) -> type:
        CALLED.append("__class__")
        return int


class OwnDict:
    """A ``__dict__`` of the class's own: reading it runs user code."""

    @property
    def __dict__(self) -> dict[str, Any]:  # type: ignore[override]
        CALLED.append("__dict__")
        return {"forged": True}


class SlotDescriptor:
    """Stands in for a slot: reading it is user code; writing goes to the real slot."""

    def __init__(self, member: Any) -> None:
        self.member = member

    def __get__(self, instance: Any, owner: Any) -> Any:
        CALLED.append("slot descriptor")
        return 0

    def __set__(self, instance: Any, value: Any) -> None:
        self.member.__set__(instance, value)


class Slots:
    __slots__ = ("a", "b", "unset")

    def __init__(self) -> None:
        self.a = 1
        self.b = [1, 2]


class ReplacedSlot:
    __slots__ = ("a",)

    def __init__(self) -> None:
        self.a = 1


ReplacedSlot.a = SlotDescriptor(ReplacedSlot.__dict__["a"])  # type: ignore[assignment,misc]


class Meta(type):
    """A metaclass answering every attribute lookup on its classes (their name, module, MRO)
    and isinstance() / issubclass() against them. (Python refuses a ``__qualname__`` property
    in a class body, so that one cannot be forged.)"""

    def __getattribute__(cls, name: str) -> Any:
        CALLED.append(f"metaclass {name}")
        return type.__getattribute__(cls, name)

    def __instancecheck__(cls, instance: Any) -> bool:
        CALLED.append("__instancecheck__")
        return False

    def __subclasscheck__(cls, subclass: Any) -> bool:
        CALLED.append("__subclasscheck__")
        return False


class WithMeta(metaclass=Meta):
    def __init__(self) -> None:
        self.kept = 4


class HostileError(Exception):
    __str__ = _called("exception __str__")
    __repr__ = _called("exception __repr__")
    __bool__ = _called("exception __bool__")
    __len__ = _called("exception __len__")


def chained() -> BaseException:
    try:
        try:
            raise HostileError("inner", Dunders())
        except HostileError as inner:
            raise ValueError("outer") from inner
    except ValueError as outer:
        return outer


class Subclassed(dict):  # type: ignore[type-arg]
    """A builtin's subclass: walking it as a dict would call its overridden methods."""

    items = _called("dict subclass items")
    keys = _called("dict subclass keys")
    __iter__ = _called("dict subclass __iter__")


class ListSubclass(list):  # type: ignore[type-arg]
    __iter__ = _called("list subclass __iter__")
    __len__ = _called("list subclass __len__")


def generator() -> Iterator[int]:
    CALLED.append("generator body")
    yield 1


def cyclic() -> list[Any]:
    loop: list[Any] = [1]
    loop.append(loop)
    return loop


def cyclic_object() -> Any:
    node = Property()
    node.next = node  # type: ignore[attr-defined]
    return node


CORPUS: dict[str, Callable[[], Any]] = {
    "dunders": Dunders,
    "attributes": Attributes,
    "property": Property,
    "lying class": LyingClass,
    "own __dict__": OwnDict,
    "slots": Slots,
    "replaced slot": ReplacedSlot,
    "metaclass instance": WithMeta,
    "metaclass class": lambda: WithMeta,
    "hostile exception": lambda: HostileError("x", Dunders()),
    "exception chain": chained,
    "dict subclass": lambda: Subclassed(a=1),
    "list subclass": lambda: ListSubclass([1, 2]),
    "generator": generator,
    "lambda": lambda: lambda: CALLED.append("lambda body"),
    "cycle": cyclic,
    "object cycle": cyclic_object,
    "nested": lambda: {"k": [Dunders(), (Attributes(), {Slots()})]},
}
