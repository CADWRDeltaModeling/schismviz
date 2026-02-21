from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("schismviz")
except PackageNotFoundError:
    __version__ = "0+unknown"

