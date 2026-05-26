#!/usr/bin/env python3

import json
import time


def read_cpu_temp():
    paths = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/hwmon/hwmon0/temp1_input"
    ]

    for path in paths:
        try:
            with open(path, "r") as f:
                raw = f.read().strip()

            value = float(raw)

            if value > 1000:
                value = value / 1000.0

            return value
        except Exception:
            continue

    return 0.0


def read_cpu_usage():

    def read_stat():
        with open("/proc/stat", "r") as f:
            line = f.readline()

        values = [float(x) for x in line.split()[1:]]

        idle = values[3]
        total = sum(values)

        return idle, total

    idle1, total1 = read_stat()
    time.sleep(0.2)
    idle2, total2 = read_stat()

    idle_delta = idle2 - idle1
    total_delta = total2 - total1

    if total_delta <= 0:
        return 0.0

    usage = 100.0 * (1.0 - (idle_delta / total_delta))
    return round(usage, 2)


def read_memory_usage_percent():
    mem_total = 0
    mem_available = 0

    with open("/proc/meminfo", "r") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                mem_available = int(line.split()[1])

    if mem_total == 0:
        return 0.0

    used = mem_total - mem_available
    return round((used / mem_total) * 100.0, 2)


# ---- FIX: define output ----
output = {
    "cpu_temp": read_cpu_temp(),
    "cpu_usage": read_cpu_usage(),
    "memory_usage": read_memory_usage_percent(),
    "timestamp": time.time()
}

print(json.dumps(output, indent=2))
