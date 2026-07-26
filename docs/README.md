# Migration — Feature Specifications

This directory holds one **spec per feature** of the `fwh_migration` domain — a
world net-migration choropleth with a year slider (1960–2025). Each document
follows a common shape ([`SPEC_TEMPLATE.md`](SPEC_TEMPLATE.md)) and states, for that
feature: how it works, whether it **fans out** (this domain is small and world-scale
— it doesn't), the **data & fields** it keys on, the **external libraries** it
relies on, its **facets & workflows**, and its **cache/output**. Claims are grounded
in the FFL `/** … */` docstrings, the handler code, and `_lib.py` / `storage.py` —
the source of truth for each facet remains its FFL docstring; these specs are the
feature-level narrative over them.

**Start here:** [**Map Rendering**](map-rendering.md) — the flagship feature (the
ISO3 join, per-year rate, and the diverging year-slider MapLibre choropleth that is
the whole point of the domain).

## Pipeline

| Spec | What it covers |
|------|----------------|
| [data-sources.md](data-sources.md) | **Ingest.** World Bank Net migration (`SM.POP.NETM`) + Total population (`SP.POP.TOTL`) — two keyless API calls, reshaped to `{iso3: {year: value}}` and cached as `migration-series.json`. |
| [map-rendering.md](map-rendering.md) | **Flagship.** Join the series onto Natural Earth geometry by ISO3, compute net migration per 1,000, and render the diverging year-slider + play choropleth (`c_<year>`/`r_<year>` props, search box, decade-history popup, About modal). |
| [workflow.md](workflow.md) | The single entry-point workflow `BuildMigrationWorldMap` (download → build, sequenced via `dependency_signal`), domain discovery, and the out-of-repo `PublishToSite` step. |

## Cross-cutting

| Spec | What it covers |
|------|----------------|
| [storage-and-cache.md](storage-and-cache.md) | Backend-aware paths (`storage.py`): local disk vs shared MinIO/S3, the `cache/migration/{cache,output}` roots, stage-local-finalize-on-close writes, and the env overrides. |

---

*See also the repo [`README.md`](../README.md) (data provenance, honest scope, run
instructions) and the FFL source at
[`src/migration/ffl/migration.ffl`](../src/migration/ffl/migration.ffl). The
live/queryable interface is the MCP `fw_capabilities` / `fw_describe_handler`
tools.*
