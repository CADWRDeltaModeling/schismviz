"""schismviz.session — Session persistence for schismviz CLI apps.

Thin re-export shim over :mod:`dvue.session_persistence`.  All logic lives
in dvue so that other dvue-based apps can reuse it.

The diskcache default for schismviz is ``~/.schismviz_sessions`` (rather
than dvue's generic ``~/.dvue_sessions``) so sessions from different dvue
apps on the same machine are kept separate.  The cookie name is
``"schismviz_user_id"`` to avoid collisions when multiple dvue apps are
served on the same origin.
"""

from __future__ import annotations

from pathlib import Path

from dvue.session_persistence import (
    install_session_handler,
    snapshot,
    restore,
)
from dvue.session_persistence import serve_session_app as _serve_session_app

__all__ = ["install_session_handler", "snapshot", "restore", "serve_session_app"]

_DEFAULT_CACHE_DIR = Path.home() / ".schismviz_sessions"
_DEFAULT_COOKIE_NAME = "schismviz_user_id"


def serve_session_app(
    build_manager_fn,
    title: str,
    port: int = 0,
    crs=None,
    station_id_column: str | None = None,
    cache_dir: str | Path | None = None,
    **pn_serve_kwargs,
) -> None:
    """Launch a session-aware Panel app for a schismviz manager.

    Delegates to :func:`dvue.session_persistence.serve_session_app` with
    ``cache_dir`` defaulting to ``~/.schismviz_sessions`` and
    ``cookie_name`` defaulting to ``"schismviz_user_id"``.

    Parameters
    ----------
    build_manager_fn:
        Zero-argument callable returning a fresh ``DataUIManager`` instance.
    title:
        Browser title; also used as the URL path key.
    port:
        TCP port (``0`` = random available port).
    crs:
        Cartopy CRS for the map panel.  ``None`` → no map.
    station_id_column:
        Column identifying stations in the catalog.
    cache_dir:
        Diskcache directory.  Defaults to ``~/.schismviz_sessions``.
    **pn_serve_kwargs:
        Forwarded to ``pn.serve()``.
    """
    _serve_session_app(
        build_manager_fn,
        title=title,
        port=port,
        crs=crs,
        station_id_column=station_id_column,
        cookie_name=_DEFAULT_COOKIE_NAME,
        cache_dir=cache_dir if cache_dir is not None else _DEFAULT_CACHE_DIR,
        **pn_serve_kwargs,
    )
