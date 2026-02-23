# schismviz examples – HelloSCHISM

This directory contains example configuration files and scripts for running
`schismviz` against the **HelloSCHISM** tutorial model.

## Getting the model data

The example files expect a subdirectory called `m1_hello_schism/` containing
the outputs of the HelloSCHISM tutorial run.  This directory is **not
included in the repository** — you need to run the model yourself first.

1. Follow the [HelloSCHISM](https://github.com/CADWRDeltaModeling/HelloSCHISM)
   instructions to set up and execute the `m1_hello_schism` scenario.
2. Copy or symlink the resulting `m1_hello_schism/` directory into
   `examples/` (i.e. alongside this README) so that the relative paths used
   by the example files resolve correctly.

After that step the layout should look like:

```
examples/
├── m1_hello_schism/          ← produced by HelloSCHISM (not in git)
│   ├── hgrid.gr3
│   ├── station.in
│   ├── param.nml
│   ├── flowlines.yaml
│   └── outputs/
│       ├── out2d_*.nc
│       ├── salinity_*.nc
│       ├── temperature_*.nc
│       ├── horizontalVelX_*.nc
│       ├── horizontalVelY_*.nc
│       ├── staout_1 … staout_9
│       └── flux.out
├── helloschism_viz_config.yaml
├── helloschism_output_config.yaml
├── helloschism_run_viz_examples.sh
└── helloschism_README.md     ← this file
```

## Files in this directory

| File | Description |
|------|-------------|
| `helloschism_viz_config.yaml` | YAML config for all `schismviz viz` sub-commands |
| `helloschism_output_config.yaml` | YAML config for `schismviz output` (station time-series UI) |
| `helloschism_run_viz_examples.sh` | Shell script with CLI examples for every visualisation command |

## Running the examples

```bash
conda activate schismviz
cd /path/to/schismviz/examples
```

### Visualisation commands (field / mesh plots)

```bash
# Run one command at a time — each opens a browser tab.
# Press Ctrl-C to stop a server before starting the next one.

# All settings from YAML (recommended)
schismviz viz mesh-view          -c helloschism_viz_config.yaml
schismviz viz elevation          -c helloschism_viz_config.yaml
schismviz viz var-animation      -c helloschism_viz_config.yaml
schismviz viz velocity           -c helloschism_viz_config.yaml
schismviz viz var-velocity       -c helloschism_viz_config.yaml
schismviz viz var-velocity-level -c helloschism_viz_config.yaml
schismviz viz stations           -c helloschism_viz_config.yaml
```

Or run all examples sequentially from the shell script:

```bash
bash helloschism_run_viz_examples.sh
```

### Station output UI

```bash
# Open the interactive time-series comparison dashboard
schismviz output --yaml-file helloschism_output_config.yaml
```

CLI-only (no YAML):

```bash
schismviz output \
    --schism_dir      ./m1_hello_schism \
    --flux_xsect_file ./m1_hello_schism/flowlines.yaml \
    --station_in_file ./m1_hello_schism/station.in \
    --flux_out        ./m1_hello_schism/outputs/flux.out \
    --reftime         2000-01-01
```
