"""The line a card reports for a run that ended early (H01, J01)."""

from repro.readable import error_line

WARNING = (
    "DeprecationWarning: ast.Str is deprecated and will be removed in Python 3.14; "
    "use ast.Constant instead"
)
#: What pytest 7.2.2 printed on Python 3.13 for Flask's tests at a 2023 commit (J01): its
#: assertion rewriter touched ``ast.Str``, and the project's ``filterwarnings = error`` made the
#: warning an error before any test ran.
CONFTEST = (
    "ImportError while loading conftest '/w/tests/conftest.py'.\n"
    "/usr/local/lib/python3.13/ast.py:422: in visit\n"
    "    return visitor(node)\n"
    "/usr/local/lib/python3.13/warnings.py:669: in _deprecated\n"
    "    warn(msg, DeprecationWarning, stacklevel=3)\n"
    f"E   {WARNING}\n"
)


def test_the_error_a_warning_became_is_the_reason() -> None:
    assert error_line(CONFTEST) == WARNING


def test_the_last_line_naming_an_error_is_the_reason() -> None:
    traceback = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "    import missing\n"
        "ModuleNotFoundError: No module named 'missing'\n"
    )
    assert error_line(traceback) == "ModuleNotFoundError: No module named 'missing'"
    assert error_line("collected 0 items\nno tests ran in 0.01s\n") == "no tests ran in 0.01s"
    assert error_line("") == ""
