"""generate-image — multi-provider image generation and bounded workflows.

Public modules:
  * cli          — CLI + orchestration (provider_generate/provider_edit, main)
  * providers    — provider registry (dialects + reliability policy)
  * reliability  — pooled httpx client, billing-aware retry, rate limit, AIMD
  * dag          — task-graph engine (graphlib parallel scheduler) + spec loader
  * flow         — bounded directed control-flow engine with cyclic routes
  * list_models  — `generate-image-models` entry point
"""

# Single source of truth: read the version the package was INSTALLED with, so the
# number in a metadata sidecar always matches the code that produced the image.
# It used to be hardcoded here and also declared in pyproject.toml — the two drifted
# and every sidecar recorded the stale one.
from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("generate-image")
except PackageNotFoundError:          # running from a source tree, not installed
    __version__ = "0+unknown"
