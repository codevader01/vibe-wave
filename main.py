"""Launch VibeWave.

Kivy has to be configured before its window module loads. That happens when
``vibewave.app`` is imported, so this file stays free of Kivy imports.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# A windowed exe has no console. Kivy would wrap stderr and loop with a
# stream handler, so the frozen app logs to the file only.
if getattr(sys, "frozen", False):
    os.environ.setdefault("KIVY_NO_CONSOLELOG", "1")
    os.environ.setdefault("KIVY_LOG_MODE", "PYTHON")


def _logging() -> None:
    from vibewave.paths import log_path

    path = log_path()
    handlers = [logging.FileHandler(path, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


if __name__ == "__main__":
    _logging()
    from vibewave.app import main

    main()
