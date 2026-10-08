"""Demo FTP server for Synapse: serves the sample datasets read-only.

Anonymous login and a named account are both allowed. Inside the Compose
network the nodes reach it as ``ftp:2121``.
"""

import logging
import os

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s ftp %(message)s")
    root = os.environ.get("FTP_ROOT", "/srv/ftp")
    authorizer = DummyAuthorizer()
    authorizer.add_anonymous(root, perm="elr")  # e=cd, l=list, r=retrieve: read-only
    authorizer.add_user(os.environ.get("FTP_USER", "synapse"), os.environ.get("FTP_PASSWORD", "synapse"), root, perm="elr")

    handler = FTPHandler
    handler.authorizer = authorizer
    handler.banner = "Synapse demo dataset server (read-only)"
    low, high = int(os.environ.get("FTP_PASV_MIN", 30000)), int(os.environ.get("FTP_PASV_MAX", 30009))
    handler.passive_ports = range(low, high + 1)
    if os.environ.get("FTP_MASQUERADE_ADDRESS"):
        handler.masquerade_address = os.environ["FTP_MASQUERADE_ADDRESS"]

    server = FTPServer(("0.0.0.0", int(os.environ.get("FTP_PORT", 2121))), handler)
    server.max_cons = 64
    server.max_cons_per_ip = 16
    server.serve_forever()


if __name__ == "__main__":
    main()
