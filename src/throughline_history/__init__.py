"""throughline-history: how a throughline graph came to be, read from git, and how
independent signings of the same items compare with what was kept."""
from importlib.metadata import PackageNotFoundError, version as _version

from .compare import compare
from .derive import EVENT_KINDS, SCHEMA_VERSION, Commit, History, derive, item_uid, summarise, under

try:
    __version__ = _version("throughline-history")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0.0.0"

__all__ = ["Commit", "History", "derive", "summarise", "compare", "under", "item_uid",
           "EVENT_KINDS", "SCHEMA_VERSION", "__version__"]
