# schismviz CLI Reference

This document describes the command-line options available in `schismviz`, based on running the CLI help commands.

## Commands run

```bash
schismviz --help
schismviz output --help
schismviz calib --help
```

## Top-level command

```text
Usage: schismviz [OPTIONS] COMMAND [ARGS]...

  schismviz - SCHISM visualization tools.

Options:
  -v, --version  Show the version and exit.
  -h, --help     Show this message and exit.

Commands:
  calib   config_file: str yaml file containing configuration
  output  Shows Data UI for SCHISM output files.
```

## `schismviz output`

```text
Usage: schismviz output [OPTIONS]

Options:
  --schism_dir TEXT       Path to the schism study directory
  --repo_dir TEXT         Path to the screened data directory
  --inventory_file TEXT   Path to the inventory file
  --flux_xsect_file TEXT  Path to the flux cross section file
  --station_in_file TEXT  Path to the station.in file
  --flux_out TEXT         Path to the flux.out file
  --reftime TEXT          Reference time
  --yaml-file TEXT        Path to the yaml file
  -h, --help              Show this message and exit.
```

### Typical usage with a YAML config file

Use your study YAML file to configure multiple SCHISM studies and datastore settings:

```bash
schismviz output --yaml-file examples/schism_slr_studies.yaml
```

If needed, you can still override datastore paths from the CLI:

```bash
schismviz output \
  --yaml-file examples/schism_slr_studies.yaml 
```

### YAML structure for `--yaml-file`

The YAML should contain:

- `schism_studies`: list of study definitions.
- `datastore`: optional datastore config used by the UI.

Example based on `examples/schism_slr_studies.yaml`:

```yaml
schism_studies:
  - label: "7.5"
    base_dir: "simulations/set1_0075_clinic"
    flux_xsect_file: "fluxflag.prop"
    station_in_file: "station.in"
    output_dir: "outputs"
    param_nml_file: "param.nml.clinic"
    flux_out: "flux.out"
    reftime: "2020-01-01"

  - label: "15"
    base_dir: "simulations/set1_0150_clinic"
    flux_xsect_file: "fluxflag.prop"
    station_in_file: "station.in"
    output_dir: "outputs"
    param_nml_file: "param.nml.clinic"
    flux_out: "flux.out"
    reftime: "2020-01-01"

datastore:
  repo_dir: /scratch/nasbdo/modeling_data/repo/continuous/screened
  inventory_file: /scratch/nasbdo/modeling_data/repo/continuous/inventory_datasets_screened_20260121.csv
```

### Notes

- `base_dir` entries are interpreted relative to the YAML file location when they are relative paths.
- When `--yaml-file` is provided, it is used to create multiple studies for comparison in the output UI.

## `schismviz calib`

```text
Usage: schismviz calib [OPTIONS] CONFIG_FILE

Options:
  --base_dir TEXT                 Base directory for config file
  --variable [flow|elev|salt|temp|ssc]
                                  Override variable from config (flow,
                                  elev, salt, temp, ssc)
  --selected-station TEXT         Station ID to include. Repeat option
                                  for multiple stations.
  --start-inst TEXT               Override start_inst date/time
  --end-inst TEXT                 Override end_inst date/time
  --start-avg TEXT                Override start_avg date/time
  --end-avg TEXT                  Override end_avg date/time
  --dry-run                       Validate config and print resolved
                                  settings without launching the UI
  -h, --help                      Show this message and exit.
```

### Typical usage

```bash
schismviz calib path/to/calibration_config.yaml
schismviz calib path/to/calibration_config.yaml --base_dir /path/to/studies
```

### Batch-metrics style YAML example

Using `examples/batch_metrics_itp2024.yaml`:

```bash
# Validate and print resolved config without opening the UI
schismviz calib examples/batch_metrics_itp2024.yaml --dry-run

# Launch UI directly from the batch config
schismviz calib examples/batch_metrics_itp2024.yaml

# Optional overrides from CLI
schismviz calib examples/batch_metrics_itp2024.yaml \
  --variable salt \
  --selected-station fmb \
  --selected-station mdm
```
