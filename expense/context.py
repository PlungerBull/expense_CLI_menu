from dataclasses import dataclass

import typer


@dataclass
class AppContext:
    verbose: bool = False


def get_verbose(ctx: typer.Context | None) -> bool:
    if ctx is None or not isinstance(ctx.obj, AppContext):
        return False
    return ctx.obj.verbose
