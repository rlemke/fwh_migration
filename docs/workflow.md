# Workflow — `BuildMigrationWorldMap` composition & publish

**Namespace:** `migration.workflows` ·
**FFL:** `src/migration/ffl/migration.ffl` (`BuildMigrationWorldMap`) ·
**Handlers:** none of its own (composes `migration.sources` + `migration.maps`) ·
**Entry point:** `src/migration/__init__.py` (`domain = DomainPackage(...)`)

## Overview

`BuildMigrationWorldMap` is the single **entry-point workflow** — the thing the
dashboard "New run" screen and `fw ffl run` invoke. It wires the two event facets
into a strictly-ordered two-step pipeline (download → build) and yields a small
status summary. There is one workflow; the domain is deliberately a single-map
pipeline.

## How it works

From the FFL `andThen` block:

```
workflow BuildMigrationWorldMap(force: Boolean = false)
    => (status: String, html_path: String, country_count: Int) andThen {
    data = DownloadMigration(force = $.force)
    map  = BuildMigrationMap()
    yield BuildMigrationWorldMap(
        status = "completed",
        html_path = map.html_path,
        country_count = map.country_count)
}
```

1. `data = DownloadMigration(force = $.force)` — fetch + cache the World Bank
   series (see [data-sources](data-sources.md)). `$.force` threads the workflow
   parameter through.
2. `map = BuildMigrationMap() after data` — the render
   ([map-rendering](map-rendering.md)). The two steps exchange no value (the render
   reads the cache the download wrote), so the compiler cannot infer the order; the
   `after` clause states it, forcing step 2 to run only once step 1 completes.
3. `yield BuildMigrationWorldMap(status="completed", html_path=map.html_path,
   country_count=map.country_count)` — the workflow's return surface.

## Fan-out

**Single-task, two sequential steps — no fan-out.** The dependency edge makes it
strictly serial; neither step fans out (whole-world bulk fetch, one render pass).

## Data & fields

- **Input:** `force: Boolean = false` — the only knob; forces a fresh World Bank
  download (see the `force` caveats in [data-sources](data-sources.md) and
  [map-rendering](map-rendering.md)).
- **Output:** `status: String` (always `"completed"` on success),
  `html_path: String` (the rendered `index.html`), `country_count: Int` (countries
  matched by the render's join).

## External libraries / binaries

None of its own — it is pure composition FFL. Its transitive deps are those of the
two facets it calls (`requests`; MapLibre/CARTO in the emitted page).

## Facets & workflows

| Facet | Kind | Purpose |
|---|---|---|
| `migration.workflows.BuildMigrationWorldMap(force: Boolean = false) => (status, html_path, country_count)` | workflow (entry point) | Build the World Bank net-migration world map (year slider 1960–2025). |

The namespace `use`s `migration.sources` and `migration.maps` to bring the two
event facets into scope. No `Effect`/`Cost` mixins on the workflow itself.

## Cache / output

The workflow writes nothing directly; its artifacts are those of `BuildMigrationMap`
— `cache/migration/output/index.html` + `migration.geojson` (MinIO on the fleet).
Per the repo README, `index.html` is then published to the facetwork-maps gallery
via the **generic `PublishToSite`** facet (from the census/publish family, not
defined in this repo) → `rlemke.github.io/facetwork-maps/world/net-migration`.

## Gotchas & notes

- **Domain discovery.** `src/migration/__init__.py` exposes
  `domain = DomainPackage(name="migration", ffl_dir=.../ffl,
  register_handlers=register_all_registry_handlers)` under the
  `facetwork.domains` entry point (`pyproject.toml`), so `fw runner start --domain
  migration` and `fw ffl seed` find it. The FFL is seeded from `ffl_dir`; the two
  event handlers register from `handlers/`.
- **Publishing is out-of-repo.** `PublishToSite` is not part of `fwh_migration`; a
  full "render + publish" run composes this workflow with the shared publish facet
  (token-gated, server3-only in the fleet). This repo's workflow stops at producing
  `index.html`.
- **`status` is not a health signal.** It is a literal `"completed"` in the yield;
  failures surface as step errors / raised exceptions in the handlers, not as a
  `status` value.

## Related specs

- [data-sources](data-sources.md) — step 1 (`DownloadMigration`).
- [map-rendering](map-rendering.md) — step 2 (`BuildMigrationMap`), the flagship.
- [storage-and-cache](storage-and-cache.md) — where the composed artifacts land.
