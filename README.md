# Visualization for SCHISM using Python

A collection of holoviews visualizations for SCHISM

Docs are at https://cadwrdeltamodeling.github.io/schismviz/html/index.html

CLI reference: [README-cli.md](README-cli.md)

Viz CLI reference: [README-viz.md](README-viz.md)

Quick start:
```bash
schismviz --help
schismviz output --yaml-file examples/schism_slr_studies.yaml
```

## Combine UI — dvue plugin integration

`schismviz` can load SCHISM output data into
[dvue](https://github.com/CADWRDeltaModeling/dvue)'s generic combine UI.
This lets you mix SCHISM study output with other registered data sources
(DSM2, CSV, etc.) in one session.

### `schismviz combine`

Launch the SCHISM-specific combine UI directly:

```bash
# One study directory per param.nml
schismviz combine study1/param.nml study2/param.nml

# Or use the same multi-study YAML config used by `schismviz output`
schismviz combine examples/schism_slr_studies.yaml

# Mixed: YAML config + additional study
schismviz combine examples/schism_slr_studies.yaml extra_study/param.nml
```

`time_range` is automatically inferred from the scanned studies' run
start/end times, so no extra configuration is needed.

### `dvue ui --plugin schismviz.readers`

Use dvue's generic combine UI when mixing SCHISM data with other source
types registered with `dvue`'s
[ReaderRegistry](https://github.com/CADWRDeltaModeling/dvue):

```bash
dvue ui --plugin schismviz.readers study1/param.nml study2/param.nml

# Combine SCHISM + DSM2 outputs in one UI
dvue ui --plugin schismviz.readers --plugin dsm2ui.dssui.dss_registry \
    study1/param.nml run_hydro.dss
```

Supported file types registered by `schismviz.readers`:

| Extension | Input | Notes |
|-----------|-------|-------|
| `.nml` | `param.nml` in a SCHISM study directory | Study name inferred from parent directory name; all default file names assumed (`station.in`, `outputs/`, etc.) |
| `.nml.clinic` | `param.nml.clinic` — baroclinic param file | Same handling as `.nml`; study name inferred from parent directory |
| `.nml.barotropic` | `param.nml.barotropic` — barotropic param file | Same handling as `.nml` |
| `.nml.tropic` | `param.nml.tropic` — tropic param file | Same handling as `.nml` |
| `.yaml` / `.yml` | Multi-study YAML config with `schism_studies` key | Same format as `schismviz output --yaml-file`; silently ignored if no `schism_studies` key |

### Python API

```python
from schismviz.readers import SchismRegistryUIManager

manager = SchismRegistryUIManager()
manager.add_source_files("study1/param.nml", "study2/param.nml")
# manager.time_range is automatically set from the studies
```


# Live examples
 0. [Mesh View 3D](https://schism.azurewebsites.net/00_mesh_view_3D)
 1. [Water Surface Elevation Animation](https://schism.azurewebsites.net/01_water_surface_elevation_animation)
 2. [Salinity Animation](https://schism.azurewebsites.net/02_salinity_animation)
 3. [Velocity Vectors](https://schism.azurewebsites.net/03_velocity_vectors)
 4. [Salinity And Velocity Animation](https://schism.azurewebsites.net/04_salinity_and_velocity_animation)
 5. [Salinity And Velocity Per Level Animation](https://schism.azurewebsites.net/05_salinity_and_velocity_per_level_animation)
 8. [View Mesh Fast](https://schism.azurewebsites.net/08_view_mesh_fast)
 9. [Stations Map](https://schism.azurewebsites.net/09_stations_map)
