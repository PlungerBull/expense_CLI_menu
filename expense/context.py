from dataclasses import dataclass

import typer


@dataclass
class AppContext:
    verbose: bool = False
    no_cache: bool = False
    no_sync_after: bool = False


def get_verbose(ctx: typer.Context | None) -> bool:
    if ctx is None or not isinstance(ctx.obj, AppContext):
        return False
    return ctx.obj.verbose


def get_no_cache(ctx: typer.Context | None) -> bool:
    if ctx is None or not isinstance(ctx.obj, AppContext):
        return False
    return ctx.obj.no_cache


def get_no_sync_after(ctx: typer.Context | None) -> bool:
    if ctx is None or not isinstance(ctx.obj, AppContext):
        return False
    return ctx.obj.no_sync_after
