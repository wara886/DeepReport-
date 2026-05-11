"""App layer exports."""

__all__ = ["run_pipeline", "run_real_data_pipeline"]

_EXPORTS = {
    "run_pipeline": ("src.app.pipeline", "run_pipeline"),
    "run_real_data_pipeline": ("src.app.stage11a_real_data_pipeline", "run_real_data_pipeline"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    module = __import__(module_name, fromlist=[attr_name])
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
