#!/usr/bin/env python3
"""
Speed Test Plugin (HTTP-based)
Measures: download Mbps, upload Mbps, latency (ping to test server).
Uses stdlib only — no speedtest-cli dependency.
Downloads/uploads against well-known open endpoints.
Output: JSON to stdout (compatible with beacon plugin system)
"""

import json
import time
import socket
import os
import threading


# Download test: fetch a known large file and measure throughput.
# Using Cloudflare's speed test endpoint (returns fixed-size payload).
DOWNLOAD_HOSTS = [
    ("speed.cloudflare.com", "/__down?bytes=10000000", 80),   # 10 MB
]

# Upload test: POST data to httpbin (or fallback to /dev/null style endpoint)
UPLOAD_HOST = ("httpbin.org", "/post", 80)

UPLOAD_SIZE_BYTES = 5 * 1024 * 1024   # 5 MB
TIMEOUT_SECONDS = 20


def http_get_timed(host, path, port=80, timeout=TIMEOUT_SECONDS):
    """
    Performs a raw HTTP/1.1 GET and measures:
    - Time to first byte (latency)
    - Total download time
    - Bytes received
    Returns (latency_ms, throughput_mbps, success).
    """
    try:
        start_connect = time.perf_counter()
        s = socket.create_connection((host, port), timeout=timeout)
        connected_at = time.perf_counter()

        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Connection: close\r\n"
            f"User-Agent: beacon-probe/1.0\r\n"
            f"\r\n"
        )
        s.sendall(request.encode())

        # Read until headers end, record time-to-first-byte
        header_buf = b""
        first_byte_time = None
        while b"\r\n\r\n" not in header_buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            if first_byte_time is None:
                first_byte_time = time.perf_counter()
            header_buf += chunk

        latency_ms = round(
            ((first_byte_time or time.perf_counter()) - connected_at) * 1000, 2
        )

        # Check HTTP status
        status_line = header_buf.split(b"\r\n")[0].decode(errors="ignore")
        if "200" not in status_line and "204" not in status_line:
            s.close()
            return latency_ms, -1.0, 0

        # Drain body and measure throughput
        body_start = time.perf_counter()
        total_bytes = len(header_buf.split(b"\r\n\r\n", 1)[-1])  # bytes after headers

        s.settimeout(timeout)
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            total_bytes += len(chunk)

        body_elapsed = time.perf_counter() - body_start
        s.close()

        if body_elapsed <= 0 or total_bytes == 0:
            return latency_ms, -1.0, 0

        throughput_mbps = round((total_bytes * 8) / (body_elapsed * 1_000_000), 2)
        return latency_ms, throughput_mbps, 1

    except Exception:
        return -1.0, -1.0, 0


def http_post_timed(host, path, port=80, upload_bytes=UPLOAD_SIZE_BYTES, timeout=TIMEOUT_SECONDS):
    """
    Performs a raw HTTP/1.1 POST with a fixed payload size.
    Measures upload throughput.
    Returns (throughput_mbps, success).
    """
    try:
        s = socket.create_connection((host, port), timeout=timeout)

        # Send headers first
        headers = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"Content-Length: {upload_bytes}\r\n"
            f"Connection: close\r\n"
            f"User-Agent: beacon-probe/1.0\r\n"
            f"\r\n"
        )
        s.sendall(headers.encode())

        # Send body in chunks — zeros are fine, we're measuring bandwidth
        chunk_size = 65536
        sent = 0
        payload_chunk = b"\x00" * chunk_size

        start = time.perf_counter()
        while sent < upload_bytes:
            remaining = upload_bytes - sent
            to_send = min(chunk_size, remaining)
            s.sendall(payload_chunk[:to_send])
            sent += to_send
        elapsed = time.perf_counter() - start

        # Drain response (don't care about body)
        s.settimeout(5)
        try:
            while s.recv(4096):
                pass
        except Exception:
            pass
        s.close()

        if elapsed <= 0:
            return -1.0, 0

        throughput_mbps = round((sent * 8) / (elapsed * 1_000_000), 2)
        return throughput_mbps, 1

    except Exception:
        return -1.0, 0


def ping_latency(host, port=80, samples=5):
    """TCP connect-based latency measurement (no ICMP needed)."""
    times = []
    for _ in range(samples):
        try:
            start = time.perf_counter()
            with socket.create_connection((host, port), timeout=3):
                pass
            times.append((time.perf_counter() - start) * 1000)
        except Exception:
            pass
        time.sleep(0.1)

    if not times:
        return -1.0
    return round(sum(times) / len(times), 2)


def main():
    # Allow env overrides for test server (useful for intranet iPerf-HTTP setups)
    dl_host = os.environ.get("BEACON_SPEEDTEST_HOST", DOWNLOAD_HOSTS[0][0])
    dl_path = os.environ.get("BEACON_SPEEDTEST_PATH", DOWNLOAD_HOSTS[0][1])
    dl_port = int(os.environ.get("BEACON_SPEEDTEST_PORT", DOWNLOAD_HOSTS[0][2]))

    up_host = os.environ.get("BEACON_SPEEDTEST_UPLOAD_HOST", UPLOAD_HOST[0])
    up_path = os.environ.get("BEACON_SPEEDTEST_UPLOAD_PATH", UPLOAD_HOST[1])
    up_port = int(os.environ.get("BEACON_SPEEDTEST_UPLOAD_PORT", UPLOAD_HOST[2]))

    # Latency first (cheap)
    latency_ms = ping_latency(dl_host, dl_port)

    # Download
    dl_latency_ms, download_mbps, dl_ok = http_get_timed(dl_host, dl_path, dl_port)

    # Upload
    upload_mbps, ul_ok = http_post_timed(up_host, up_path, up_port)

    output = {
        "metrics": [
            {
                "name": "beacon_speedtest_latency_ms",
                "kind": "gauge",
                "value": latency_ms,
                "labels": {"server": dl_host}
            },
            {
                "name": "beacon_speedtest_download_mbps",
                "kind": "gauge",
                "value": download_mbps,
                "labels": {"server": dl_host, "success": str(dl_ok)}
            },
            {
                "name": "beacon_speedtest_upload_mbps",
                "kind": "gauge",
                "value": upload_mbps,
                "labels": {"server": up_host, "success": str(ul_ok)}
            },
            {
                "name": "beacon_speedtest_download_success",
                "kind": "gauge",
                "value": dl_ok,
                "labels": {"server": dl_host}
            },
            {
                "name": "beacon_speedtest_upload_success",
                "kind": "gauge",
                "value": ul_ok,
                "labels": {"server": up_host}
            },
        ]
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
