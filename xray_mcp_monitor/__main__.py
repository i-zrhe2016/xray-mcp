import sys

from .cli import main as cli_main
from .server import main as server_main
from .webapp import main as web_main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        raise SystemExit(cli_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "web":
        raise SystemExit(web_main(sys.argv[2:]))
    server_main()
