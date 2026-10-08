"""Ned Watch for Python: know when your agent silently stops.

    from nedwatch import Ned
    ned = Ned()

    @ned.deadman("nightly-sync", every="1h")
    def sync(): ...

Docs: https://ned.watch/integrations/python
"""
__version__ = "0.1.2"

from .client import Deadman, Ned, NedConfigError, NedError, Overrun, Run  # noqa: E402
from .detect import default_name, detect_framework  # noqa: E402
from .up import is_up, up_state  # noqa: E402
from .verify import verify_signature  # noqa: E402

__all__ = ["Ned", "Deadman", "Overrun", "Run", "NedError", "NedConfigError", "verify_signature", "is_up", "up_state",
           "detect_framework", "default_name", "__version__"]
