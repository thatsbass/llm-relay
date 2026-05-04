# Compatibility shim for pip < 22 editable installs (pip install -e .)
# All real configuration lives in pyproject.toml.
from setuptools import setup
setup()
