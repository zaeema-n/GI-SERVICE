"""Root logger → stdout so INFO reaches Choreo Runtime Logs."""

from __future__ import annotations

import logging
import sys


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
        force=True,
    )


setup_logging()
