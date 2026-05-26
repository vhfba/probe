#!/usr/bin/env python3
"""
Wi-Fi Connectivity Plugin
Measures: gateway ping latency, packet loss, DNS resolution time,
          HTTP reachability, connected SSID, local IP.
Output: JSON to stdout (compatible with beacon plugin system)
"""

import json
import time
import socket
import subprocess
import struct
import os
import re


def get_connected_ssid():
    try:
        out = subprocess.check_output(
            ["iwgetid", "-r"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return out if out else "unknown"
    except Exception:
        return "unknown"


def get_local_ip(iface="wlan0"):
    try:
        out = subprocess.check_output(
            ["ip", "-4", "addr", "show", iface], stderr=subprocess.DEVNULL
        ).decode()
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        return match.group(1) if match else "unknown"
    except Exception:
        return "unknown"


def get_default_gateway():
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.strip().split()
                if parts[1] == "00000000":  # default route
                    gw_hex = parts[2]
                    gw_bytes = bytes.fromhex(gw_hex)[::-1]  # little-endian
                    return socket.inet_ntoa(gw_bytes)
    except Exception:
        pass
    return None


def ping(host, count=5):
    """
    Returns (avg_latency_ms, packet_loss_percent) using system ping.
    """
    try:
        out = subprocess.check_output(
            ["ping", "-c", str(count), "-W", "2", host],
            stderr=subprocess.DEVNULL
        ).decode()

        # Parse packet loss
        loss_match = re.search(r"(\d+)% packet loss", out)
        loss = float(loss_match.group(1)) if loss_match else 100.0

        # Parse avg rtt
        rtt_match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", out)
        avg_ms = float(rtt_match.group(1)) if rtt_match else -1.0

        return avg_ms, loss

    except subprocess.CalledProcessError:
        # ping returns non-zero on 100% loss
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


def http_reachable(url="http://connectivitycheck.gstatic.com/generate_204"):
    """
    Returns (reachable: bool, latency_ms: float).
    Uses a lightweight HTTP/1.0 raw socket request to avoid dependencies.
    """
    try:
        parsed_host = url.split("//")[1].split("/")[0]
        path = "/" + "/".join(url.split("//")[1].split("/")[1:])
        port = 443 if url.startswith("https") else 80

        start = time.perf_counter()
        with socket.create_connection((parsed_host, port), timeout=5) as s:
            request = f"GET {path} HTTP/1.0\r\nHost: {parsed_host}\r\n\r\n"
            s.sendall(request.encode())
            response = s.recv(64).decode(errors="ignore")
        elapsed = (time.perf_counter() - start) * 1000

        # 204 No Content or 200 OK both indicate reachability
        reachable = "204" in response or "200" in response
        return reachable, round(elapsed, 2)

    except Exception:
        return False, -1.0


def main():
    iface = os.environ.get("BEACON_WIFI_IFACE", "wlan0")

    ssid = get_connected_ssid()
    local_ip = get_local_ip(iface)
    gateway = get_default_gateway()

    # Gateway ping
    gw_latency_ms = -1.0
    gw_packet_loss = 100.0
    if gateway:
        gw_latency_ms, gw_packet_loss = ping(gateway, count=5)

    # DNS
    dns_latency_ms = dns_resolution_time("google.com")
    dns_ok = 1 if dns_latency_ms >= 0 else 0

    # HTTP reachability
    http_ok, http_latency_ms = http_reachable()

    output = {
        "metrics": [
            {
                "name": "beacon_wifi_gateway_latency_ms",
                "kind": "gauge",
                "value": gw_latency_ms,
                "labels": {"ssid": ssid, "gateway": gateway or "unknown", "iface": iface}
            },
            {
                "name": "beacon_wifi_gateway_packet_loss_percent",
                "kind": "gauge",
                "value": gw_packet_loss,
                "labels": {"ssid": ssid, "gateway": gateway or "unknown", "iface": iface}
            },
            {
                "name": "beacon_wifi_dns_latency_ms",
                "kind": "gauge",
                "value": dns_latency_ms,
                "labels": {"ssid": ssid, "resolver": "system", "iface": iface}
            },
            {
                "name": "beacon_wifi_dns_reachable",
                "kind": "gauge",
                "value": dns_ok,
                "labels": {"ssid": ssid, "iface": iface}
            },
            {
                "name": "beacon_wifi_http_reachable",
                "kind": "gauge",
                "value": 1 if http_ok else 0,
                "labels": {"ssid": ssid, "iface": iface}
            },
            {
                "name": "beacon_wifi_http_latency_ms",
                "kind": "gauge",
                "value": http_latency_ms,
                "labels": {"ssid": ssid, "iface": iface}
            },
            {
                "name": "beacon_wifi_connected",
                "kind": "gauge",
                "value": 1 if ssid != "unknown" else 0,
                "labels": {"ssid": ssid, "ip": local_ip, "iface": iface}
            },
        ]
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
