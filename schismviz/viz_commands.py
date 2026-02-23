"""
Visualization functions extracted from SCHISM notebooks.

Each function builds and returns a Panel servable object that can be served
via ``pn.serve()`` or explored interactively in a notebook.

Notebooks mapped to functions
------------------------------
- 08_view_mesh_fast         -> :func:`mesh_view_panel`
- 01_water_surface_elev_3d  -> :func:`elevation_animation_panel`
- 02_salinity_animation     -> :func:`var_animation_panel`
- 03_velocity_vectors       -> :func:`velocity_vectors_panel`
- 04_salinity_velocity      -> :func:`var_velocity_panel`
- 05_salinity_velocity_lvl  -> :func:`var_velocity_level_panel`
- 09_stations_map           -> :func:`stations_map_panel`
"""
from __future__ import annotations

import warnings
from typing import Optional

import numpy as np
import pandas as pd
import xarray as xr

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _open_mfdataset(pattern: str) -> xr.Dataset:
    return xr.open_mfdataset(
        pattern,
        concat_dim="time",
        combine="nested",
        data_vars="minimal",
        coords="minimal",
        compat="override",
    )


def _read_mesh(hgrid: str):
    from schimpy import schism_mesh
    return schism_mesh.read_mesh(hgrid)


def _make_trimesh(smesh, varname: Optional[str] = None, values=None):
    """Build an hv.TriMesh from a schimpy mesh, optionally with a scalar field."""
    import holoviews as hv
    nodes = pd.DataFrame(smesh.nodes, columns=["x", "y", "z"])
    if varname is not None and values is not None:
        nodes[varname] = values
        pts = hv.Points(nodes, vdims=varname)
    else:
        pts = hv.Points(nodes)
    return hv.TriMesh((smesh.elems, pts))


def _mesh_raster(smesh, width: int = 800, height: int = 400):
    """Return a rasterized mesh overlay (edges + nodes)."""
    import holoviews as hv
    from holoviews import opts
    from holoviews.operation import datashader

    trimesh = hv.TriMesh((smesh.elems, smesh.nodes))
    img = datashader.rasterize(trimesh.edgepaths).opts(
        opts.Image(cmap=["darkblue"])
    ).opts(width=width, height=height)
    elems_only = datashader.spread(img)
    nodes_only = datashader.dynspread(
        datashader.rasterize(trimesh.nodes).opts(opts.Image(cmap=["blue"])),
        shape="circle",
        max_px=6,
    )
    return elems_only * nodes_only


# ---------------------------------------------------------------------------
# Public panel-building functions
# ---------------------------------------------------------------------------

def mesh_view_panel(hgrid: str, width: int = 800, height: int = 400,
                    title: str = "SCHISM Mesh View"):
    """
    Fast mesh rendering with edges and nodes.

    Based on: *08_view_mesh_fast.ipynb*

    Parameters
    ----------
    hgrid:
        Path to ``hgrid.gr3`` mesh file.
    width, height:
        Dimensions of the rendered plot in pixels.
    title:
        Dashboard title shown in the browser tab.

    Returns
    -------
    panel.Column
    """
    import holoviews as hv
    import panel as pn
    from holoviews import opts
    from holoviews.operation import datashader

    hv.extension("bokeh")

    grid = _read_mesh(hgrid)
    full_mesh = _mesh_raster(grid, width=width, height=height)

    # Also add 2-D projections (XY, XZ, YZ)
    grid_nodes = grid.nodes * [1, 1, -1]  # flip depth sign

    def _proj(slice_idx, xlabel, ylabel, proj_title):
        nodes_slice = grid_nodes[:, slice_idx]
        tm = hv.TriMesh((grid.elems, nodes_slice))
        img = datashader.rasterize(tm.edgepaths).opts(
            opts.Image(cmap=["darkblue"])
        ).opts(width=width // 2, height=height // 2)
        return datashader.spread(img).opts(
            title=proj_title, xlabel=xlabel, ylabel=ylabel
        )

    views = hv.Layout([
        _proj([0, 1], "x", "y", "Top view (XY)"),
        _proj([0, 2], "x", "depth", "Side view (XZ)"),
        _proj([1, 2], "y", "depth", "Front view (YZ)"),
    ]).cols(1).opts(shared_axes=False)

    return pn.Column(
        pn.pane.Markdown(f"# {title}"),
        pn.Row(full_mesh),
        pn.pane.Markdown("## 2-D Projections"),
        pn.Row(views),
    )


def elevation_animation_panel(hgrid: str, out2d_pattern: str,
                               title: str = "Water Surface Elevation",
                               width: int = 800, height: int = 800):
    """
    Interactive 3-D water-surface elevation animation (Plotly backend).

    Based on: *01_water_surface_elevation_animation.ipynb*

    Parameters
    ----------
    hgrid:
        Path to ``hgrid.gr3`` mesh file.
    out2d_pattern:
        Glob pattern for ``out2d_*.nc`` output files.
    width, height:
        Plot dimensions in pixels.
    title:
        Dashboard title.

    Returns
    -------
    panel.Column
    """
    import holoviews as hv
    import panel as pn
    from .plotly_ext import TriSurface

    hv.extension("plotly")

    ds = _open_mfdataset(out2d_pattern)
    smesh = _read_mesh(hgrid)

    dfelems = pd.DataFrame(smesh.elems, columns=[0, 1, 2])
    dfnodes = pd.DataFrame(smesh.nodes, columns=["x", "y", "z"])
    dfnodes["z"] = -dfnodes["z"]

    mesh_surface = TriSurface(dfnodes.copy(), simplices=dfelems.values).opts(
        plot_edges=False, cmap="gray"
    )

    dfsurface = dfnodes.copy()

    def show_combined(time=0):
        dfsurface["z"] = ds.elevation.values[time, :]
        water_surface = TriSurface(dfsurface, simplices=dfelems.values).opts(
            width=width, zlim=(-10, 2)
        )
        return (
            water_surface.opts(plot_edges=False, cmap="kbc", clim=(0, 2), colorbar=True)
            * mesh_surface
        )

    time_slider = pn.widgets.IntSlider(
        name="Time Index", start=0, end=len(ds.time) - 1
    )

    return pn.Column(
        pn.pane.Markdown(
            f"# {title}\n"
            "* Move the time slider to animate the water surface.\n"
            "* Use the mouse wheel to zoom; drag to rotate."
        ),
        time_slider,
        hv.DynamicMap(show_combined, streams={"time": time_slider}).opts(
            width=width, height=height
        ),
    )


def var_animation_panel(hgrid: str, var_pattern: str, varname: str = "salinity",
                         title: Optional[str] = None,
                         width: int = 600, height: int = 400):
    """
    Animate any node-based scalar variable with time and vertical-layer sliders.

    Based on: *02_salinity_animation.ipynb*

    Parameters
    ----------
    hgrid:
        Path to ``hgrid.gr3`` mesh file.
    var_pattern:
        Glob pattern for the variable nc files (e.g. ``salinity_*.nc``).
    varname:
        Name of the variable inside the nc files (e.g. ``"salinity"``).
    title:
        Dashboard title (defaults to ``"SCHISM: <varname>"``).
    width, height:
        Plot dimensions in pixels.

    Returns
    -------
    panel.Column
    """
    import datashader
    import holoviews as hv
    import panel as pn
    from holoviews import opts
    from holoviews.operation.datashader import rasterize

    hv.extension("bokeh")

    if title is None:
        title = f"SCHISM: {varname}"

    ds = _open_mfdataset(var_pattern)
    smesh = _read_mesh(hgrid)

    nodes = pd.DataFrame(smesh.nodes, columns=["x", "y", "z"])
    nodes[varname] = ds[varname].values[0, :, 0]

    trimesh = hv.TriMesh((smesh.elems, hv.Points(nodes, vdims=varname)))
    trimesh = trimesh.opts(
        opts.TriMesh(
            cmap="rainbow4",
            cnorm="eq_hist",
            colorbar=True,
            node_alpha=0,
            edge_alpha=0,
            edge_color=varname,
            filled=True,
            height=height,
            inspection_policy="edges",
            tools=["hover"],
            width=width,
        )
    )

    def update(time=0, depth=0):
        trimesh.nodes.data[varname] = ds[varname].values[time, :, depth]
        return rasterize(
            trimesh, precompute=False, dynamic=True,
            aggregator=datashader.mean(varname),
        ).opts(colorbar=True, cmap="rainbow4", width=width, tools=["hover"])

    time_slider = pn.widgets.DiscreteSlider(
        name="Time",
        options=dict(
            zip(ds.time.astype("str").values, range(len(ds.time)))
        ),
    )
    depth_slider = pn.widgets.Select(
        name="Vertical Layer",
        options=dict(
            zip(
                ds.nSCHISM_vgrid_layers.astype("str").values,
                range(len(ds.nSCHISM_vgrid_layers)),
            )
        ),
    )

    return pn.Column(
        pn.pane.Markdown(f"# {title}"),
        pn.Row(time_slider, depth_slider),
        pn.Row(pn.bind(update, time=time_slider, depth=depth_slider)),
    )


def velocity_vectors_panel(out2d_pattern: str,
                            title: str = "Velocity Vectors",
                            width: int = 600, height: int = 400):
    """
    Depth-averaged velocity vector field animation.

    Based on: *03_velocity_vectors.ipynb*

    Parameters
    ----------
    out2d_pattern:
        Glob pattern for ``out2d_*.nc`` files (must contain
        ``depthAverageVelX`` and ``depthAverageVelY``).
    title:
        Dashboard title.
    width, height:
        Plot dimensions in pixels.

    Returns
    -------
    panel.Row
    """
    import holoviews as hv
    import panel as pn
    from holoviews import dim, opts

    hv.extension("bokeh")

    ds = _open_mfdataset(out2d_pattern)
    vmag = np.sqrt(ds.depthAverageVelX ** 2 + ds.depthAverageVelY ** 2)
    vangle = np.arctan2(ds.depthAverageVelY, ds.depthAverageVelX)
    vel = xr.Dataset({"mag": vmag, "angle": vangle})

    def velocity_field(time=0, vector_size=1):
        data = vel.isel(time=time)
        vf = hv.VectorField(
            (
                vel.coords["SCHISM_hgrid_node_x"],
                vel.coords["SCHISM_hgrid_node_y"],
                data.angle,
                data.mag,
            )
        )
        vf = vf.opts(
            opts.VectorField(
                pivot="tip",
                color=dim("Magnitude"),
                magnitude=dim("Magnitude").norm() * 2000 * vector_size,
                rescale_lengths=False,
            )
        )
        return vf.opts(width=width)

    dmap = hv.DynamicMap(velocity_field, kdims=["time", "vector_size"]).opts(
        title=title
    )
    hv.output(widget_location="top")
    dmap = dmap.redim.range(time=(0, len(vel.time) - 1)).redim.values(
        vector_size=[0.25, 0.5, 0.75, 1, 2, 5, 10, 20]
    )

    return pn.Column(
        pn.pane.Markdown(f"# {title}"),
        pn.Row(dmap),
    )


def var_velocity_panel(hgrid: str, out2d_pattern: str, var_pattern: str,
                        varname: str = "salinity",
                        title: Optional[str] = None,
                        width: int = 1000, height: int = 500):
    """
    Scalar variable coloured mesh overlaid with depth-averaged velocity vectors.

    Based on: *04_salinity_and_velocity_animation.ipynb*

    Parameters
    ----------
    hgrid:
        Path to ``hgrid.gr3`` mesh file.
    out2d_pattern:
        Glob pattern for ``out2d_*.nc`` files.
    var_pattern:
        Glob pattern for the scalar variable files (e.g. ``salinity_*.nc``).
    varname:
        Name of the variable inside the nc files.
    title:
        Dashboard title.
    width, height:
        Plot dimensions in pixels.

    Returns
    -------
    panel.Column
    """
    import datashader
    import holoviews as hv
    import panel as pn
    from holoviews import dim, opts
    from holoviews.operation.datashader import rasterize

    hv.extension("bokeh")

    if title is None:
        title = f"SCHISM: {varname} + Depth-Averaged Velocity"

    dsv = _open_mfdataset(out2d_pattern)
    ds = _open_mfdataset(var_pattern)
    smesh = _read_mesh(hgrid)

    nodes = pd.DataFrame(smesh.nodes, columns=["x", "y", "z"])
    nodes[varname] = ds[varname].values[0, :, 0]

    trimesh = hv.TriMesh((smesh.elems, hv.Points(nodes, vdims=varname)))
    trimesh = trimesh.opts(
        opts.TriMesh(
            cmap="rainbow4",
            cnorm="eq_hist",
            colorbar=True,
            node_alpha=0,
            edge_alpha=0,
            edge_color=varname,
            filled=True,
            height=height,
            inspection_policy="edges",
            tools=["hover"],
            width=width,
        )
    )

    vmag = np.sqrt(dsv.depthAverageVelX ** 2 + dsv.depthAverageVelY ** 2)
    vangle = np.arctan2(dsv.depthAverageVelY, dsv.depthAverageVelX)
    vel = xr.Dataset({"mag": vmag, "angle": vangle})

    def velocity_field(time, vector_size=1):
        data = vel.isel(time=time)
        vf = hv.VectorField(
            (
                vel.coords["SCHISM_hgrid_node_x"],
                vel.coords["SCHISM_hgrid_node_y"],
                data.angle,
                data.mag,
            )
        )
        vf = vf.opts(
            opts.VectorField(
                pivot="tip",
                color=dim("Magnitude"),
                magnitude=dim("Magnitude").norm() * 2000 * vector_size,
                rescale_lengths=False,
            )
        )
        return vf.opts(width=width)

    def var_mesh(time, level):
        trimesh.nodes.data[varname] = ds[varname].isel(
            time=time, nSCHISM_vgrid_layers=level
        )
        return rasterize(
            trimesh, precompute=False, dynamic=False,
            aggregator=datashader.mean(varname),
        ).opts(colorbar=True, cmap="rainbow4", width=width, height=height, tools=["hover"])

    def update(time, level):
        return var_mesh(time, level) * velocity_field(time, 1)

    time_slider = pn.widgets.DiscreteSlider(
        name="Time",
        options=dict(zip(ds.time.astype("str").values, range(len(ds.time)))),
    )
    level_selector = pn.widgets.Select(
        name="Vertical Layer",
        options=dict(
            zip(
                ds.nSCHISM_vgrid_layers.astype("str").values,
                range(len(ds.nSCHISM_vgrid_layers)),
            )
        ),
    )

    return pn.Column(
        pn.pane.Markdown(f"# {title}"),
        pn.Row(time_slider, level_selector),
        pn.Row(
            hv.DynamicMap(
                update, streams={"time": time_slider, "level": level_selector}
            )
        ),
    )


def var_velocity_level_panel(hgrid: str, out2d_pattern: str,
                               velx_pattern: str, vely_pattern: str,
                               var_pattern: str, varname: str = "salinity",
                               title: Optional[str] = None,
                               width: int = 1000, height: int = 500):
    """
    Scalar variable coloured mesh overlaid with *per-level* velocity vectors.

    Uses the full 3-D horizontal velocity fields (``horizontalVelX`` /
    ``horizontalVelY``) instead of the depth-averaged 2-D vectors.

    Based on: *05_salinity_and_velocity_per_level_animation.ipynb*

    Parameters
    ----------
    hgrid:
        Path to ``hgrid.gr3`` mesh file.
    out2d_pattern:
        Glob pattern for ``out2d_*.nc`` files (used for node coordinates).
    velx_pattern:
        Glob pattern for ``horizontalVelX_*.nc`` files.
    vely_pattern:
        Glob pattern for ``horizontalVelY_*.nc`` files.
    var_pattern:
        Glob pattern for the scalar variable files (e.g. ``salinity_*.nc``).
    varname:
        Name of the variable inside the nc files.
    title:
        Dashboard title.
    width, height:
        Plot dimensions in pixels.

    Returns
    -------
    panel.Column
    """
    import datashader
    import holoviews as hv
    import panel as pn
    from holoviews import dim, opts
    from holoviews.operation.datashader import rasterize

    hv.extension("bokeh")

    if title is None:
        title = f"SCHISM: {varname} + Per-Level Velocity"

    outds = _open_mfdataset(out2d_pattern)
    dsvx = _open_mfdataset(velx_pattern)
    dsvy = _open_mfdataset(vely_pattern)
    ds = _open_mfdataset(var_pattern)
    smesh = _read_mesh(hgrid)

    nodes = pd.DataFrame(smesh.nodes, columns=["x", "y", "z"])
    nodes[varname] = ds[varname].values[0, :, 0]

    trimesh = hv.TriMesh((smesh.elems, hv.Points(nodes, vdims=varname)))
    trimesh = trimesh.opts(
        opts.TriMesh(
            cmap="rainbow4",
            cnorm="eq_hist",
            colorbar=True,
            node_alpha=0,
            edge_alpha=0,
            edge_color=varname,
            filled=True,
            height=height,
            inspection_policy="edges",
            tools=["hover"],
            width=width,
        )
    )

    vmag = np.sqrt(dsvx.horizontalVelX ** 2 + dsvy.horizontalVelY ** 2)
    vangle = np.arctan2(dsvy.horizontalVelY, dsvx.horizontalVelX)
    vel = xr.Dataset({"mag": vmag, "angle": vangle})

    def velocity_field(time, level, vector_size=1):
        data = vel.isel(time=time, nSCHISM_vgrid_layers=level)
        vf = hv.VectorField(
            (
                outds.coords["SCHISM_hgrid_node_x"],
                outds.coords["SCHISM_hgrid_node_y"],
                data.angle,
                data.mag,
            )
        )
        vf = vf.opts(
            opts.VectorField(
                pivot="tip",
                color=dim("Magnitude"),
                magnitude=dim("Magnitude").norm() * 2000 * vector_size,
                rescale_lengths=False,
            )
        )
        return vf.opts(width=width)

    def var_mesh(time, level):
        trimesh.nodes.data[varname] = ds[varname].isel(
            time=time, nSCHISM_vgrid_layers=level
        )
        return rasterize(
            trimesh, precompute=False, dynamic=False,
            aggregator=datashader.mean(varname),
        ).opts(colorbar=True, cmap="rainbow4", width=width, height=height, tools=["hover"])

    def update(time, level):
        return var_mesh(time, level) * velocity_field(time, level, 1)

    time_slider = pn.widgets.DiscreteSlider(
        name="Time",
        options=dict(zip(ds.time.astype("str").values, range(len(ds.time)))),
    )
    level_select = pn.widgets.Select(
        name="Vertical Layer",
        options=dict(
            zip(
                ds.nSCHISM_vgrid_layers.astype("str").values,
                range(len(ds.nSCHISM_vgrid_layers)),
            )
        ),
    )

    return pn.Column(
        pn.pane.Markdown(f"# {title}"),
        pn.Row(time_slider, level_select),
        pn.Row(
            hv.DynamicMap(
                update, streams={"time": time_slider, "level": level_select}
            )
        ),
    )


def stations_map_panel(hgrid: str, station_in: str, staout_prefix: str,
                        reftime: str = "2000-01-01",
                        title: str = "Station Output Display",
                        width: int = 800, height: int = 400):
    """
    Interactive stations map: click a station to display its time-series output.

    Based on: *09_stations_map.ipynb*

    Parameters
    ----------
    hgrid:
        Path to ``hgrid.gr3`` mesh file.
    station_in:
        Path to ``station.in`` file.
    staout_prefix:
        Path prefix for ``staout_N`` files (e.g.
        ``./outputs/staout_``).  The variable index (1-9) is appended
        automatically.
    reftime:
        Model reference time (ISO-8601 string, e.g. ``"2000-01-01"``).
    title:
        Dashboard title.
    width, height:
        Plot dimensions in pixels.

    Returns
    -------
    panel.Column
    """
    import holoviews as hv
    import hvplot.pandas  # noqa: F401 – registers hvplot accessor
    import panel as pn
    from holoviews import opts
    from holoviews.operation import datashader
    from schimpy import station

    hv.extension("bokeh")

    reftime_ts = pd.Timestamp(reftime)

    dfs = station.read_station_in(station_in)
    dfs = dfs.reset_index()

    grid = _read_mesh(hgrid)

    # --- mesh background ---
    trimesh_bg = hv.TriMesh((grid.elems, grid.nodes))
    img = datashader.rasterize(trimesh_bg.edgepaths).opts(
        opts.Image(cmap=["darkblue"])
    ).opts(width=width, height=height)
    elems_only = datashader.spread(img)

    # --- station points ---
    selectable_pts = hv.Points(
        dfs, kdims=["x", "y"], vdims=["z", "id", "subloc", "name"]
    ).opts(color="red", size=10, tools=["hover", "tap"])

    select_station = hv.streams.Selection1D(source=selectable_pts)
    vartype_widget = pn.widgets.Select(
        name="Variable Type", options=station.station_variables
    )

    # --- station time-series callback ---
    def show_station_data_for_index(index, vartype):
        if not index:
            return pn.pane.Str("Click on a red dot to display station output.")
        sdfs = dfs.iloc[index]
        ids = sdfs["id"].unique()

        plots = []
        for station_id in ids:
            try:
                station_index = station.station_variables.index(vartype)
                file_path = f"{staout_prefix}{station_index + 1}"
                df = station.read_staout(file_path, station_in, reftime_ts)
                df.index.name = "Time"
                cols = df.columns[df.columns.str.contains(station_id)]
                if len(cols) == 0:
                    plots.append(
                        pn.pane.Str(f"No data found for station {station_id!r}.")
                    )
                else:
                    plots.append(df[list(cols)].hvplot(title=f"{station_id} – {vartype}"))
            except Exception as exc:
                plots.append(pn.pane.Str(f"Error loading {station_id!r}: {exc}"))

        return pn.Column(*plots)

    return pn.Column(
        pn.pane.Markdown(
            f"# {title}\n"
            "Click on the red dots to display output at that station."
        ),
        elems_only.opts(alpha=0.2) * selectable_pts,
        vartype_widget,
        pn.Row(
            pn.bind(
                show_station_data_for_index,
                index=select_station.param.index,
                vartype=vartype_widget,
            )
        ),
    )
