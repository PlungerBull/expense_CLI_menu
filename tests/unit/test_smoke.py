import typer

from expense.__main__ import app


def test_app_is_typer_instance():
    assert isinstance(app, typer.Typer)
