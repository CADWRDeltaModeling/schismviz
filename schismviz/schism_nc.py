"""Generic UI manager for any combined SCHISM netCDF output file.

This module provides :class:`SchismNcUIManager`, a
:class:`~dvue.tsdataui.TimeSeriesDataUIManager` subclass that accepts **any**
combination of SCHISM combined output files — ``out2d_*.nc``,
``salinity_*.nc``, ``temperature_*.nc``, ``hvel_*.nc``, ``zCoordinates_*.nc``,
etc. — and auto-discovers the available variables.

* 2-D variables (those **without** a ``nSCHISM_vgrid_layers`` dimension)
  produce one catalog row per *(node, variable)*.
* 3-D variables (those **with** a ``nSCHISM_vgrid_layers`` dimension)
  produce one row per *(node, variable, layer_k)* for each selected layer.

By default only the **surface** (k = last) and **bottom** (k = 0) layers are
exposed.  Pass ``layers="all"`` to expose every layer, or
``layers=[k1, k2, ...]`` to select specific indices.

.. note::
    This manager handles **combined** output files only.  If your run
    produced per-processor ``schout_XXXXXX_N.nc`` files, pre-combine them
    first with :func:`bdschism.combine_nc.combine_nc` before passing them
    here.

Typical usage
-------------
>>> from schismviz.schism_nc import SchismNcUIManager
>>> import glob
>>> sal_files = sorted(glob.glob("outputs/salinity_*.nc"))
>>> mgr = SchismNcUIManager(*sal_files, nodes={\"Martinez\": 1042}, layers=None)
>>> app = mgr.get_panel()
>>> app.servable()
"""

from __future__ import annotations

import glob as _glob
import logging
import pathlib
from typing import Sequence, Union

import numpy as np
import pandas as pd
import param
import holoviews as hv
import panel as pn

hv.extension("bokeh")
pn.extension("tabulator", notifications=True, design="native")

from dvue.tsdataui import TimeSeriesDataUIManager, TimeSeriesPlotAction
from schismviz._nc_utils import (
    _parse_base_date,
    _decode_times,
    _classify_vars,
    _resolve_layers,
    SCHISM_HGRID_NODE_DIM,
    SCHISM_VGRID_DIM,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CRS helpers for map display
# ---------------------------------------------------------------------------


def _autodetect_epsg(x_arr: "np.ndarray", y_arr: "np.ndarray") -> int | None:
    """Guess EPSG code from node coordinate ranges.

    Returns
    -------
    int or None
        4326 for geographic (lat/lon), 32610 for UTM Zone 10 N (Bay-Delta),
        or *None* when the range is ambiguous / synthetic.
    """
    max_abs_x = float(np.abs(x_arr).max())
    max_abs_y = float(np.abs(y_arr).max())
    # Geographic WGS84
    if max_abs_x <= 180.0 and max_abs_y <= 90.0:
        return 4326
    # Projected (UTM-like): easting 100 000 – 900 000, northing 0 – 10 100 000
    x_min = float(x_arr.min())
    x_max = float(x_arr.max())
    y_min = float(y_arr.min())
    y_max = float(y_arr.max())
    if 100_000 <= x_min and x_max <= 900_000 and 0 <= y_min and y_max <= 10_100_000:
        # Default to UTM Zone 10 N (Bay-Delta / NorCal standard per AGENTS.md)
        return 32610
    return None


def _epsg_to_cartopy(epsg: int):
    """Convert an EPSG code to a :mod:`cartopy.crs` object.

    Handles geographic EPSG:4326/4269, WGS-84 / NAD83 UTM zones
    (EPSG:326nn / 327nn / 269nn), and falls back to ``ccrs.epsg()``
    for other codes.
    """
    import cartopy.crs as ccrs

    if epsg in (4326, 4269, 4267):
        return ccrs.PlateCarree()
    # WGS-84 UTM north (32601–32660)
    if 32601 <= epsg <= 32660:
        return ccrs.UTM(zone=epsg - 32600)
    # WGS-84 UTM south (32701–32760)
    if 32701 <= epsg <= 32760:
        return ccrs.UTM(zone=epsg - 32700, southern_hemisphere=True)
    # NAD83 UTM north (26901–26960)
    if 26901 <= epsg <= 26960:
        return ccrs.UTM(zone=epsg - 26900)
    # Generic fallback via pyproj
    try:
        return ccrs.epsg(epsg)
    except Exception:
        logger.warning("Could not convert EPSG:%d to cartopy CRS; defaulting to PlateCarree.", epsg)
        return ccrs.PlateCarree()


# ---------------------------------------------------------------------------
# Plot action
# ---------------------------------------------------------------------------


class SchismNcPlotAction(TimeSeriesPlotAction):
    """TimeSeriesPlotAction with layer-aware curve labels and titles."""

    @staticmethod
    def _make_label(r) -> str:
        node_name = r.get("node_name", str(r.get("node_id", "?")))
        var = r.get("variable", "")
        layer_k = r.get("layer_k", pd.NA)
        if pd.isna(layer_k):
            return f"{node_name}:{var}"
        return f"{node_name}:{var}[k={int(layer_k)}]"

    def create_curve(self, df, r, unit, file_index=None):
        label = self._make_label(r)
        if file_index:
            label = f"{file_index}:{label}"
        var = r.get("variable", "")
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
            title_map[group_key] = {"nodes": set(), "vars": set(), "layers": set()}
        title_map[group_key]["nodes"].add(
            str(row.get("node_name", row.get("node_id", "")))
        )
        title_map[group_key]["vars"].add(str(row.get("variable", "")))
        layer_k = row.get("layer_k", pd.NA)
        if not pd.isna(layer_k):
            title_map[group_key]["layers"].add(int(layer_k))

    def create_title(self, v):
        if isinstance(v, dict):
            nodes = ", ".join(sorted(v.get("nodes", [])))
            vars_ = ", ".join(sorted(v.get("vars", [])))
            layers = v.get("layers", set())
            layer_str = ""
            if layers:
                layer_str = " [k=" + ",".join(str(k) for k in sorted(layers)) + "]"
            return f"{vars_}{layer_str} @ node(s) {nodes}"
        return str(v)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class SchismNcUIManager(TimeSeriesDataUIManager):
    """UI manager for any combined SCHISM netCDF output files.

    Auto-discovers 2-D and 3-D variables from the supplied files and builds
    a time-series catalog.  Optionally uses :mod:`suxarray` for grid context
    when ``zcoord_files`` are provided.

    Parameters
    ----------
    *nc_files : str or Path
        Paths to combined SCHISM netCDF files (e.g. ``out2d_*.nc``,
        ``salinity_*.nc``).  Files are sorted lexicographically before
        opening.
    nodes : list of int | dict | pandas.DataFrame | None
        Which mesh nodes to include.

        * **None** – all nodes (may produce a very large catalog).
        * **list of int** – 0-based node indices into
          ``nSCHISM_hgrid_node``.
        * **dict** – ``{name: node_id}`` mapping.
        * **pandas.DataFrame** – must have a ``node_id`` (int) column and an
          optional ``name`` column for human-readable labels.

    variables : list of str | None
        Explicit variable names to include.  Defaults to all data variables
        found in the files (excluding grid topology variables).
    layers : None | "all" | list of int
        Which vertical layers to include for 3-D variables.

        * ``None`` *(default)* — surface (k = last) and bottom (k = 0).
        * ``"all"`` — every layer.
        * ``[k1, k2, ...]`` — specific layer indices (0-based).

    zcoord_files : list of str/Path | None
        Paths to ``zCoordinates_*.nc`` files.  When supplied, a
        :class:`suxarray.Grid` is opened for grid-context queries.
    coord_files : list of str/Path | None
        Paths to ``out2d_*.nc`` files that carry the mesh node coordinates
        (``SCHISM_hgrid_node_x`` / ``SCHISM_hgrid_node_y``).  Required when
        the primary *nc_files* are tracer or velocity outputs that do **not**
        embed node positions (e.g. ``salinity_*.nc``, ``temperature_*.nc``,
        ``hvel_*.nc``).  Not needed for ``out2d_*.nc`` which includes coords.
    study_name : str
        Label displayed in the UI title bar.
    epsg : int or None
        EPSG code for the node coordinate reference system.  Used to build a
        :class:`geopandas.GeoDataFrame` catalog so that the dvue map panel
        displays an interactive node-selection map.

        * ``None`` *(default)* — auto-detect from the coordinate range:
          geographic lat/lon → EPSG:4326; UTM-like projected values in the
          Bay-Delta easting/northing window → EPSG:32610 (UTM Zone 10 N).
          If detection fails (e.g. synthetic grids), map display is skipped.
        * Any valid EPSG integer — force that CRS (e.g. ``32610`` for UTM10N,
          ``4326`` for WGS-84 lat/lon, ``26910`` for NAD83 UTM10N).
    """

    study_name = param.String(default="schism_nc", doc="Label for this study")
    show_source_compare = param.Boolean(
        default=True,
        doc="Show the Source Compare action in the Add to Catalog menu.",
    )

    def __init__(
        self,
        *nc_files: Union[str, pathlib.Path],
        nodes=None,
        variables: list[str] | None = None,
        layers: Union[None, str, list[int]] = None,
        zcoord_files=None,
        coord_files=None,
        study_name: str = "schism_nc",
        epsg: int | None = None,
        **kwargs,
    ):
        self._nc_files = sorted(str(f) for f in nc_files)
        if not self._nc_files:
            raise ValueError("At least one NC file must be provided.")

        self._variables_arg = list(variables) if variables is not None else None
        self._nodes_arg = nodes
        self._layers_arg = layers
        self._epsg_arg = epsg  # None = auto-detect during _build_catalog
        self._zcoord_files = (
            sorted(str(f) for f in zcoord_files) if zcoord_files else None
        )
        # coord_files: out2d_*.nc files that carry SCHISM_hgrid_node_x/y when
        # the primary nc_files do not (e.g. salinity_*.nc, temperature_*.nc).
        self._coord_files = (
            sorted(str(f) for f in coord_files) if coord_files else None
        )

        # Lazy state
        self._ds = None
        self._ds_coords = None   # separate coord dataset when coord_files given
        self._base_date: pd.Timestamp | None = None
        self._grid = None  # suxarray.Grid, populated lazily
        self._map_epsg: int | None = None  # resolved EPSG (set in _build_catalog)

        # Build catalog before super().__init__ which calls get_data_catalog()
        self._dfcat = self._build_catalog()

        super().__init__(**kwargs)

        self.study_name = study_name
        self.color_cycle_column = "variable"
        self.dashed_line_cycle_column = "node_name"
        self.marker_cycle_column = "node_name"

    # ------------------------------------------------------------------
    # Dataset / grid access
    # ------------------------------------------------------------------

    def _open_dataset(self):
        """Return the lazily-opened multi-file xarray Dataset."""
        if self._ds is None:
            import xarray as xr

            self._ds = xr.open_mfdataset(
                self._nc_files,
                concat_dim="time",
                combine="nested",
                data_vars="minimal",
                coords="minimal",
                compat="override",
            )
            base_date_str = self._ds.time.attrs.get("base_date", "")
            if not base_date_str.strip():
                raise ValueError(
                    "NC file has no 'base_date' attribute on the time variable. "
                    "Cannot decode timestamps."
                )
            self._base_date = _parse_base_date(base_date_str)
        return self._ds

    def _open_coord_dataset(self):
        """Return a Dataset that is guaranteed to contain node coordinates.

        If *coord_files* were provided those are opened; otherwise the primary
        dataset is used (which works for ``out2d_*.nc`` that carry the coords).
        If neither source has coordinates a :exc:`KeyError` will surface when
        ``_build_catalog`` tries to access ``SCHISM_hgrid_node_x``.
        """
        if self._coord_files is not None:
            if self._ds_coords is None:
                import xarray as xr

                self._ds_coords = xr.open_mfdataset(
                    self._coord_files,
                    concat_dim="time",
                    combine="nested",
                    data_vars="minimal",
                    coords="minimal",
                    compat="override",
                )
            return self._ds_coords
        return self._open_dataset()

    def _open_grid(self):
        """Return a :class:`suxarray.Grid` (lazily), or ``None`` if no zcoord files."""
        if self._zcoord_files is None:
            return None
        if self._grid is None:
            try:
                from suxarray.core.api import open_grid

                self._grid = open_grid(self._nc_files, self._zcoord_files)
            except Exception as exc:
                logger.warning("suxarray grid could not be opened: %s", exc)
                self._grid = None
        return self._grid

    # ------------------------------------------------------------------
    # Node resolution
    # ------------------------------------------------------------------

    def _resolve_nodes(
        self, node_x: np.ndarray, node_y: np.ndarray
    ) -> tuple[list[int], list[str]]:
        """Resolve *nodes* argument into parallel (node_ids, node_names) lists."""
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

    # ------------------------------------------------------------------
    # Catalog construction
    # ------------------------------------------------------------------

    def _build_catalog(self) -> pd.DataFrame:
        ds = self._open_dataset()
        ds_coords = self._open_coord_dataset()

        # Extract node coordinates (may be (time, node) in combined datasets)
        try:
            node_x_da = ds_coords["SCHISM_hgrid_node_x"]
            node_y_da = ds_coords["SCHISM_hgrid_node_y"]
        except KeyError as exc:
            raise KeyError(
                "SCHISM_hgrid_node_x / SCHISM_hgrid_node_y not found in the "
                "supplied NC files.  For tracer/velocity output files that do "
                "not embed node coordinates (e.g. salinity_*.nc), pass the "
                "corresponding out2d_*.nc files via the 'coord_files' argument "
                "so that node positions can be resolved."
            ) from exc
        if "time" in node_x_da.dims:
            node_x = node_x_da.isel(time=0).values
            node_y = node_y_da.isel(time=0).values
        else:
            node_x = node_x_da.values
            node_y = node_y_da.values

        node_ids, node_names = self._resolve_nodes(node_x, node_y)

        # Determine which variables to include
        var_info = _classify_vars(ds)  # varname → (unit, is_3d)
        if self._variables_arg is not None:
            # Filter to requested variables, warn on missing
            filtered = {}
            for v in self._variables_arg:
                if v in var_info:
                    filtered[v] = var_info[v]
                else:
                    logger.warning("Requested variable %r not found in NC files; skipped.", v)
            var_info = filtered

        if not var_info:
            raise ValueError(
                "Catalog is empty — no matching data variables found in the NC files."
            )

        # Determine layer indices for 3-D variables
        n_layers = ds.sizes.get(SCHISM_VGRID_DIM, 0)
        layer_indices = _resolve_layers(n_layers, self._layers_arg) if n_layers > 0 else []

        representative_file = self._nc_files[0]
        rows = []
        for node_id, node_name in zip(node_ids, node_names):
            for varname, (unit, is_3d) in var_info.items():
                if is_3d:
                    for k in layer_indices:
                        rows.append(
                            {
                                "node_id": int(node_id),
                                "node_name": node_name,
                                "variable": varname,
                                "layer_k": int(k),
                                "unit": unit,
                                "x": float(node_x[node_id]),
                                "y": float(node_y[node_id]),
                                "filename": representative_file,
                            }
                        )
                else:
                    rows.append(
                        {
                            "node_id": int(node_id),
                            "node_name": node_name,
                            "variable": varname,
                            "layer_k": pd.NA,
                            "unit": unit,
                            "x": float(node_x[node_id]),
                            "y": float(node_y[node_id]),
                            "filename": representative_file,
                        }
                    )

        if not rows:
            raise ValueError(
                "Catalog is empty — no rows were generated. "
                "Check nodes, variables, and layer arguments."
            )

        df = pd.DataFrame(rows)
        # Use nullable integer type so pd.NA round-trips without coercion to float
        df["layer_k"] = df["layer_k"].astype(pd.Int64Dtype())

        # Attempt to wrap as GeoDataFrame for map display
        df = self._try_wrap_geodataframe(df, node_x, node_y)
        return df

    def _try_wrap_geodataframe(
        self,
        df: pd.DataFrame,
        node_x: "np.ndarray | None" = None,
        node_y: "np.ndarray | None" = None,
    ) -> pd.DataFrame:
        """Wrap *df* in a :class:`geopandas.GeoDataFrame` if a valid CRS can be
        determined from the node coordinates.

        Determines the EPSG from ``self._epsg_arg`` (explicit) or auto-detects
        from the x/y value ranges.  On failure or when the CRS cannot be
        determined, returns *df* unchanged and logs a warning.

        The resolved EPSG is stored in ``self._map_epsg`` so the CLI handler
        can retrieve it for the ``serve_session_app`` call.
        """
        try:
            import geopandas as gpd
            from shapely.geometry import Point
        except ImportError:
            logger.debug("geopandas/shapely not available; map view disabled.")
            return df

        # Resolve x/y arrays (use catalog columns as fallback)
        if node_x is None or node_y is None:
            x_arr = df["x"].values
            y_arr = df["y"].values
        else:
            x_arr = node_x
            y_arr = node_y

        # Determine EPSG
        epsg = self._epsg_arg
        if epsg is None:
            epsg = _autodetect_epsg(x_arr, y_arr)
        if epsg is None:
            logger.debug(
                "CRS auto-detection failed for coordinate range x=[%g, %g], "
                "y=[%g, %g].  Map view disabled.  Pass epsg= to override.",
                float(x_arr.min()), float(x_arr.max()),
                float(y_arr.min()), float(y_arr.max()),
            )
            return df

        self._map_epsg = epsg

        try:
            geometry = [Point(float(x), float(y)) for x, y in zip(df["x"], df["y"])]
            gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=f"EPSG:{epsg}")
            logger.debug("Map GeoDataFrame built with EPSG:%d (%d rows).", epsg, len(gdf))
            return gdf
        except Exception as exc:
            logger.warning("Could not build GeoDataFrame for map view: %s", exc)
            return df

    def get_map_crs(self):
        """Return the cartopy CRS for the map panel, or *None* if unavailable."""
        if self._map_epsg is None:
            return None
        return _epsg_to_cartopy(self._map_epsg)

    # ------------------------------------------------------------------
    # TimeSeriesDataUIManager required overrides
    # ------------------------------------------------------------------

    def get_data_catalog(self) -> pd.DataFrame:
        return self._dfcat

    def get_time_range(self, dfcat: pd.DataFrame) -> tuple:
        ds = self._open_dataset()
        times = _decode_times(self._base_date, ds.time.values)
        valid = times[times.notna()]
        return (valid[0], valid[-1])

    def is_irregular(self, r) -> bool:
        return False

    def build_station_name(self, r) -> str:
        node_name = r.get("node_name", str(r.get("node_id", "?")))
        var = r.get("variable", "")
        layer_k = r.get("layer_k", pd.NA)
        if pd.isna(layer_k):
            return f"{node_name}:{var}"
        return f"{node_name}:{var}[k={int(layer_k)}]"

    def get_data_for_time_range(self, r, time_range) -> tuple[pd.DataFrame, str, str]:
        """Extract a time series at a single node (and optional layer).

        Returns ``(df, unit, ptype)`` as required by dvue.
        """
        ds = self._open_dataset()
        times = _decode_times(self._base_date, ds.time.values)
        mask = (times >= pd.Timestamp(time_range[0])) & (times <= pd.Timestamp(time_range[1]))

        varname = r["variable"]
        node_id = int(r["node_id"])
        layer_k = r.get("layer_k", pd.NA)

        da = ds[varname].isel(**{SCHISM_HGRID_NODE_DIM: node_id})
        if not pd.isna(layer_k):
            da = da.isel(**{SCHISM_VGRID_DIM: int(layer_k)})

        values = da.values[mask]
        index = times[mask]

        col_name = self.build_station_name(r)
        df = pd.DataFrame({col_name: values}, index=index)
        df.index.name = "Time"
        return df, r.get("unit", ""), "INST-VAL"

    def get_data_reference(self, row):
        """Return a lightweight adapter so the dvue plot action can load data.

        The dvue :class:`~dvue.actions.PlotAction` always calls
        ``get_data_reference(row).getData(time_range=...)``.  When
        ``data_catalog`` is ``None`` (Pattern-B manager) the base-class
        implementation raises ``NotImplementedError``, which the plot action
        silently interprets as "no data".  This override returns a thin
        wrapper that delegates to :meth:`get_data_for_time_range`.
        """
        mgr = self

        class _Ref:
            def getData(self, time_range=None):
                tr = time_range if time_range is not None else mgr.time_range
                df, unit, _ = mgr.get_data_for_time_range(row, tr)
                df.attrs["unit"] = unit
                return df

            def get_attribute(self, key, default=None):
                return row.get(key, default)

        return _Ref()

    # ------------------------------------------------------------------
    # UI config
    # ------------------------------------------------------------------

    def get_table_schema(self, df=None):
        if df is None:
            df = self.get_data_catalog()
        # Only show layer_k column when there are any 3-D rows
        has_3d = df["layer_k"].notna().any()
        required = ["node_id", "node_name", "variable", "unit", "x", "y"]
        widths = {
            "node_id": "8%",
            "node_name": "15%",
            "variable": "20%",
            "unit": "8%",
            "x": "12%",
            "y": "12%",
        }
        if has_3d:
            required.insert(3, "layer_k")
            widths["layer_k"] = "8%"
        return {
            "required_columns": required,
            "optional_columns": [],
            "hidden_by_default": [],
            "drop_if_all_null": False,
            "column_widths": widths,
            "filters": {
                "node_name": {"type": "input", "func": "like", "placeholder": "Enter match"},
                "variable": {"type": "input", "func": "like", "placeholder": "Enter match"},
            },
        }

    def get_tooltips(self) -> list:
        return [
            ("Node", "@node_name"),
            ("Variable", "@variable"),
            ("Layer k", "@layer_k"),
            ("Unit", "@unit"),
            ("x", "@x"),
            ("y", "@y"),
        ]

    def get_map_color_columns(self) -> list:
        return ["variable"]

    def get_name_to_color(self) -> dict:
        return {}

    def get_map_marker_columns(self) -> list:
        return ["variable"]

    def get_name_to_marker(self) -> dict:
        return {}

    def _make_plot_action(self):
        return SchismNcPlotAction()


# ---------------------------------------------------------------------------
# Click CLI command
# ---------------------------------------------------------------------------

import click
import yaml as _yaml
from schismviz.session import serve_session_app


def _load_yaml_section(config_file, section):
    if config_file is None:
        return {}
    with open(config_file) as fh:
        data = _yaml.safe_load(fh) or {}
    return data.get(section, {})


def _merge(cfg, **cli_overrides):
    merged = dict(cfg)
    for k, v in cli_overrides.items():
        if v is not None:
            merged[k] = v
    return merged


@click.command(name="nc")
@click.option(
    "--config", "-c",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="YAML configuration file.  CLI options override values in this file.",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Directory containing the SCHISM combined NC output files.",
)
@click.option(
    "--pattern",
    default=None,
    help=(
        "Glob pattern for NC files relative to --output-dir, "
        "e.g. 'salinity_*.nc' or '*.nc' (default: '*.nc')."
    ),
)
@click.option(
    "--zcoord-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help=(
        "Directory containing zCoordinates_*.nc files for 3-D grid context. "
        "When provided, suxarray is used to open the grid."
    ),
)
@click.option(
    "--coord-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help=(
        "Directory containing out2d_*.nc files that provide mesh node "
        "coordinates (SCHISM_hgrid_node_x/y).  Required when the primary "
        "output files (salinity, temperature, hvel) do not embed coordinates."
    ),
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
    help="Comma-separated variable names, e.g. 'Salinity,temperature'.",
)
@click.option(
    "--layers",
    default=None,
    help=(
        "Vertical layer selection for 3-D variables.  "
        "Use 'all' for every layer, or a comma-separated list of 0-based "
        "indices, e.g. '0,5,10'.  Default (unset): surface + bottom only."
    ),
)
@click.option("--title", default=None, help="Dashboard title shown in the browser.")
@click.option(
    "--port", default=None, type=int,
    help="Port for the Panel server (0 or unset = random available port).",
)
@click.option(
    "--epsg", default=None, type=int,
    help=(
        "EPSG code for the node coordinate reference system.  Used to display "
        "an interactive map of nodes.  When omitted, the CRS is auto-detected "
        "from the coordinate range (geographic → EPSG:4326; Bay-Delta UTM → "
        "EPSG:32610).  Pass 0 to disable the map even when auto-detection "
        "would succeed."
    ),
)
@click.option(
    "--show/--no-show", default=True,
    help="Open a browser tab automatically (default: --show).",
)
def show_schism_nc_ui(
    config,
    output_dir,
    pattern,
    zcoord_dir,
    coord_dir,
    nodes,
    nodes_csv,
    variables,
    layers,
    title,
    port,
    epsg,
    show,
):
    """Interactive time-series UI for any combined SCHISM netCDF output files.

    Handles out2d, salinity, temperature, hvel and other combined outputs.
    2-D variables produce one time-series per node; 3-D variables produce
    one per (node, layer).

    \b
    Examples:
      schismviz nc --output-dir outputs/ --pattern "salinity_*.nc" --nodes 0,100
      schismviz nc --output-dir outputs/ --layers all --nodes-csv nodes.csv
      schismviz nc --config my_project.yaml

    \b
    YAML config (section ``nc``):
      nc:
        output_dir: outputs/
        pattern: "salinity_*.nc"
        zcoord_dir: outputs/
        nodes: "0,100,500"
        variables: "Salinity"
        layers: "0,last"
        title: "SCHISM salinity"
        port: 0

    \b
    Note:
      This command works with *combined* output files only.  Per-processor
      ``schout_XXXXXX_N.nc`` files must be pre-combined with
      ``bdschism combine-nc`` before use.
    """
    import pandas as pd

    # ---- merge YAML + CLI --------------------------------------------------
    cfg = _load_yaml_section(config, "nc")
    cfg = _merge(
        cfg,
        output_dir=output_dir,
        pattern=pattern,
        zcoord_dir=zcoord_dir,
        coord_dir=coord_dir,
        nodes=nodes,
        nodes_csv=nodes_csv,
        variables=variables,
        layers=layers,
        title=title,
        port=port,
        epsg=epsg,
    )

    # ---- resolve NC files --------------------------------------------------
    out_dir = cfg.get("output_dir", ".")
    glob_pattern = cfg.get("pattern", "*.nc")
    files = sorted(_glob.glob(str(pathlib.Path(out_dir) / glob_pattern)))
    if not files:
        raise click.ClickException(
            f"No files matching '{glob_pattern}' found in '{out_dir}'."
        )

    # ---- resolve coord files (optional, for tracer/velocity files) ---------
    coord_files_arg = None
    coord_dir_val = cfg.get("coord_dir")
    if coord_dir_val is not None:
        coord_files_arg = sorted(
            _glob.glob(str(pathlib.Path(coord_dir_val) / "out2d_*.nc"))
        )
        if not coord_files_arg:
            logger.warning(
                "No out2d_*.nc files found in '%s'; node coordinates may be "
                "missing for tracer/velocity output files.",
                coord_dir_val,
            )
            coord_files_arg = None

    # ---- resolve zcoord files (optional) -----------------------------------
    zcoord_files_arg = None
    zcoord_dir_val = cfg.get("zcoord_dir")
    if zcoord_dir_val is not None:
        zcoord_files_arg = sorted(
            _glob.glob(str(pathlib.Path(zcoord_dir_val) / "zCoordinates_*.nc"))
        )
        if not zcoord_files_arg:
            logger.warning(
                "No zCoordinates_*.nc files found in '%s'; grid context disabled.",
                zcoord_dir_val,
            )
            zcoord_files_arg = None

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

    # ---- resolve layers ----------------------------------------------------
    layers_arg = None
    layers_str = cfg.get("layers")
    if layers_str is not None:
        s = str(layers_str).strip()
        if s.lower() == "all":
            layers_arg = "all"
        else:
            layers_arg = [int(k.strip()) for k in s.split(",") if k.strip()]

    # ---- build manager and launch UI ---------------------------------------
    dashboard_title = cfg.get("title", "SCHISM NC Viewer")
    server_port = int(cfg.get("port", 0) or 0)

    # Resolve EPSG / CRS for the map panel
    epsg_arg = cfg.get("epsg")
    # epsg=0 is a sentinel to disable the map explicitly
    if epsg_arg == 0:
        epsg_arg = None
        map_crs = None
    elif epsg_arg is not None:
        epsg_arg = int(epsg_arg)
        map_crs = _epsg_to_cartopy(epsg_arg)
    else:
        # Auto-detect from first coord file (or first primary file)
        probe_files = coord_files_arg or files
        map_crs = None
        try:
            import xarray as xr

            ds_probe = xr.open_dataset(probe_files[0])
            _px = ds_probe["SCHISM_hgrid_node_x"].values
            _py = ds_probe["SCHISM_hgrid_node_y"].values
            ds_probe.close()
            epsg_arg = _autodetect_epsg(_px, _py)
            if epsg_arg is not None:
                map_crs = _epsg_to_cartopy(epsg_arg)
            else:
                logger.info(
                    "CRS auto-detection inconclusive; map view disabled. "
                    "Use --epsg to enable."
                )
        except Exception as exc:
            logger.warning("CRS probe failed (%s); map view disabled.", exc)

    def build_manager():
        return SchismNcUIManager(
            *files,
            nodes=nodes_arg,
            variables=variables_arg,
            layers=layers_arg,
            zcoord_files=zcoord_files_arg,
            coord_files=coord_files_arg,
            study_name=cfg.get("title", "SCHISM NC Viewer"),
            epsg=epsg_arg,
        )

    serve_session_app(
        build_manager,
        title=dashboard_title,
        port=server_port,
        open=show,
        crs=map_crs,
        station_id_column="node_id" if map_crs is not None else None,
    )
