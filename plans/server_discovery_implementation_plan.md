# Implementation Plan: Concurrent Server Discovery & Probing

This implementation plan outlines the design and additions required to support multiple candidate proxy servers, allowing the client to concurrently probe and lock onto the first responding active server on startup.

---

## 🛠️ Feature Overview

- **Problem Statement**: In distributed or high-availability setups, multiple proxy servers may be running. The client needs to quickly find the first available active server and use it for the remainder of the process.
- **Design Goals**:
  - **Zero Perf Overhead**: Near-instant discovery (sub-10ms when local server is up) and capped at 500ms max even if multiple candidates are dead or hanging.
  - **Concurrent Probing**: Avoid slow sequential timeouts by probing all candidates in parallel using `concurrent.futures.ThreadPoolExecutor`.
  - **Backward Compatibility**: Fully support existing single-string configurations, comma-separated environment variables/strings, and list arrays in `config.json`.
  - **Sticky Session**: Once a server is selected, the client instance locks onto it (`self.base_url`) for its entire lifecycle.

---

## 📐 Detailed Component Changes

### 1. 📡 Proxy Client (`ngd_proxy/client.py`)

We will update the `__init__` method and add the concurrent probing function `_discover_active_server`:

- **Updated `__init__`**:
  - Accepts `base_url` as `Optional[Union[str, List[str]]]`.
  - Parses either string lists or comma-separated strings into a robust `self.base_urls: List[str]` list.
  - Loads `server_base_url` from `config.json` as either a JSON array list or a comma-separated string.
  - Executes `self.base_url = self._discover_active_server()` to lock the active endpoint.

- **Concurrently Probing Delegate**:
  ```python
  def _discover_active_server(self) -> str:
      """
      Concurrently probes all configured base_urls to find the first responding server.
      Uses a lightweight /status request with a short timeout.
      If no server responds, falls back to the first URL in the list.
      """
      if len(self.base_urls) <= 1:
          url = self.base_urls[0].rstrip("/")
          logger.info(f"Using single configured server: {url}")
          return url

      import concurrent.futures

      def probe_url(url: str) -> Optional[str]:
          clean_url = url.rstrip("/")
          probe_endpoint = f"{clean_url}/status"
          headers = {}
          if self.api_key:
              headers["X-API-Key"] = self.api_key
          try:
              # Use a very short timeout (e.g. 0.5s) for discovery
              response = requests.get(probe_endpoint, headers=headers, timeout=0.5)
              if response.status_code == 200:
                  return clean_url
          except Exception:
              pass
          return None

      logger.info(f"Probing {len(self.base_urls)} candidate servers: {self.base_urls}")
      
      # Concurrently probe all candidate URLs
      with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.base_urls)) as executor:
          futures = {executor.submit(probe_url, url): url for url in self.base_urls}
          
          # Wait for the first success
          active_url = None
          for future in concurrent.futures.as_completed(futures):
              result = future.result()
              if result:
                  active_url = result
                  break  # Lock on first responding active server

      if active_url:
          logger.info(f"Discovered active server: {active_url}")
          return active_url
      else:
          fallback = self.base_urls[0].rstrip("/")
          logger.warning(f"No active server responded. Falling back to first candidate: {fallback}")
          return fallback
  ```

---

## 🧪 Verification & Testing Plan

### Automated Integration Tests (`tests/test_cache.py`)

We will add a dedicated integration test case: **`test_21_server_discovery_and_probing`**, verifying:
1. **Multi-URL Input**: Initiating the client with `base_url=["http://127.0.0.1:9999", "http://127.0.0.1:8099"]` (where `9999` is a dead/unbound port and `8099` is our active test server port).
2. **Ignored Failures**: Probing successfully ignores the dead port and locks onto the active port `http://127.0.0.1:8099` within milliseconds.
3. **Sticky routing**: All subsequent queries (e.g. `client.status()`) execute successfully against the discovered port.
4. **Fallback Handling**: If all configured ports are dead, ensures it falls back to the first port in the list gracefully.

### Manual Verification (`test__server_discovery.ipynb`)

 We will create a Jupyter playbook `test__server_discovery.ipynb` demonstrating the usage of multiple servers, logging discovery performance metrics, and showcasing how config fallbacks work.
