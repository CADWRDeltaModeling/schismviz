"""dvue DataReferenceReader for combined SCHISM netCDF output files.

Registers under ``ref_type = "schism_nc"`` with the dvue
:class:`~dvue.registry.ReaderRegistry`.  Activated automatically when
schismviz is installed via the ``dvue.plugins`` entry point.

``scan()`` reads only file metadata (variable names, node coordinates, time
extents) and returns one :class:`SchismNcDataReference` per
*(node_id, variable[, layer_k])* for **every** node in the file.  No
time-series data is loaded at this stage — ``getData()`` on each reference
is lazy and only reads the NC array when the user selects a node.

Usage via dvue CLI (after schismviz is installed)::

    dvue ui out2d_1.nc out2d_2.nc
    dvue ui schism_nc:salinity_1.nc   # explicit ref_type prefix

Usage in Python::

    from schismviz.schism_nc_reader import SchismNcReader
    from dvue.registry_ui import RegistryUIManager

    mgr = RegistryUIManager()
    mgr.add_source_files("outputs/out2d_1.nc", "outputs/out2d_2.nc")
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any, List, Optional

import numpy as np
import pandas as pd

from dvue.catalog import DataReference, DataReferenceReader

from schismviz._nc_utils import (
    _classify_vars,
    _decode_times,
    _parse_base_date,
    _resolve_layers,
    SCHISM_HGRID_NODE_DIM,
    SCHISM_VGRID_DIM,
)

logger = logging.getLogger(__name__)


class SchismNcDataReference(DataReference):
    """DataReference for a single SCHISM NC node/variable/layer time series.

    Sets ``ref_type = "schism_nc"`` so registry dispatch resolves to
    :class:`SchismNcReader`.
    """

    ref_type: str = "schism_nc"


class SchismNcReader(DataReferenceReader):
    """Load a single time-series from a combined SCHISM netCDF output file.

    One instance is created per source file path (``source``).  The opened
    :class:`xarray.Dataset` is cached between :meth:`load` calls.

    Parameters
    ----------
    source : str
        Path to a combined SCHISM netCDF file (e.g. ``out2d_1.nc``).

    Class attributes
    ----------------
    default_layers : None | "all" | list[int]
        Layer selection for 3-D variables.  Mirrors the argument accepted
        by :func:`schismviz._nc_utils._resolve_layers`:

        * ``None`` *(default)* — surface (last k) and bottom (k = 0).
        * ``"all"`` — every layer.
        * ``[k, ...]`` — explicit 0-based layer indices.
    """

    default_layers = None  # surface + bottom

    def __init__(self, source: str) -> None:
        self._source = source
        self._ds = None
        self._base_date: Optional[pd.Timestamp] = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _open(self):
        """Return the lazily-opened xarray Dataset."""
        if self._ds is None:
            import xarray as xr

            self._ds = xr.open_dataset(self._source)
            base_date_str = self._ds.time.attrs.get("base_date", "")
            if not base_date_str.strip():
                raise ValueError(
                    f"NC file {self._source!r} has no 'base_date' attribute on "
                    "the time variable. Cannot decode timestamps."
                )
            self._base_date = _parse_base_date(base_date_str)
        return self._ds

    # ------------------------------------------------------------------
    # DataReferenceReader protocol
    # ------------------------------------------------------------------

    def load(self, **attributes: Any) -> pd.DataFrame:
        """Return a single-column DataFrame with a DatetimeIndex.

        Required attributes
        -------------------
        variable : str
            Variable name as stored in the NC file (e.g. ``"elevation"``,
            ``"Salinity"``).
        node_id : int
            0-based SCHISM node index.
        layer_k : int or None
            0-based vertical layer index.  Pass ``None`` (or omit) for
            2-D variables.

        Optional attributes
        -------------------
        time_range : tuple[pd.Timestamp, pd.Timestamp] or None
            When provided, the returned DataFrame is sliced to this window
            (inclusive on both ends).
        """
        ds = self._open()
        variable = attributes["variable"]
        node_id = int(attributes["node_id"])
        layer_k = attributes.get("layer_k")
        time_range = attributes.get("time_range")

        times = _decode_times(self._base_date, ds.time.values)

        da = ds[variable]
        sel = {SCHISM_HGRID_NODE_DIM: node_id}
        if SCHISM_VGRID_DIM in da.dims:
            k = int(layer_k) if layer_k is not None else -1
            sel[SCHISM_VGRID_DIM] = k
        da = da.isel(sel)

        values = da.values.copy()

        # Mask dry instances for elevation.
        # SCHISM outputs raw elevation even for dry nodes; the value is
        # meaningless when total depth (depth + elevation) < h0.  Use the
        # minimum_depth scalar stored in the file as h0 (default 0.01 m).
        if variable == "elevation" and "depth" in ds:
            node_depth = float(ds["depth"].isel({SCHISM_HGRID_NODE_DIM: node_id}).values)
            h0 = float(ds["minimum_depth"].values.flat[0]) if "minimum_depth" in ds else 0.01
            dry_mask = (node_depth + values) < h0
            values = np.where(dry_mask, np.nan, values)

        df = pd.DataFrame({variable: values}, index=times)

        # Drop any NaT-indexed rows produced by fill-value time sentinels
        # (incomplete/pre-allocated output files).  These rows carry no real
        # data and their presence would corrupt downstream plots.
        df = df[df.index.notna()]

        if time_range is not None:
            start = pd.Timestamp(time_range[0])
            end = pd.Timestamp(time_range[1])
            df = df.loc[start:end]

        return df

    # ------------------------------------------------------------------
    # Scan (file discovery)
    # ------------------------------------------------------------------

    @classmethod
    def scan(cls, path: str) -> List[SchismNcDataReference]:
        """Scan a SCHISM combined NC file and return DataReferences.

        Returns one reference per *(node_id, variable[, layer_k])* tuple for
        **every** node in the file.  No time-series data is read at this stage;
        actual data is loaded lazily the first time
        :meth:`~dvue.catalog.DataReference.getData` is called on a reference
        (i.e. when the user selects a node in the UI).

        Node coordinates (``SCHISM_hgrid_node_x/y``) are stored as ``x``
        and ``y`` attributes when present in the file so the dvue map panel
        can render all nodes immediately.

        Time extent is stored as ``time_extent_start`` / ``time_extent_end``
        (ISO-8601 strings) so :meth:`~dvue.registry_ui.RegistryUIManager.on_file_added`
        can expand ``self.time_range`` automatically.

        Parameters
        ----------
        path : str
            Absolute path to the NC file.

        Returns
        -------
        list[SchismNcDataReference]

        Raises
        ------
        ValueError
            If the file has no ``base_date`` attribute on the time variable
            (not a combined SCHISM output).
        """
        import xarray as xr

        ds = xr.open_dataset(path)
        try:
            return cls._scan_dataset(ds, path)
        finally:
            ds.close()

    @classmethod
    def _scan_dataset(
        cls, ds, path: str
    ) -> List[SchismNcDataReference]:
        """Internal: produce refs from an already-open Dataset."""
        base_date_str = ds.time.attrs.get("base_date", "")
        if not base_date_str.strip():
            raise ValueError(
                f"NC file {path!r} has no 'base_date' attribute on the time "
                "variable.  Only combined SCHISM output files are supported."
            )
        base_date = _parse_base_date(base_date_str)
        times = _decode_times(base_date, ds.time.values)

        time_extent_start = times[0].isoformat() if len(times) > 0 else ""
        time_extent_end = times[-1].isoformat() if len(times) > 0 else ""

        # Node coordinates (present in out2d, absent in tracer/velocity files)
        node_x: Optional[np.ndarray] = None
        node_y: Optional[np.ndarray] = None
        try:
            nx_da = ds["SCHISM_hgrid_node_x"]
            ny_da = ds["SCHISM_hgrid_node_y"]
            node_x = nx_da.isel(time=0).values if "time" in nx_da.dims else nx_da.values
            node_y = ny_da.isel(time=0).values if "time" in ny_da.dims else ny_da.values
        except KeyError:
            logger.debug(
                "scan(%s): SCHISM_hgrid_node_x/y absent; "
                "node geometry will not be embedded in refs.",
                pathlib.Path(path).name,
            )

        n_nodes = ds.sizes.get(SCHISM_HGRID_NODE_DIM, 0)

        var_info = _classify_vars(ds)  # varname → (unit, is_3d)
        n_layers = ds.sizes.get(SCHISM_VGRID_DIM, 0)
        layer_indices = (
            _resolve_layers(n_layers, cls.default_layers) if n_layers > 0 else []
        )

        # One shared reader instance per file (flyweight)
        reader = cls(path)

        refs: List[SchismNcDataReference] = []
        for node_id in range(n_nodes):
            station_label = f"node_{node_id}"
            geo_kwargs: dict = {}
            if node_x is not None:
                geo_kwargs["x"] = float(node_x[node_id])
                geo_kwargs["y"] = float(node_y[node_id])

            for varname, (unit, is_3d) in var_info.items():
                if is_3d:
                    for k in layer_indices:
                        name = f"{station_label}:{varname}[k={k}]"
                        refs.append(
                            SchismNcDataReference(
                                source=path,
                                reader=reader,
                                name=name,
                                station=station_label,
                                variable=varname,
                                node_id=node_id,
                                layer_k=int(k),
                                unit=unit,
                                time_extent_start=time_extent_start,
                                time_extent_end=time_extent_end,
                                **geo_kwargs,
                            )
                        )
                else:
                    name = f"{station_label}:{varname}"
                    refs.append(
                        SchismNcDataReference(
                            source=path,
                            reader=reader,
                            name=name,
                            station=station_label,
                            variable=varname,
                            node_id=node_id,
                            layer_k=None,
                            unit=unit,
                            time_extent_start=time_extent_start,
                            time_extent_end=time_extent_end,
                            **geo_kwargs,
                        )
                    )

        logger.debug(
            "scan(%s): %d refs (%d nodes × %d vars%s)",
            pathlib.Path(path).name,
            len(refs),
            n_nodes,
            len(var_info),
            f" × {len(layer_indices)} layers" if layer_indices else "",
        )
        return refs

    @classmethod
    def catalog_crs(cls) -> Optional[str]:
        """CRS is not known at class level; auto-detected per-file in scan().

        Returns ``None``; consumers that need a CRS should call
        :func:`schismviz._nc_utils._autodetect_epsg` on the x/y values in
        the returned refs.
        """
        return None

    def __repr__(self) -> str:
        return f"SchismNcReader(source={self._source!r})"
