"""Unit tests for SchismCalibPlotUIManager.

The manager's __init__ loads a YAML config file and creates SchismStudy
objects; we bypass that by building the manager state directly or by
supplying a minimal in-memory config via a temporary file.
"""
import pathlib
import tempfile
import textwrap
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import pytest

from dvue.catalog import DataCatalog, DataReference
from schismviz.schismcalibplotui import SchismCalibPlotUIManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_station_catalog():
    rows = [
        {"id": "STA_01", "name": "Station 1", "variable": "elev", "unit": "m"},
        {"id": "STA_01", "name": "Station 1", "variable": "salt", "unit": "PSU"},
        {"id": "STA_02", "name": "Station 2", "variable": "flow", "unit": "cms"},
    ]
    df = pd.DataFrame(rows)
    return gpd.GeoDataFrame(
        df,
        geometry=[Point(622_000, 4_200_000)] * 3,
        crs="EPSG:32610",
    )


def _make_minimal_manager():
    """Build a SchismCalibPlotUIManager without touching the file system.

    We patch all heavy collaborators so only the logic under test runs.
    """
    mgr = object.__new__(SchismCalibPlotUIManager)

    # Required instance state
    mock_study = MagicMock()
    mock_study.get_catalog.return_value = _make_station_catalog()
    mgr.studies = {"Run1": mock_study}
    mgr.variable_filter = None
    mgr.selected_stations = set()
    mgr.disclaimer_text = None

    mock_datastore = MagicMock()
    mock_datastore.get_catalog.return_value = pd.DataFrame(
        columns=["station_id", "subloc", "param", "unit"]
    )
    mgr.datastore = mock_datastore
    mgr.dcat = mock_datastore.get_catalog.return_value
    mgr.dcat["full_id"] = ""

    # Config stubs needed for other methods
    mgr.config = {}
    mgr.labels = ["Observed", "Run1"]
    mgr.reftime = pd.Timestamp("2020-01-01")
    mgr.window_inst = (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-04-01"))
    mgr.window_avg = (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-04-01"))

    # Build the dvue catalog using the real method
    mgr._dvue_catalog = mgr._build_dvue_catalog()
    return mgr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager():
    return _make_minimal_manager()


# ---------------------------------------------------------------------------
# View-layer methods
# ---------------------------------------------------------------------------


def test_table_column_width_map(manager):
    col_map = manager.get_table_column_width_map()
    assert isinstance(col_map, dict)
    for col in ("id", "name", "variable", "unit"):
        assert col in col_map


def test_table_filters(manager):
    filters = manager.get_table_filters()
    assert isinstance(filters, dict)
    for col in manager.get_table_column_width_map():
        assert col in filters


def test_get_name_to_marker_returns_iterable(manager):
    """B4 fix: get_name_to_marker() must not raise NotImplementedError."""
    result = manager.get_name_to_marker()
    # Must be a non-empty list or a non-empty dict
    assert result is not None
    assert len(result) > 0


def test_get_name_to_marker_contains_circle(manager):
    """At minimum 'circle' should be a supported marker."""
    result = manager.get_name_to_marker()
    if isinstance(result, list):
        assert "circle" in result
    elif isinstance(result, dict):
        all_markers = list(result.values())
        assert any("circle" in str(v) for v in all_markers)


def test_tooltips(manager):
    tooltips = manager.get_tooltips()
    assert isinstance(tooltips, list)
    keys = [t[0] for t in tooltips]
    for col in ("id", "name", "variable"):
        assert col in keys


def test_map_color_columns(manager):
    cols = manager.get_map_color_columns()
    assert isinstance(cols, list)
    assert len(cols) > 0


def test_map_marker_columns(manager):
    cols = manager.get_map_marker_columns()
    assert isinstance(cols, list)
    assert len(cols) > 0


# ---------------------------------------------------------------------------
# Data-layer methods
# ---------------------------------------------------------------------------


def test_get_data_catalog_columns(manager):
    dfcat = manager.get_data_catalog()
    for col in ("id", "name", "variable", "unit"):
        assert col in dfcat.columns


def test_get_data_catalog_filters_valid_variables(manager):
    dfcat = manager.get_data_catalog()
    from schismviz.schismcalibplotui import VALID_VARIABLES
    assert dfcat["variable"].isin(VALID_VARIABLES).all()


def test_get_data_catalog_no_duplicates(manager):
    dfcat = manager.get_data_catalog()
    assert not dfcat.duplicated(subset=["id", "variable"]).any()


def test_get_data_catalog_variable_filter():
    mgr = _make_minimal_manager()
    mgr.variable_filter = "elev"
    dfcat = mgr.get_data_catalog()
    assert (dfcat["variable"] == "elev").all()


def test_get_data_catalog_station_filter():
    mgr = _make_minimal_manager()
    mgr.selected_stations = {"STA_01"}
    dfcat = mgr.get_data_catalog()
    assert (dfcat["id"] == "STA_01").all()


def test_data_catalog_property(manager):
    cat = manager.data_catalog
    assert isinstance(cat, DataCatalog)


def test_catalog_key_format(manager):
    cat = manager.data_catalog
    names = cat.list_names()
    assert "STA_01_elev" in names
    assert "STA_01_salt" in names
    assert "STA_02_flow" in names


def test_get_data_reference_via_property(manager):
    """DataReference can be retrieved via data_catalog."""
    cat = manager.data_catalog
    ref = cat.get("STA_01_elev")
    assert isinstance(ref, DataReference)


def test_build_station_name_not_required():
    """SchismCalibPlotUIManager does not need build_station_name for its workflow."""
    # The calib manager uses create_panel/plot_metrics rather than build_station_name.
    # Verify the attribute exists (may raise NotImplementedError from base class) but
    # we don't require it to be implemented.
    mgr = _make_minimal_manager()
    assert hasattr(mgr, "build_station_name")


# ---------------------------------------------------------------------------
# get_datastore_param_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variable,expected", [
    ("flow", "flow"),
    ("elev", "elev"),
    ("salt", "ec"),
    ("temp", "temp"),
    ("ssc", "ssc"),
])
def test_get_datastore_param_name(manager, variable, expected):
    result = manager.get_datastore_param_name(variable)
    assert result == expected


# ---------------------------------------------------------------------------
# Verify get_map_color_category has been removed (B5 fix)
# ---------------------------------------------------------------------------


def test_get_map_color_category_removed():
    """B5: get_map_color_category() should no longer exist on the manager."""
    mgr = _make_minimal_manager()
    assert not hasattr(mgr, "get_map_color_category"), (
        "get_map_color_category() is dead code and should have been removed (B5)"
    )
