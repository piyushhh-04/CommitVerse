import commitverse_core


def test_package_version():
    assert commitverse_core.__version__ == "0.1.0"


def test_package_import():
    assert commitverse_core is not None