"""Unit tests for SchismOutputUIDataManager and SchismDataReferenceReader.

All disk I/O is mocked so the tests run without real SCHISM output files.
"""
import pathlib
from unittest.mock import MagicMock, patch
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point
import holoviews as hv

hv.extension("bokeh")
import pytest

from dvue.catalog import DataCatalog, DataReference
from dvue.math_reference import MathDataReference
from schismviz.schismui import (
    SchismDataReferenceReader,
    SchismOutputUIDataManager,
    SchismTimeSeriesPlotAction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_study_catalog(source_label="study1", output_dir="/fake/output1"):
    """Return a tiny GeoDataFrame mimicking SchismStudy.get_catalog()."""
    rows = [
        {
            "id": "DWR_A1",
            "name": "Station A",
            "variable": "elev",
            "unit": "m",
            "filename": f"{output_dir}/staout_1",
            "source": source_label,
        },
        {
            "id": "DWR_B2",
            "name": "Station B",
            "variable": "salt",
            "unit": "PSU",
            "filename": f"{output_dir}/staout_5",
            "source": source_label,
        },
        {
            "id": "DWR_B2",
            "name": "Station B",
            "variable": "elev",
            "unit": "m",
            "filename": f"{output_dir}/staout_1",
            "source": source_label,
        },
    ]
    df = pd.DataFrame(rows)
    gdf = gpd.GeoDataFrame(
        df,
        geometry=[Point(622_000, 4_200_000), Point(623_000, 4_201_000), Point(623_000, 4_201_000)],
        crs="EPSG:32610",
    )
    return gdf


def _make_time_series():
    """Return a tiny time-indexed DataFrame."""
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    return pd.DataFrame({"value": np.arange(5, dtype=float)}, index=idx)


def _make_mock_study(source_label="study1", output_dir="/fake/output1"):
    study = MagicMock()
    study.study_name = source_label
    study.output_dir = pathlib.Path(output_dir)
    study.reftime = pd.Timestamp("2020-01-01")
    study.endtime = pd.Timestamp("2020-04-01")
    study.get_catalog.return_value = _make_study_catalog(source_label, output_dir)
    study.get_data.return_value = _make_time_series()
    return study


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_study():
    return _make_mock_study("study1", "/fake/output1")


@pytest.fixture
def minimal_manager(minimal_study):
    """SchismOutputUIDataManager built from one mock study, no datastore."""
    with patch("schismviz.schismui.SchismDataReferenceReader") as MockReader:
        MockReader.return_value = MagicMock(spec=SchismDataReferenceReader)
        mgr = SchismOutputUIDataManager(minimal_study, datastore=None)
    return mgr


# ---------------------------------------------------------------------------
# SchismOutputUIDataManager – metadata methods
# ---------------------------------------------------------------------------


def test_table_column_width_map(minimal_manager):
    col_map = minimal_manager.get_table_column_width_map()
    assert isinstance(col_map, dict)
    for col in ("id", "station_name", "variable", "unit", "source"):
        assert col in col_map, f"Expected column '{col}' in table_column_width_map"
    for width in col_map.values():
        assert width.endswith("%"), f"Width should be a percentage string, got: {width}"


def test_table_filters(minimal_manager):
    filters = minimal_manager.get_table_filters()
    assert isinstance(filters, dict)
    for col in minimal_manager.get_table_column_width_map():
        assert col in filters, f"Expected filter entry for column '{col}'"


def test_get_data_catalog_columns(minimal_manager):
    dfcat = minimal_manager.get_data_catalog()
    for col in ("id", "station_name", "variable", "unit", "source", "filename"):
        assert col in dfcat.columns, f"Expected column '{col}' in data catalog"


def test_build_station_name(minimal_manager):
    row = pd.Series({"source": "study1", "id": "DWR_A1", "variable": "elev"})
    name = minimal_manager.build_station_name(row)
    assert "study1" in name
    assert "DWR_A1" in name
    assert "elev" in name


def test_build_station_name_no_source(minimal_manager):
    row = pd.Series({"id": "DWR_A1", "variable": "elev"})
    name = minimal_manager.build_station_name(row)
    assert "DWR_A1" in name


def test_data_catalog_property(minimal_manager):
    cat = minimal_manager.data_catalog
    assert isinstance(cat, DataCatalog)


def test_catalog_key_format(minimal_manager):
    cat = minimal_manager.data_catalog
    names = cat.list_names()
    assert "study1::DWR_A1/elev" in names
    assert "study1::DWR_B2/salt" in names


def test_catalog_preserves_station_name(minimal_manager):
    """station_name attribute must survive the catalog round-trip for table display."""
    dfcat = minimal_manager.get_data_catalog()
    assert "station_name" in dfcat.columns
    # Raw ref rows must have a non-null station_name
    raw_rows = dfcat[dfcat["ref_type"] == "raw"] if "ref_type" in dfcat.columns else dfcat
    assert raw_rows["station_name"].notna().all()


def test_get_data_reference_study(minimal_manager):
    dfcat = minimal_manager.get_data_catalog()
    row = dfcat[dfcat["id"] == "DWR_A1"].iloc[0]
    ref = minimal_manager.get_data_reference(row)
    assert isinstance(ref, DataReference)
    assert ref.name == "study1::DWR_A1/elev"


def test_get_data_reference_datastore(minimal_study):
    """Datastore rows use source='datastore'; key is 'datastore::{id}/{variable}'."""
    datastore = MagicMock()
    obs_rows = [
        {
            "id": "DWR_A1_default",
            "name": "Station A Obs",
            "variable": "elev",
            "unit": "m",
            "filename": "/obs/file.csv",
            "source": "datastore",
        }
    ]
    obs_df = gpd.GeoDataFrame(
        obs_rows,
        geometry=[Point(622_000, 4_200_000)],
        crs="EPSG:32610",
    )
    with patch.object(
        SchismOutputUIDataManager, "_convert_to_study_format", return_value=obs_df
    ):
        datastore.get_catalog.return_value = obs_df
        mgr = SchismOutputUIDataManager(minimal_study, datastore=datastore)

    dfcat = mgr.get_data_catalog()
    obs_row = dfcat[dfcat["source"] == "datastore"].iloc[0]
    ref = mgr.get_data_reference(obs_row)
    assert ref.name.startswith("datastore::")


def test_tooltips(minimal_manager):
    tooltips = minimal_manager.get_tooltips()
    assert isinstance(tooltips, list)
    assert len(tooltips) > 0
    tooltip_keys = [t[0] for t in tooltips]
    for key in ("id", "name", "variable"):
        assert key in tooltip_keys


def test_map_color_columns(minimal_manager):
    cols = minimal_manager.get_map_color_columns()
    assert isinstance(cols, list)
    assert len(cols) > 0


def test_map_marker_columns(minimal_manager):
    cols = minimal_manager.get_map_marker_columns()
    assert isinstance(cols, list)


def test_is_irregular(minimal_manager):
    row = pd.Series({"id": "DWR_A1", "variable": "elev"})
    assert minimal_manager.is_irregular(row) is False


# ---------------------------------------------------------------------------
# Math reference support
# ---------------------------------------------------------------------------


def test_math_ref_appears_in_get_data_catalog(minimal_manager):
    """After a MathDataReference is added to the live catalog, get_data_catalog()
    must return a row for it (ref_type == 'math')."""
    from dvue.catalog import InMemoryDataReferenceReader
    from dvue.math_reference import MathDataReference

    ts = _make_time_series()
    # Add a simple pass-through math ref: result = x where x = one raw ref
    raw_ref = minimal_manager.data_catalog.get("study1::DWR_A1/elev")
    math_ref = MathDataReference(
        expression="x",
        variable_map={"x": raw_ref},
        name="math_test_elev",
    )
    minimal_manager.data_catalog.add(math_ref)

    dfcat = minimal_manager.get_data_catalog()
    math_rows = dfcat[dfcat["ref_type"] == "math"]
    assert len(math_rows) >= 1
    assert "math_test_elev" in math_rows["name"].values


def test_math_ref_get_data_reference(minimal_manager):
    """get_data_reference() must resolve a math ref by the 'name' catalog key."""
    from dvue.math_reference import MathDataReference

    raw_ref = minimal_manager.data_catalog.get("study1::DWR_A1/elev")
    math_ref = MathDataReference(
        expression="x",
        variable_map={"x": raw_ref},
        name="math_elev_lookup",
    )
    minimal_manager.data_catalog.add(math_ref)

    dfcat = minimal_manager.get_data_catalog()
    math_row = dfcat[dfcat["name"] == "math_elev_lookup"].iloc[0]
    ref = minimal_manager.get_data_reference(math_row)
    assert ref.name == "math_elev_lookup"
    assert isinstance(ref, MathDataReference)


def test_build_station_name_math_ref(minimal_manager):
    """build_station_name() must not crash for math ref rows (NaN id/source/variable)."""
    from dvue.math_reference import MathDataReference

    raw_ref = minimal_manager.data_catalog.get("study1::DWR_A1/elev")
    math_ref = MathDataReference(
        expression="x",
        variable_map={"x": raw_ref},
        name="math_station_name_test",
    )
    minimal_manager.data_catalog.add(math_ref)

    dfcat = minimal_manager.get_data_catalog()
    math_row = dfcat[dfcat["name"] == "math_station_name_test"].iloc[0]
    # Must not raise
    result = minimal_manager.build_station_name(math_row)
    assert isinstance(result, str)
    assert "math_station_name_test" in result


def test_plot_action_create_curve_math_ref(minimal_manager):
    """create_curve() must handle math ref rows (NaN source/id/variable)."""
    from dvue.math_reference import MathDataReference

    raw_ref = minimal_manager.data_catalog.get("study1::DWR_A1/elev")
    math_ref = MathDataReference(
        expression="x",
        variable_map={"x": raw_ref},
        name="math_curve_test",
    )
    minimal_manager.data_catalog.add(math_ref)

    dfcat = minimal_manager.get_data_catalog()
    math_row = dfcat[dfcat["name"] == "math_curve_test"].iloc[0]

    action = SchismTimeSeriesPlotAction()
    ts = _make_time_series()
    curve = action.create_curve(ts, math_row, "m", file_index="")
    assert isinstance(curve, hv.Curve)
    assert "math_curve_test" in curve.label


def test_plot_action_append_to_title_map_math_ref(minimal_manager):
    """append_to_title_map() must not crash for math ref rows (NaN source)."""
    from dvue.math_reference import MathDataReference

    raw_ref = minimal_manager.data_catalog.get("study1::DWR_A1/elev")
    math_ref = MathDataReference(
        expression="x",
        variable_map={"x": raw_ref},
        name="math_title_test",
    )
    minimal_manager.data_catalog.add(math_ref)

    dfcat = minimal_manager.get_data_catalog()
    math_row = dfcat[dfcat["name"] == "math_title_test"].iloc[0]

    action = SchismTimeSeriesPlotAction()
    title_map = {}
    # Must not raise
    action.append_to_title_map(title_map, "m", math_row)
    assert "m" in title_map
    # Title must contain the math ref name
    assert "math_title_test" in title_map["m"]


# ---------------------------------------------------------------------------
# SchismDataReferenceReader
# ---------------------------------------------------------------------------


def test_reader_repr():
    reader = SchismDataReferenceReader(
        study_dir_map={"/fake/output1": MagicMock()},
        obs_datastore=None,
        manager=MagicMock(convert_units=False),
    )
    assert "SchismDataReferenceReader" in repr(reader)


def test_reader_load_no_convert():
    """Reader returns raw data and does NOT call convert_to_SI when convert_units=False."""
    ts = _make_time_series()
    ts.attrs["unit"] = "m"
    study = MagicMock()
    study.get_data.return_value = ts
    manager = MagicMock()
    manager.convert_units = False
    reader = SchismDataReferenceReader(
        study_dir_map={"/fake/output1": study},
        obs_datastore=None,
        manager=manager,
    )
    attrs = {"source": "study1", "unit": "m", "filename": "/fake/output1/staout_1", "variable": "elev"}
    with patch("schismviz.schismui.schismstudy.convert_to_SI") as mock_convert:
        df = reader.load(**attrs)
    mock_convert.assert_not_called()
    assert isinstance(df, pd.DataFrame)


def test_reader_load_converts_units():
    """Reader calls convert_to_SI when convert_units=True."""
    ts = _make_time_series()
    ts.attrs["unit"] = "m"
    study = MagicMock()
    study.get_data.return_value = ts
    manager = MagicMock()
    manager.convert_units = True
    reader = SchismDataReferenceReader(
        study_dir_map={"/fake/output1": study},
        obs_datastore=None,
        manager=manager,
    )
    attrs = {"source": "study1", "unit": "m", "filename": "/fake/output1/staout_1", "variable": "elev"}
    converted_ts = ts.copy()
    converted_ts.attrs["unit"] = "m"
    with patch("schismviz.schismui.schismstudy.convert_to_SI", return_value=(converted_ts, "m")) as mock_convert:
        df = reader.load(**attrs)
    mock_convert.assert_called_once()
    assert isinstance(df, pd.DataFrame)


def test_reader_load_datastore():
    """Reader delegates to datastore when source=='datastore'."""
    ts = _make_time_series()
    ts.attrs["unit"] = "m"
    obs_datastore = MagicMock()
    obs_datastore.get_data.return_value = ts
    manager = MagicMock()
    manager.convert_units = False
    reader = SchismDataReferenceReader(
        study_dir_map={},
        obs_datastore=obs_datastore,
        manager=manager,
    )
    attrs = {"source": "datastore", "unit": "m", "variable": "elev"}
    with patch("schismviz.schismui.schismstudy.convert_to_SI"):
        df = reader.load(**attrs)
    obs_datastore.get_data.assert_called_once_with(attrs)
    assert isinstance(df, pd.DataFrame)


# ---------------------------------------------------------------------------
# SchismTimeSeriesPlotAction
# ---------------------------------------------------------------------------


def test_plot_action_create_curve():
    action = SchismTimeSeriesPlotAction()
    ts = _make_time_series()
    row = pd.Series({"source": "study1", "id": "DWR_A1", "variable": "elev"})
    curve = action.create_curve(ts, row, "m", file_index="")
    assert isinstance(curve, hv.Curve)
    label = curve.label
    assert "study1" in label
    assert "DWR_A1" in label
    assert "elev" in label


def test_plot_action_append_to_title_map():
    action = SchismTimeSeriesPlotAction()
    title_map = {}
    row = pd.Series({"source": "study1", "id": "DWR_A1", "variable": "elev"})
    action.append_to_title_map(title_map, "m", row)
    assert "m" in title_map
    value = title_map["m"]
    assert "study1" in value[0]
    assert "elev" in value[1]
    assert "DWR_A1" in value[2]


def test_plot_action_create_title():
    action = SchismTimeSeriesPlotAction()
    title = action.create_title(["study1", "elev", "DWR_A1"])
    assert "elev" in title
    assert "DWR_A1" in title
    assert "study1" in title


def test_plot_action_append_no_duplicate():
    """Appending same row twice must not duplicate values in title accumulator."""
    action = SchismTimeSeriesPlotAction()
    title_map = {}
    row = pd.Series({"source": "study1", "id": "DWR_A1", "variable": "elev"})
    action.append_to_title_map(title_map, "m", row)
    action.append_to_title_map(title_map, "m", row)
    value = title_map["m"]
    # "study1" should appear exactly once in value[0]
    assert value[0].count("study1") == 1
