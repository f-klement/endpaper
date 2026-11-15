"""A test module's own caches are emptied each time the run leaves a module.

The hook is `pytest_runtest_teardown` in `conftest.py`; these call it with
stand ins for the item that just ran, the one after it and the session's
collection.
"""

import functools
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from tests import conftest


@functools.cache
def _a_cache_from_outside_the_collection() -> list[int]:
    return [2]


def _a_test_module(name: str) -> Any:
    module: Any = ModuleType(f"tests.{name}")

    @functools.cache
    def index() -> list[int]:
        return [1]

    index.__module__ = module.__name__
    module.index = index
    module.imported = _a_cache_from_outside_the_collection
    module.index()
    module.imported()
    return module


def _item(module: ModuleType, *collected: ModuleType) -> pytest.Item:
    session = SimpleNamespace(items=[SimpleNamespace(module=each) for each in collected])
    return cast(pytest.Item, SimpleNamespace(module=module, session=session))


@pytest.mark.parametrize("nextitem", ["another module", "the end of the session"])
def test_leaving_a_module_empties_the_caches_it_defines(nextitem: str) -> None:
    owner, another = _a_test_module("test_owner"), _a_test_module("test_another")
    after = None if nextitem == "the end of the session" else _item(another, owner, another)

    conftest.pytest_runtest_teardown(_item(owner, owner, another), after)

    assert owner.index.cache_info().currsize == 0


def test_leaving_a_module_empties_a_cache_it_filled_in_another_test_module() -> None:
    owner, caller = _a_test_module("test_owner"), _a_test_module("test_caller")

    conftest.pytest_runtest_teardown(_item(caller, owner, caller), None)

    assert owner.index.cache_info().currsize == 0


def test_a_cache_defined_outside_the_collected_modules_is_left_alone() -> None:
    owner = _a_test_module("test_owner")

    conftest.pytest_runtest_teardown(_item(owner, owner), None)

    assert owner.imported.cache_info().currsize == 1


def test_a_class_carrying_a_cache_s_two_names_is_not_emptied() -> None:
    owner = _a_test_module("test_owner")
    emptied: list[str] = []

    class LooksLikeACache:
        cache_info = staticmethod(lambda: None)
        cache_clear = staticmethod(lambda: emptied.append("the class"))

    LooksLikeACache.__module__ = owner.__name__
    owner.LooksLikeACache = LooksLikeACache

    conftest.pytest_runtest_teardown(_item(owner, owner), None)

    assert emptied == []


def test_the_hook_is_registered_to_run_after_pytest_s_own_teardown(
    pytestconfig: pytest.Config,
) -> None:
    """`trylast`, so a module fixture reading a cache as it tears down cannot
    fill it again behind the hook. Every case above calls the hook directly,
    so this is what holds the name pytest registers it under, and the order."""
    hook = pytestconfig.pluginmanager.hook.pytest_runtest_teardown
    ours = [each for each in hook.get_hookimpls() if each.function is conftest.pytest_runtest_teardown]

    assert [each.trylast for each in ours] == [True]


def test_a_test_followed_by_one_from_its_own_module_keeps_them() -> None:
    owner = _a_test_module("test_owner")

    conftest.pytest_runtest_teardown(_item(owner, owner), _item(owner, owner))

    assert owner.index.cache_info().currsize == 1
