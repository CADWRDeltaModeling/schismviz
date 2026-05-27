"""SCHISM readers and registry-backed UI manager for dvue.

Registering this module with the dvue plugin mechanism makes SCHISM study
output directories and YAML config files loadable in dvue's generic combine
UI::

    dvue ui --plugin schismviz.readers /path/to/study/param.nml
    dvue ui --plugin schismviz.readers /path/to/schism_studies.yaml

The :func:`register_readers` function is used by setuptools entry points
(``dvue.plugins`` group).  For backward compatibility, registration also
fires at import time, so all three entry points work:

1. ``dvue ui --plugin schismviz.readers`` (generic dvue combine UI)
2. ``schismviz combine`` (SCHISM-specific combine UI via this package's CLI)
3. ``import schismviz.readers`` in user notebooks / scripts

Classes
-------
SchismDataReference
    :class:`~dvue.catalog.DataReference` subclass with
    ``ref_type = "schism_output"`` so that
    :meth:`~dvue.catalog.DataReference._load_data` falls back to
    :class:`~dvue.registry.ReaderRegistry` when no embedded reader is present.
SchismOutputReader
    :class:`~dvue.catalog.DataReferenceReader` that scans SCHISM study
    directories (via ``param.nml``) or multi-study YAML config files and
    loads individual station/variable time series on demand.
SchismRegistryPlotAction
    :class:`~dvue.registry_ui.RegistryPlotAction` subclass that uses
    ``station_name`` (human-readable name) in curve labels instead of the
    raw station ID.
SchismRegistryUIManager
    :class:`~dvue.registry_ui.RegistryUIManager` subclass that wires in
    :class:`SchismRegistryPlotAction`, infers ``time_range`` from scanned
    studies, and exposes SCHISM-specific table columns.
"""

from __future__ import annotations

import logging
import os
import pathlib
from typing import List, Optional

import holoviews as hv
import cartopy.crs as ccrs
import pandas as pd
import yaml

from dvue.catalog import DataReference, DataReferenceReader
from dvue.registry import ReaderRegistry
from dvue.registry_ui import RegistryPlotAction, RegistryUIManager

from schismviz.schismstudy import SchismStudy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SchismDataReference
# ---------------------------------------------------------------------------


class SchismDataReference(DataReference):
    """DataReference for a single SCHISM station/variable time series.

    Sets ``ref_type = "schism_output"`` so that
    :meth:`~dvue.catalog.DataReference._load_data` resolves the reader via
    :class:`~dvue.registry.ReaderRegistry` using ``(ref_type, source)`` as
    the lookup key when no embedded reader instance is present.
    """

    ref_type: str = "schism_output"


# ---------------------------------------------------------------------------
# SchismOutputReader
# ---------------------------------------------------------------------------


class SchismOutputReader(DataReferenceReader):
    """Read SCHISM station output time series.

    One reader instance is created per study directory
    (``source = str(base_dir)``).  The :class:`SchismStudy` is lazily
    instantiated on the first :meth:`load` call using the study-config
    attributes stored on the :class:`SchismDataReference`.

    Parameters
    ----------
    source : str
        Absolute path to the SCHISM study base directory.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self._study: Optional[SchismStudy] = None

    # ------------------------------------------------------------------
    # Scan (file discovery)
    # ------------------------------------------------------------------

    @classmethod
    def scan(cls, path: str) -> List[SchismDataReference]:
        """Scan *path* and return one :class:`SchismDataReference` per
        station/variable combination found in the study.

        Parameters
        ----------
        path : str
            Path to one of:

            * A ``param.nml`` file or a compound variant such as
              ``param.nml.clinic``, ``param.nml.barotropic``, or
              ``param.nml.tropic`` — the study directory is inferred as the
              parent directory, using default file names for all other study
              config options.
            * A YAML file with a top-level ``schism_studies`` key — all
              listed studies are scanned in order.

        Returns
        -------
        list of SchismDataReference
            Empty list when *path* is a YAML file that does not contain a
            ``schism_studies`` section (i.e. it is not a SCHISM config).
        """
        path = str(path)
        suffixes = [s.lower() for s in pathlib.Path(path).suffixes]
        # Matches plain .nml and compound variants: .nml.clinic, .nml.barotropic, .nml.tropic
        if suffixes and suffixes[0] == ".nml":
            return cls._scan_nml(path)
        last = os.path.splitext(path)[1].lower()
        if last in (".yaml", ".yml"):
            return cls._scan_yaml(path)
        return []

    @classmethod
    def _scan_nml(cls, path: str) -> List[SchismDataReference]:
        """Create refs for a single study whose param.nml (or variant such as
        ``param.nml.clinic``, ``param.nml.barotropic``, ``param.nml.tropic``)
        is at *path*."""
        base_dir = str(pathlib.Path(path).parent)
        study_name = pathlib.Path(base_dir).name
        # Probe for the flux cross-section file: prefer the YAML variant, fall
        # back to fluxflag.prop (BayDeltaSCHISM convention).  SchismStudy
        # handles both: .yaml → load_flux_dataframe; other → station_names_from_file.
        flux_xsect_file = "flow_station_xsects.yaml"
        for candidate in ("flow_station_xsects.yaml", "fluxflag.prop"):
            if (pathlib.Path(base_dir) / candidate).exists():
                flux_xsect_file = candidate
                break
        config = {
            "study_name": study_name,
            "base_dir": base_dir,
            "output_dir": "outputs",
            "param_nml_file": pathlib.Path(path).name,
            "flux_xsect_file": flux_xsect_file,
            "station_in_file": "station.in",
            "flux_out": "flux.out",
            "reftime": None,
        }
        return cls._refs_from_study_config(config)

    @classmethod
    def _scan_yaml(cls, path: str) -> List[SchismDataReference]:
        """Parse a SCHISM multi-study YAML config and create refs per study."""
        try:
            with open(path, "r") as fh:
                yaml_data = yaml.safe_load(fh)
        except Exception as exc:
            logger.warning("SchismOutputReader.scan: cannot parse %s: %s", path, exc)
            return []

        if not isinstance(yaml_data, dict) or "schism_studies" not in yaml_data:
            # Not a SCHISM config YAML — silently return nothing.
            return []

        yaml_base_dir = pathlib.Path(path).parent
        refs: List[SchismDataReference] = []
        for study_config in yaml_data.get("schism_studies", []):
            from dvue import utils  # local import avoids circular dependency

            raw_base_dir = study_config.get("base_dir", ".")
            base_dir = str(
                utils.interpret_file_relative_to(yaml_base_dir, raw_base_dir)
            )
            config = {
                "study_name": study_config.get("label", pathlib.Path(base_dir).name),
                "base_dir": base_dir,
                "output_dir": study_config.get("output_dir", "outputs"),
                "param_nml_file": study_config.get("param_nml_file", "param.nml"),
                "flux_xsect_file": study_config.get(
                    "flux_xsect_file", "flow_station_xsects.yaml"
                ),
                "station_in_file": study_config.get("station_in_file", "station.in"),
                "flux_out": study_config.get("flux_out", "flux.out"),
                "reftime": study_config.get("reftime", None),
            }
            refs.extend(cls._refs_from_study_config(config))
        return refs

    @classmethod
    def _refs_from_study_config(cls, config: dict) -> List[SchismDataReference]:
        """Open *config* as a :class:`SchismStudy`, enumerate its catalog,
        and return one :class:`SchismDataReference` per station/variable row.

        Study-level metadata (``reftime``, ``endtime``) is stored as
        ``study_start`` / ``study_end`` attributes on every ref so that
        :meth:`SchismRegistryUIManager.on_file_added` can set ``time_range``
        without needing to open the study a second time.
        """
        base_dir = config["base_dir"]
        study_name = config["study_name"]
        try:
            study = SchismStudy(
                study_name=study_name,
                base_dir=base_dir,
                output_dir=config.get("output_dir", "outputs"),
                param_nml_file=config.get("param_nml_file", "param.nml"),
                flux_xsect_file=config.get(
                    "flux_xsect_file", "flow_station_xsects.yaml"
                ),
                station_in_file=config.get("station_in_file", "station.in"),
                flux_out=config.get("flux_out", "flux.out"),
                reftime=config.get("reftime"),
            )
        except Exception as exc:
            logger.warning(
                "SchismOutputReader: cannot open study at %s: %s", base_dir, exc
            )
            return []

        try:
            catalog_df = study.get_catalog()
        except Exception as exc:
            logger.warning(
                "SchismOutputReader: cannot build catalog for %s: %s", base_dir, exc
            )
            return []

        study_start = str(study.reftime) if hasattr(study, "reftime") else ""
        study_end = str(study.endtime) if hasattr(study, "endtime") else ""

        refs: List[SchismDataReference] = []
        for _, row in catalog_df.iterrows():
            station_id = str(row["id"])
            variable = str(row["variable"])
            ref_name = f"{study_name}::{station_id}/{variable}"
            attrs: dict = {
                # Study config — needed to lazy-reconstruct SchismStudy in load().
                "base_dir": base_dir,
                "study_name": study_name,
                "output_dir": config.get("output_dir", "outputs"),
                "param_nml_file": config.get("param_nml_file", "param.nml"),
                "flux_xsect_file": config.get(
                    "flux_xsect_file", "flow_station_xsects.yaml"
                ),
                "station_in_file": config.get("station_in_file", "station.in"),
                "flux_out": config.get("flux_out", "flux.out"),
                "reftime": config.get("reftime"),
                # Time extent — dvue standard names used by RegistryUIManager.on_file_added
                # to auto-expand time_range without re-opening the study.
                "time_extent_start": study_start,
                "time_extent_end": study_end,
                # Legacy names kept for backward compatibility.
                "study_start": study_start,
                "study_end": study_end,
                # Station / variable metadata.
                "id": station_id,
                "variable": variable,
                "unit": str(row.get("unit", "")),
                "station_name": str(row.get("name", "")),
                "filename": str(row.get("filename", "")),
            }
            if "geometry" in row.index and row["geometry"] is not None:
                attrs["geometry"] = row["geometry"]

            refs.append(
                SchismDataReference(
                    source=base_dir,
                    name=ref_name,
                    **attrs,
                )
            )
        return refs

    # ------------------------------------------------------------------
    # Load (data retrieval)
    # ------------------------------------------------------------------

    def load(self, **attrs) -> pd.DataFrame:
        """Load data for a single station/variable.

        The :class:`SchismStudy` is created lazily on the first call using
        the study-config attributes stored on the
        :class:`SchismDataReference`.  ``time_range`` (if present) is used
        to slice the result after loading the full series, since
        :class:`SchismStudy` has no native time-windowing API.

        Parameters
        ----------
        **attrs
            The full ``_attributes`` dict of the calling
            :class:`SchismDataReference`, unpacked as keyword arguments.
            Required keys: ``id``, ``variable``, ``filename``.
            Optional keys: all :class:`SchismStudy` constructor args,
            ``time_range``.
        """
        if self._study is None:
            self._study = SchismStudy(
                study_name=attrs.get("study_name", pathlib.Path(self.source).name),
                base_dir=attrs.get("base_dir", self.source),
                output_dir=attrs.get("output_dir", "outputs"),
                param_nml_file=attrs.get("param_nml_file", "param.nml"),
                flux_xsect_file=attrs.get(
                    "flux_xsect_file", "flow_station_xsects.yaml"
                ),
                station_in_file=attrs.get("station_in_file", "station.in"),
                flux_out=attrs.get("flux_out", "flux.out"),
                reftime=attrs.get("reftime"),
            )

        df = self._study.get_data(attrs)
        df = df[slice(df.first_valid_index(), df.last_valid_index())]

        # Apply time-range windowing (SchismStudy always loads the full series).
        time_range = attrs.get("time_range")
        if time_range is not None:
            start = pd.Timestamp(time_range[0])
            end = pd.Timestamp(time_range[1])
            df = df.loc[start:end]

        df.attrs["unit"] = attrs.get("unit", "")
        df.attrs["ptype"] = "INST-VAL"
        return df

    def __repr__(self) -> str:
        return (
            f"SchismOutputReader(source={self.source!r}, "
            f"study_loaded={self._study is not None})"
        )


# ---------------------------------------------------------------------------
# SchismRegistryPlotAction
# ---------------------------------------------------------------------------


class SchismRegistryPlotAction(RegistryPlotAction):
    """RegistryPlotAction subclass with SCHISM-specific curve labels.

    Uses ``station_name`` (human-readable station display name) in curve
    labels and titles when available, falling back to the ``station`` (ID)
    column.  Curve label format: ``station_name/variable`` (multi-variable)
    or ``station_name`` (single variable).  Title format:
    ``variable @ station_name``.
    """

    def create_curve(self, data, row, unit, file_index=""):
        varying = getattr(self, "_varying", {"station": True, "variable": True})
        file_index_label = f"{file_index}:" if file_index else ""
        # Prefer human-readable station_name over the station/id column.
        station_display = str(
            row.get("station_name") or row.get("station") or "unknown"
        )
        variable = str(row.get("variable") or "")

        if row.get("ref_type") == "math":
            crvlabel = f'{file_index_label}{row.get("name", "math_ref")}'
        else:
            parts = [station_display]
            if varying.get("variable", True):
                parts.append(self.format_variable(variable))
            crvlabel = f'{file_index_label}{"/".join(parts)}'

        ylabel = self.format_variable(variable) + (f" ({unit})" if unit else "")
        crv = hv.Curve(data.iloc[:, [0]], label=crvlabel).redim(value=crvlabel)
        return crv.opts(
            xlabel="Time",
            ylabel=ylabel,
            responsive=True,
            active_tools=["wheel_zoom"],
            tools=["hover"],
        )

    def append_to_title_map(self, title_map, group_key, row):
        value = title_map.get(group_key, ["", ""])
        station_display = str(
            row.get("station_name") or row.get("station") or ""
        )
        variable = str(row.get("variable") or "")
        value[0] = self._append_value(self.format_variable(variable), value[0])
        value[1] = self._append_value(station_display, value[1])
        title_map[group_key] = value


# ---------------------------------------------------------------------------
# SchismRegistryUIManager
# ---------------------------------------------------------------------------


class SchismRegistryUIManager(RegistryUIManager):
    def __init__(self, files=(), **kwargs):
        super().__init__(files=files, **kwargs)
        if self.crs is None:
            self.crs = ccrs.UTM(10)  # SCHISM Bay-Delta geometry is EPSG:32610

    """RegistryUIManager subclass for SCHISM output data.

    Extends the generic :class:`~dvue.registry_ui.RegistryUIManager` with:

    * :class:`SchismRegistryPlotAction` for SCHISM-specific curve labels
      (uses ``station_name`` rather than raw station ID).
    * :meth:`normalize_ref` that maps ``id`` → ``station`` and keeps
      ``station_name`` available for display.
    * :meth:`on_file_added` that expands ``time_range`` from each study's
      ``reftime`` / ``endtime`` stored as ref attributes during
      :meth:`~SchismOutputReader.scan`.
    * Table columns: ``station``, ``station_name``, ``variable``, ``unit``.

    The catalog ``primary_key`` (``["source_num", "station", "variable"]``)
    is inherited from :class:`~dvue.registry_ui.RegistryUIManager`; each
    unique study directory is a separate source, and ``source_num`` is
    auto-assigned in the order files are added.

    Usage
    -----
    Launched automatically by ``schismviz combine``::

        schismviz combine study1/param.nml study2/param.nml
        schismviz combine multi_study_config.yaml

    Or constructed directly::

        from schismviz.readers import SchismRegistryUIManager
        manager = SchismRegistryUIManager()
        manager.add_source_files("study1/param.nml", "study2/param.nml")
    """

    # ------------------------------------------------------------------
    # Customisation hooks
    # ------------------------------------------------------------------

    def normalize_ref(self, ref: DataReference) -> None:
        """Map SCHISM ref attributes to the common ``station``/``variable`` schema.

        Sets ``ref.station`` from ``ref.id`` (the SCHISM station identifier
        such as ``"ROLD004_default"``).  ``station_name`` (human-readable
        display name) is already stored on the ref by
        :meth:`~SchismOutputReader._refs_from_study_config` and requires no
        further action here.
        """
        if not ref._attributes.get("station"):
            station = ref._attributes.get("id", "")
            ref.set_attribute("station", str(station))
        if not ref._attributes.get("variable"):
            ref.set_attribute("variable", "")

    def on_file_added(self, path: str, refs: List[DataReference]) -> None:
        """Expand ``time_range`` to cover the newly added study or studies.

        Delegates to the base :class:`~dvue.registry_ui.RegistryUIManager`
        implementation, which reads ``time_extent_start`` / ``time_extent_end``
        attributes set by :meth:`~SchismOutputReader._refs_from_study_config`.
        """
        super().on_file_added(path, refs)

    # ------------------------------------------------------------------
    # Plot action
    # ------------------------------------------------------------------

    def _make_plot_action(self) -> SchismRegistryPlotAction:
        return SchismRegistryPlotAction()

    # ------------------------------------------------------------------
    # Table / map configuration
    # ------------------------------------------------------------------

    def _get_table_column_width_map(self) -> dict:
        return {
            "station": "10%",
            "station_name": "15%",
            "variable": "12%",
            "unit": "10%",
        }

    def get_table_filters(self) -> dict:
        return {
            "station": {
                "type": "input",
                "func": "like",
                "placeholder": "Enter match",
            },
            "station_name": {
                "type": "input",
                "func": "like",
                "placeholder": "Enter match",
            },
            "variable": {
                "type": "input",
                "func": "like",
                "placeholder": "Enter match",
            },
            "unit": {
                "type": "input",
                "func": "like",
                "placeholder": "Enter match",
            },
        }

    def get_tooltips(self) -> list:
        return [
            ("station", "@station"),
            ("name", "@station_name"),
            ("variable", "@variable"),
            ("unit", "@unit"),
        ]

    def get_map_color_columns(self) -> list:
        return ["variable", "unit"]

    def get_map_marker_columns(self) -> list:
        return ["variable", "unit"]

    def is_irregular(self, r) -> bool:
        return False


# Optional dvue.cli plugin hooks.
# When dvue ui imports this module via --plugin, it can use these symbols
# to launch with SCHISM-specific manager behavior and CRS.
DVueUIManager = SchismRegistryUIManager
DVueUI_CRS = ccrs.UTM(10)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_readers() -> None:
    """Register SCHISM readers with dvue's :class:`ReaderRegistry`.

    This is the callable referenced by the ``dvue.plugins`` entry point:

    ``schismviz = \"schismviz.readers:register_readers\"``.
    """

    # Compound NML extensions (.nml.clinic, .nml.barotropic, .nml.tropic) are
    # identified by their *last* suffix via os.path.splitext in the registry;
    # scan() inspects the full suffix chain to confirm the .nml prefix.
    ReaderRegistry.register(
        "schism_output",
        SchismOutputReader,
        extensions=[
            ".nml",
            ".clinic",
            ".barotropic",
            ".tropic",
            ".yaml",
            ".yml",
        ],
    )

# Backward compatibility: preserve import-time registration behavior.
register_readers()
