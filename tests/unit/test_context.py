"""Direct tests for expense/context.py — AppContext + get_verbose."""

from types import SimpleNamespace

from expense.context import AppContext, get_verbose


def test_app_context_default_verbose_false():
    assert AppContext().verbose is False


def test_app_context_explicit_verbose_true():
    assert AppContext(verbose=True).verbose is True


def test_get_verbose_returns_false_when_ctx_is_none():
    assert get_verbose(None) is False


def test_get_verbose_returns_false_when_ctx_obj_is_not_app_context():
    fake_ctx = SimpleNamespace(obj=None)
    assert get_verbose(fake_ctx) is False  # type: ignore[arg-type]

    fake_ctx2 = SimpleNamespace(obj={"verbose": True})
    assert get_verbose(fake_ctx2) is False  # type: ignore[arg-type]


def test_get_verbose_returns_true_when_app_context_set():
    fake_ctx = SimpleNamespace(obj=AppContext(verbose=True))
    assert get_verbose(fake_ctx) is True  # type: ignore[arg-type]


def test_get_verbose_returns_false_when_app_context_default():
    fake_ctx = SimpleNamespace(obj=AppContext())
    assert get_verbose(fake_ctx) is False  # type: ignore[arg-type]
