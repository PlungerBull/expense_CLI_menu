"""Local SQLite replica — public surface.

See [docs/cli-runtime.md](../../docs/cli-runtime.md) for runtime semantics
and [api-design-principles.md §3b](../../../expense_world_engine/docs/api-design-principles.md)
for the architectural standard.
"""

from expense.cache.db import SCHEMA_VERSION, cache_path, connect, wipe
from expense.cache.queries import (
    get_account,
    get_category,
    get_hashtag,
    get_inbox,
    get_reconciliation,
    get_transaction,
    list_accounts,
    list_categories,
    list_hashtags,
    list_inbox,
    list_reconciliations,
    list_transactions,
)
from expense.cache.state import CacheState, is_healthy, read, write_identity, write_token
from expense.cache.sync import (
    RESOURCE_KEYS,
    SyncSummary,
    apply_response,
    cold_start,
    delta_sync,
    ensure_synced,
    refresh_after_write,
)

__all__ = [
    "SCHEMA_VERSION",
    "CacheState",
    "RESOURCE_KEYS",
    "SyncSummary",
    "apply_response",
    "cache_path",
    "cold_start",
    "connect",
    "delta_sync",
    "ensure_synced",
    "get_account",
    "get_category",
    "get_hashtag",
    "get_inbox",
    "get_reconciliation",
    "get_transaction",
    "is_healthy",
    "list_accounts",
    "list_categories",
    "list_hashtags",
    "list_inbox",
    "list_reconciliations",
    "list_transactions",
    "read",
    "refresh_after_write",
    "wipe",
    "write_identity",
    "write_token",
]
