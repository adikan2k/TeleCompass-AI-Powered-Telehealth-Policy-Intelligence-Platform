from importlib.metadata import version

import telecompass


def test_package_imports_with_installed_version() -> None:
    assert telecompass.__version__
    assert telecompass.__version__ == version("telecompass")
