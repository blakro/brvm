"""Point d'entrée de `python -m brvm`."""

import sys

from .cli import main

sys.exit(main())
