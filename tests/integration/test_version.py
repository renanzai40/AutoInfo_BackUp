import importlib.metadata

import autoinfo


def test_version_matches_installed_metadata():
    assert autoinfo.__version__ == importlib.metadata.version("autoinfo")


def test_version_single_source():
    from autoinfo import _version

    assert autoinfo.__version__ == _version.__version__
