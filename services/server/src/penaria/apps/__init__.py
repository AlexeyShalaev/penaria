"""One package per process: each puts together its settings, DI container and entrypoints.

The apps only assemble what the features, modules and integrations provide, and do not import
each other. Run one with ``python -m penaria.apps.<name>``.
"""
