import logging
import pandas as pd
import cartopy.crs as ccrs
import holoviews as hv

hv.extension("bokeh")
from dvue.catalog import DataReferenceReader, DataReference, DataCatalog
from dvue.dataui import DataUI
from dvue.tsdataui import TimeSeriesDataUIManager, TimeSeriesPlotAction
from dvue import utils
from . import schismstudy, datastore
import pathlib
import param
import panel as pn

logger = logging.getLogger(__name__)


class SchismDataReferenceReader(DataReferenceReader):
    """Reads a single SCHISM time series from a study output file or the
    observation datastore.

    ``source == "datastore"`` rows are fetched via the observation datastore;
    all other rows are fetched from the matching :class:`SchismStudy` output
    files.  ``convert_units`` is checked on the owning manager at every
    :meth:`load` call.  Caching is intentionally disabled on all
    :class:`~dvue.catalog.DataReference` objects using this reader so that
    toggling ``convert_units`` is always reflected immediately.

    Parameters
    ----------
    study_dir_map : dict
        Mapping of ``str(output_dir)`` → :class:`SchismStudy`.
    obs_datastore : StationDatastore or None
        Observation datastore for ``source == "datastore"`` entries.
    manager : SchismOutputUIDataManager
        Owning manager; provides the reactive ``convert_units`` flag.
    """

    def __init__(self, study_dir_map, obs_datastore, manager):
        self._study_dir_map = study_dir_map
        self._datastore = obs_datastore
        self._manager = manager

    def load(self, **attributes) -> pd.DataFrame:
        source = attributes.get("source", "")
        unit = attributes.get("unit", "")
        if source == "datastore":
            df = self._datastore.get_data(attributes)
            if self._manager.convert_units:
                df, unit = schismstudy.convert_to_SI(df, unit)
        else:
            base_dir = str(pathlib.Path(attributes["filename"]).parent)
            study = self._study_dir_map[base_dir]
            try:
                df = study.get_data(attributes)
            except KeyError as e:
                logger.warning(str(e).strip("'\""))
                raise
            if self._manager.convert_units:
                df, unit = schismstudy.convert_to_SI(df, unit)
        df = df[slice(df.first_valid_index(), df.last_valid_index())]
        df.attrs["unit"] = unit
        df.attrs["ptype"] = "INST-VAL"
        return df

    def __repr__(self) -> str:
        return f"SchismDataReferenceReader(sources={list(self._study_dir_map.keys())!r})"


class SchismTimeSeriesPlotAction(TimeSeriesPlotAction):
    """TimeSeriesPlotAction with SCHISM-specific curve creation and titles."""

    def create_curve(self, df, r, unit, file_index=None):
        # Math refs have ref_type='math' and lack meaningful source/id/variable.
        # Use the catalog name as the curve label/title instead.
        ref_type = r.get("ref_type", "raw") if hasattr(r, "get") else "raw"
        if ref_type != "raw":
            label = str(r["name"]) if "name" in r.index else "math_ref"
            if file_index:
                label = f"{label} [{file_index}]"
            crv = hv.Curve(df.iloc[:, [0]], label=label).redim(value=label)
            return crv.opts(
                xlabel="Time",
                ylabel=f"({unit})",
                title=label,
                responsive=True,
                active_tools=["wheel_zoom"],
                tools=["hover"],
            )
        crvlabel = f'{r["source"]}::{r["id"]}/{r["variable"]}'
        ylabel = f'{r["variable"]} ({unit})'
        title = f'{r["variable"]} @ {r["id"]}'
        crv = hv.Curve(df.iloc[:, [0]], label=crvlabel).redim(value=crvlabel)
        return crv.opts(
            xlabel="Time",
            ylabel=ylabel,
            title=title,
            responsive=True,
            active_tools=["wheel_zoom"],
            tools=["hover"],
        )

    def _append_value(self, new_value, value):
        if new_value not in value:
            value += f'{", " if value else ""}{new_value}'
        return value

    def append_to_title_map(self, title_map, group_key, row):
        # Math refs have ref_type='math' and lack meaningful source/id/variable.
        ref_type = row.get("ref_type", "raw") if hasattr(row, "get") else "raw"
        if ref_type != "raw":
            title_map.setdefault(group_key, str(row.get("name", group_key)))
            return
        if group_key in title_map:
            value = title_map[group_key]
        else:
            value = ["", "", ""]
        value[0] = self._append_value(str(row["source"]), value[0])
        value[2] = self._append_value(str(row["id"]), value[2])
        value[1] = self._append_value(str(row["variable"]), value[1])
        title_map[group_key] = value

    def create_title(self, v):
        title = f"{v[1]} @ {v[2]} ({v[0]})"
        return title


class SchismOutputUIDataManager(TimeSeriesDataUIManager):

    convert_units = param.Boolean(default=True, doc="Convert units to SI")
    show_source_compare = param.Boolean(
        default=True,
        doc="Show the Source Compare action in the Add to Catalog menu.",
    )

    def __init__(self, *studies, datastore=None, time_range=None, **kwargs):
        """
        geolocations is a geodataframe with id, and geometry columns
        This is merged with the data catalog to get the station locations.
        """
        self.studies = studies
        self.study_dir_map = {str(s.output_dir): s for s in self.studies}
        self.datastore = datastore
        self.catalog = self._merge_catalogs(self.studies, self.datastore)
        self.catalog["filename"] = self.catalog["filename"].astype(str)
        self.catalog.reset_index(drop=True, inplace=True)
        self.time_range = time_range
        reftimes = [s.reftime for s in studies]
        stime = min(reftimes)
        etime = max(reftimes)
        if self.time_range is None:
            self.time_range = (
                pd.Timestamp(stime),
                pd.Timestamp(etime + pd.Timedelta(days=250)),
            )
        # Initialize _dvue_catalog to None BEFORE super().__init__() so that the
        # data_catalog property returns None during base-class init (which triggers
        # the correct get_data_catalog() path rather than crashing with AttributeError).
        self._dvue_catalog = None
        super().__init__(**kwargs)
        self.color_cycle_column = "id"
        self.dashed_line_cycle_column = "source"
        self.marker_cycle_column = "variable"
        # Build dvue catalog after param is fully initialized
        self._schism_reader = SchismDataReferenceReader(
            self.study_dir_map, self.datastore, self
        )
        geo_crs = (
            str(self.catalog.crs)
            if hasattr(self.catalog, "crs") and self.catalog.crs is not None
            else None
        )
        self._dvue_catalog = self._build_dvue_catalog(geo_crs)

    def get_widgets(self):
        widget_tabs = super().get_widgets()
        widget_tabs["Plot"].append(pn.Param(self.param.convert_units))
        return widget_tabs

    def _merge_catalogs(self, studies, datastore):
        """
        Merge the schism study and the datastore catalogs
        """
        dfs = [s.get_catalog() for s in studies]
        df = pd.concat(dfs)
        if datastore is not None:
            dfobs = self._convert_to_study_format(datastore.get_catalog())
            dfobs["source"] = "datastore"
            df = pd.concat([df, dfobs])
        return df

    def _convert_to_study_format(self, df):
        df = df.copy()
        df["subloc"] = df["subloc"].apply(lambda v: "default" if len(v) == 0 else v)
        df["id"] = df["station_id"].astype(str) + "_" + df["subloc"]
        df = df.rename(columns={"param": "variable"})
        gdf = schismstudy.convert_station_to_gdf(df)
        return gdf[["id", "name", "variable", "unit", "filename", "geometry"]]

    def get_data_catalog(self):
        # When the live DataCatalog is available, always rebuild from it so that
        # MathDataReference entries added by the Math Ref editor are immediately
        # visible in the table.  _enrich_catalog_with_math_ref_hints fills the
        # 'expression' column for raw refs so users can see their alias tokens.
        if self._dvue_catalog is not None:
            df = super().get_data_catalog()  # TimeSeriesDataUIManager live-rebuild path
            return self._enrich_catalog_with_math_ref_hints(df)
        # Fallback during construction before _dvue_catalog is built.
        return self.catalog

    @property
    def data_catalog(self) -> DataCatalog:
        return self._dvue_catalog

    def get_data_reference(self, row):
        # In the live-catalog path get_data_catalog() returns to_dataframe().reset_index()
        # where the 'name' column is always the catalog key for both raw and math refs.
        # Guard against NaN 'name' (should not happen, but defensive).
        if "name" in row.index and not pd.isna(row.get("name", None)):
            return self._dvue_catalog.get(row["name"])
        # Legacy fallback for the static self.catalog path (construction only).
        ref_name = f"{row['source']}::{row['id']}/{row['variable']}"
        return self._dvue_catalog.get(ref_name)

    def _make_plot_action(self):
        return SchismTimeSeriesPlotAction()

    def _build_dvue_catalog(self, crs=None) -> DataCatalog:
        catalog = DataCatalog(primary_key=["source_num", "id", "variable"], crs=crs)
        for _, row in self.catalog.iterrows():
            ref_name = f"{row['source']}::{row['id']}/{row['variable']}"
            attrs = {k: v for k, v in row.items() if k != "geometry"}
            # Preserve human-readable station name as 'station_name' so it
            # survives catalog.to_dataframe().reset_index() where 'name' becomes
            # the catalog key (ref_name) rather than the station display name.
            attrs["station_name"] = attrs.pop("name", "")
            if "geometry" in row.index and row["geometry"] is not None:
                attrs["geometry"] = row["geometry"]
            try:
                catalog.add(DataReference(
                    reader=self._schism_reader,
                    name=ref_name,
                    cache=False,  # convert_units is reactive; always re-run
                    **attrs,
                ))
            except ValueError:
                pass  # duplicate name; skip
        return catalog

    def get_time_range(self, dfcat):
        return self.time_range

    def build_station_name(self, r):
        # Math refs (ref_type='math') lack id/variable — fall back to catalog name.
        ref_type = r.get("ref_type", "raw") if hasattr(r, "get") else "raw"
        if ref_type != "raw":
            # Source-compare refs carry compare_op + compare_source attributes;
            # use them to build a human-readable label.
            compare_op = r.get("compare_op", None) if hasattr(r, "get") else None
            if compare_op is not None and not (isinstance(compare_op, float) and pd.isna(compare_op)):
                compare_src = r.get("compare_source", "")
                id_part = r.get("id", "") if "id" in r.index else ""
                var_part = r.get("variable", "") if "variable" in r.index else ""
                if id_part and var_part:
                    return f"{compare_op}({compare_src}): {id_part} @ {var_part}"
                elif id_part:
                    return f"{compare_op}({compare_src}): {id_part}"
            return str(r["name"]) if "name" in r.index else "math_ref"
        name = r["id"] + ":" + r["variable"]
        if "source" not in r or pd.isna(r["source"]) or not r["source"]:
            return f"{name}"
        return f'{r["source"]}:{name}'

    def get_table_column_width_map(self):
        """only columns to be displayed in the table should be included in the map"""
        column_width_map = {
            "id": "10%",
            "station_name": "15%",
            "variable": "15%",
            "unit": "15%",
            "source": "10%",
        }
        return column_width_map

    def get_table_filters(self):
        table_filters = {
            "id": {"type": "input", "func": "like", "placeholder": "Enter match"},
            "station_name": {"type": "input", "func": "like", "placeholder": "Enter match"},
            "variable": {"type": "input", "func": "like", "placeholder": "Enter match"},
            "unit": {"type": "input", "func": "like", "placeholder": "Enter match"},
            "source": {"type": "input", "func": "like", "placeholder": "Enter match"},
        }
        return table_filters

    def is_irregular(self, r):
        return False

    def get_data_for_time_range(self, r, time_range):
        ref_name = f"{r['source']}::{r['id']}/{r['variable']}"
        ref = self._dvue_catalog.get(ref_name)
        df = ref.getData(time_range=time_range)
        unit = df.attrs.get("unit", r["unit"])
        ptype = df.attrs.get("ptype", "INST-VAL")
        return df, unit, ptype

    # methods below if geolocation data is available
    def get_tooltips(self):
        return [
            ("id", "@id"),
            ("name", "@station_name"),
            ("variable", "@variable"),
            ("unit", "@unit"),
            ("source", "@source"),
        ]

    def get_map_color_columns(self):
        """return the columns that can be used to color the map"""
        return ["variable", "source", "unit"]

    def get_map_marker_columns(self):
        """return the columns that can be used to color the map"""
        return ["variable", "source", "unit"]


import click
import yaml
from schismviz.session import serve_session_app


@click.command()
@click.option("--schism_dir", default=".", help="Path to the schism study directory")
@click.option(
    "--repo_dir", default="screened", help="Path to the screened data directory"
)
@click.option(
    "--inventory_file",
    default="inventory_datasets.csv",
    help="Path to the inventory file",
)
@click.option(
    "--flux_xsect_file",
    default="flow_station_xsects.yaml",
    help="Path to the flux cross section file",
)
@click.option(
    "--station_in_file", default="station.in", help="Path to the station.in file"
)
@click.option("--flux_out", default="flux.out", help="Path to the flux.out file")
@click.option("--reftime", default=None, help="Reference time")
@click.option("--yaml-file", default=None, help="Path to the yaml file")
@click.option("--port", default=5006, help="Port to serve the UI on")
def show_schism_output_ui(
    schism_dir=".",
    flux_xsect_file="flow_station_xsects.yaml",
    station_in_file="station.in",
    flux_out="flux.out",
    reftime=None,
    repo_dir="screened",
    inventory_file="inventory_datasets.csv",
    yaml_file=None,
    port=5006,
):
    """
    Shows Data UI for SCHISM output files.

    This function creates a Data UI for SCHISM output files, allowing users to visualize and analyze the data.
    It can handle multiple studies and datasets, and provides options for customizing the display.
    The function can be run from the command line or imported as a module.

    If a YAML file is provided, it will be used to create multiple studies.
    Otherwise, a single study will be created using the provided parameters.

    Example YAML file::

    .. code-block:: yaml
        \b
        schism_studies:
            - label: Study1
            base_dir: "study1_directory"
            flux_xsect_file: "study1_flow_station_xsects.yaml"
            station_in_file: "study1_station.in"
            output_dir: "outputs"
            param_nml_file: "param.nml"
            flux_out: "study1_flux.out"
            reftime: "2020-01-01"
            - label: Study2
            base_dir: "study2_directory"
        datastore:
            repo_dir: /repo/continuous/screened
            inventory_file: "inventory_datasets.csv"
    """
    if yaml_file:
        # Load the YAML file and create multiple studies
        with open(yaml_file, "r") as file:
            yaml_data = yaml.safe_load(file)
        # get the base directory of the yaml file
        yaml_file_base_dir = pathlib.Path(yaml_file).parent
        studies = []
        for study_config in yaml_data.get("schism_studies", []):
            study_config["base_dir"] = utils.interpret_file_relative_to(yaml_file_base_dir, study_config["base_dir"])
            studies.append(
                schismstudy.SchismStudy(
                    study_name=study_config["label"],
                    base_dir=study_config["base_dir"],
                    output_dir=study_config.get("output_dir", "outputs"),
                    param_nml_file=study_config.get("param_nml_file", "param.nml"),
                    flux_xsect_file=study_config.get(
                        "flux_xsect_file", "flow_station_xsects.yaml"
                    ),
                    station_in_file=study_config.get("station_in_file", "station.in"),
                    flux_out=study_config.get("flux_out", "flux.out"),
                    reftime=reftime,
                    **study_config.get("additional_parameters", {}),
                )
            )

        datastore_config = yaml_data.get("datastore", {})
        repo_dir = datastore_config.get("repo_dir", repo_dir)
        inventory_file = datastore_config.get("inventory_file", inventory_file)
    else:
        # Create a single study if no YAML file is provided
        studies = [
            schismstudy.SchismStudy(
                schism_dir,
                flux_xsect_file=flux_xsect_file,
                station_in_file=station_in_file,
                flux_out=flux_out,
                reftime=reftime,
            )
        ]

    # study.reftime to study.endtime is the range of a single study
    # Initialize the union range
    union_start = min(study.reftime for study in studies)
    union_end = max(study.endtime for study in studies)

    # Create the union range as a single variable
    time_range = (union_start, union_end)

    # Create the datastore only when the inventory file actually exists
    ds = None
    if pathlib.Path(inventory_file).exists():
        ds = datastore.StationDatastore(repo_dir=repo_dir, inventory_file=inventory_file)
    else:
        logger.info("No datastore inventory file found (%s); running without observation datastore.", inventory_file)

    # Launch the session-aware UI
    def build_manager():
        return SchismOutputUIDataManager(
            *studies,
            datastore=ds,
            time_range=time_range,
        )

    serve_session_app(build_manager, title="Schism Output UI", crs=ccrs.UTM(10), port=port)
