# Run:
# python3 pi_agent.py

import json
import os
import hashlib
import ipaddress
import queue
import subprocess
import threading
import time
import socket
import tempfile
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Any
import requests
import yaml
import zipfile
import shutil


class PluginManager:

    def __init__(
        self,
        plugin_dir=None
    ):

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.plugin_dir = plugin_dir or os.path.join(base_dir, "plugins")

        os.makedirs(
            self.plugin_dir,
            exist_ok=True
        )

        self.plugins = {}

    def load_plugins(self):

        self.plugins = {}

        if not os.path.exists(
            self.plugin_dir
        ):
            return

        for name in os.listdir(
            self.plugin_dir
        ):

            path = os.path.join(
                self.plugin_dir,
                name
            )

            manifest_path = self._manifest_path(path)

            if manifest_path is None:
                continue

            with open(manifest_path) as f:

                manifest = json.load(f)

            entrypoint = os.path.join(
                path,
                manifest["entrypoint"]
            )

            self.plugins[
                manifest["id"]
            ] = {

                "manifest": manifest,

                "entrypoint":
                    os.path.abspath(
                        entrypoint
                    )
            }

    def _manifest_path(self, path):
        for filename in ("manifest.json", "plugin.json"):
            candidate = os.path.join(path, filename)
            if os.path.exists(candidate):
                return candidate

        return None

    def install_plugin_zip(
        self,
        zip_path
    ):

        temp_dir = tempfile.mkdtemp(prefix="beacon_plugin_")

        with zipfile.ZipFile(
            zip_path,
            "r"
        ) as zip_ref:

            zip_ref.extractall(
                temp_dir
            )

        manifest_path = self._manifest_path(temp_dir)

        if manifest_path is None:
            raise Exception(
                "manifest.json missing"
            )

        with open(manifest_path) as f:
            manifest = json.load(f)

        plugin_id = manifest["id"]

        final_dir = os.path.join(
            self.plugin_dir,
            plugin_id
        )

        if os.path.exists(final_dir):
            shutil.rmtree(final_dir)

        os.makedirs(final_dir)

        for item in os.listdir(temp_dir):

            shutil.move(
                os.path.join(temp_dir, item),
                os.path.join(final_dir, item)
            )

        entrypoint = os.path.join(
            final_dir,
            manifest["entrypoint"]
        )

        os.chmod(
            entrypoint,
            0o755
        )

        self.load_plugins()
        shutil.rmtree(temp_dir, ignore_errors=True)

    def download_plugin(
        self,
        url,
        checksum=None,
        api_key=None
    ):

        headers = {}
        if api_key:
            headers["X-Api-Key"] = api_key

        response = requests.get(
            url,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        bundle = response.content
        if checksum and is_sha256(checksum):
            actual = hashlib.sha256(bundle).hexdigest()
            if actual.lower() != checksum.lower():
                raise Exception(
                    f"Plugin checksum mismatch: expected {checksum}, got {actual}"
                )

        fd, local_zip = tempfile.mkstemp(
            prefix="beacon_plugin_",
            suffix=".zip"
        )

        with os.fdopen(fd, "wb") as f:
            f.write(response.content)

        self.install_plugin_zip(
            local_zip
        )
        os.remove(local_zip)

    def run_plugin(
        self,
        plugin_id,
        context=None
    ):

        if plugin_id not in self.plugins:
            raise Exception(
                f"Plugin {plugin_id} missing"
            )

        plugin = self.plugins[
            plugin_id
        ]

        manifest = plugin["manifest"]

        env = os.environ.copy()
        env["BEACON_PLUGIN_CONTEXT"] = json.dumps(
            context or {}
        )

        result = subprocess.run(

            [plugin["entrypoint"]],

            input=json.dumps(context or {}),

            capture_output=True,

            text=True,

            env=env,

            timeout=manifest.get(
                "timeout_seconds",
                30
            )
        )

        if result.stderr:
            print(
                f"[{plugin_id}] stderr:"
            )
            print(result.stderr)

        if result.returncode != 0:

            raise Exception(
                f"{plugin_id} failed"
            )

        return json.loads(
            result.stdout
        )


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "configs", "config.yaml")

DEFAULT_CONFIG = {
    "device_id": "raspberrypi-001",
    "probe_name": "raspberrypi-001",
    "probe_location": "Building A",
    "probe_ssid": "",
    "agent_version": "1.0.0-pi",
    "graphql_url": "http://localhost:5000/graphql",
    "api_key": "",
    "heartbeat_interval": 30,
    "metrics_interval": 5,
    "action_poll_interval": 10,
    "wifi_interface": "wlan0",
    "ethernet_interface": "eth0",
    "wifi_credentials": {
        "ssid": "",
        "password": ""
    },
    "ethernet_config": {
        "dhcp": True,

        "static": {
            "address": "172.25.20.151",
            "netmask": "255.255.255.0",
            "gateway": "172.25.20.1",
            "dns": [
                "172.25.11.5",
                "172.25.11.6"
            ]
        }
    }

}


class ConfigManager:
    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.config = self.load()

    def load(self):
        if not os.path.exists(self.path):
            self.save(DEFAULT_CONFIG)
            return DEFAULT_CONFIG

        with open(self.path, "r") as f:
            return yaml.safe_load(f)

    def save(self, config=None):
        if config:
            self.config = config

        with open(self.path, "w") as f:
            yaml.dump(self.config, f)

    def update(self, data: Dict[str, Any]):
        self.config.update(data)
        self.save()

# Graphql


class GraphQLClient:
    def __init__(self, url, api_key=""):
        self.url = url
        self.api_key = api_key

    def execute(self, query, variables=None):
        payload = {
            "query": query,
            "variables": variables or {}
        }

        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

        response = requests.post(
            self.url,
            json=payload,
            headers=headers,
            timeout=15
        )

        response.raise_for_status()

        data = response.json()
        if data.get("errors"):
            raise Exception(
                "GraphQL errors: "
                + json.dumps(data["errors"])
            )

        return data


# Mask

def mask_to_cidr(mask):
    return ipaddress.IPv4Network(
        f"0.0.0.0/{mask}"
    ).prefixlen


def is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdefABCDEF" for ch in value)
    )


def resolve_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def metric_labels(config, plugin_id):
    return [
        {"key": "probe_id", "value": str(config["device_id"])},
        {"key": "site", "value": str(config.get("probe_location", "unknown"))},
        {"key": "test_type", "value": str(plugin_id).upper()},
    ]


def absolute_url(url, graphql_url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme and parsed.netloc:
        return url

    base = graphql_url.rsplit("/graphql", 1)[0].rstrip("/")
    return urllib.parse.urljoin(
        base + "/",
        url.lstrip("/")
    )

# Network


class NetworkManager:
    def __init__(self, config):
        self.config = config

    def configure_ethernet(self):

        iface = self.config["ethernet_interface"]

        eth = self.config["ethernet_config"]

        if eth["dhcp"]:

            subprocess.run([
                "sudo",
                "dhclient",
                "-r",
                iface
            ])

            subprocess.run([
                "sudo",
                "dhclient",
                iface
            ])

            return

        static = eth["static"]

        address = static["address"]
        netmask = static["netmask"]
        gateway = static["gateway"]
        dns_servers = static["dns"]

        if not address or not netmask or not gateway:
            return

        cidr = mask_to_cidr(netmask)

        subprocess.run([
            "sudo",
            "ip",
            "addr",
            "flush",
            "dev",
            iface
        ])

        subprocess.run([
            "sudo",
            "ip",
            "addr",
            "add",
            f"{address}/{cidr}",
            "dev",
            iface
        ])

        subprocess.run([
            "sudo",
            "ip",
            "link",
            "set",
            iface,
            "up"
        ])

        subprocess.run([
            "sudo",
            "ip",
            "route",
            "replace",
            "default",
            "via",
            gateway
        ])

        with open("/etc/resolv.conf", "w") as f:
            for dns in dns_servers:
                f.write(f"nameserver {dns}\n")

    def ethernet_connected(self):
        iface = self.config["ethernet_interface"]

        try:
            with open(f"/sys/class/net/{iface}/operstate") as f:
                state = f.read().strip()

            return state == "up"

        except Exception:
            return False

    def connect_ethernet(self):
        iface = self.config["ethernet_interface"]

        try:
            self.configure_ethernet()

            if self.config["ethernet_config"]["dhcp"]:

                subprocess.run(
                    ["sudo", "dhclient", iface],
                    check=False
                )

            return self.ethernet_connected()

        except Exception:
            return False

    def wifi_connected(self):
        try:
            output = subprocess.check_output(
                ["iwgetid"]
            ).decode().strip()

            return len(output) > 0
        except Exception:
            return False

    def connect_wifi(self):
        wifi = self.config["wifi_credentials"]

        ssid = wifi["ssid"]
        password = wifi["password"]

        if not ssid:
            return False

        wpa_conf = f'''
network={{
    ssid="{ssid}"
    psk="{password}"
}}
'''

        with open("/tmp/wpa_supplicant.conf", "w") as f:
            f.write(wpa_conf)

        iface = self.config["wifi_interface"]

        subprocess.run([
            "sudo",
            "pkill",
            "wpa_supplicant"
        ], check=False)

        subprocess.run([
            "sudo",
            "wpa_supplicant",
            "-B",
            "-i",
            iface,
            "-c",
            "/tmp/wpa_supplicant.conf"
        ], check=False)

        subprocess.run([
            "sudo",
            "dhclient",
            iface
        ], check=False)

        time.sleep(5)

        return self.wifi_connected()


class PiAgent:
    def __init__(self):

        self.config_manager = ConfigManager()

        self.config = (
            self.config_manager.config
        )

        self.graphql = GraphQLClient(
            self.config["graphql_url"],
            self.config.get("api_key", "")
        )

        self.network = NetworkManager(
            self.config
        )

        self.metric_queue = queue.Queue()
        self.enabled_tests = {}
        self.available_plugins = {}
        self.next_scheduled_run = {}
        self.state_lock = threading.Lock()

        self.plugins = PluginManager()
        self.plugins.load_plugins()

    def sync_plugins(self):

        query = """
        query ProbeCfg($probeId: String!) {
            probeConfig(probeId: $probeId) {
                enabledTests {
                    testType
                    intervalSeconds
                    enabled
                }
                availablePlugins {
                id
                version
                    checksum
                    available
                    executionMode
                    bundleUrl
                    bundleDownloadUrl
                }
            }
        }
        """

        try:

            response = self.graphql.execute(
                query,
                {
                    "probeId": self.config["device_id"]
                }
            )

            data = response["data"]["probeConfig"]

            enabled_tests = {
                test["testType"]: {
                    "testType": test["testType"],
                    "intervalSeconds": int(
                        test.get("intervalSeconds") or 30
                    ),
                    "enabled": bool(test.get("enabled", True))
                }
                for test in data.get("enabledTests", [])
                if test.get("enabled", True)
            }

            plugins = data.get("availablePlugins", [])
            plugin_map = {
                plugin["id"]: plugin
                for plugin in plugins
                if plugin.get("available", True)
            }

            with self.state_lock:
                self.enabled_tests = enabled_tests
                self.available_plugins = plugin_map

            for plugin in plugins:
                if not plugin.get("available", True):
                    continue

                plugin_id = plugin["id"]

                local = self.plugins.plugins.get(plugin_id)

                needs_update = (
                    local is None
                    or local["manifest"]["version"]
                    != plugin["version"]
                )

                if needs_update:

                    print(
                        f"Installing {plugin_id}"
                    )

                    download_url = (
                        plugin.get("bundleDownloadUrl")
                        or plugin.get("bundleUrl")
                    )

                    if not download_url:
                        print(f"{plugin_id} has no bundle URL")
                        continue

                    self.plugins.download_plugin(
                        absolute_url(
                            download_url,
                            self.config["graphql_url"]
                        ),
                        plugin.get("checksum"),
                        self.config.get("api_key", "")
                    )

        except Exception as e:

            print(
                "Plugin sync failed:",
                e
            )

    # Heartbeat

    def send_heartbeat(self):
        mutation = """
        mutation Heartbeat($input: ProbeHeartbeatInputTypeInput!) {
            recordProbeHeartbeat(input: $input) {
                success
                autoRegistered
                message
                runtime {
                    probeId
                    status
                    canEmitMetrics
                    enabledTests
                    site
                    ipAddress
                }
            }
        }
        """

        variables = {
            "input": {
                "probeId": self.config["device_id"],
                "name": self.config.get(
                    "probe_name",
                    self.config["device_id"]
                ),
                "location": self.config.get(
                    "probe_location",
                    "unknown"
                ),
                "ipAddress": resolve_local_ip(),
                "ssid": self.config.get("probe_ssid") or None,
                "agentVersion": self.config.get(
                    "agent_version",
                    "1.0.0-pi"
                )
            }
        }

        try:
            response = self.graphql.execute(
                mutation,
                variables
            )

            result = response["data"]["recordProbeHeartbeat"]
            if not result.get("success"):
                raise Exception(
                    result.get("message")
                    or "Heartbeat failed"
                )

            print("Heartbeat sent:", response)

        except Exception as e:
            print("Heartbeat failed:", e)

    # Send Metrics

    def build_metric_samples(self, payload):
        samples = []

        for plugin_id, metrics in payload.get("metrics", {}).items():
            labels = metric_labels(
                self.config,
                plugin_id
            )

            if isinstance(metrics, dict) and isinstance(
                metrics.get("metrics"),
                list
            ):
                for sample in metrics["metrics"]:
                    samples.append({
                        "name": sample["name"],
                        "kind": sample.get("kind", "gauge"),
                        "value": float(sample.get("value", 0)),
                        "timestampUtc": utc_now_iso(),
                        "labels": [
                            {
                                "key": str(key),
                                "value": str(value)
                            }
                            for key, value
                            in sample.get("labels", {}).items()
                        ] or labels
                    })

                continue

            if isinstance(metrics, dict):
                for key, value in metrics.items():
                    if isinstance(value, bool):
                        value = 1 if value else 0

                    if not isinstance(value, (int, float)):
                        continue

                    samples.append({
                        "name": (
                            "beacon_pi_"
                            + str(plugin_id).lower()
                            + "_"
                            + str(key).lower()
                        ),
                        "kind": "gauge",
                        "value": float(value),
                        "timestampUtc": utc_now_iso(),
                        "labels": labels
                    })

        return samples

    def send_metrics(self, payload):
        mutation = """
        mutation ReportMetrics($input: ReportProbeMetricsInputTypeInput!) {
            reportProbeMetrics(input: $input) {
                success
                message
                probeId
                acceptedSamples
                receivedAtUtc
            }
        }
        """

        samples = self.build_metric_samples(payload)
        if not samples:
            print("No numeric metric samples to send")
            return

        variables = {
            "input": {
                "probeId": self.config["device_id"],
                "samples": samples
            }
        }

        try:
            response = self.graphql.execute(
                mutation,
                variables
            )

            result = response["data"]["reportProbeMetrics"]
            if not result.get("success"):
                raise Exception(
                    result.get("message")
                    or "Metric send failed"
                )

            print("Metrics sent:", response)

        except Exception as e:
            print("Metric send failed:", e)
            self.metric_queue.put(payload)

    # Get configs from server

    def fetch_remote_config(self):
        query = """
        query ProbeCfg($probeId: String!) {
            probeConfig(probeId: $probeId) {
                enabledTests {
                    testType
                    intervalSeconds
                    enabled
                }
            }
        }
        """

        variables = {
            "probeId": self.config["device_id"]
        }

        try:
            response = self.graphql.execute(
                query,
                variables
            )

            data = response["data"]["probeConfig"]
            enabled_tests = {
                test["testType"]: {
                    "testType": test["testType"],
                    "intervalSeconds": int(
                        test.get("intervalSeconds") or 30
                    ),
                    "enabled": bool(test.get("enabled", True))
                }
                for test in data.get("enabledTests", [])
                if test.get("enabled", True)
            }

            with self.state_lock:
                self.enabled_tests = enabled_tests

            print("Remote config updated")

        except Exception as e:
            print("Failed fetching config:", e)

    # Network

    def ensure_connectivity(self):
        if self.can_reach_central():
            return True

        if self.network.ethernet_connected():
            return True

        if self.network.connect_ethernet():
            print("Ethernet connected")
            return True

        if self.network.wifi_connected():
            return True

        if self.network.connect_wifi():
            print("WiFi connected")
            return True

        return False

    def can_reach_central(self):
        try:
            parsed = urllib.parse.urlparse(
                self.config["graphql_url"]
            )
            host = parsed.hostname
            port = parsed.port or (
                443 if parsed.scheme == "https" else 80
            )

            if not host:
                return False

            with socket.create_connection(
                (host, port),
                timeout=3
            ):
                return True
        except OSError:
            return False

    # Tests

    def run_due_tests(self):
        now = time.time()
        due_tests = []

        with self.state_lock:
            for plugin_id, cfg in self.enabled_tests.items():
                due_at = self.next_scheduled_run.get(plugin_id, 0)
                if now >= due_at:
                    due_tests.append((plugin_id, cfg))
                    self.next_scheduled_run[plugin_id] = (
                        now + cfg["intervalSeconds"]
                    )

        if not due_tests:
            return

        payload = {

            "device_id":
                self.config[
                    "device_id"
                ],

            "timestamp":
                int(time.time()),

            "metrics": {}
        }

        for plugin_id, test_cfg in due_tests:

            try:

                metrics = (
                    self.plugins.run_plugin(
                        plugin_id,
                        {
                            "probeId": self.config["device_id"],
                            "testType": plugin_id,
                            "scheduled": test_cfg,
                            "timestampUtc": utc_now_iso()
                        }
                    )
                )

                payload["metrics"][
                    plugin_id
                ] = metrics

            except Exception as e:

                print(
                    f"{plugin_id} failed:",
                    e
                )

        self.send_metrics(payload)

    def poll_and_execute_actions(self):
        query = """
        query PendingActions($probeId: String!, $limit: Int) {
            pendingProbeActions(probeId: $probeId, limit: $limit) {
                executionId
                probeId
                pluginId
                status
                requestedAtUtc
            }
        }
        """

        try:
            response = self.graphql.execute(
                query,
                {
                    "probeId": self.config["device_id"],
                    "limit": 10
                }
            )

            for action in response["data"]["pendingProbeActions"]:
                self.execute_action(action)

        except Exception as e:
            print("Action poll failed:", e)

    def update_action_status(
        self,
        execution_id,
        status,
        error_message=None
    ):
        mutation = """
        mutation UpdateAction($input: UpdateProbeActionStatusInputTypeInput!) {
            updateProbeActionStatus(input: $input) {
                success
                message
                execution {
                    executionId
                    status
                }
            }
        }
        """

        response = self.graphql.execute(
            mutation,
            {
                "input": {
                    "probeId": self.config["device_id"],
                    "executionId": execution_id,
                    "status": status,
                    "errorMessage": error_message
                }
            }
        )

        result = response["data"]["updateProbeActionStatus"]
        if not result.get("success"):
            raise Exception(
                result.get("message")
                or f"Failed updating action to {status}"
            )

    def execute_action(self, action):
        execution_id = action["executionId"]
        plugin_id = action["pluginId"]

        try:
            self.update_action_status(
                execution_id,
                "Running"
            )

            result = self.plugins.run_plugin(
                plugin_id,
                {
                    "probeId": self.config["device_id"],
                    "action": action,
                    "timestampUtc": utc_now_iso()
                }
            )

            self.send_metrics({
                "device_id": self.config["device_id"],
                "timestamp": int(time.time()),
                "metrics": {
                    plugin_id: result
                }
            })

            status = result.get("status", "SUCCEEDED")
            if str(status).upper() == "TIMED_OUT":
                self.update_action_status(
                    execution_id,
                    "TimedOut",
                    result.get("errorMessage")
                )
            elif str(status).upper() == "FAILED":
                self.update_action_status(
                    execution_id,
                    "Failed",
                    result.get("errorMessage")
                )
            else:
                self.update_action_status(
                    execution_id,
                    "Succeeded"
                )

        except subprocess.TimeoutExpired as e:
            self.update_action_status(
                execution_id,
                "TimedOut",
                str(e)
            )
        except Exception as e:
            try:
                self.update_action_status(
                    execution_id,
                    "Failed",
                    str(e)
                )
            except Exception as status_error:
                print("Action status update failed:", status_error)

            print(f"Action {execution_id} failed:", e)

    # Heartbeat loop

    def heartbeat_loop(self):
        while True:
            if self.ensure_connectivity():
                self.send_heartbeat()
                self.fetch_remote_config()
                self.sync_plugins()

            time.sleep(
                self.config["heartbeat_interval"]
            )

    # Metrics loop

    def metrics_loop(self):
        while True:
            if self.ensure_connectivity():
                self.run_due_tests()

            time.sleep(
                self.config["metrics_interval"]
            )

    def action_loop(self):
        while True:
            if self.ensure_connectivity():
                self.poll_and_execute_actions()

            time.sleep(
                self.config.get("action_poll_interval", 10)
            )

    def retry_loop(self):

        while True:

            try:

                payload = self.metric_queue.get(
                    timeout=5
                )

                try:

                    self.send_metrics(payload)

                except Exception:

                    self.metric_queue.put(
                        payload
                    )

            except queue.Empty:
                pass

            time.sleep(5)

    def start(self):
        print("Starting Pi Agent")

        threading.Thread(
            target=self.heartbeat_loop,
            daemon=True
        ).start()

        threading.Thread(
            target=self.metrics_loop,
            daemon=True
        ).start()

        threading.Thread(
            target=self.action_loop,
            daemon=True
        ).start()

        threading.Thread(
            target=self.retry_loop,
            daemon=True
        ).start()

        while True:
            time.sleep(1)

# main


if __name__ == "__main__":
    agent = PiAgent()
    agent.start()
