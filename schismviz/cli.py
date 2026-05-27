import click
import cartopy.crs as ccrs
from schismviz import __version__
from schismviz import schismui, schismcalibplotui
from schismviz.viz_cli import viz
from schismviz.out2dui import show_out2d_ui


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(
    __version__, "-v", "--version", message="%(prog)s, version %(version)s"
)
def main():
    """schismviz - SCHISM visualization tools."""
    pass


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--port", default=0, help="Port to serve the UI on (0 = random available port)."
)
@click.argument("files", nargs=-1, type=click.Path())
def combine(files, port):
    """Launch the SCHISM combine UI backed by dvue's RegistryUIManager.

    FILES can be ``param.nml`` files (one per study directory) or a YAML
    config file with a ``schism_studies`` key.  Multiple sources of either
    kind may be mixed on the same command line.

    Examples::

        schismviz combine study1/param.nml study2/param.nml

        schismviz combine multi_study_config.yaml

        dvue ui --plugin schismviz.readers study1/param.nml

    The UI supports drag-and-drop of additional ``param.nml`` / YAML files
    at runtime to add more studies without restarting.
    """
    from schismviz.readers import SchismRegistryUIManager
    from schismviz.session import serve_session_app

    def build_manager():
        manager = SchismRegistryUIManager()
        if files:
            manager.add_source_files(*files)
        return manager

    serve_session_app(
        build_manager, title="SCHISM Combine UI", crs=ccrs.UTM(10), port=port
    )


main.add_command(schismui.show_schism_output_ui, name="output")
main.add_command(schismcalibplotui.schism_calib_plot_ui, name="calib")
main.add_command(viz, name="viz")
main.add_command(show_out2d_ui, name="out2d")
main.add_command(combine, name="combine")


if __name__ == "__main__":
    import sys
    sys.exit(main())
