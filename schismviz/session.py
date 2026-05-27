"""schismviz.session — Session persistence for schismviz CLI apps.

Built on :class:`dvue.session_persistence.SessionManager` (Layer 1 in-memory
registry + optional Layer 2 diskcache) and the
:attr:`~dvue.dataui.DataUIManager.show_reset_session_button` param introduced
in :mod:`dvue.dataui`.

The diskcache default for schismviz is ``~/.schismviz_sessions`` (rather than
dvue's generic ``~/.dvue_sessions``) so sessions from different dvue apps on
the same machine are kept separate.  The cookie name is
``"schismviz_user_id"`` to avoid collisions when multiple dvue apps are
served on the same origin.
"""

from __future__ import annotations

from pathlib import Path

import panel as pn

from dvue.session_persistence import install_session_handler, SessionManager
from dvue.dataui import DataUI

__all__ = ["serve_session_app", "COOKIE_NAME"]

COOKIE_NAME: str = "schismviz_user_id"
_DEFAULT_CACHE_DIR: Path = Path.home() / ".schismviz_sessions"


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

    Uses :class:`~dvue.session_persistence.SessionManager` for the two-layer
    persistence contract and sets
    :attr:`~dvue.dataui.DataUIManager.show_reset_session_button` on every
    freshly built manager so that :meth:`~dvue.dataui.DataUI.create_view`
    automatically inserts a **Reset Session** button in the action bar.

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
    install_session_handler(cookie_name=COOKIE_NAME)

    session_mgr = SessionManager(
        cookie_name=COOKIE_NAME,
        cache_dir=cache_dir or _DEFAULT_CACHE_DIR,
    )

    app_key = title.lower().replace(" ", "-")

    def make_app():
        user_id = session_mgr.current_user_id
        reg_key = session_mgr.make_reg_key(user_id, app_key)
        entry = session_mgr.get_entry(reg_key)

        if entry:
            # Registry hit: reuse existing objects; re-register per-Document hooks.
            ui, tmpl = entry["ui"], entry["template"]
            pn.state.onload(lambda: (ui.setup_location_sync(), ui.setup_url_sync()))
            tmpl.servable()
            return

        # Registry miss: build a fresh manager and UI.
        mgr = build_manager_fn()
        mgr.show_reset_session_button = True
        mgr.session_cookie_name = COOKIE_NAME

        dataui_kwargs: dict = {}
        if crs is not None:
            dataui_kwargs["crs"] = crs
        if station_id_column is not None:
            dataui_kwargs["station_id_column"] = station_id_column

        ui = DataUI(mgr, **dataui_kwargs)
        tmpl = ui.create_view(title=title)
        tmpl.servable()

        if reg_key:
            session_mgr.set_entry(reg_key, {"mgr": mgr, "ui": ui, "template": tmpl})

    pn.serve(
        {app_key: make_app},
        port=port,
        show=True,
        unused_session_lifetime_milliseconds=2_592_000_000,
        **pn_serve_kwargs,
    )
