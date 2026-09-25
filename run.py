#!/usr/bin/env python3
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dictdigger.main import EXIT_FAILED, main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nGoodbye!", file=sys.stderr)
        sys.exit(130)
    except EOFError:
        print("\nInput ended unexpectedly; exiting.", file=sys.stderr)
        sys.exit(EXIT_FAILED)
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(141)
