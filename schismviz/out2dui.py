"""
UI manager for SCHISM out2d netCDF output files.

Provides time-series extraction at user-specified mesh nodes for 2D-field
variables written into ``out2d_*.nc`` files (elevation, depth-averaged
velocity components, dry-flag, …).

Typical usage
-------------
>>> from schismviz.out2dui import SchismOut2DUIManager
>>> import glob
>>> files = sorted(glob.glob("outputs/out2d_*.nc"))
>>> nodes = [0, 100, 500]          # node indices, or a DataFrame – see __init__
>>> mgr = SchismOut2DUIManager(*files, nodes=nodes)
>>> app = mgr.get_panel()
>>> app.servable()
"""

from __future__ import annotations

import glob as _glob
import logging
import pathlib
from typing import Sequence

import numpy as np
import pandas as pd
import param
import holoviews as hv
import panel as pn

hv.extension("bokeh")
pn.extension("tabulator", notifications=True, design="native")

from dvue.tsdataui import TimeSeriesDataUIManager, TimeSeriesPlotAction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Variables present in every standard out2d file, keyed by SCHISM variable
# name → (display_label, unit).
# ---------------------------------------------------------------------------
_OUT2D_NODE_VARS: dict[str, tuple[str, str]] = {
    "elevation": ("elevation", "m"),
    "depthAverageVelX": ("vel_x", "m/s"),
    "depthAverageVelY": ("vel_y", "m/s"),
    "dryFlagNode": ("dryFlag", ""),
}


def _parse_base_date(base_date_str: str) -> pd.Timestamp:
    """Parse the SCHISM *base_date* attribute string to a Timestamp.

    The attribute is formatted as ``' 2009  2 10       0.00       8.00'``.
    Only the first three integer fields (year, month, day) are used.
    """
    parts = base_date_str.split()
    return pd.Timestamp(int(parts[0]), int(parts[1]), int(parts[2]))


class SchismOut2DPlotAction(TimeSeriesPlotAction):
    """TimeSeriesPlotAction with out2d-specific curve labels and titles."""

    def create_curve(self, df, r, unit, file_index=None):
        node_name = r.get("node_name", str(r.get("node_id", "?")))
        var = r.get("variable", "")
        label = f"{node_name}:{var}"
        if file_index:
            label = f"{file_index}:{label}"
        ylabel = f"{var} ({unit})" if unit else var
        crv = hv.Curve(df.iloc[:, [0]], label=label).redim(value=label)
        return crv.opts(
            xlabel="Time",
            ylabel=ylabel,
            title=label,
            responsive=True,
            active_tools=["wheel_zoom"],
            tools=["hover"],
        )

    def append_to_title_map(self, title_map, group_key, row):
        if group_key not in title_map:
            title_map[group_key] = {"nodes": set(), "vars": set()}
        title_map[group_key]["nodes"].add(str(row.get("node_name", row.get("node_id", ""))))
        title_map[group_key]["vars"].add(str(row.get("variable", "")))

    def create_title(self, v):
        if isinstance(v, dict):
            nodes = ", ".join(sorted(v.get("nodes", [])))
            return f"{', '.join(sorted(v.get('vars', [])))} @ node(s) {nodes}"
        return str(v)


class SchismOut2DUIManager(TimeSeriesDataUIManager):
    """UI manager for SCHISM ``out2d_*.nc`` netCDF output files.

    Exposes a time-series catalog of 2D-field variables at user-specified
    mesh nodes.  Uses :mod:`xarray` ``open_mfdataset`` (lazy) to span
    multiple consecutive output files.

    Parameters
    ----------
    *out2d_files : str or Path
        Paths to ``out2d_*.nc`` files.  Pass them in any order; they are
        sorted lexicographically before opening.
    nodes : list of int | pandas.DataFrame | dict | None
        Which mesh nodes to include in the catalog.

        * **None** – all nodes (may produce a very large catalog).
        * **list/array of int** – node indices (0-based) into
          ``nSCHISM_hgrid_node``.
        * **pandas.DataFrame** – must have a ``node_id`` column (int) and
          an optional ``name`` column for human-readable labels.
        * **dict** – mapping ``{name: node_id}`` pairs.

    variables : list of str | None
        Variable names from the out2d files to include.  Defaults to
        ``["elevation", "depthAverageVelX", "depthAverageVelY",
        "dryFlagNode"]``.
    study_name : str
        Label for this study, shown in the UI title.
    """

    study_name = param.String(default="out2d", doc="Label for this study")
    show_source_compare = param.Boolean(
        default=True,
        doc="Show the Source Compare action in the Add to Catalog menu.",
    )

    def __init__(
        self,
        *out2d_files: str | pathlib.Path,
        nodes=None,
        variables: list[str] | None = None,
        study_name: str = "out2d",
        **kwargs,
    ):
        self._out2d_files = sorted(str(f) for f in out2d_files)
        if not self._out2d_files:
            raise ValueError("At least one out2d file must be provided.")

        self._variables = list(variables) if variables is not None else list(_OUT2D_NODE_VARS)
        self._nodes_arg = nodes

        # Lazy dataset — opened on first access.
        self._ds = None
        self._base_date: pd.Timestamp | None = None

        # Build the catalog DataFrame *before* super().__init__() which
        # calls get_data_catalog() and get_time_range() during setup.
        self._dfcat = self._build_catalog()

        super().__init__(**kwargs)

        # Set visual styling param defaults *after* super().__init__()
        self.study_name = study_name
        self.color_cycle_column = "variable"
        self.dashed_line_cycle_column = "node_name"
        self.marker_cycle_column = "node_name"

    # ------------------------------------------------------------------
    # Dataset access
    # ------------------------------------------------------------------

    def _open_dataset(self):
        """Return the lazily-opened multi-file xarray Dataset."""
        if self._ds is None:
            import xarray as xr

            self._ds = xr.open_mfdataset(
                self._out2d_files,
                concat_dim="time",
                combine="nested",
                data_vars="minimal",
                coords="minimal",
                compat="override",
            )
            base_date_str = self._ds.time.attrs.get("base_date", "")
            if not base_date_str.strip():
                raise ValueError(
                    "out2d file has no 'base_date' attribute on the time variable. "
                    "Cannot decode timestamps."
                )
            self._base_date = _parse_base_date(base_date_str)
        return self._ds

    def _decode_times(self, time_seconds) -> pd.DatetimeIndex:
        """Convert seconds-since-base_date array to DatetimeIndex."""
        return self._base_date + pd.to_timedelta(time_seconds, unit="s")

    # ------------------------------------------------------------------
    # Catalog construction
    # ------------------------------------------------------------------

    def _resolve_nodes(
        self, node_x: np.ndarray, node_y: np.ndarray
    ) -> tuple[list[int], list[str]]:
        """Resolve the *nodes* argument into parallel (node_ids, names) lists."""
        arg = self._nodes_arg
        if arg is None:
            ids = list(range(len(node_x)))
            names = [str(i) for i in ids]
        elif isinstance(arg, pd.DataFrame):
            ids = list(arg["node_id"].astype(int))
            names = list(
                arg["name"].astype(str) if "name" in arg.columns else arg["node_id"].astype(str)
            )
        elif isinstance(arg, dict):
            names = list(arg.keys())
            ids = [int(v) for v in arg.values()]
        else:
            ids = [int(i) for i in arg]
            names = [str(i) for i in ids]
        return ids, names

    def _build_catalog(self) -> pd.DataFrame:
        ds = self._open_dataset()

        # node_x / node_y may be (time, node) in the combined dataset if the
        # variable is promoted; use .values on the first time step when needed.
        node_x_da = ds["SCHISM_hgrid_node_x"]
        node_y_da = ds["SCHISM_hgrid_node_y"]
        if "time" in node_x_da.dims:
            node_x = node_x_da.isel(time=0).values
            node_y = node_y_da.isel(time=0).values
        else:
            node_x = node_x_da.values
            node_y = node_y_da.values

        node_ids, node_names = self._resolve_nodes(node_x, node_y)

        representative_file = self._out2d_files[0]
        rows = []
        for node_id, node_name in zip(node_ids, node_names):
            for var in self._variables:
                if var not in ds.data_vars:
                    logger.warning("Variable %r not found in out2d files; skipped.", var)
                    continue
                _, unit = _OUT2D_NODE_VARS.get(var, (var, ""))
                rows.append(
                    {
                        "node_id": int(node_id),
                        "node_name": node_name,
                        "variable": var,
                        "unit": unit,
                        "x": float(node_x[node_id]),
                        "y": float(node_y[node_id]),
                        "filename": representative_file,
                    }
                )

        if not rows:
            raise ValueError(
                "Catalog is empty — no matching variables found in the out2d files."
            )
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # TimeSeriesDataUIManager required overrides
    # ------------------------------------------------------------------

    def get_data_catalog(self) -> pd.DataFrame:
        return self._dfcat

    def get_time_range(self, dfcat: pd.DataFrame) -> tuple:
        ds = self._open_dataset()
        times = self._decode_times(ds.time.values)
        return (times[0], times[-1])

    def is_irregular(self, r) -> bool:
        return False

    def build_station_name(self, r) -> str:
        return f"{r['node_name']}:{r['variable']}"

    def get_data_for_time_range(self, r, time_range) -> tuple[pd.DataFrame, str, str]:
        """Extract time series at a single node for one variable.

        Returns ``(df, unit, ptype)`` as required by dvue.
        """
        ds = self._open_dataset()
        times = self._decode_times(ds.time.values)
        mask = (times >= pd.Timestamp(time_range[0])) & (times <= pd.Timestamp(time_range[1]))
        values = ds[r["variable"]].isel(nSCHISM_hgrid_node=int(r["node_id"])).values[mask]
        index = times[mask]
        df = pd.DataFrame({r["variable"]: values}, index=index)
        df.index.name = "Time"
        return df, r["unit"], "INST-VAL"

    # ------------------------------------------------------------------
    # DataUIManager required overrides — table / map configuration
    # ------------------------------------------------------------------

    def get_table_column_width_map(self) -> dict:
        return {
            "node_id": "10%",
            "node_name": "15%",
            "variable": "20%",
            "unit": "10%",
            "x": "15%",
            "y": "15%",
        }

    def get_table_filters(self) -> dict:
        return {
            "node_name": {
                "type": "input",
                "func": "like",
                "placeholder": "Enter match",
            },
            "variable": {
                "type": "input",
                "func": "like",
                "placeholder": "Enter match",
            },
        }

    def get_tooltips(self) -> list:
        return [
            ("Node", "@node_name"),
            ("Variable", "@variable"),
            ("Unit", "@unit"),
            ("x", "@x"),
            ("y", "@y"),
        ]

    def get_map_color_columns(self) -> list:
        return ["variable"]

    def get_name_to_color(self) -> dict:
        # Let dvue cycle through default colors.
        return {}

    def get_map_marker_columns(self) -> list:
        return ["variable"]

    def get_name_to_marker(self) -> dict:
        return {}

    # ------------------------------------------------------------------
    # Custom plot action
    # ------------------------------------------------------------------

    def _make_plot_action(self):
        return SchismOut2DPlotAction()


# ---------------------------------------------------------------------------
# Click CLI command
# ---------------------------------------------------------------------------

import click
import yaml as _yaml
from schismviz.session import serve_session_app


def _load_yaml_section(config_file, section):
    """Return *section* from a YAML file, or empty dict."""
    if config_file is None:
        return {}
    with open(config_file) as fh:
        data = _yaml.safe_load(fh) or {}
    return data.get(section, {})


def _merge(cfg, **cli_overrides):
    """Overlay non-None CLI values onto *cfg* dict."""
    merged = dict(cfg)
    for k, v in cli_overrides.items():
        if v is not None:
            merged[k] = v
    return merged


@click.command(name="out2d")
@click.option(
    "--config", "-c",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="YAML configuration file. CLI options override values in this file.",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Directory that contains the out2d_*.nc files.",
)
@click.option(
    "--nodes",
    default=None,
    help="Comma-separated 0-based node indices to include, e.g. '0,100,500'.",
)
@click.option(
    "--nodes-csv",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="CSV file with columns 'node_id' and optional 'name'.",
)
@click.option(
    "--variables",
    default=None,
    help="Comma-separated variable names, e.g. 'elevation,depthAverageVelX'.",
)
@click.option("--title", default=None, help="Dashboard title shown in the browser.")
@click.option(
    "--port", default=None, type=int,
    help="Port for the Panel server (0 or unset = random available port).",
)
@click.option(
    "--show/--no-show", default=True,
    help="Open a browser tab automatically (default: --show).",
)
def show_out2d_ui(
    config,
    output_dir,
    nodes,
    nodes_csv,
    variables,
    title,
    port,
    show,
):
    """Interactive time-series UI for SCHISM out2d_*.nc output files.

    Displays a Panel dashboard letting you select mesh nodes and explore
    2D-field variables (elevation, depth-averaged velocity, …) as time series.

    \b
    Examples:
      schismviz out2d --output-dir outputs/ --nodes 0,100,500
      schismviz out2d --config my_project.yaml

    \b
    YAML config (section ``out2d``):
      out2d:
        output_dir: outputs/
        nodes: "0,100,500"
        nodes_csv: nodes.csv
        variables: "elevation,depthAverageVelX"
        title: "SCHISM out2d"
        port: 0
    """
    import glob as _glob
    import pandas as pd
    import panel as pn
    from dvue.dataui import DataUI

    # ---- merge YAML + CLI --------------------------------------------------
    cfg = _load_yaml_section(config, "out2d")
    cfg = _merge(
        cfg,
        output_dir=output_dir,
        nodes=nodes,
        nodes_csv=nodes_csv,
        variables=variables,
        title=title,
        port=port,
    )

    # ---- resolve out2d files -----------------------------------------------
    out_dir = cfg.get("output_dir", ".")
    files = sorted(_glob.glob(str(pathlib.Path(out_dir) / "out2d_*.nc")))
    if not files:
        raise click.ClickException(
            f"No out2d_*.nc files found in '{out_dir}'. "
            "Use --output-dir to point to the SCHISM outputs directory."
        )

    # ---- resolve nodes -----------------------------------------------------
    nodes_arg = None
    nodes_csv_path = cfg.get("nodes_csv")
    nodes_str = cfg.get("nodes")
    if nodes_csv_path is not None:
        nodes_arg = pd.read_csv(nodes_csv_path)
        if "node_id" not in nodes_arg.columns:
            raise click.ClickException(
                f"nodes-csv '{nodes_csv_path}' must have a 'node_id' column."
            )
    elif nodes_str is not None:
        nodes_arg = [int(n.strip()) for n in str(nodes_str).split(",") if n.strip()]

    # ---- resolve variables -------------------------------------------------
    variables_arg = None
    variables_str = cfg.get("variables")
    if variables_str is not None:
        variables_arg = [v.strip() for v in str(variables_str).split(",") if v.strip()]

    # ---- build manager and launch UI ---------------------------------------
    dashboard_title = cfg.get("title", "SCHISM out2d")
    server_port = int(cfg.get("port", 0) or 0)

    def build_manager():
        return SchismOut2DUIManager(
            *files,
            nodes=nodes_arg,
            variables=variables_arg,
            study_name=cfg.get("title", "SCHISM out2d"),
        )

    serve_session_app(build_manager, title=dashboard_title, port=server_port, open=show)
