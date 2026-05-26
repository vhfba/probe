#!/usr/bin/env python3
"""
Wired/Ethernet Plugin
Measures: link state, IP address, gateway ping latency, packet loss, DNS latency.
Output: JSON to stdout (compatible with beacon plugin system)
"""

import json
import time
import socket
import subprocess
import re
import os


def get_link_state(iface):
    """Returns 1 if link is up, 0 if down."""
    try:
        with open(f"/sys/class/net/{iface}/operstate") as f:
            state = f.read().strip()
        return 1 if state == "up" else 0
    except Exception:
        return 0


def get_local_ip(iface):
    try:
        out = subprocess.check_output(
            ["ip", "-4", "addr", "show", iface], stderr=subprocess.DEVNULL
        ).decode()
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        return match.group(1) if match else "unknown"
    except Exception:
        return "unknown"


def get_link_speed_mbps(iface):
    """Read negotiated link speed from sysfs. Returns -1 if unavailable."""
    try:
        with open(f"/sys/class/net/{iface}/speed") as f:
            return int(f.read().strip())
    except Exception:
        return -1


def get_default_gateway_for_iface(iface):
    """Find gateway associated with this specific interface."""
    try:
        out = subprocess.check_output(
            ["ip", "route", "show", "dev", iface], stderr=subprocess.DEVNULL
        ).decode()
        match = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
        if match:
            return match.group(1)
        # Fall back: any route with a via
        match = re.search(r"via (\d+\.\d+\.\d+\.\d+)", out)
        return match.group(1) if match else None
    except Exception:
        return None


def get_default_gateway_global():
    """Fallback: read the default gateway from /proc/net/route."""
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.strip().split()
                if parts[1] == "00000000":
                    gw_hex = parts[2]
                    gw_bytes = bytes.fromhex(gw_hex)[::-1]
                    return socket.inet_ntoa(gw_bytes)
    except Exception:
        pass
    return None


def ping(host, count=5):
    """Returns (avg_latency_ms, packet_loss_percent)."""
    try:
        out = subprocess.check_output(
            ["ping", "-c", str(count), "-W", "2", host],
            stderr=subprocess.DEVNULL
        ).decode()

        loss_match = re.search(r"(\d+)% packet loss", out)
        loss = float(loss_match.group(1)) if loss_match else 100.0

        rtt_match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", out)
        avg_ms = float(rtt_match.group(1)) if rtt_match else -1.0

        return avg_ms, loss

    except subprocess.CalledProcessError:
        return -1.0, 100.0
    except Exception:
        return -1.0, 100.0


def dns_resolution_time(hostname="google.com"):
    """Returns DNS resolution time in ms, or -1 on failure."""
    try:
        start = time.perf_counter()
        socket.getaddrinfo(hostname, None)
        elapsed = (time.perf_counter() - start) * 1000
        return round(elapsed, 2)
    except Exception:
        return -1.0


def get_rx_tx_bytes(iface):
    """Read cumulative RX/TX bytes from sysfs."""
    try:
        with open(f"/sys/class/net/{iface}/statistics/rx_bytes") as f:
            rx = int(f.read().strip())
        with open(f"/sys/class/net/{iface}/statistics/tx_bytes") as f:
            tx = int(f.read().strip())
        return rx, tx
    except Exception:
        return 0, 0


def get_rx_tx_errors(iface):
    try:
        with open(f"/sys/class/net/{iface}/statistics/rx_errors") as f:
            rx_err = int(f.read().strip())
        with open(f"/sys/class/net/{iface}/statistics/tx_errors") as f:
            tx_err = int(f.read().strip())
        return rx_err, tx_err
    except Exception:
        return 0, 0


def main():
    iface = os.environ.get("BEACON_ETH_IFACE", "eth0")

    link_up = get_link_state(iface)
    local_ip = get_local_ip(iface)
    link_speed = get_link_speed_mbps(iface)
    rx_bytes, tx_bytes = get_rx_tx_bytes(iface)
    rx_errors, tx_errors = get_rx_tx_errors(iface)

    gateway = get_default_gateway_for_iface(iface) or get_default_gateway_global()

    gw_latency_ms = -1.0
    gw_packet_loss = 100.0
    if link_up and gateway:
        gw_latency_ms, gw_packet_loss = ping(gateway, count=5)

    dns_latency_ms = -1.0
    if link_up:
        dns_latency_ms = dns_resolution_time("google.com")

    output = {
        "metrics": [
            {
                "name": "beacon_eth_link_up",
                "kind": "gauge",
                "value": link_up,
                "labels": {"iface": iface, "ip": local_ip}
            },
            {
                "name": "beacon_eth_link_speed_mbps",
                "kind": "gauge",
                "value": link_speed,
                "labels": {"iface": iface}
            },
            {
                "name": "beacon_eth_gateway_latency_ms",
                "kind": "gauge",
                "value": gw_latency_ms,
                "labels": {"iface": iface, "gateway": gateway or "unknown"}
            },
            {
                "name": "beacon_eth_gateway_packet_loss_percent",
                "kind": "gauge",
                "value": gw_packet_loss,
                "labels": {"iface": iface, "gateway": gateway or "unknown"}
            },
            {
                "name": "beacon_eth_dns_latency_ms",
                "kind": "gauge",
                "value": dns_latency_ms,
                "labels": {"iface": iface}
            },
            {
                "name": "beacon_eth_rx_bytes_total",
                "kind": "counter",
                "value": rx_bytes,
                "labels": {"iface": iface}
            },
            {
                "name": "beacon_eth_tx_bytes_total",
                "kind": "counter",
                "value": tx_bytes,
                "labels": {"iface": iface}
            },
            {
                "name": "beacon_eth_rx_errors_total",
                "kind": "counter",
                "value": rx_errors,
                "labels": {"iface": iface}
            },
            {
                "name": "beacon_eth_tx_errors_total",
                "kind": "counter",
                "value": tx_errors,
                "labels": {"iface": iface}
            },
        ]
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
