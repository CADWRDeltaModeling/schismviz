from click.testing import CliRunner
from schismviz.cli import main


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"], prog_name="schismviz")
    assert result.exit_code == 0
    assert "schismviz" in result.output


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
