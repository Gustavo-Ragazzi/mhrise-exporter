"""Entry point for the windowed executable (MHRiseExporter.exe)."""

import sys

if len(sys.argv) > 1:
    from mhrise_exporter.cli import main

    sys.exit(main())

from mhrise_exporter.gui import main

main()
