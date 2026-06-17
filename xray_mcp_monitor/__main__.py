import sys

from .cli import main as cli_main
from .server import main as server_main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        raise SystemExit(cli_main(sys.argv[2:]))
    server_main()
