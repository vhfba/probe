#!/usr/bin/env python3
"""
iPerf3 Test Plugin
Measures: TCP throughput (download + upload), UDP jitter, UDP packet loss.
Requires: iperf3 installed on the Pi (`sudo apt install iperf3`)
          and an iperf3 server running somewhere on the network.

Server address is read from:
  - BEACON_IPERF_HOST env var (set via probe config / action context)
  - stdin JSON context: {"iperf_host": "...", "iperf_port": 5201}

Output: JSON to stdout (compatible with beacon plugin system)
"""

import json
import os
import subprocess
import sys
import shutil


DEFAULT_HOST = os.environ.get("BEACON_IPERF_HOST", "")
DEFAULT_PORT = int(os.environ.get("BEACON_IPERF_PORT", "5201"))
DURATION_SECONDS = int(os.environ.get("BEACON_IPERF_DURATION", "5"))


def iperf3_available():
    return shutil.which("iperf3") is not None


def run_iperf3_tcp(host, port, duration, reverse=False):
    """
    Run an iperf3 TCP test.
    reverse=False → upload (client → server)
    reverse=True  → download (server → client)
    Returns parsed result dict or None on failure.
    """
    cmd = [
        "iperf3",
        "-c", host,
        "-p", str(port),
        "-t", str(duration),
        "-J",           # JSON output
        "--connect-timeout", "5000",
    ]
    if reverse:
        cmd.append("-R")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=duration + 15
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        return data

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def run_iperf3_udp(host, port, duration, bandwidth_mbps=10):
    """
    Run an iperf3 UDP test to measure jitter and packet loss.
    bandwidth_mbps: target send rate (keep low to avoid flooding).
    Returns parsed result dict or None on failure.
    """
    cmd = [
        "iperf3",
        "-c", host,
        "-p", str(port),
        "-t", str(duration),
        "-u",
        "-b", f"{bandwidth_mbps}M",
        "-J",
        "--connect-timeout", "5000",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=duration + 15
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        return data

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def extract_tcp_mbps(data):
    """Extract bits_per_second from iperf3 JSON result."""
    try:
        bps = data["end"]["sum_received"]["bits_per_second"]
        return round(bps / 1_000_000, 2)
    except (KeyError, TypeError):
        try:
            bps = data["end"]["sum_sent"]["bits_per_second"]
            return round(bps / 1_000_000, 2)
        except Exception:
            return -1.0


def extract_udp_stats(data):
    """Extract jitter_ms and lost_percent from iperf3 UDP JSON result."""
    try:
        end = data["end"]["sum"]
        jitter_ms = round(end.get("jitter_ms", -1.0), 3)
        lost_percent = round(end.get("lost_percent", -1.0), 2)
        packets_sent = end.get("packets", 0)
        packets_lost = end.get("lost_packets", 0)
        return jitter_ms, lost_percent, packets_sent, packets_lost
    except Exception:
        return -1.0, -1.0, 0, 0


def main():
    host = DEFAULT_HOST
    port = DEFAULT_PORT

    # Allow passing host directly as CLI argument for manual testing:
    #   python iperf_test.py 192.168.1.1
    #   python iperf_test.py 192.168.1.1 5201
    if len(sys.argv) >= 2:
        host = sys.argv[1]
    if len(sys.argv) >= 3:
        port = int(sys.argv[2])

    # Read context from stdin only when piped (agent usage).
    # Skips blocking wait when run interactively from a terminal.
    if not sys.stdin.isatty():
        try:
            ctx_raw = sys.stdin.read().strip()
            if ctx_raw:
                ctx = json.loads(ctx_raw)
                host = ctx.get("iperf_host", host) or host
                port = int(ctx.get("iperf_port", port) or port)
        except Exception:
            pass

    metrics = []

    if not iperf3_available():
        metrics.append({
            "name": "beacon_iperf_available",
            "kind": "gauge",
            "value": 0,
            "labels": {"reason": "iperf3_not_installed"}
        })
        print(json.dumps({"metrics": metrics}, indent=2))
        return

    if not host:
        metrics.append({
            "name": "beacon_iperf_available",
            "kind": "gauge",
            "value": 0,
            "labels": {"reason": "no_server_configured"}
        })
        print(json.dumps({"metrics": metrics}, indent=2))
        return

    metrics.append({
        "name": "beacon_iperf_available",
        "kind": "gauge",
        "value": 1,
        "labels": {"server": host}
    })

    labels_base = {"server": host, "port": str(port)}

    # TCP Upload (client → server)
    upload_data = run_iperf3_tcp(host, port, DURATION_SECONDS, reverse=False)
    upload_mbps = extract_tcp_mbps(upload_data) if upload_data else -1.0
    metrics.append({
        "name": "beacon_iperf_tcp_upload_mbps",
        "kind": "gauge",
        "value": upload_mbps,
        "labels": {**labels_base, "direction": "upload", "success": str(1 if upload_data else 0)}
    })

    # TCP Download (server → client, -R flag)
    download_data = run_iperf3_tcp(host, port, DURATION_SECONDS, reverse=True)
    download_mbps = extract_tcp_mbps(download_data) if download_data else -1.0
    metrics.append({
        "name": "beacon_iperf_tcp_download_mbps",
        "kind": "gauge",
        "value": download_mbps,
        "labels": {**labels_base, "direction": "download", "success": str(1 if download_data else 0)}
    })

    # UDP Jitter + Packet Loss
    udp_data = run_iperf3_udp(host, port, DURATION_SECONDS)
    if udp_data:
        jitter_ms, lost_percent, pkts_sent, pkts_lost = extract_udp_stats(udp_data)
    else:
        jitter_ms, lost_percent, pkts_sent, pkts_lost = -1.0, -1.0, 0, 0

    metrics += [
        {
            "name": "beacon_iperf_udp_jitter_ms",
            "kind": "gauge",
            "value": jitter_ms,
            "labels": {**labels_base, "success": str(1 if udp_data else 0)}
        },
        {
            "name": "beacon_iperf_udp_packet_loss_percent",
            "kind": "gauge",
            "value": lost_percent,
            "labels": {**labels_base, "success": str(1 if udp_data else 0)}
        },
        {
            "name": "beacon_iperf_udp_packets_sent",
            "kind": "gauge",
            "value": pkts_sent,
            "labels": labels_base
        },
        {
            "name": "beacon_iperf_udp_packets_lost",
            "kind": "gauge",
            "value": pkts_lost,
            "labels": labels_base
        },
    ]

    output = {"metrics": metrics}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
