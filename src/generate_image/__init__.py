"""generate-image — multi-provider image generation with a DAG scheduler.

Public modules:
  * cli          — CLI + orchestration (provider_generate/provider_edit, main)
  * providers    — provider registry (dialects + reliability policy)
  * reliability  — pooled httpx client, billing-aware retry, rate limit, AIMD
  * dag          — task-graph engine (graphlib parallel scheduler) + spec loader
  * list_models  — `generate-image-models` entry point
"""

__version__ = "2.0.0"
