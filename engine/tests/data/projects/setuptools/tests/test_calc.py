import iniconfig

from calc import add


def test_add():
    assert add(1, 2) == 3


def test_a_dependency_is_installed():
    assert iniconfig.IniConfig
