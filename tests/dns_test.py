#!/usr/bin/env python3
"""
DNS Test Plugin
Measures: resolution latency per resolver, success/failure, tested domain.
Tests multiple resolvers (system, 8.8.8.8, 1.1.1.1) for comparison.
Output: JSON to stdout (compatible with beacon plugin system)
"""

import json
import time
import socket
import subprocess
import os


# Domains to test — mix of common and local-relevant
TEST_DOMAINS = [
    "google.com",
    "cloudflare.com",
    "github.com",
]

# Resolvers to compare (name -> IP)
RESOLVERS = {
    "system": None,       # uses OS resolver
    "google": "8.8.8.8",
    "cloudflare": "1.1.1.1",
}


def resolve_with_system(domain):
    """Resolve using the OS resolver. Returns (latency_ms, success)."""
    try:
        start = time.perf_counter()
        socket.getaddrinfo(domain, None)
        elapsed = (time.perf_counter() - start) * 1000
        return round(elapsed, 2), 1
    except Exception:
        return -1.0, 0


def resolve_with_dig(domain, resolver_ip):
    """
    Resolve using a specific resolver via `dig`.
    Returns (latency_ms, success).
    dig is available on Raspberry Pi OS (dnsutils package).
    Falls back gracefully if not installed.
    """
    try:
        result = subprocess.run(
            ["dig", f"@{resolver_ip}", domain, "+time=3", "+tries=1", "+stats"],
            capture_output=True,
            text=True,
            timeout=5
        )

        output = result.stdout

        # Parse query time from dig stats: "Query time: 12 msec"
        for line in output.splitlines():
            if "Query time:" in line:
                parts = line.split()
                idx = parts.index("time:") + 1
                latency = float(parts[idx])
                success = 1 if result.returncode == 0 and "NOERROR" in output else 0
                return latency, success

        # dig ran but no query time found
        success = 1 if result.returncode == 0 and "NOERROR" in output else 0
        return -1.0, success

    except FileNotFoundError:
        # dig not installed — fall back to raw socket TCP DNS
        return resolve_via_raw_socket(domain, resolver_ip)
    except subprocess.TimeoutExpired:
        return -1.0, 0
    except Exception:
        return -1.0, 0


def resolve_via_raw_socket(domain, resolver_ip, port=53):
    """
    Minimal DNS query over UDP using raw sockets.
    Used as fallback when dig is unavailable.
    """
    try:
        # Build a minimal DNS query for A record
        def encode_name(name):
            encoded = b""
            for part in name.split("."):
                encoded += bytes([len(part)]) + part.encode()
            return encoded + b"\x00"

        transaction_id = b"\xaa\xbb"
        flags = b"\x01\x00"          # standard query, recursion desired
        qdcount = b"\x00\x01"        # 1 question
        ancount = b"\x00\x00"
        nscount = b"\x00\x00"
        arcount = b"\x00\x00"
        qname = encode_name(domain)
        qtype = b"\x00\x01"          # A record
        qclass = b"\x00\x01"         # IN

        packet = (transaction_id + flags + qdcount + ancount +
                  nscount + arcount + qname + qtype + qclass)

        start = time.perf_counter()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(3)
            s.sendto(packet, (resolver_ip, port))
            data, _ = s.recvfrom(512)
        elapsed = (time.perf_counter() - start) * 1000

        # Check RCODE in response flags (byte 3, lower 4 bits)
        rcode = data[3] & 0x0F
        success = 1 if rcode == 0 else 0
        return round(elapsed, 2), success

    except Exception:
        return -1.0, 0


def main():
    domain = os.environ.get("BEACON_DNS_TEST_DOMAIN", TEST_DOMAINS[0])
    all_domains = os.environ.get("BEACON_DNS_ALL_DOMAINS", "0") == "1"

    domains = TEST_DOMAINS if all_domains else [domain]

    metrics = []

    for test_domain in domains:
        # System resolver
        sys_latency, sys_ok = resolve_with_system(test_domain)
        metrics.append({
            "name": "beacon_dns_latency_ms",
            "kind": "gauge",
            "value": sys_latency,
            "labels": {
                "domain": test_domain,
                "resolver": "system",
                "resolver_ip": "system"
            }
        })
        metrics.append({
            "name": "beacon_dns_success",
            "kind": "gauge",
            "value": sys_ok,
            "labels": {
                "domain": test_domain,
                "resolver": "system",
                "resolver_ip": "system"
            }
        })

        # External resolvers via dig / raw socket
        for resolver_name, resolver_ip in RESOLVERS.items():
            if resolver_ip is None:
                continue  # already tested system above

            latency, ok = resolve_with_dig(test_domain, resolver_ip)

            metrics.append({
                "name": "beacon_dns_latency_ms",
                "kind": "gauge",
                "value": latency,
                "labels": {
                    "domain": test_domain,
                    "resolver": resolver_name,
                    "resolver_ip": resolver_ip
                }
            })
            metrics.append({
                "name": "beacon_dns_success",
                "kind": "gauge",
                "value": ok,
                "labels": {
                    "domain": test_domain,
                    "resolver": resolver_name,
                    "resolver_ip": resolver_ip
                }
            })

    output = {"metrics": metrics}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
