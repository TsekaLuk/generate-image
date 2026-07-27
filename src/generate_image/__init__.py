"""generate-image — multi-provider image generation and bounded workflows.

Public modules:
  * cli          — CLI + orchestration (provider_generate/provider_edit, main)
  * providers    — provider registry (dialects + reliability policy)
  * reliability  — pooled httpx client, billing-aware retry, rate limit, AIMD
  * dag          — task-graph engine (graphlib parallel scheduler) + spec loader
  * flow         — bounded directed control-flow engine with cyclic routes
  * list_models  — `generate-image-models` entry point
"""

__version__ = "2.1.0"
