"""Shared utilities for reading SCHISM netCDF output files.

These helpers are used by both :mod:`schismviz.out2dui` and
:mod:`schismviz.schism_nc` to avoid duplication.
"""

from __future__ import annotations

from typing import Union

import pandas as pd

# ---------------------------------------------------------------------------
# Known SCHISM variable → unit mapping
# ---------------------------------------------------------------------------

#: Maps SCHISM netCDF variable name to its physical unit string.
SCHISM_VAR_UNITS: dict[str, str] = {
    # 2-D / out2d variables
    "elevation": "m",
    "depthAverageVelX": "m/s",
    "depthAverageVelY": "m/s",
    "dahv": "m/s",            # depth-averaged horizontal velocity (vector)
    "dahv_x": "m/s",
    "dahv_y": "m/s",
    "dryFlagNode": "",
    "dryFlagElement": "",
    "dryFlagSide": "",
    "bottom_index_node": "",
    # 3-D tracer variables
    "salinity": "PSU",
    "Salinity": "PSU",
    "salt": "PSU",
    "temperature": "deg_C",
    "Temperature": "deg_C",
    "temp": "deg_C",
    # 3-D velocity
    "hvel": "m/s",
    "hvel_x": "m/s",
    "hvel_y": "m/s",
    "u": "m/s",
    "v": "m/s",
    "w": "m/s",
    "vertical_velocity": "m/s",
    # z-coordinates
    "zcor": "m",
    "zCoordinates": "m",
    "z_coord": "m",
}

# ---------------------------------------------------------------------------
# SCHISM grid / topology variable names to exclude from data catalogs
# ---------------------------------------------------------------------------

#: Variable names that represent mesh topology or static coordinate fields
#: rather than time-varying physical data.  These are skipped when building
#: a data catalog from an xarray Dataset.
SCHISM_GRID_VARS: frozenset[str] = frozenset(
    [
        "SCHISM_hgrid",
        "SCHISM_hgrid_node_x",
        "SCHISM_hgrid_node_y",
        "SCHISM_hgrid_face_x",
        "SCHISM_hgrid_face_y",
        "SCHISM_hgrid_edge_x",
        "SCHISM_hgrid_edge_y",
        "SCHISM_hgrid_face_nodes",
        "SCHISM_hgrid_edge_nodes",
        "bottom_index_node",
        "depth",
        "dryFlagNode",
        "dryFlagElement",
        "dryFlagSide",
        "node_bottom_index",
    ]
)

# Dimension name used by SCHISM for 3-D vertical layers
SCHISM_VGRID_DIM: str = "nSCHISM_vgrid_layers"

# Dimension name used by SCHISM for horizontal nodes
SCHISM_HGRID_NODE_DIM: str = "nSCHISM_hgrid_node"


# ---------------------------------------------------------------------------
# Time decoding
# ---------------------------------------------------------------------------


def _parse_base_date(base_date_str: str) -> pd.Timestamp:
    """Parse the SCHISM *base_date* attribute string to a :class:`~pandas.Timestamp`.

    The attribute is formatted as ``' 2009  2 10       0.00       8.00'``.
    Only the first three integer fields (year, month, day) are used.

    Parameters
    ----------
    base_date_str:
        Raw string value of the ``base_date`` attribute on the ``time``
        variable in a SCHISM netCDF output file.

    Returns
    -------
    pandas.Timestamp
        Midnight on the parsed calendar date.
    """
    parts = base_date_str.split()
    return pd.Timestamp(int(parts[0]), int(parts[1]), int(parts[2]))


#: Any time value larger than this is treated as a NetCDF fill-value sentinel
#: and replaced with NaN.  The canonical NetCDF4 default fill value for float64
#: is 9.969209968386869e+36; using 1e30 as the threshold is safe because no
#: real SCHISM simulation runs for >3×10²² years.
_NC_TIME_FILL_THRESHOLD: float = 1e30


def _decode_times(base_date: pd.Timestamp, time_seconds) -> pd.DatetimeIndex:
    """Convert a seconds-since-*base_date* array to a :class:`~pandas.DatetimeIndex`.

    NetCDF output files that were pre-allocated but not fully written (e.g. an
    incomplete run) contain the default ``_FillValue`` sentinel
    (``9.969209968386869e+36``) in unwritten time slots.  xarray does not always
    mask these values because the attribute may not be explicitly set in the
    file metadata.  Passing the sentinel to :func:`pandas.to_timedelta` causes
    an ``OverflowError`` (too large for int64 nanoseconds) which in older
    pandas versions silently wraps to a large negative value, producing
    timestamps far in the past.

    This function replaces any value larger than :data:`_NC_TIME_FILL_THRESHOLD`
    with ``NaN`` before conversion, which produces ``NaT`` entries for those
    slots.  Callers should drop ``NaT`` rows from the resulting index.

    Parameters
    ----------
    base_date:
        Reference date returned by :func:`_parse_base_date`.
    time_seconds:
        Array-like of float seconds since *base_date* (the raw ``time``
        variable values from SCHISM netCDF output).

    Returns
    -------
    pandas.DatetimeIndex
    """
    import numpy as np

    arr = np.asarray(time_seconds, dtype=np.float64)
    # Mask fill-value sentinels so they become NaT rather than overflowing.
    arr = np.where(arr > _NC_TIME_FILL_THRESHOLD, np.nan, arr)
    # Build per-element timedeltas, skipping NaN to avoid overflow.
    nat = np.timedelta64("NaT")
    td64 = np.where(
        np.isnan(arr),
        nat,
        (arr * 1e9).astype("timedelta64[ns]"),
    )
    return pd.DatetimeIndex(base_date.to_datetime64() + td64)


# ---------------------------------------------------------------------------
# Variable classification
# ---------------------------------------------------------------------------


def _classify_vars(ds) -> dict[str, tuple[str, bool]]:
    """Classify data variables in *ds* into (unit, is_3d) pairs.

    Grid topology variables listed in :data:`SCHISM_GRID_VARS` are excluded.
    A variable is considered 3-D when its dimensions include
    :data:`SCHISM_VGRID_DIM`.

    Parameters
    ----------
    ds:
        :class:`xarray.Dataset` opened from one or more SCHISM combined NC
        output files.

    Returns
    -------
    dict
        Mapping ``varname → (unit_str, is_3d)`` for every data variable that
        should appear in a user-facing catalog.
    """
    result: dict[str, tuple[str, bool]] = {}
    for varname in ds.data_vars:
        if varname in SCHISM_GRID_VARS:
            continue
        var = ds[varname]
        # Only include time-varying, node-based variables.  Variables with
        # neither 'time' nor 'nSCHISM_hgrid_node' in their dimensions are
        # static fields, scalar metadata, or face/edge fields — skip them.
        if "time" not in var.dims or SCHISM_HGRID_NODE_DIM not in var.dims:
            continue
        is_3d = SCHISM_VGRID_DIM in var.dims
        unit = SCHISM_VAR_UNITS.get(varname, "")
        result[varname] = (unit, is_3d)
    return result


# ---------------------------------------------------------------------------
# Layer index resolution
# ---------------------------------------------------------------------------


def _resolve_layers(
    n_layers: int,
    layers_arg: Union[None, str, list[int]],
) -> list[int]:
    """Resolve the *layers* argument to a concrete list of layer indices.

    Parameters
    ----------
    n_layers:
        Total number of vertical layers in the dataset
        (``ds.dims[SCHISM_VGRID_DIM]``).
    layers_arg:
        Controls which layer indices are included:

        * ``None`` — surface and bottom layers only:
          ``[0, n_layers - 1]`` (when ``n_layers >= 2``; ``[0]`` otherwise).
        * ``"all"`` — every layer: ``list(range(n_layers))``.
        * A list/sequence of ``int`` — the specified indices (validated to be
          in ``[0, n_layers)``) are returned as-is.

    Returns
    -------
    list of int
        Sorted, deduplicated list of valid layer indices.

    Raises
    ------
    ValueError
        If any requested index is out of range or *layers_arg* is not a
        recognised value.
    """
    if layers_arg is None:
        if n_layers <= 1:
            return list(range(n_layers))
        return [0, n_layers - 1]
    if isinstance(layers_arg, str):
        if layers_arg.lower() == "all":
            return list(range(n_layers))
        raise ValueError(
            f"layers_arg string must be 'all', got {layers_arg!r}"
        )
    # Treat as an iterable of ints
    indices = sorted(set(int(k) for k in layers_arg))
    bad = [k for k in indices if k < 0 or k >= n_layers]
    if bad:
        raise ValueError(
            f"Layer indices {bad} are out of range for a dataset with "
            f"{n_layers} layers (valid: 0..{n_layers - 1})."
        )
    return indices
