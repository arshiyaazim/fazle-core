"""
Backward-compatibility shim — DEPRECATED.

``modules.fazle_payment_ingest.fpe_bridge`` was renamed to ``modules.fazle_payment_ingest.fpe_bridge`` as part of the ``fazle_`` prefix
unification.  This module re-exports the new module so that any external
caller that still imports the old path keeps working.

It emits a :class:`DeprecationWarning` on first attribute access.  The
re-export is LAZY (PEP 562 module-level ``__getattr__``), so importing this
shim never triggers the import of the new module and cannot introduce a
circular import.

Remove this shim once no caller uses the old path any more.
"""
from __future__ import annotations

import warnings
from importlib import import_module

_NEW = "modules.fazle_payment_ingest.fpe_bridge"
_OLD = "modules.fazle_payment_ingest.fpe_bridge"


def _warn() -> None:
    warnings.warn(
        f"{_OLD} is deprecated; use {_NEW} instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def __getattr__(name: str):
    _warn()
    _mod = import_module(_NEW)
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(
            f"module {_OLD!r} has no attribute {name!r}"
        ) from None


def __dir__() -> list:
    return dir(import_module(_NEW))
