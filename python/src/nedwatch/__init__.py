"""Ned Watch for Python: know when your agent silently stops.

    from nedwatch import Ned
    ned = Ned()

    @ned.deadman("nightly-sync", every="1h")
    def sync(): ...

Docs: https://ned.watch/integrations/python
"""
__version__ = "0.1.0"

from .client import Deadman, Ned, NedConfigError, NedError, Overrun, Run  # noqa: E402
from .detect import default_name, detect_framework  # noqa: E402
from .verify import verify_signature  # noqa: E402

__all__ = ["Ned", "Deadman", "Overrun", "Run", "NedError", "NedConfigError", "verify_signature",
           "detect_framework", "default_name", "__version__"]
