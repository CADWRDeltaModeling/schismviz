# schismviz — Agent Instructions

## Scope

Use this file when working in the `schismviz/` workspace root.

## Purpose

`schismviz` provides interactive Panel + HoloViews visualizations and CLI tools for
[SCHISM](https://ccrm.vims.edu/schismweb/) coastal hydrodynamic model outputs, calibration
metrics, and observation data. It builds on **dvue** (sibling package) for catalog/manager/action
patterns.

## Fast Start For Agents

```bash
pip install -e ".[dev]"   # development install
pytest                     # run all tests
pytest -m serial           # run only serial tests (avoids race conditions)
schismviz --help           # CLI entry point
```

Run examples:
```bash
schismviz output --yaml-file examples/schism_slr_studies.yaml
schismviz calib examples/batch_metrics_itp2024.yaml
schismviz viz mesh-view --help
```

## Key Modules

| Module | Purpose |
|--------|---------|
| [schismviz/cli.py](schismviz/cli.py) | Click CLI router; entry point `schismviz` |
| [schismviz/schismui.py](schismviz/schismui.py) | `SchismDataUIManager`; extends `dvue.tsdataui.TimeSeriesDataUIManager` |
| [schismviz/schismstudy.py](schismviz/schismstudy.py) | `SchismStudy`; reads SCHISM netCDF/station/flux outputs; unit conversion |
| [schismviz/datastore.py](schismviz/datastore.py) | `StationDatastore`; reads observation time series from DMS datastore via CSV inventory |
| [schismviz/viz_cli.py](schismviz/viz_cli.py) | `schismviz viz` sub-commands (mesh, elevation, velocity, stations) |
| [schismviz/suxarray.py](schismviz/suxarray.py) | `UxDataset` wrapper for unstructured-mesh xarray + PyVista 3D rendering |
| [schismviz/calibplot.py](schismviz/calibplot.py) | Low-level calibration scatter/KDE/time-series plot generation |
| [schismviz/schismcalibplotui.py](schismviz/schismcalibplotui.py) | Calibration UI; extends `dvue.dataui.DataUI` |

## Architecture

Data flow: **CLI/YAML → UIManager → Catalog → Actions → Panel dashboard**

- dvue framework provides base classes for managers, catalogs, and actions
- SCHISM outputs read via xarray/netCDF4 and `schimpy`
- Observation data via DMS datastore (CSV inventory + disk cache)
- Panel for dashboards; HoloViews/Bokeh for plots

## CLI Pattern

All `viz` sub-commands support YAML config with CLI overrides:
- YAML sections use underscores; CLI flags use hyphens
- `--config` / `-c` accepts a YAML file; CLI args override YAML values
- See [examples/viz_config_example.yaml](examples/viz_config_example.yaml) for reference

## Conventions

- UI manager classes: `*UI`, `*UIManager`, `*DataUIManager` (subclass dvue base classes)
- Data classes use `param.Parameterized`
- Logger per module: `logger = logging.getLogger(__name__)`
- Flake8: max-line-length=100; see [setup.cfg](setup.cfg)
- CRS hardcoded to EPSG:32610 (UTM Zone 10 N) for spatial data
- Observation inventory CSV columns: `station_id`, `subloc`, `name`, `unit`, `param`, `filename`, `lat`, `lon`, `x`, `y`

## Pitfalls

- When extending with mixed catalogs (raw + math references), guard against NaN in the
  **`source` column** (not `filename`) — see `dvue/AGENTS.md` for the safe pattern.
  `SchismDataUIManager.get_data_reference()` already does this correctly.
- HoloViews has issues with dots in dataset dimension names; see workaround in [calibplot.py](schismviz/calibplot.py).
- `schout_reader.py` is pre-xarray; avoid extending it — use xarray-based paths instead.
- Spatial operations assume UTM Zone 10 N (EPSG:32610); do not add CRS auto-detection without testing.

## SchismDataUIManager — Catalog Pattern

`SchismDataUIManager` uses **dvue Pattern A** (live `DataCatalog`) with:

```python
catalog = DataCatalog(primary_key=["source_num", "id", "variable"], crs=crs)
```

- Multi-source by design — each SCHISM study output directory is a separate `source`.
- The observation datastore uses `source="datastore"`.
- `source_num` is auto-assigned in the order studies are passed to the constructor.
- Refs are added with an **explicit `name`** (`f"{source}::{id}/{variable}"`) to preserve
  human-readable study-path identity; auto-derivation is skipped when `name` is set.
- `_build_dvue_catalog()` is called after `super().__init__()` once the reader is ready.
- Do **not** pass `url_column`, `url_num_column`, or `identity_key_columns` to `super().__init__()` —
  these parameters no longer exist in dvue.

## Docs & References

- [README.md](README.md) — overview and quick-start
- [README-cli.md](README-cli.md) — `schismviz output` and `schismviz calib` reference
- [README-viz.md](README-viz.md) — `schismviz viz` reference
- [examples/](examples/) — YAML configurations
- [notebooks/](notebooks/) — Panel interactive dashboards (00–09)
- Full docs: https://cadwrdeltamodeling.github.io/schismviz/html/index.html

## Downstream Integration

- Uses **dvue** for catalog/UI patterns — read `dvue/AGENTS.md` before changing manager or catalog behavior.
- Observation data from **dms_datastore** package; do not add datastore logic inside schismviz.
