import click
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


main.add_command(schismui.show_schism_output_ui, name="output")
main.add_command(schismcalibplotui.schism_calib_plot_ui, name="calib")
main.add_command(viz, name="viz")
main.add_command(show_out2d_ui, name="out2d")


if __name__ == "__main__":
    import sys
    sys.exit(main())
