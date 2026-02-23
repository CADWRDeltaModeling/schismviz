#!/usr/bin/env bash
# =============================================================================
# schismviz viz – CLI equivalents for the m1_hello_schism notebook examples
#
# Run from the examples directory after activating the conda environment:
#
#   conda activate schismviz
#   cd /path/to/schismviz/examples
#   bash run_viz_examples.sh
#
# Each command launches an interactive Panel dashboard in a browser tab.
# Press Ctrl+C to stop the server before running the next command.
#
# Alternatively, use the YAML config file for any command:
#   schismviz viz <command> -c helloschism_viz_config.yaml
# =============================================================================

set -euo pipefail

TESTDATA="./m1_hello_schism"

# ---------------------------------------------------------------------------
# 08_view_mesh_fast.ipynb  →  schismviz viz mesh-view
# ---------------------------------------------------------------------------
echo "==> mesh-view (notebook 08_view_mesh_fast)"
schismviz viz mesh-view \
    --hgrid "${TESTDATA}/hgrid.gr3"

# ---------------------------------------------------------------------------
# 01_water_surface_elevation_animation.ipynb  →  schismviz viz elevation
# ---------------------------------------------------------------------------
echo "==> elevation (notebook 01_water_surface_elevation_animation)"
schismviz viz elevation \
    --hgrid "${TESTDATA}/hgrid.gr3" \
    --out2d-pattern "${TESTDATA}/outputs/out2d_*.nc"

# ---------------------------------------------------------------------------
# 02_salinity_animation.ipynb  →  schismviz viz var-animation --varname salinity
# ---------------------------------------------------------------------------
echo "==> var-animation salinity (notebook 02_salinity_animation)"
schismviz viz var-animation \
    --hgrid "${TESTDATA}/hgrid.gr3" \
    --var-pattern "${TESTDATA}/outputs/salinity_*.nc" \
    --varname salinity

# ---------------------------------------------------------------------------
# temperature (same notebook pattern, different variable)
# ---------------------------------------------------------------------------
echo "==> var-animation temperature"
schismviz viz var-animation \
    --hgrid "${TESTDATA}/hgrid.gr3" \
    --var-pattern "${TESTDATA}/outputs/temperature_*.nc" \
    --varname temperature

# ---------------------------------------------------------------------------
# 03_velocity_vectors.ipynb  →  schismviz viz velocity
# ---------------------------------------------------------------------------
echo "==> velocity (notebook 03_velocity_vectors)"
schismviz viz velocity \
    --out2d-pattern "${TESTDATA}/outputs/out2d_*.nc"

# ---------------------------------------------------------------------------
# 04_salinity_and_velocity_animation.ipynb  →  schismviz viz var-velocity
# ---------------------------------------------------------------------------
echo "==> var-velocity (notebook 04_salinity_and_velocity_animation)"
schismviz viz var-velocity \
    --hgrid "${TESTDATA}/hgrid.gr3" \
    --out2d-pattern "${TESTDATA}/outputs/out2d_*.nc" \
    --var-pattern "${TESTDATA}/outputs/salinity_*.nc" \
    --varname salinity

# ---------------------------------------------------------------------------
# 05_salinity_and_velocity_per_level_animation.ipynb  →  schismviz viz var-velocity-level
# ---------------------------------------------------------------------------
echo "==> var-velocity-level (notebook 05_salinity_and_velocity_per_level_animation)"
schismviz viz var-velocity-level \
    --hgrid "${TESTDATA}/hgrid.gr3" \
    --out2d-pattern "${TESTDATA}/outputs/out2d_*.nc" \
    --velx-pattern "${TESTDATA}/outputs/horizontalVelX_*.nc" \
    --vely-pattern "${TESTDATA}/outputs/horizontalVelY_*.nc" \
    --var-pattern "${TESTDATA}/outputs/salinity_*.nc" \
    --varname salinity

# ---------------------------------------------------------------------------
# 09_stations_map.ipynb  →  schismviz viz stations
# param.nml: start_year=2000, start_month=1, start_day=1  →  reftime=2000-01-01
# ---------------------------------------------------------------------------
echo "==> stations (notebook 09_stations_map)"
schismviz viz stations \
    --hgrid "${TESTDATA}/hgrid.gr3" \
    --station-in "${TESTDATA}/station.in" \
    --staout-prefix "${TESTDATA}/outputs/staout_" \
    --reftime 2000-01-01

# ---------------------------------------------------------------------------
# schismviz output  – interactive time-series / station comparison UI
#
# Option A: fully specified on the command line (single study, no datastore)
# ---------------------------------------------------------------------------
echo "==> output (CLI flags, single study)"
schismviz output \
    --schism_dir "${TESTDATA}" \
    --flux_xsect_file "${TESTDATA}/flowlines.yaml" \
    --station_in_file "${TESTDATA}/station.in" \
    --flux_out "${TESTDATA}/outputs/flux.out" \
    --reftime 2000-01-01

# ---------------------------------------------------------------------------
# Option B: YAML config file (preferred – supports multiple studies and an
# optional screened datastore for observation comparison)
# ---------------------------------------------------------------------------
echo "==> output (YAML config)"
schismviz output --yaml-file ./helloschism_output_config.yaml
