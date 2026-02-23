# schismviz viz — SCHISM Field & Mesh Visualisation CLI

The `schismviz viz` command group launches interactive [Panel](https://panel.holoviz.org/) /
[HoloViews](https://holoviews.org/) dashboards from SCHISM model output, directly from the
command line.  All commands open a browser tab showing a live, interactive plot served on
`localhost`.

---

## Table of contents

1. [Quick start](#quick-start)
2. [Configuration: YAML file + CLI overrides](#configuration-yaml-file--cli-overrides)
3. [Common options](#common-options)
4. [Commands](#commands)
   - [mesh-view](#mesh-view)
   - [elevation](#elevation)
   - [var-animation](#var-animation)
   - [velocity](#velocity)
   - [var-velocity](#var-velocity)
   - [var-velocity-level](#var-velocity-level)
   - [stations](#stations)
5. [YAML configuration reference](#yaml-configuration-reference)
6. [Using the functions in a notebook](#using-the-functions-in-a-notebook)

---

## Quick start

```bash
# Install (inside the schismviz conda environment)
pip install -e .

# See the top-level help
schismviz viz --help

# See help for a specific command
schismviz viz var-animation --help
```

Every command launches a Panel server (default port **5006**) and opens your browser
automatically.  Press **Ctrl-C** to stop the server.

---

## Configuration: YAML file + CLI overrides

All commands accept a YAML configuration file with `--config` / `-c`.  Every option in the
table below maps to a YAML key of the same name (underscores, not hyphens) inside a
section named after the command.

```
YAML section name          CLI command
─────────────────────────  ─────────────────────
mesh_view                  mesh-view
elevation_animation        elevation
var_animation              var-animation
velocity_vectors           velocity
var_velocity_animation     var-velocity
var_velocity_level_animation  var-velocity-level
stations_map               stations
```

An annotated template is provided at
[`examples/viz_config_example.yaml`](examples/viz_config_example.yaml).

### Override precedence

```
YAML file  <  CLI flag
```

CLI flags always win.  Omit a flag to keep the YAML default; omit both to use the
built-in default shown in [Common options](#common-options).

### Example workflow

```bash
# 1.  Copy and edit the template for your project
cp examples/viz_config_example.yaml my_project.yaml
$EDITOR my_project.yaml

# 2.  Launch with all settings from YAML
schismviz viz var-animation -c my_project.yaml

# 3.  Override just the port for a second simultaneous dashboard
schismviz viz velocity -c my_project.yaml --port 5099
```

---

## Common options

These options are available on every `viz` sub-command.

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | — | YAML configuration file |
| `--hgrid` | | path | — | Path to `hgrid.gr3` SCHISM mesh file |
| `--port` | | int | `5006` | Port for the Panel server |
| `--show / --no-show` | | flag | `--show` | Open a browser tab automatically |
| `--title` | | str | command-specific | Dashboard title shown in the browser tab |
| `--width` | | int | command-specific | Plot width in pixels |
| `--height` | | int | command-specific | Plot height in pixels |

---

## Commands

### mesh-view

Render the SCHISM unstructured mesh using fast
[datashader](https://datashader.org/) rasterisation.  The top panel shows the
full 2-D plan view (edges + nodes); three additional panels below show XY, XZ,
and YZ cross-section projections of the 3-D mesh.

**Notebook origin:** `notebooks/08_view_mesh_fast.ipynb`

```
schismviz viz mesh-view [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--hgrid` | required | Path to `hgrid.gr3` |
| `--width` | `800` | Plot width in pixels |
| `--height` | `400` | Plot height in pixels |
| `--title` | `"SCHISM Mesh View"` | Dashboard title |
| `--port` | `5006` | Server port |

**Examples**

```bash
# Minimal (all common options from the command line)
schismviz viz mesh-view --hgrid hgrid.gr3

# From YAML
schismviz viz mesh-view -c my_project.yaml

# YAML plus an override
schismviz viz mesh-view -c my_project.yaml --width 1200 --height 600
```

**YAML section**

```yaml
mesh_view:
  hgrid: ./hgrid.gr3
  width: 800
  height: 400
  title: "SCHISM Mesh View"
  port: 5006
```

---

### elevation

Interactive 3-D water-surface elevation animation using the **Plotly** backend.
Both the fixed bathymetry mesh and the time-varying water surface are rendered
as triangulated surfaces.  A time-index slider on the dashboard steps through
model time.

**Notebook origin:** `notebooks/01_water_surface_elevation_animation.ipynb`

```
schismviz viz elevation [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--hgrid` | required | Path to `hgrid.gr3` |
| `--out2d-pattern` | required | Glob for `out2d_*.nc` files (must contain `elevation`) |
| `--width` | `800` | Plot width in pixels |
| `--height` | `800` | Plot height in pixels |
| `--title` | `"Water Surface Elevation"` | Dashboard title |
| `--port` | `5006` | Server port |

**Examples**

```bash
schismviz viz elevation \
    --hgrid hgrid.gr3 \
    --out2d-pattern "outputs/out2d_*.nc"

schismviz viz elevation -c my_project.yaml --port 5007
```

**YAML section**

```yaml
elevation_animation:
  hgrid: ./hgrid.gr3
  out2d_pattern: "./outputs/out2d_*.nc"
  width: 800
  height: 800
  title: "Water Surface Elevation"
  port: 5007
```

---

### var-animation

Animate any node-based scalar variable (e.g. `salinity`, `temperature`) using
a colour-mapped triangulated mesh.  Two interactive widgets allow you to step
through **model time** and select the **vertical layer** independently.

**Notebook origin:** `notebooks/02_salinity_animation.ipynb`

```
schismviz viz var-animation [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--hgrid` | required | Path to `hgrid.gr3` |
| `--var-pattern` | required | Glob for the scalar variable nc files (e.g. `salinity_*.nc`) |
| `--varname` | `salinity` | Variable name inside the nc files |
| `--width` | `600` | Plot width in pixels |
| `--height` | `400` | Plot height in pixels |
| `--title` | `"SCHISM: <varname>"` | Dashboard title |
| `--port` | `5006` | Server port |

**Examples**

```bash
# Salinity
schismviz viz var-animation \
    --hgrid hgrid.gr3 \
    --var-pattern "outputs/salinity_*.nc" \
    --varname salinity

# Temperature
schismviz viz var-animation \
    --hgrid hgrid.gr3 \
    --var-pattern "outputs/temperature_*.nc" \
    --varname temperature \
    --title "Temperature"
```

**YAML section**

```yaml
var_animation:
  hgrid: ./hgrid.gr3
  var_pattern: "./outputs/salinity_*.nc"
  varname: salinity
  width: 600
  height: 400
  title: "Salinity"
  port: 5008
```

---

### velocity

Animate the **depth-averaged velocity vector field**.  Each arrow represents
the magnitude and direction of the depth-averaged horizontal velocity
(`depthAverageVelX` / `depthAverageVelY`) at a mesh node.  An interactive
scale selector lets you adjust arrow lengths at runtime.

**Notebook origin:** `notebooks/03_velocity_vectors.ipynb`

```
schismviz viz velocity [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--out2d-pattern` | required | Glob for `out2d_*.nc` files (must contain `depthAverageVelX` and `depthAverageVelY`) |
| `--width` | `600` | Plot width in pixels |
| `--height` | `400` | Plot height in pixels |
| `--title` | `"Depth-Averaged Velocity Vectors"` | Dashboard title |
| `--port` | `5006` | Server port |

**Examples**

```bash
schismviz viz velocity --out2d-pattern "outputs/out2d_*.nc"

schismviz viz velocity -c my_project.yaml --no-show   # headless / CI
```

**YAML section**

```yaml
velocity_vectors:
  out2d_pattern: "./outputs/out2d_*.nc"
  width: 600
  height: 400
  title: "Depth-Averaged Velocity Vectors"
  port: 5009
```

---

### var-velocity

Overlay a **scalar variable colour map** with **depth-averaged velocity
arrows** in a single dashboard.  Both model time and vertical layer are
controlled by interactive widgets.

**Notebook origin:** `notebooks/04_salinity_and_velocity_animation.ipynb`

```
schismviz viz var-velocity [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--hgrid` | required | Path to `hgrid.gr3` |
| `--out2d-pattern` | required | Glob for `out2d_*.nc` files |
| `--var-pattern` | required | Glob for the scalar variable nc files |
| `--varname` | `salinity` | Variable name inside the nc files |
| `--width` | `1000` | Plot width in pixels |
| `--height` | `500` | Plot height in pixels |
| `--title` | `"SCHISM: <varname> + Depth-Averaged Velocity"` | Dashboard title |
| `--port` | `5006` | Server port |

**Examples**

```bash
schismviz viz var-velocity \
    --hgrid hgrid.gr3 \
    --out2d-pattern "outputs/out2d_*.nc" \
    --var-pattern "outputs/salinity_*.nc" \
    --varname salinity
```

**YAML section**

```yaml
var_velocity_animation:
  hgrid: ./hgrid.gr3
  out2d_pattern: "./outputs/out2d_*.nc"
  var_pattern: "./outputs/salinity_*.nc"
  varname: salinity
  width: 1000
  height: 500
  title: "Salinity + Depth-Averaged Velocity"
  port: 5010
```

---

### var-velocity-level

Like [var-velocity](#var-velocity), but uses the **full 3-D horizontal
velocity fields** (`horizontalVelX` / `horizontalVelY`) instead of the
depth-averaged 2-D vectors.  The selected vertical layer applies to both the
scalar field and the velocity arrows simultaneously.

**Notebook origin:** `notebooks/05_salinity_and_velocity_per_level_animation.ipynb`

```
schismviz viz var-velocity-level [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--hgrid` | required | Path to `hgrid.gr3` |
| `--out2d-pattern` | required | Glob for `out2d_*.nc` files (used for node coordinates) |
| `--velx-pattern` | required | Glob for `horizontalVelX_*.nc` files |
| `--vely-pattern` | required | Glob for `horizontalVelY_*.nc` files |
| `--var-pattern` | required | Glob for the scalar variable nc files |
| `--varname` | `salinity` | Variable name inside the nc files |
| `--width` | `1000` | Plot width in pixels |
| `--height` | `500` | Plot height in pixels |
| `--title` | `"SCHISM: <varname> + Per-Level Velocity"` | Dashboard title |
| `--port` | `5006` | Server port |

**Examples**

```bash
schismviz viz var-velocity-level \
    --hgrid hgrid.gr3 \
    --out2d-pattern  "outputs/out2d_*.nc" \
    --velx-pattern   "outputs/horizontalVelX_*.nc" \
    --vely-pattern   "outputs/horizontalVelY_*.nc" \
    --var-pattern    "outputs/salinity_*.nc" \
    --varname salinity

# Same thing, port override only
schismviz viz var-velocity-level -c my_project.yaml --port 5011
```

**YAML section**

```yaml
var_velocity_level_animation:
  hgrid: ./hgrid.gr3
  out2d_pattern: "./outputs/out2d_*.nc"
  velx_pattern: "./outputs/horizontalVelX_*.nc"
  vely_pattern: "./outputs/horizontalVelY_*.nc"
  var_pattern: "./outputs/salinity_*.nc"
  varname: salinity
  width: 1000
  height: 500
  title: "Salinity + Per-Level Velocity"
  port: 5011
```

---

### stations

Interactive **stations map**.  The mesh is rendered in the background and each
station from `station.in` is shown as a red dot.  Clicking a dot displays the
time-series from the corresponding `staout_N` file for the variable type
selected in the widget dropdown.

**Notebook origin:** `notebooks/09_stations_map.ipynb`

```
schismviz viz stations [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--hgrid` | required | Path to `hgrid.gr3` |
| `--station-in` | required | Path to `station.in` |
| `--staout-prefix` | required | Path prefix for `staout_N` files — the numeric index (1–9) is appended automatically, e.g. `./outputs/staout_` |
| `--reftime` | `"2000-01-01"` | Model reference time (ISO-8601) used to build the time index |
| `--width` | `800` | Plot width in pixels |
| `--height` | `400` | Plot height in pixels |
| `--title` | `"Station Output Display"` | Dashboard title |
| `--port` | `5006` | Server port |

**Examples**

```bash
schismviz viz stations \
    --hgrid hgrid.gr3 \
    --station-in station.in \
    --staout-prefix outputs/staout_ \
    --reftime 2020-03-01

schismviz viz stations -c my_project.yaml
```

**YAML section**

```yaml
stations_map:
  hgrid: ./hgrid.gr3
  station_in: ./station.in
  staout_prefix: "./outputs/staout_"
  reftime: "2000-01-01"
  width: 800
  height: 400
  title: "Station Output Display"
  port: 5012
```

---

## YAML configuration reference

Below is the full annotated template.  A copy is provided at
[`examples/viz_config_example.yaml`](examples/viz_config_example.yaml).

```yaml
# Each top-level key corresponds to a viz sub-command.
# Only include sections relevant to commands you actually use.

mesh_view:
  hgrid: ./hgrid.gr3
  width: 800
  height: 400
  title: "SCHISM Mesh View"
  port: 5006

elevation_animation:
  hgrid: ./hgrid.gr3
  out2d_pattern: "./outputs/out2d_*.nc"
  width: 800
  height: 800
  title: "Water Surface Elevation"
  port: 5007

var_animation:
  hgrid: ./hgrid.gr3
  var_pattern: "./outputs/salinity_*.nc"
  varname: salinity
  width: 600
  height: 400
  title: "Salinity"
  port: 5008

velocity_vectors:
  out2d_pattern: "./outputs/out2d_*.nc"
  width: 600
  height: 400
  title: "Depth-Averaged Velocity Vectors"
  port: 5009

var_velocity_animation:
  hgrid: ./hgrid.gr3
  out2d_pattern: "./outputs/out2d_*.nc"
  var_pattern: "./outputs/salinity_*.nc"
  varname: salinity
  width: 1000
  height: 500
  title: "Salinity + Depth-Averaged Velocity"
  port: 5010

var_velocity_level_animation:
  hgrid: ./hgrid.gr3
  out2d_pattern: "./outputs/out2d_*.nc"
  velx_pattern: "./outputs/horizontalVelX_*.nc"
  vely_pattern: "./outputs/horizontalVelY_*.nc"
  var_pattern: "./outputs/salinity_*.nc"
  varname: salinity
  width: 1000
  height: 500
  title: "Salinity + Per-Level Velocity"
  port: 5011

stations_map:
  hgrid: ./hgrid.gr3
  station_in: ./station.in
  staout_prefix: "./outputs/staout_"
  reftime: "2000-01-01"
  width: 800
  height: 400
  title: "Station Output Display"
  port: 5012
```

---

## Using the functions in a notebook

Every command delegates to a pure function in
[`schismviz/viz_commands.py`](schismviz/viz_commands.py) that returns a
`panel.Column` / `panel.Row` object — exactly as if you were working in a
notebook.  You can import and use these functions directly:

```python
import panel as pn
pn.extension()

from schismviz.viz_commands import (
    mesh_view_panel,
    elevation_animation_panel,
    var_animation_panel,
    velocity_vectors_panel,
    var_velocity_panel,
    var_velocity_level_panel,
    stations_map_panel,
)

# display inline in a Jupyter notebook
mesh_view_panel("hgrid.gr3")
```

```python
# or serve as a standalone app
pn.serve(
    var_animation_panel(
        "hgrid.gr3",
        "outputs/salinity_*.nc",
        varname="salinity",
    ),
    title="Salinity",
    port=5008,
    show=True,
)
```

| Function | Required arguments | Optional arguments |
|---|---|---|
| `mesh_view_panel` | `hgrid` | `width`, `height`, `title` |
| `elevation_animation_panel` | `hgrid`, `out2d_pattern` | `title`, `width`, `height` |
| `var_animation_panel` | `hgrid`, `var_pattern` | `varname`, `title`, `width`, `height` |
| `velocity_vectors_panel` | `out2d_pattern` | `title`, `width`, `height` |
| `var_velocity_panel` | `hgrid`, `out2d_pattern`, `var_pattern` | `varname`, `title`, `width`, `height` |
| `var_velocity_level_panel` | `hgrid`, `out2d_pattern`, `velx_pattern`, `vely_pattern`, `var_pattern` | `varname`, `title`, `width`, `height` |
| `stations_map_panel` | `hgrid`, `station_in`, `staout_prefix` | `reftime`, `title`, `width`, `height` |
