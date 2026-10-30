"""SSH to Cisco routers (CUBE) with netmiko, plus the pasted/CSV router list parser."""

import csv
import io
from dataclasses import dataclass

from .errors import UserError

SSH_DEVICE_TYPE = "cisco_ios"
SSH_PORT = 22
SSH_TIMEOUT = 15


class CubeError(UserError):
    pass


@dataclass
class Router:
    ip: str
    hostname: str

    @property
    def label(self) -> str:
        return f"{self.hostname} ({self.ip})"


def parse_routers(data: bytes) -> list[Router]:
    """Rows of router_ip,hostname (header row first). A missing hostname falls back to the IP."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
    if "router_ip" not in fields:
        raise CubeError("The router list needs a router_ip column (and a hostname column).")
    routers: list[Router] = []
    for row in reader:
        ip = (row.get(fields["router_ip"]) or "").strip()
        if not ip:
            continue
        host = (row.get(fields["hostname"]) or "").strip() if "hostname" in fields else ""
        routers.append(Router(ip, host or ip))
    return routers


def run_command(router: Router, username: str, password: str, command: str) -> str:
    """Connect, run one command, return its output. Errors become CubeError with a readable message."""
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

    params = {
        "device_type": SSH_DEVICE_TYPE, "host": router.ip, "username": username, "password": password,
        "port": SSH_PORT, "timeout": SSH_TIMEOUT,
    }
    try:
        with ConnectHandler(**params) as conn:
            return conn.send_command(command)
    except NetmikoAuthenticationException:
        raise CubeError(f"Authentication failed for {router.label}.")
    except NetmikoTimeoutException:
        raise CubeError(f"Connection to {router.label} timed out.")
    except Exception as e:
        raise CubeError(f"Could not connect to {router.label}: {e}")
