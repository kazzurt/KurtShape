"""Compatibility entry point for the isolated native regression suite."""
import sys

from run_native_tests import main

if __name__ == "__main__":
    sys.argv[1:1] = ["--suite", "native"]
    raise SystemExit(main())
