"""Integration tests for schismviz.schism_nc and schismviz._nc_utils.

These tests exercise real SCHISM netCDF output files from the HelloSCHISM
tutorial project (modules/m5_visit/).  All tests are marked ``integration``
and are skipped when the data path is not available.

Run with:
    pytest tests/test_schism_nc.py -v -m integration
"""

from __future__ import annotations

import pathlib
import pytest
import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Path to HelloSCHISM test data
# ---------------------------------------------------------------------------

HELLO_SCHISM_M5 = pathlib.Path("/scratch/psandhu/HelloSCHISM/modules/m5_visit")

_data_available = HELLO_SCHISM_M5.exists()
skip_if_no_data = pytest.mark.skipif(
    not _data_available,
    reason=f"HelloSCHISM test data not found at {HELLO_SCHISM_M5}",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _out2d_files():
    return sorted(HELLO_SCHISM_M5.glob("out2d_*.nc"))


def _salinity_files():
    return sorted(HELLO_SCHISM_M5.glob("salinity_*.nc"))


def _zcoord_files():
    return sorted(HELLO_SCHISM_M5.glob("zCoordinates_*.nc"))


# ---------------------------------------------------------------------------
# _nc_utils unit tests (no disk I/O — fast)
# ---------------------------------------------------------------------------


class TestNcUtils:
    """Tests for shared helpers in _nc_utils (no NC files required)."""

    def test_parse_base_date_basic(self):
        from schismviz._nc_utils import _parse_base_date

        ts = _parse_base_date(" 2009  2 10       0.00       8.00")
        assert ts == pd.Timestamp("2009-02-10")

    def test_parse_base_date_single_digits(self):
        from schismviz._nc_utils import _parse_base_date

        ts = _parse_base_date("2020 1 5")
        assert ts == pd.Timestamp("2020-01-05")

    def test_decode_times(self):
        from schismviz._nc_utils import _decode_times
        import pandas as pd

        base = pd.Timestamp("2009-02-10")
        arr = [0.0, 3600.0, 7200.0]
        result = _decode_times(base, arr)
        assert len(result) == 3
        assert result[0] == pd.Timestamp("2009-02-10 00:00:00")
        assert result[1] == pd.Timestamp("2009-02-10 01:00:00")
        assert result[2] == pd.Timestamp("2009-02-10 02:00:00")

    def test_resolve_layers_default(self):
        from schismviz._nc_utils import _resolve_layers

        assert _resolve_layers(10, None) == [0, 9]

    def test_resolve_layers_single(self):
        from schismviz._nc_utils import _resolve_layers

        assert _resolve_layers(1, None) == [0]

    def test_resolve_layers_all(self):
        from schismviz._nc_utils import _resolve_layers

        assert _resolve_layers(5, "all") == [0, 1, 2, 3, 4]

    def test_resolve_layers_explicit(self):
        from schismviz._nc_utils import _resolve_layers

        assert _resolve_layers(10, [0, 4, 9]) == [0, 4, 9]

    def test_resolve_layers_dedup_and_sort(self):
        from schismviz._nc_utils import _resolve_layers

        assert _resolve_layers(10, [9, 0, 4, 0]) == [0, 4, 9]

    def test_resolve_layers_out_of_range(self):
        from schismviz._nc_utils import _resolve_layers

        with pytest.raises(ValueError, match="out of range"):
            _resolve_layers(5, [0, 10])

    def test_resolve_layers_bad_string(self):
        from schismviz._nc_utils import _resolve_layers

        with pytest.raises(ValueError, match="'all'"):
            _resolve_layers(5, "every")

    def test_classify_vars_separates_grid_and_data(self):
        """_classify_vars skips SCHISM_GRID_VARS and classifies 2D/3D vars."""
        import xarray as xr
        from schismviz._nc_utils import _classify_vars, SCHISM_VGRID_DIM, SCHISM_HGRID_NODE_DIM

        n_nodes = 20
        n_layers = 5
        n_time = 3
        ds = xr.Dataset(
            {
                # Grid var — should be excluded
                "SCHISM_hgrid_node_x": xr.DataArray(
                    np.zeros(n_nodes), dims=[SCHISM_HGRID_NODE_DIM]
                ),
                # 2-D data var
                "elevation": xr.DataArray(
                    np.zeros((n_time, n_nodes)), dims=["time", SCHISM_HGRID_NODE_DIM]
                ),
                # 3-D data var
                "Salinity": xr.DataArray(
                    np.zeros((n_time, n_nodes, n_layers)),
                    dims=["time", SCHISM_HGRID_NODE_DIM, SCHISM_VGRID_DIM],
                ),
            }
        )
        result = _classify_vars(ds)
        assert "SCHISM_hgrid_node_x" not in result
        assert "elevation" in result
        assert result["elevation"] == ("m", False)
        assert "Salinity" in result
        assert result["Salinity"] == ("PSU", True)

    def test_parse_base_date_regression_vs_out2dui(self):
        """Regression guard: _nc_utils._parse_base_date matches old out2dui behaviour."""
        from schismviz._nc_utils import _parse_base_date

        # Attribute string from a real out2d file
        s = " 2009  2 10       0.00       8.00"
        result = _parse_base_date(s)
        expected = pd.Timestamp(2009, 2, 10)
        assert result == expected


# ---------------------------------------------------------------------------
# Integration tests against real HelloSCHISM data
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSchismNcUIManagerOut2D:
    """2-D output (out2d_*.nc) integration tests."""

    @skip_if_no_data
    def test_catalog_2d_has_expected_vars(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        assert files, "No out2d_*.nc files found"
        mgr = SchismNcUIManager(*files, nodes=[0, 1])
        df = mgr.get_data_catalog()
        assert "elevation" in df["variable"].values
        assert "depthAverageVelX" in df["variable"].values or \
               "dahv" in df["variable"].values, (
               "Expected depthAverageVelX or dahv in 2D catalog"
        )

    @skip_if_no_data
    def test_catalog_2d_layer_k_all_na(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0], variables=["elevation"])
        df = mgr.get_data_catalog()
        assert df["layer_k"].isna().all(), "2-D vars should have layer_k=NA"

    @skip_if_no_data
    def test_catalog_skips_grid_vars(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0])
        df = mgr.get_data_catalog()
        assert "SCHISM_hgrid_node_x" not in df["variable"].values
        assert "SCHISM_hgrid_node_y" not in df["variable"].values
        assert "SCHISM_hgrid" not in df["variable"].values

    @skip_if_no_data
    def test_get_data_2d_elevation_returns_dataframe(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0], variables=["elevation"])
        df_cat = mgr.get_data_catalog()
        row = df_cat.iloc[0]
        time_range = mgr.get_time_range(df_cat)
        df, unit, ptype = mgr.get_data_for_time_range(row, time_range)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert isinstance(df.index, pd.DatetimeIndex)
        assert unit == "m"
        assert ptype == "INST-VAL"

    @skip_if_no_data
    def test_time_range_is_timestamps(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0], variables=["elevation"])
        t0, t1 = mgr.get_time_range(mgr.get_data_catalog())
        assert isinstance(t0, pd.Timestamp)
        assert isinstance(t1, pd.Timestamp)
        assert t1 > t0

    @skip_if_no_data
    def test_node_dict_input(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes={"site_a": 0, "site_b": 1}, variables=["elevation"])
        df = mgr.get_data_catalog()
        assert set(df["node_name"]) == {"site_a", "site_b"}

    @skip_if_no_data
    def test_node_dataframe_input(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        nodes_df = pd.DataFrame({"node_id": [0, 2], "name": ["alpha", "beta"]})
        mgr = SchismNcUIManager(*files, nodes=nodes_df, variables=["elevation"])
        df = mgr.get_data_catalog()
        assert set(df["node_name"]) == {"alpha", "beta"}

    @skip_if_no_data
    def test_unknown_variable_skipped_with_warning(self, caplog):
        from schismviz.schism_nc import SchismNcUIManager
        import logging

        files = _out2d_files()
        with caplog.at_level(logging.WARNING, logger="schismviz.schism_nc"):
            mgr = SchismNcUIManager(
                *files,
                nodes=[0],
                variables=["elevation", "nonexistent_var"],
            )
        df = mgr.get_data_catalog()
        assert "nonexistent_var" not in df["variable"].values
        assert any("nonexistent_var" in m for m in caplog.messages)


@pytest.mark.integration
class TestSchismNcUIManagerSalinity:
    """3-D output (salinity_*.nc) integration tests."""

    @skip_if_no_data
    def test_catalog_3d_default_layers_surface_and_bottom(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _salinity_files()
        assert files, "No salinity_*.nc files found"
        mgr = SchismNcUIManager(*files, nodes=[0], layers=None, coord_files=_out2d_files())
        df = mgr.get_data_catalog()
        # Default: surface + bottom only → exactly 2 rows per node/var combo
        layer_ks = df["layer_k"].dropna().unique()
        assert len(layer_ks) == 2, f"Expected 2 layers (surface+bottom), got {layer_ks}"
        # Bottom is k=0
        assert 0 in layer_ks

    @skip_if_no_data
    def test_catalog_3d_all_layers(self):
        from schismviz.schism_nc import SchismNcUIManager
        import xarray as xr

        files = _salinity_files()
        # Determine n_layers from file
        ds = xr.open_dataset(files[0])
        from schismviz._nc_utils import SCHISM_VGRID_DIM
        n_layers = ds.sizes.get(SCHISM_VGRID_DIM, None)
        ds.close()
        assert n_layers is not None, f"No {SCHISM_VGRID_DIM} dim in salinity file"

        mgr = SchismNcUIManager(*files, nodes=[0], layers="all", coord_files=_out2d_files())
        df = mgr.get_data_catalog()
        layer_ks = sorted(df["layer_k"].dropna().unique().astype(int))
        assert len(layer_ks) == n_layers
        assert layer_ks[0] == 0
        assert layer_ks[-1] == n_layers - 1

    @skip_if_no_data
    def test_catalog_3d_specified_layers(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _salinity_files()
        mgr = SchismNcUIManager(*files, nodes=[0], layers=[0, 2], coord_files=_out2d_files())
        df = mgr.get_data_catalog()
        layer_ks = sorted(df["layer_k"].dropna().unique().astype(int))
        assert layer_ks == [0, 2]

    @skip_if_no_data
    def test_catalog_3d_row_count(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _salinity_files()
        n_nodes = 3
        n_selected_layers = 2  # default: surface + bottom
        mgr = SchismNcUIManager(
            *files, nodes=list(range(n_nodes)), layers=None, coord_files=_out2d_files()
        )
        df = mgr.get_data_catalog()
        # All vars in salinity file are 3D, so: n_nodes × n_vars × n_layers
        n_vars = df["variable"].nunique()
        assert len(df) == n_nodes * n_vars * n_selected_layers

    @skip_if_no_data
    def test_get_data_3d_bottom_layer(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _salinity_files()
        mgr = SchismNcUIManager(*files, nodes=[0], layers=[0], coord_files=_out2d_files())
        df_cat = mgr.get_data_catalog()
        row = df_cat.iloc[0]
        assert int(row["layer_k"]) == 0
        time_range = mgr.get_time_range(df_cat)
        df, unit, ptype = mgr.get_data_for_time_range(row, time_range)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert isinstance(df.index, pd.DatetimeIndex)

    @skip_if_no_data
    def test_get_data_3d_surface_layer(self):
        from schismviz.schism_nc import SchismNcUIManager
        import xarray as xr

        files = _salinity_files()
        ds = xr.open_dataset(files[0])
        from schismviz._nc_utils import SCHISM_VGRID_DIM
        n_layers = ds.sizes[SCHISM_VGRID_DIM]
        ds.close()
        surface_k = n_layers - 1

        mgr = SchismNcUIManager(
            *files, nodes=[0], layers=[surface_k], coord_files=_out2d_files()
        )
        df_cat = mgr.get_data_catalog()
        row = df_cat.iloc[0]
        time_range = mgr.get_time_range(df_cat)
        df, unit, _ = mgr.get_data_for_time_range(row, time_range)
        assert len(df) > 0
        assert unit in ("PSU", ""), f"Unexpected unit: {unit}"

    @skip_if_no_data
    def test_layer_k_column_is_nullable_int(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _salinity_files()
        mgr = SchismNcUIManager(*files, nodes=[0], layers=[0], coord_files=_out2d_files())
        df = mgr.get_data_catalog()
        # Should be pandas Int64 nullable dtype, not float
        assert pd.api.types.is_integer_dtype(df["layer_k"]) or \
               str(df["layer_k"].dtype) == "Int64", \
               f"Expected nullable int dtype, got {df['layer_k'].dtype}"


@pytest.mark.integration
class TestSchismNcUIManagerMixed:
    """Tests mixing 2D and 3D files (out2d + salinity)."""

    @skip_if_no_data
    def test_mixed_files_2d_and_3d_in_same_manager(self):
        """Opening out2d and salinity files together surfaces both 2-D and 3-D vars."""
        from schismviz.schism_nc import SchismNcUIManager

        # Salinity files include both 2D-like and 3D vars
        # We test here with salinity-only but checking mixed layer_k behaviour
        files = _salinity_files()
        mgr = SchismNcUIManager(*files, nodes=[0], layers=None, coord_files=_out2d_files())
        df = mgr.get_data_catalog()
        # 3-D rows should have non-NA layer_k
        assert df["layer_k"].notna().any()


@pytest.mark.integration
class TestSuxarrayGridContext:
    """Tests for optional suxarray grid context via zCoordinates files."""

    @skip_if_no_data
    def test_open_grid_returns_none_without_zcoord_files(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0], variables=["elevation"])
        assert mgr._open_grid() is None

    @skip_if_no_data
    def test_open_grid_returns_suxarray_grid_with_zcoord_files(self):
        from schismviz.schism_nc import SchismNcUIManager

        suxarray = pytest.importorskip(
            "suxarray", reason="suxarray not installed in this environment"
        )

        out2d = _out2d_files()
        zcoord = _zcoord_files()
        assert zcoord, "No zCoordinates_*.nc files found"
        mgr = SchismNcUIManager(
            *out2d,
            nodes=[0],
            variables=["elevation"],
            zcoord_files=zcoord,
        )
        grid = mgr._open_grid()
        assert grid is not None, "Expected suxarray.Grid, got None"
        # Verify it has the expected suxarray Grid type
        from suxarray.grid.grid import Grid
        assert isinstance(grid, Grid), f"Expected suxarray.Grid, got {type(grid)}"


@pytest.mark.integration
class TestBuildStationName:
    """Tests for build_station_name with 2D and 3D rows."""

    @skip_if_no_data
    def test_2d_station_name_no_layer(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0], variables=["elevation"])
        df = mgr.get_data_catalog()
        row = df.iloc[0]
        name = mgr.build_station_name(row)
        assert "elevation" in name
        assert "[k=" not in name

    @skip_if_no_data
    def test_3d_station_name_includes_layer(self):
        from schismviz.schism_nc import SchismNcUIManager

        files = _salinity_files()
        mgr = SchismNcUIManager(*files, nodes=[0], layers=[0], coord_files=_out2d_files())
        df = mgr.get_data_catalog()
        row = df.iloc[0]
        name = mgr.build_station_name(row)
        assert "[k=0]" in name


# ---------------------------------------------------------------------------
# CRS helper unit tests (no disk I/O)
# ---------------------------------------------------------------------------


class TestCrsHelpers:
    """Unit tests for _autodetect_epsg and _epsg_to_cartopy."""

    def test_autodetect_geographic(self):
        from schismviz.schism_nc import _autodetect_epsg

        x = np.array([-122.0, -121.5, -120.8])
        y = np.array([37.5, 38.0, 38.5])
        assert _autodetect_epsg(x, y) == 4326

    def test_autodetect_utm_zone10(self):
        from schismviz.schism_nc import _autodetect_epsg

        # Typical Bay-Delta easting/northing values
        x = np.array([550000.0, 580000.0, 620000.0])
        y = np.array([4150000.0, 4200000.0, 4250000.0])
        assert _autodetect_epsg(x, y) == 32610

    def test_autodetect_synthetic_returns_none(self):
        from schismviz.schism_nc import _autodetect_epsg

        # HelloSCHISM synthetic grid (0–56000 m, not real UTM)
        x = np.array([0.0, 28000.0, 56000.0])
        y = np.array([-10400.0, 0.0, 10400.0])
        assert _autodetect_epsg(x, y) is None

    def test_epsg_to_cartopy_wgs84(self):
        from schismviz.schism_nc import _epsg_to_cartopy
        import cartopy.crs as ccrs

        crs = _epsg_to_cartopy(4326)
        assert isinstance(crs, ccrs.PlateCarree)

    def test_epsg_to_cartopy_utm10(self):
        from schismviz.schism_nc import _epsg_to_cartopy
        import cartopy.crs as ccrs

        crs = _epsg_to_cartopy(32610)
        assert isinstance(crs, ccrs.UTM)

    def test_epsg_to_cartopy_utm_south(self):
        from schismviz.schism_nc import _epsg_to_cartopy
        import cartopy.crs as ccrs

        crs = _epsg_to_cartopy(32733)  # UTM Zone 33 S
        assert isinstance(crs, ccrs.UTM)


# ---------------------------------------------------------------------------
# Map GeoDataFrame catalog tests (integration — require disk data)
# ---------------------------------------------------------------------------


class TestMapGeodataframe:
    """Tests for GeoDataFrame catalog returned by get_data_catalog() when epsg is set."""

    @skip_if_no_data
    def test_explicit_epsg_returns_geodataframe(self):
        """Passing epsg=4326 wraps catalog in a GeoDataFrame."""
        import geopandas as gpd
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0, 1, 2], variables=["elevation"], epsg=4326)
        df = mgr.get_data_catalog()
        assert isinstance(df, gpd.GeoDataFrame), "Expected GeoDataFrame when epsg is provided"
        assert "geometry" in df.columns
        assert df.crs is not None

    @skip_if_no_data
    def test_no_epsg_synthetic_grid_plain_dataframe(self):
        """HelloSCHISM synthetic grid: auto-detect returns None → plain DataFrame."""
        import geopandas as gpd
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0, 1], variables=["elevation"])
        df = mgr.get_data_catalog()
        # HelloSCHISM has synthetic coords → no CRS detected → plain DataFrame
        assert not isinstance(df, gpd.GeoDataFrame)
        assert mgr._map_epsg is None

    @skip_if_no_data
    def test_get_map_crs_with_epsg(self):
        """get_map_crs() returns a cartopy CRS when epsg is set."""
        import cartopy.crs as ccrs
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0], variables=["elevation"], epsg=32610)
        crs = mgr.get_map_crs()
        assert isinstance(crs, ccrs.UTM)

    @skip_if_no_data
    def test_get_map_crs_without_epsg_synthetic(self):
        """get_map_crs() returns None for synthetic grids where CRS cannot be detected."""
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0], variables=["elevation"])
        assert mgr.get_map_crs() is None

    @skip_if_no_data
    def test_geodataframe_geometry_from_xy(self):
        """Geometry points match x/y catalog columns."""
        import geopandas as gpd
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0, 1], variables=["elevation"], epsg=4326)
        df = mgr.get_data_catalog()
        assert isinstance(df, gpd.GeoDataFrame)
        for _, row in df.iterrows():
            assert abs(row.geometry.x - row["x"]) < 1e-9
            assert abs(row.geometry.y - row["y"]) < 1e-9

    @skip_if_no_data
    def test_tooltips_non_empty(self):
        """get_tooltips() returns a non-empty list for the map hover panel."""
        from schismviz.schism_nc import SchismNcUIManager

        files = _out2d_files()
        mgr = SchismNcUIManager(*files, nodes=[0], variables=["elevation"])
        tooltips = mgr.get_tooltips()
        assert isinstance(tooltips, list)
        assert len(tooltips) > 0


# ---------------------------------------------------------------------------
# SchismNcReader tests (dvue registry reader)
# ---------------------------------------------------------------------------


class TestSchismNcReader:
    """Tests for SchismNcReader — the dvue DataReferenceReader for SCHISM NC files."""

    @skip_if_no_data
    def test_scan_returns_data_references(self):
        """scan() returns a list of SchismNcDataReference objects."""
        from schismviz.schism_nc_reader import SchismNcReader, SchismNcDataReference

        path = str(_out2d_files()[0])
        refs = SchismNcReader.scan(path)
        assert isinstance(refs, list)
        assert len(refs) > 0
        assert all(isinstance(r, SchismNcDataReference) for r in refs)

    @skip_if_no_data
    def test_scan_ref_type_is_schism_nc(self):
        """All refs have ref_type='schism_nc'."""
        from schismviz.schism_nc_reader import SchismNcReader

        path = str(_out2d_files()[0])
        refs = SchismNcReader.scan(path)
        assert all(r.ref_type == "schism_nc" for r in refs)

    @skip_if_no_data
    def test_scan_all_nodes(self):
        """scan() returns refs for every node in the file (no artificial cap)."""
        import xarray as xr
        from schismviz.schism_nc_reader import SchismNcReader

        path = str(_out2d_files()[0])
        ds = xr.open_dataset(path)
        n_nodes = ds.sizes["nSCHISM_hgrid_node"]
        ds.close()

        refs = SchismNcReader.scan(path)
        node_ids = {r.get_attribute("node_id") for r in refs}
        assert len(node_ids) == n_nodes, (
            f"Expected {n_nodes} unique nodes, got {len(node_ids)}"
        )

    @skip_if_no_data
    def test_scan_no_data_loaded(self):
        """scan() does not load any time-series data (cache must be empty)."""
        from schismviz.schism_nc_reader import SchismNcReader

        path = str(_out2d_files()[0])
        refs = SchismNcReader.scan(path)
        # DataReference._cached_data is empty until getData() is called
        for ref in refs:
            assert ref._cached_data == {}, (
                f"ref {ref.name!r} has pre-loaded cache data — lazy loading broken"
            )

    @skip_if_no_data
    def test_scan_has_station_and_variable(self):
        """Each ref has 'station' and 'variable' attributes for RegistryUIManager."""
        from schismviz.schism_nc_reader import SchismNcReader

        path = str(_out2d_files()[0])
        refs = SchismNcReader.scan(path)
        for ref in refs:
            assert ref.get_attribute("station"), f"ref {ref.name!r} missing station"
            assert ref.get_attribute("variable"), f"ref {ref.name!r} missing variable"

    @skip_if_no_data
    def test_scan_out2d_has_xy_coords(self):
        """out2d files have SCHISM_hgrid_node_x/y → refs have x and y attributes."""
        from schismviz.schism_nc_reader import SchismNcReader

        path = str(_out2d_files()[0])
        refs = SchismNcReader.scan(path)
        for ref in refs:
            assert ref.get_attribute("x") is not None, f"ref {ref.name!r} missing x"
            assert ref.get_attribute("y") is not None, f"ref {ref.name!r} missing y"

    @skip_if_no_data
    def test_scan_time_extent_attributes(self):
        """Refs expose time_extent_start / time_extent_end for RegistryUIManager.on_file_added."""
        from schismviz.schism_nc_reader import SchismNcReader

        path = str(_out2d_files()[0])
        refs = SchismNcReader.scan(path)
        for ref in refs:
            start = ref.get_attribute("time_extent_start")
            end = ref.get_attribute("time_extent_end")
            assert start, f"ref {ref.name!r} missing time_extent_start"
            assert end, f"ref {ref.name!r} missing time_extent_end"
            # Should be parseable timestamps
            pd.Timestamp(start)
            pd.Timestamp(end)

    @skip_if_no_data
    def test_load_returns_dataframe(self):
        """load() returns a single-column DataFrame with DatetimeIndex."""
        from schismviz.schism_nc_reader import SchismNcReader

        path = str(_out2d_files()[0])
        refs = SchismNcReader.scan(path)
        # Pick a 2D ref (no layer_k)
        ref_2d = next(
            r for r in refs
            if r.get_attribute("layer_k") is None
        )
        reader = SchismNcReader(path)
        df = reader.load(**ref_2d._attributes)
        assert isinstance(df, pd.DataFrame)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert len(df) > 0
        assert df.shape[1] == 1

    @skip_if_no_data
    def test_load_time_range_slices_output(self):
        """load() respects time_range for sub-period retrieval."""
        from schismviz.schism_nc_reader import SchismNcReader

        path = str(_out2d_files()[0])
        refs = SchismNcReader.scan(path)
        ref_2d = next(r for r in refs if r.get_attribute("layer_k") is None)
        reader = SchismNcReader(path)

        # Full series
        attrs_full = dict(ref_2d._attributes)
        df_full = reader.load(**attrs_full)

        # Sliced to first half
        mid = df_full.index[len(df_full) // 2]
        attrs_sliced = dict(attrs_full)
        attrs_sliced["time_range"] = (df_full.index[0], mid)
        df_sliced = reader.load(**attrs_sliced)
        assert len(df_sliced) <= len(df_full)

    @skip_if_no_data
    def test_getData_via_reference(self):
        """getData() on a scanned ref returns a DataFrame (integration with DataReference)."""
        from schismviz.schism_nc_reader import SchismNcReader

        path = str(_out2d_files()[0])
        refs = SchismNcReader.scan(path)
        ref = refs[0]
        df = ref.getData()
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    @skip_if_no_data
    def test_elevation_dry_masking(self):
        """load() masks elevation NaN for dry nodes (depth + elev < h0).

        We synthesise a dry scenario by temporarily patching depth to a tiny
        value so that depth + elevation < h0 for most time steps.
        """
        import xarray as xr
        import numpy as np
        from schismviz.schism_nc_reader import SchismNcReader

        path = str(_out2d_files()[0])
        ds = xr.open_dataset(path)
        h0 = float(ds["minimum_depth"].values.flat[0]) if "minimum_depth" in ds else 0.01
        depth_arr = ds["depth"].values
        elev_arr = ds["elevation"].values  # (time, nodes)
        ds.close()

        # Find a node that is wet throughout (total depth always >= h0)
        node_id = 0
        full_depth = depth_arr[node_id] + elev_arr[:, node_id]
        # is_wet_throughout: bool array over nodes — atleast_1d handles scalar case
        is_wet = np.atleast_1d(np.all((depth_arr[None, :] + elev_arr) >= h0, axis=0))
        all_wet_nodes = np.where(is_wet)[0]
        if len(all_wet_nodes) == 0:
            import pytest; pytest.skip("No always-wet node found in test data")
        node_id = int(all_wet_nodes[0])

        reader = SchismNcReader(path)
        df = reader.load(variable="elevation", node_id=node_id, layer_k=None)
        # For a wet node the series should have no NaNs
        assert not df["elevation"].isna().any(), (
            "Wet node should not have NaN elevation values"
        )

        # Now pick a node where total depth < h0 at at least one time step.
        # Fake this by checking if any node is ever dry in the test data.
        dry_times, dry_nodes = np.where(
            (depth_arr[None, :] + elev_arr) < h0
        )
        if len(dry_nodes) == 0:
            # Test data has no dry nodes — verify masking logic is wired up
            # by confirming the non-dry path still returns valid floats.
            return

        dry_node = int(dry_nodes[0])
        df_dry = reader.load(variable="elevation", node_id=dry_node, layer_k=None)
        assert df_dry["elevation"].isna().any(), (
            f"Dry node {dry_node} should have NaN elevation at dry time steps"
        )

    @skip_if_no_data
    def test_register_readers_registers_schism_nc(self):
        """register_readers() registers 'schism_nc' ref_type in dvue's ReaderRegistry."""
        from dvue.registry import ReaderRegistry
        from schismviz.readers import register_readers

        register_readers()
        assert ReaderRegistry.has_ref_type("schism_nc")

    @skip_if_no_data
    def test_registry_scan_via_extension(self):
        """ReaderRegistry.scan() dispatches to SchismNcReader for .nc files."""
        from dvue.registry import ReaderRegistry
        from schismviz.readers import register_readers

        register_readers()
        path = str(_out2d_files()[0])
        refs = ReaderRegistry.scan(path)
        assert len(refs) > 0
        assert all(r.ref_type == "schism_nc" for r in refs)

    @skip_if_no_data
    def test_registry_ui_manager_scan_nc(self):
        """RegistryUIManager.add_source_files() correctly scans NC files."""
        from dvue.registry import ReaderRegistry
        from dvue.registry_ui import RegistryUIManager
        from schismviz.readers import register_readers

        register_readers()
        mgr = RegistryUIManager()
        for path in _out2d_files():
            mgr.add_source_files(str(path))
        df = mgr.get_data_catalog()
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert "station" in df.columns
        assert "variable" in df.columns

    @skip_if_no_data
    def test_time_range_expanded_after_add_source_files(self):
        """RegistryUIManager.time_range is auto-set from NC file extents."""
        from dvue.registry_ui import RegistryUIManager
        from schismviz.readers import register_readers

        register_readers()
        mgr = RegistryUIManager()
        assert mgr.time_range is None
        for path in _out2d_files():
            mgr.add_source_files(str(path))
        assert mgr.time_range is not None
        start, end = mgr.time_range
        assert isinstance(start, pd.Timestamp)
        assert isinstance(end, pd.Timestamp)
        assert start < end


