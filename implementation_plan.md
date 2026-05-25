# Proposal: Package `ngd_proxy` into an Installable Python Library

To allow you to install and import your Norgate Data Proxy cleanly in any script across Windows, macOS, or Linux using `pip`, we propose transforming the codebase into a standard, single Python package named `ngd_proxy`.

---

## Proposed Changes

We will restructure the directory layout to separate package code from metadata and tests:

```text
ngd_proxy/                   <-- Root directory
  ├── ngd_proxy/             <-- Python Package
  │     ├── __init__.py      <-- Exposes public classes
  │     ├── client.py        <-- HTTP Client
  │     ├── norgatedata_cache.py <-- Unified Cache Manager
  │     ├── server.py        <-- FastAPI Server
  │     └── config.json.example <-- Example config
  ├── tests/
  │     └── test_cache.py    <-- Integration tests
  ├── pyproject.toml         <-- Packaging Metadata & CLI registrations
  ├── README.md
  ├── .gitignore
  └── requirements.txt
```

---

## Namespace & Code Adjustments

### 1. Package Entrypoint (`ngd_proxy/__init__.py`)
We will create a new entrypoint exposing the classes directly:
```python
from .client import NorgateDataClient
from .norgatedata_cache import NorgateDataCache

__all__ = ["NorgateDataClient", "NorgateDataCache"]
```
This enables extremely clean client imports:
```python
from ngd_proxy import NorgateDataCache

cache = NorgateDataCache()
```

### 2. Relative Namespaces
- **`norgatedata_cache.py`:** Update the import of `NorgateDataClient` to use a relative import:
  ```diff
-from client import NorgateDataClient
+from .client import NorgateDataClient
  ```

---

## Modern Packaging Config (`pyproject.toml`)

We will create a standard, modern `pyproject.toml` file utilizing `setuptools`. It will register a global system command:

#### [NEW] [pyproject.toml](file:///c:/Projects/claudeai/gemini/ngd_proxy/pyproject.toml)
```toml
[build-system]
requires = ["setuptools>=61.0.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ngd_proxy"
version = "1.0.0"
description = "A high-performance HTTP & Parquet proxy and caching engine for Norgate Data."
readme = "README.md"
requires-python = ">=3.8"
dependencies = [
    "fastapi>=0.100.0",
    "uvicorn>=0.22.0",
    "pandas>=2.0.0",
    "pyarrow>=12.0.0",
    "psutil>=5.9.0",
    "requests>=2.31.0",
    "cryptography>=41.0.0",
    "jinja2>=3.1.0"
]

[project.scripts]
ngd-proxy-server = "ngd_proxy.server:main"
```

> [!TIP]
> **Automatic CLI Command (`ngd-proxy-server`)**
> - The `[project.scripts]` block registers a global shell command: **`ngd-proxy-server`**.
> - Once installed, you don't need to locate `server.py` to start the server! Simply open a terminal on your Windows host and type **`ngd-proxy-server`** (with optional parameters like `--port 8000` or `--mock`).

---

## Verification Plan

### Local Installation & Testing
1. **Editable Installation:** Run `pip install -e .` inside the `C:\venv\ngd_proxy` virtual environment. This installs the package locally but keeps edits live.
2. **CLI Test:** Run the global CLI `ngd-proxy-server --mock` in the terminal to verify automatic path registration.
3. **Automated Test Run:** Run `pytest` or `python tests/test_cache.py` to verify that imports and caching behave perfectly.
