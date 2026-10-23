"""pytest_homeassistant as an alias of tests, for a core release before it.

Written by release.sh's alias_pytest_homeassistant; never committed.
"""

import importlib
import importlib.abc
import importlib.util
import sys


class _TestsAlias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Import pytest_homeassistant.<name> as the module tests.<name>."""

    def find_spec(self, fullname, path, target=None):
        if fullname.startswith(f"{__name__}."):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        module = importlib.import_module(f"tests{spec.name[len(__name__) :]}")
        spec.loader_state = module.__spec__
        return module

    def exec_module(self, module):
        # The import system set the alias spec on the tests module; put back its own.
        module.__spec__ = module.__spec__.loader_state


sys.meta_path.insert(0, _TestsAlias())
