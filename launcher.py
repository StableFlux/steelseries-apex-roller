"""PyInstaller entry-point shim. The package's __main__ does the actual work."""
import sys

from apex_roller.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
