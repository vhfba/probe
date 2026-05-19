# Probe Agent

The probe agent simulates the runtime that would execute on a deployed BEACON probe. It is plugin-driven and talks to the central server over GraphQL plus bundle download HTTP endpoints.

The first successful `recordProbeHeartbeat` auto-registers the probe in central-server. There is no manual probe registration flow anymore.

## Responsibilities

- send heartbeat updates with `recordProbeHeartbeat`
- fetch probe config with `probeConfig`
- poll pending actions with `pendingProbeActions`
- download assigned plugin bundles from central-server
- execute scheduled plugins on interval
- execute action plugins on demand
- push metric snapshots with `reportProbeMetrics`
- update action execution status with `updateProbeActionStatus`

## Local Endpoints

- `GET /health`
- `GET /api/runtime`
- `GET /api/tests/latest`
- `GET /api/tests/history`
- `GET /api/wifi/summary`

These endpoints are for local inspection only. Prometheus should scrape central-server `/metrics`, not the probe agent.

## Plugin Contract

Each plugin bundle zip must contain:

- `manifest.json`
- `plugin.py`

Supported entrypoints:

- `run_scheduled(context)` for `SCHEDULED` plugins
- `run_action(context)` for `ACTION` plugins

### Scheduled result shape

```python
{
  "metrics": [
    {"name": "metric_name", "kind": "gauge", "value": 1.0, "labels": {"k": "v"}}
  ],
  "records": [
    {
      "category": "ping",
      "testType": "PING",
      "target": "8.8.8.8",
      "passed": True,
      "latencyMs": 12.3
    }
  ]
}
```

### Action result shape

```python
{
  "status": "SUCCEEDED",
  "metrics": [
    {"name": "metric_name", "kind": "gauge", "value": 1.0, "labels": {"k": "v"}}
  ],
  "record": {
    "category": "action",
    "pluginId": "WIFI_SCAN_ACTION",
    "passed": True
  }
}
```

## Current Example Plugins

Scheduled:

- `PING`
- `HTTP`
- `IPERF`
- `WIFI`

Action:

- `WIFI_SCAN_ACTION`

Built bundle archives are placed in:

- `code/central-server/plugin-bundles/`

Checksums are written to:

- [plugin-bundle-registry.json](/C:/Users/joaom/Faculdade/beacon/code/probe-agent/plugin-bundle-registry.json)

## Build Plugin Bundles

From `code/probe-agent`:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\build_plugin_bundles.ps1
```

## Run Locally

1. Install dependencies:

```powershell
pip install -r requirements.txt
```

2. Configure `.env`:

```dotenv
PROBE_ID=probe-mock-01
CENTRAL_SERVER_BASE_URL=http://localhost:5000
CENTRAL_SERVER_PROBE_API_KEY=<AUTH_PROBE_API_KEY from central-server>
```

3. Start the agent:

```powershell
python mock_probe_agent.py
```

## Central Server Setup For A Working Demo

1. Register scheduled and action plugins with `registerPlugin`.
2. Start the agent so it can auto-register itself through `recordProbeHeartbeat`.
3. Wait for the probe to appear in `fleetStatus` or the fleet UI.
4. Assign plugins to that probe with `setProbePlugins`.
5. Enable scheduled plugins with `updateProbeTestConfig`.
6. Trigger action plugins with `triggerProbeAction`.

Important distinction:

- scheduled plugins require both assignment and test configuration
- action plugins require assignment and then explicit triggering

## Troubleshooting

- Heartbeat not updating:
  - Confirm `CENTRAL_SERVER_PROBE_API_KEY` matches `AUTH_PROBE_API_KEY`.
  - Confirm the probe can reach `/graphql`.
  - Confirm the probe appears in `fleetStatus` after startup; the first heartbeat creates the probe record.

- No plugins loaded:
  - Confirm plugin records were registered in central-server.
  - Confirm the probe has already auto-registered and was then assigned those plugins.
  - Confirm bundle files exist in `code/central-server/plugin-bundles`.

- Scheduled checks never run:
  - Confirm `updateProbeTestConfig` was called for each scheduled plugin.

- Actions never run:
  - Confirm the action plugin is assigned to the probe.
  - Confirm `triggerProbeAction` queued work.
  - Confirm the agent can call `pendingProbeActions`.
