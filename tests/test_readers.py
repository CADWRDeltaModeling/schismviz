"""Unit tests for schismviz.readers.

All disk I/O is mocked so the tests run without real SCHISM output files.
"""
import pathlib
from unittest.mock import MagicMock, patch
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import pytest

import holoviews as hv

hv.extension("bokeh")

from dvue.registry import ReaderRegistry


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registration_on_import():
    """Importing schismviz.readers registers SchismOutputReader at import time."""
    # Clear any state from previous test runs.
    ReaderRegistry.clear_instance_cache()
    import schismviz.readers  # noqa: F401

    assert ReaderRegistry.can_handle("param.nml"), ".nml not registered"
    assert ReaderRegistry.can_handle("studies.yaml"), ".yaml not registered"
    assert ReaderRegistry.can_handle("studies.yml"), ".yml not registered"
    assert ReaderRegistry.can_handle("param.nml.clinic"), ".nml.clinic not registered"
    assert ReaderRegistry.can_handle("param.nml.barotropic"), ".nml.barotropic not registered"
    assert ReaderRegistry.can_handle("param.nml.tropic"), ".nml.tropic not registered"


def test_register_readers_function_registers_plugin_mappings():
    """register_readers() maps schism_output and supported extensions."""
    from schismviz.readers import SchismOutputReader, register_readers

    register_readers()

    readers = ReaderRegistry.get_registered_readers()
    extensions = ReaderRegistry.get_registered_extensions()

    assert readers.get("schism_output") is SchismOutputReader
    for ext in [".nml", ".clinic", ".barotropic", ".tropic", ".yaml", ".yml"]:
        assert extensions.get(ext) is SchismOutputReader


def test_ref_type():
    """SchismDataReference advertises ref_type='schism_output'."""
    from schismviz.readers import SchismDataReference

    ref = SchismDataReference(source=".", name="test::A/elev", id="A", variable="elev")
    assert ref.ref_type == "schism_output"


# ---------------------------------------------------------------------------
# scan() — extension dispatch
# ---------------------------------------------------------------------------


def test_scan_non_schism_yaml(tmp_path):
    """scan() returns an empty list for YAML files without schism_studies."""
    from schismviz.readers import SchismOutputReader

    yaml_file = tmp_path / "other.yaml"
    yaml_file.write_text("key: value\nanother: data\n")
    refs = SchismOutputReader.scan(str(yaml_file))
    assert refs == []


def test_scan_empty_schism_studies_yaml(tmp_path):
    """scan() returns an empty list for YAML with empty schism_studies."""
    from schismviz.readers import SchismOutputReader

    yaml_file = tmp_path / "empty.yaml"
    yaml_file.write_text("schism_studies: []\n")
    refs = SchismOutputReader.scan(str(yaml_file))
    assert refs == []


def test_scan_yaml_bad_study_path(tmp_path):
    """scan() skips a study whose base_dir does not exist (logs warning, no crash)."""
    from schismviz.readers import SchismOutputReader

    yaml_file = tmp_path / "studies.yaml"
    yaml_file.write_text(
        "schism_studies:\n"
        "  - label: missing_study\n"
        "    base_dir: /nonexistent/path/study\n"
    )
    refs = SchismOutputReader.scan(str(yaml_file))
    assert refs == []


def test_scan_nml_bad_path(tmp_path):
    """scan() of a .nml whose parent directory lacks study files returns empty list."""
    from schismviz.readers import SchismOutputReader

    nml_file = tmp_path / "param.nml"
    nml_file.write_text("")  # empty file — SchismStudy init will fail
    refs = SchismOutputReader.scan(str(nml_file))
    assert refs == []


def test_scan_compound_nml_dispatches(tmp_path):
    """scan() routes compound .nml.clinic / .nml.barotropic / .nml.tropic to _scan_nml."""
    from schismviz.readers import SchismOutputReader

    for variant in ("param.nml.clinic", "param.nml.barotropic", "param.nml.tropic"):
        nml_file = tmp_path / variant
        nml_file.write_text("")  # empty — SchismStudy init will fail → returns []
        refs = SchismOutputReader.scan(str(nml_file))
        # Returns [] (failed study), not None — confirms dispatch reached _scan_nml
        assert refs == [], f"{variant} should dispatch to _scan_nml and return []"


# ---------------------------------------------------------------------------
# scan() — successful scan via mock SchismStudy
# ---------------------------------------------------------------------------


def _make_mock_catalog():
    """Minimal GeoDataFrame mimicking SchismStudy.get_catalog()."""
    return gpd.GeoDataFrame(
        [
            {
                "id": "DWR_A1",
                "name": "Station A",
                "variable": "elev",
                "unit": "m",
                "filename": "/fake/outputs/staout_1",
                "source": "study1",
                "geometry": Point(0.0, 0.0),
            },
            {
                "id": "DWR_A1",
                "name": "Station A",
                "variable": "salt",
                "unit": "PSU",
                "filename": "/fake/outputs/staout_5",
                "source": "study1",
                "geometry": Point(0.0, 0.0),
            },
        ],
        geometry="geometry",
    )


def _make_mock_study():
    study = MagicMock()
    study.reftime = pd.Timestamp("2020-01-01")
    study.endtime = pd.Timestamp("2020-12-31")
    study.get_catalog.return_value = _make_mock_catalog()
    return study


@patch("schismviz.readers.SchismStudy")
def test_scan_nml_returns_refs(mock_study_class, tmp_path):
    """scan() of a param.nml returns one SchismDataReference per station/variable."""
    from schismviz.readers import SchismDataReference, SchismOutputReader

    mock_study_class.return_value = _make_mock_study()

    nml_file = tmp_path / "param.nml"
    nml_file.write_text("")

    refs = SchismOutputReader.scan(str(nml_file))

    assert len(refs) == 2
    assert all(isinstance(r, SchismDataReference) for r in refs)
    assert all(r.ref_type == "schism_output" for r in refs)
    assert {r._attributes["variable"] for r in refs} == {"elev", "salt"}
    # source = base_dir (parent of param.nml)
    assert all(r.source == str(tmp_path) for r in refs)


@patch("schismviz.readers.SchismStudy")
def test_scan_nml_stores_study_times(mock_study_class, tmp_path):
    """scan() stores study_start and study_end on each ref."""
    from schismviz.readers import SchismOutputReader

    mock_study_class.return_value = _make_mock_study()

    nml_file = tmp_path / "param.nml"
    nml_file.write_text("")

    refs = SchismOutputReader.scan(str(nml_file))
    assert refs[0]._attributes["study_start"] == "2020-01-01 00:00:00"
    assert refs[0]._attributes["study_end"] == "2020-12-31 00:00:00"


@patch("schismviz.readers.SchismStudy")
def test_scan_yaml_multiple_studies(mock_study_class, tmp_path):
    """scan() of a multi-study YAML returns refs for every study."""
    from schismviz.readers import SchismOutputReader

    mock_study_class.return_value = _make_mock_study()

    study_dir1 = tmp_path / "study1"
    study_dir2 = tmp_path / "study2"
    study_dir1.mkdir()
    study_dir2.mkdir()

    yaml_file = tmp_path / "studies.yaml"
    yaml_file.write_text(
        f"schism_studies:\n"
        f"  - label: s1\n"
        f"    base_dir: {study_dir1}\n"
        f"  - label: s2\n"
        f"    base_dir: {study_dir2}\n"
    )

    refs = SchismOutputReader.scan(str(yaml_file))
    # 2 studies × 2 variables each = 4 refs
    assert len(refs) == 4
    study_names = {r._attributes["study_name"] for r in refs}
    assert study_names == {"s1", "s2"}


# ---------------------------------------------------------------------------
# SchismRegistryUIManager
# ---------------------------------------------------------------------------


def test_normalize_ref_sets_station():
    """normalize_ref maps id → station."""
    from schismviz.readers import SchismDataReference, SchismRegistryUIManager

    manager = SchismRegistryUIManager()
    ref = SchismDataReference(
        source=".",
        name="study::STIN/elev",
        id="STIN",
        variable="elev",
        unit="m",
    )
    manager.normalize_ref(ref)
    assert ref._attributes["station"] == "STIN"
    assert ref._attributes["variable"] == "elev"


def test_normalize_ref_preserves_station_name():
    """normalize_ref does not overwrite an existing station_name attribute."""
    from schismviz.readers import SchismDataReference, SchismRegistryUIManager

    manager = SchismRegistryUIManager()
    ref = SchismDataReference(
        source=".",
        name="study::STIN/elev",
        id="STIN",
        variable="elev",
        station_name="Collinsville",
    )
    manager.normalize_ref(ref)
    assert ref._attributes["station_name"] == "Collinsville"


@patch("schismviz.readers.SchismStudy")
def test_on_file_added_sets_time_range(mock_study_class, tmp_path):
    """on_file_added expands time_range from study_start / study_end on refs."""
    from schismviz.readers import SchismOutputReader, SchismRegistryUIManager

    mock_study_class.return_value = _make_mock_study()

    nml_file = tmp_path / "param.nml"
    nml_file.write_text("")

    manager = SchismRegistryUIManager()
    assert manager.time_range is None

    refs = SchismOutputReader.scan(str(nml_file))
    manager.on_file_added(str(nml_file), refs)

    assert manager.time_range is not None
    start, end = manager.time_range
    assert start == pd.Timestamp("2020-01-01")
    assert end == pd.Timestamp("2020-12-31")


@patch("schismviz.readers.SchismStudy")
def test_on_file_added_expands_existing_time_range(mock_study_class, tmp_path):
    """on_file_added extends an existing time_range outward."""
    from schismviz.readers import SchismOutputReader, SchismRegistryUIManager

    mock_study_class.return_value = _make_mock_study()

    nml_file = tmp_path / "param.nml"
    nml_file.write_text("")

    manager = SchismRegistryUIManager()
    manager.time_range = (pd.Timestamp("2019-06-01"), pd.Timestamp("2020-06-01"))

    refs = SchismOutputReader.scan(str(nml_file))
    manager.on_file_added(str(nml_file), refs)

    start, end = manager.time_range
    assert start == pd.Timestamp("2019-06-01")   # earlier boundary preserved
    assert end == pd.Timestamp("2020-12-31")       # expanded to study end


@patch("schismviz.readers.SchismStudy")
def test_add_source_files_integration(mock_study_class, tmp_path):
    """add_source_files populates the dvue catalog with SCHISM refs."""
    from schismviz.readers import SchismRegistryUIManager

    mock_study_class.return_value = _make_mock_study()

    nml_file = tmp_path / "param.nml"
    nml_file.write_text("")

    manager = SchismRegistryUIManager()
    manager.add_source_files(str(nml_file))

    dfcat = manager.get_data_catalog()
    assert len(dfcat) == 2
    assert set(dfcat["variable"].tolist()) == {"elev", "salt"}
    # station column should be populated from id
    assert all(dfcat["station"] == "DWR_A1")
    # station_name should be preserved
    assert all(dfcat["station_name"] == "Station A")
