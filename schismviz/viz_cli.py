"""
Click-based command-line interface for SCHISM field/mesh visualisation.

Usage pattern (YAML config + optional CLI overrides)
-----------------------------------------------------
All commands accept a ``--config`` / ``-c`` option pointing to a YAML file.
Every key in the relevant YAML section corresponds to a CLI option of the same
name (with underscores replaced by hyphens).  CLI options take precedence over
YAML values, so you can set project-level defaults in the file and override
individual values on the command line without editing the file.

Example::

    # Use all settings from YAML
    schismviz viz mesh-view -c my_project.yaml

    # Override the port for this run
    schismviz viz var-animation -c my_project.yaml --port 5099

    # Fully specify on the command line (no YAML)
    schismviz viz stations \\
        --hgrid ./hgrid.gr3 \\
        --station-in ./station.in \\
        --staout-prefix ./outputs/staout_ \\
        --reftime 2000-01-01

YAML structure
--------------
Each sub-command reads from a section whose name matches the command key in the
table below::

    mesh_view:               # mesh-view
    elevation_animation:     # elevation
    var_animation:           # var-animation
    velocity_vectors:        # velocity
    var_velocity_animation:  # var-velocity
    var_velocity_level_animation: # var-velocity-level
    stations_map:            # stations

See ``examples/viz_config_example.yaml`` for a fully annotated template.
"""
from __future__ import annotations

import pathlib
from typing import Any

import click
import yaml


# ---------------------------------------------------------------------------
# YAML / overrides helpers
# ---------------------------------------------------------------------------

def _load_yaml_section(config_file: str | None, section: str) -> dict[str, Any]:
    """Return the named section from a YAML file, or an empty dict."""
    if config_file is None:
        return {}
    with open(config_file, "r") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get(section, {})


def _merge(cfg: dict[str, Any], **cli_overrides) -> dict[str, Any]:
    """
    Merge CLI keyword overrides into *cfg*.

    Only non-``None`` CLI values replace the YAML defaults, so omitting a CLI
    flag keeps whatever was in the YAML file.
    """
    merged = dict(cfg)
    for key, value in cli_overrides.items():
        if value is not None:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Reusable option decorators
# ---------------------------------------------------------------------------

_CONFIG = click.option(
    "--config", "-c",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="YAML configuration file.  CLI options override values in this file.",
)
_PORT = click.option(
    "--port", default=None, type=int,
    help="Port for the Panel server (default: 5006).",
)
_SHOW = click.option(
    "--show/--no-show", default=True,
    help="Open a browser tab automatically (default: --show).",
)
_TITLE = click.option("--title", default=None, help="Dashboard title shown in the browser.")
_HGRID = click.option(
    "--hgrid", default=None, type=click.Path(),
    help="Path to hgrid.gr3 SCHISM mesh file.",
)
_WIDTH = click.option(
    "--width", default=None, type=int,
    help="Plot width in pixels.",
)
_HEIGHT = click.option(
    "--height", default=None, type=int,
    help="Plot height in pixels.",
)
_OUT2D = click.option(
    "--out2d-pattern", "out2d_pattern", default=None,
    help="Glob pattern for out2d_*.nc output files.",
)
_VAR_PATTERN = click.option(
    "--var-pattern", "var_pattern", default=None,
    help="Glob pattern for the scalar variable nc files (e.g. salinity_*.nc).",
)
_VARNAME = click.option(
    "--varname", default=None,
    help="Variable name inside the nc files (e.g. salinity).",
)


def _require(values: dict[str, Any], *keys: str) -> None:
    """Raise a UsageError for the first missing required key."""
    for key in keys:
        if not values.get(key):
            flag = "--" + key.replace("_", "-")
            raise click.UsageError(
                f"{flag} is required (provide it on the command line or "
                f"in the YAML config file)."
            )


def _serve(panel_obj, title: str, port: int, show: bool) -> None:
    import panel as pn
    pn.serve(panel_obj, title=title, port=port, show=show)


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------

@click.group()
def viz():
    """SCHISM mesh and field visualisation commands.

    \b
    Commands launch an interactive Panel/HoloViews dashboard.
    Use --config / -c to load settings from a YAML file and optionally
    override individual values with CLI flags.
    """


# ---------------------------------------------------------------------------
# mesh-view
# ---------------------------------------------------------------------------

@viz.command("mesh-view")
@_CONFIG
@_HGRID
@_PORT
@_SHOW
@_TITLE
@_WIDTH
@_HEIGHT
def mesh_view(config, hgrid, port, show, title, width, height):
    """Render the SCHISM mesh with nodes and edges (fast datashader rasterize).

    Also shows XY, XZ, and YZ cross-section projections of the 3-D mesh.

    \b
    YAML section: mesh_view
    Keys: hgrid, port, show, title, width, height
    """
    import panel as pn
    from .viz_commands import mesh_view_panel

    pn.extension()
    cfg = _merge(
        _load_yaml_section(config, "mesh_view"),
        hgrid=hgrid, port=port, title=title, width=width, height=height,
    )
    _require(cfg, "hgrid")

    panel = mesh_view_panel(
        cfg["hgrid"],
        width=cfg.get("width", 800),
        height=cfg.get("height", 400),
        title=cfg.get("title", "SCHISM Mesh View"),
    )
    _serve(panel, cfg.get("title", "SCHISM Mesh View"), cfg.get("port", 5006), show)


# ---------------------------------------------------------------------------
# elevation
# ---------------------------------------------------------------------------

@viz.command("elevation")
@_CONFIG
@_HGRID
@_OUT2D
@_PORT
@_SHOW
@_TITLE
@_WIDTH
@_HEIGHT
def elevation_animation(config, hgrid, out2d_pattern, port, show, title, width, height):
    """Interactive 3-D water-surface elevation animation (Plotly backend).

    Displays both the bathymetry mesh and the animated water surface.  Use
    the time slider to step through model time steps.

    \b
    YAML section: elevation_animation
    Keys: hgrid, out2d_pattern, port, show, title, width, height
    """
    import panel as pn
    from .viz_commands import elevation_animation_panel

    pn.extension()
    cfg = _merge(
        _load_yaml_section(config, "elevation_animation"),
        hgrid=hgrid, out2d_pattern=out2d_pattern, port=port,
        title=title, width=width, height=height,
    )
    _require(cfg, "hgrid", "out2d_pattern")

    panel = elevation_animation_panel(
        cfg["hgrid"],
        cfg["out2d_pattern"],
        title=cfg.get("title", "Water Surface Elevation"),
        width=cfg.get("width", 800),
        height=cfg.get("height", 800),
    )
    _serve(panel, cfg.get("title", "Water Surface Elevation"), cfg.get("port", 5006), show)


# ---------------------------------------------------------------------------
# var-animation
# ---------------------------------------------------------------------------

@viz.command("var-animation")
@_CONFIG
@_HGRID
@_VAR_PATTERN
@_VARNAME
@_PORT
@_SHOW
@_TITLE
@_WIDTH
@_HEIGHT
def var_animation(config, hgrid, var_pattern, varname, port, show, title, width, height):
    """Animate a node-based scalar variable (e.g. salinity, temperature).

    Provides time-step and vertical-layer selection sliders.

    \b
    YAML section: var_animation
    Keys: hgrid, var_pattern, varname, port, show, title, width, height

    \b
    Example:
        schismviz viz var-animation \\
            --hgrid hgrid.gr3 \\
            --var-pattern "outputs/salinity_*.nc" \\
            --varname salinity
    """
    import panel as pn
    from .viz_commands import var_animation_panel

    pn.extension()
    cfg = _merge(
        _load_yaml_section(config, "var_animation"),
        hgrid=hgrid, var_pattern=var_pattern, varname=varname,
        port=port, title=title, width=width, height=height,
    )
    _require(cfg, "hgrid", "var_pattern")

    _varname = cfg.get("varname", "salinity")
    panel = var_animation_panel(
        cfg["hgrid"],
        cfg["var_pattern"],
        varname=_varname,
        title=cfg.get("title", f"SCHISM: {_varname}"),
        width=cfg.get("width", 600),
        height=cfg.get("height", 400),
    )
    _serve(panel, cfg.get("title", f"SCHISM: {_varname}"), cfg.get("port", 5006), show)


# ---------------------------------------------------------------------------
# velocity
# ---------------------------------------------------------------------------

@viz.command("velocity")
@_CONFIG
@_OUT2D
@_PORT
@_SHOW
@_TITLE
@_WIDTH
@_HEIGHT
def velocity_vectors(config, out2d_pattern, port, show, title, width, height):
    """Animate depth-averaged velocity vectors over the model domain.

    Vector scale can be adjusted interactively via the widget.

    \b
    YAML section: velocity_vectors
    Keys: out2d_pattern, port, show, title, width, height
    """
    import panel as pn
    from .viz_commands import velocity_vectors_panel

    pn.extension()
    cfg = _merge(
        _load_yaml_section(config, "velocity_vectors"),
        out2d_pattern=out2d_pattern, port=port, title=title,
        width=width, height=height,
    )
    _require(cfg, "out2d_pattern")

    panel = velocity_vectors_panel(
        cfg["out2d_pattern"],
        title=cfg.get("title", "Velocity Vectors"),
        width=cfg.get("width", 600),
        height=cfg.get("height", 400),
    )
    _serve(panel, cfg.get("title", "Velocity Vectors"), cfg.get("port", 5006), show)


# ---------------------------------------------------------------------------
# var-velocity
# ---------------------------------------------------------------------------

@viz.command("var-velocity")
@_CONFIG
@_HGRID
@_OUT2D
@_VAR_PATTERN
@_VARNAME
@_PORT
@_SHOW
@_TITLE
@_WIDTH
@_HEIGHT
def var_velocity(config, hgrid, out2d_pattern, var_pattern, varname,
                  port, show, title, width, height):
    """Scalar field colour map overlaid with depth-averaged velocity vectors.

    Both variable and level can be changed interactively with the sliders.

    \b
    YAML section: var_velocity_animation
    Keys: hgrid, out2d_pattern, var_pattern, varname, port, show,
          title, width, height

    \b
    Example:
        schismviz viz var-velocity \\
            --hgrid hgrid.gr3 \\
            --out2d-pattern "outputs/out2d_*.nc" \\
            --var-pattern "outputs/salinity_*.nc" \\
            --varname salinity
    """
    import panel as pn
    from .viz_commands import var_velocity_panel

    pn.extension()
    cfg = _merge(
        _load_yaml_section(config, "var_velocity_animation"),
        hgrid=hgrid, out2d_pattern=out2d_pattern, var_pattern=var_pattern,
        varname=varname, port=port, title=title, width=width, height=height,
    )
    _require(cfg, "hgrid", "out2d_pattern", "var_pattern")

    _varname = cfg.get("varname", "salinity")
    panel = var_velocity_panel(
        cfg["hgrid"],
        cfg["out2d_pattern"],
        cfg["var_pattern"],
        varname=_varname,
        title=cfg.get("title", f"SCHISM: {_varname} + Depth-Averaged Velocity"),
        width=cfg.get("width", 1000),
        height=cfg.get("height", 500),
    )
    _serve(panel, cfg.get("title", f"SCHISM: {_varname} + Velocity"),
           cfg.get("port", 5006), show)


# ---------------------------------------------------------------------------
# var-velocity-level
# ---------------------------------------------------------------------------

@viz.command("var-velocity-level")
@_CONFIG
@_HGRID
@_OUT2D
@click.option(
    "--velx-pattern", "velx_pattern", default=None,
    help="Glob pattern for horizontalVelX_*.nc files.",
)
@click.option(
    "--vely-pattern", "vely_pattern", default=None,
    help="Glob pattern for horizontalVelY_*.nc files.",
)
@_VAR_PATTERN
@_VARNAME
@_PORT
@_SHOW
@_TITLE
@_WIDTH
@_HEIGHT
def var_velocity_level(config, hgrid, out2d_pattern, velx_pattern, vely_pattern,
                        var_pattern, varname, port, show, title, width, height):
    """Scalar field overlaid with per-level (3-D) velocity vectors.

    Uses the full ``horizontalVelX`` / ``horizontalVelY`` fields rather than
    the depth-averaged 2-D velocity.  Both time and vertical level are
    selectable via widgets.

    \b
    YAML section: var_velocity_level_animation
    Keys: hgrid, out2d_pattern, velx_pattern, vely_pattern, var_pattern,
          varname, port, show, title, width, height

    \b
    Example:
        schismviz viz var-velocity-level \\
            --hgrid hgrid.gr3 \\
            --out2d-pattern "outputs/out2d_*.nc" \\
            --velx-pattern "outputs/horizontalVelX_*.nc" \\
            --vely-pattern "outputs/horizontalVelY_*.nc" \\
            --var-pattern "outputs/salinity_*.nc" \\
            --varname salinity
    """
    import panel as pn
    from .viz_commands import var_velocity_level_panel

    pn.extension()
    cfg = _merge(
        _load_yaml_section(config, "var_velocity_level_animation"),
        hgrid=hgrid, out2d_pattern=out2d_pattern,
        velx_pattern=velx_pattern, vely_pattern=vely_pattern,
        var_pattern=var_pattern, varname=varname,
        port=port, title=title, width=width, height=height,
    )
    _require(cfg, "hgrid", "out2d_pattern", "velx_pattern", "vely_pattern", "var_pattern")

    _varname = cfg.get("varname", "salinity")
    panel = var_velocity_level_panel(
        cfg["hgrid"],
        cfg["out2d_pattern"],
        cfg["velx_pattern"],
        cfg["vely_pattern"],
        cfg["var_pattern"],
        varname=_varname,
        title=cfg.get("title", f"SCHISM: {_varname} + Per-Level Velocity"),
        width=cfg.get("width", 1000),
        height=cfg.get("height", 500),
    )
    _serve(panel, cfg.get("title", f"SCHISM: {_varname} + Per-Level Velocity"),
           cfg.get("port", 5006), show)


# ---------------------------------------------------------------------------
# stations
# ---------------------------------------------------------------------------

@viz.command("stations")
@_CONFIG
@_HGRID
@click.option(
    "--station-in", "station_in", default=None, type=click.Path(),
    help="Path to station.in file.",
)
@click.option(
    "--staout-prefix", "staout_prefix", default=None, type=click.Path(),
    help=(
        "Path prefix for staout_N files.  The variable index (1-9) is "
        "appended automatically, e.g. ./outputs/staout_"
    ),
)
@click.option(
    "--reftime", default=None,
    help="Model reference time in ISO-8601 format (e.g. 2000-01-01).",
)
@_PORT
@_SHOW
@_TITLE
@_WIDTH
@_HEIGHT
def stations_map(config, hgrid, station_in, staout_prefix, reftime,
                  port, show, title, width, height):
    """Interactive stations map with clickable time-series output display.

    The mesh is drawn in the background; red dots mark each station from
    ``station.in``.  Clicking a dot shows the corresponding time-series from
    the ``staout_N`` files for the selected variable type.

    \b
    YAML section: stations_map
    Keys: hgrid, station_in, staout_prefix, reftime, port, show,
          title, width, height

    \b
    Example:
        schismviz viz stations \\
            --hgrid hgrid.gr3 \\
            --station-in station.in \\
            --staout-prefix outputs/staout_ \\
            --reftime 2000-01-01
    """
    import panel as pn
    from .viz_commands import stations_map_panel

    pn.extension()
    cfg = _merge(
        _load_yaml_section(config, "stations_map"),
        hgrid=hgrid, station_in=station_in, staout_prefix=staout_prefix,
        reftime=reftime, port=port, title=title, width=width, height=height,
    )
    _require(cfg, "hgrid", "station_in", "staout_prefix")

    panel = stations_map_panel(
        cfg["hgrid"],
        cfg["station_in"],
        cfg["staout_prefix"],
        reftime=cfg.get("reftime", "2000-01-01"),
        title=cfg.get("title", "Station Output Display"),
        width=cfg.get("width", 800),
        height=cfg.get("height", 400),
    )
    _serve(panel, cfg.get("title", "Station Output Display"),
           cfg.get("port", 5006), show)
