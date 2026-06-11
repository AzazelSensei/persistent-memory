import importlib


def test_package_imports():
    mod = importlib.import_module("persistent_memory")
    assert mod is not None


def test_pydantic_and_yaml_available():
    import pydantic
    import yaml

    assert pydantic.VERSION.startswith("2.")
    assert hasattr(yaml, "safe_load")
