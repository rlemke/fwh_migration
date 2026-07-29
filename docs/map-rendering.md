# Map Rendering — join, per-year rate & the year-slider choropleth

**Flagship spec.**

**Namespace:** `migration.maps` ·
**FFL:** `src/migration/ffl/migration.ffl` (`BuildMigrationMap`) ·
**Handler:** `src/migration/handlers/migration_handlers.py` (`handle_build_migration_map`) ·
**Library:** `src/migration/_lib.py` (`build_migration_map`, `_render_html`, `_world_geojson`) ·
**Storage:** `src/migration/storage.py`

## Overview

This is the payload feature of the domain and the reason it exists: it joins the
cached World Bank series onto **Natural Earth** country geometry, computes **net
migration per 1,000 population** for every year, and renders a single
self-contained MapLibre world choropleth with a **year slider (1960–2025) + play**.
Green = net immigration (a country gains people), red = net emigration (loses
people). The output HTML is what ships to
`rlemke.github.io/facetwork-maps/world/net-migration`.

It answers the whole user request ("show world migration over time, comparable
across small and large countries") in one render pass over the pre-fetched series.

## How it works

`build_migration_map(force=False)` (`_lib.py`):

1. **Load series.** `_load_series()` reads `migration-series.json`; if it is not
   cached it raises `RuntimeError("migration series not cached — run
   DownloadMigration first")` (the workflow guarantees ordering).
2. **Re-key by join code.** `by_iso = {ISO_ALIASES.get(iso, iso): rec ...}` applies
   the World Bank→Natural Earth ISO bridge (currently only `XKX → KOS`, Kosovo).
3. **Load geometry.** `_world_geojson()` returns Natural Earth
   `ne_110m_admin_0_countries` — from the cache if present, else one HTTP GET to
   the `natural-earth-vector` raw GeoJSON, cached on first use.
4. **Join + compute rates.** For each geometry feature it takes `ISO_A3`
   (falling back to `ADM0_A3` when `ISO_A3` is missing or `"-99"`), looks up the
   record, and for every year `1960..2025` writes two flattened properties:
   `c_<year>` = net count (`int(round(v))`) and, when population is present and
   positive, `r_<year>` = `round(v / pop * 1000, 2)` (net per 1,000 people).
   Unmatched features keep only `NAME`. `matched` counts joined countries.
5. **Render + write.** `_render_html(fc, years)` builds the page; the FeatureCollection
   is written to `migration.geojson` and the HTML to `index.html` under
   `output_root()`. Returns a `MigrationMapResult(geojson_path, html_path,
   country_count=matched, year_min, year_max)`.

Data shape: `series JSON + Natural Earth GeoJSON → flattened per-year properties →
index.html + migration.geojson`.

## Fan-out

**Single-task — no fan-out.** It is one world-scale render over ~180 country
polygons and 66 year-columns; the FFL declares one event facet with no `foreach`.
Time is dominated by the (cached) geometry download, not compute.

## Data & fields

- **Join key:** Natural Earth `ISO_A3`, with `ADM0_A3` as the fallback when
  `ISO_A3` is absent or the sentinel `"-99"` (this is how Kosovo/`KOS` and other
  disputed/limited-recognition entries join). The World Bank side is re-keyed
  through `ISO_ALIASES` before the lookup.
- **Emitted per-country properties:** `NAME` plus, per matched year, `c_<year>`
  (integer net count) and `r_<year>` (float rate per 1,000). The rate is the
  choropleth variable; the count feeds the popup and its by-decade history table.
- **Colour scale:** a fixed **diverging** ramp on the rate, symmetric domain
  `RATE_DOMAIN = 25.0` (`RAMP` from `#67001f` dark red at −25 through `#f7f7f7`
  white at 0 to `#00441b` dark green at +25). Fixed domain keeps colours comparable
  as the animation steps through years; `null`/no-data → `NODATA = "#e0e0e0"`.

## External libraries / binaries

- **`requests`** (pip) — only for the one-time Natural Earth geometry download in
  `_world_geojson()`. After first run it reads from cache.
- **MapLibre GL JS 4.7.1** — loaded in the HTML as a CDN `<script>` + `<link>`
  (`unpkg.com`); a **browser** dependency, **not** a pip dep. The renderer emits a
  fully self-contained page (the GeoJSON is inlined as `const DATA=…`).
- **CARTO Voyager raster tiles** — the basemap (`basemaps.cartocdn.com`), attributed
  to OpenStreetMap © CARTO · World Bank.
- No shapely / pyproj / GDAL — geometry is passed through untouched; only tag
  properties are rewritten. No binaries.

## Facets & workflows

| Facet | Kind | Effect / Cost / Timeout | Purpose |
|---|---|---|---|
| `migration.maps.BuildMigrationMap() => (html_path, geojson_path, country_count, year_min, year_max)` | event | `Effect(kind="io")` · `Cost(tier="cheap")` · `Timeout(minutes=10)` | Join the cached series onto Natural Earth geometry, compute net migration per 1,000 per year, and render the diverging year-slider choropleth. Callers order it with `after` — it reads the download's cache and takes no value from it. |

`handle_build_migration_map` calls `build_migration_map()` (note: it does **not**
thread `force` through — the render always rebuilds from whatever series is cached)
and returns the five result fields.

### What the rendered page contains (`_render_html` and helpers)

- **Year slider + play** — `#year` range input (`min=1960 max=2025`), a `#play`
  button that `setInterval`s at 450 ms and loops `Y0..Y1`, and a `#yr` label. Each
  step rebuilds the fill via `colorExpr(year)` (a MapLibre `interpolate` expression
  over `r_<year>`, with a `case` for `null → NODATA`).
- **Click popup** — per-country card with the selected year's count + rate and a
  **by-decade history** table (`DECADES` = every year `% 10 == 0` plus the final
  year).
- **Country search box** — `_search_box`/`_search_css`/`_search_js`: type-ahead over
  feature `NAME`, `fitBounds` to a client-computed bbox, then opens the popup.
- **"About this data" modal** (`_modal_*`) + a fixed **provenance footer**
  (`_attribution`) linking the FFL file and source repo — matches the gallery's
  "About this data" popup parity convention.

## Cache / output

- **Geometry cache key:** `cache_root()/world-countries.geojson` (Natural Earth,
  downloaded once). Same root as the series cache.
- **Outputs** (under `output_root()` — `s3://afl-cache/cache/migration/output/` on
  the fleet, `<FW_DATA_ROOT>/migration-output/` locally, override
  `FW_MIGRATION_OUTPUT_DIR`):
  - `index.html` — the self-contained year-slider map (the published artifact).
  - `migration.geojson` — the joined FeatureCollection with the flattened
    `c_<year>` / `r_<year>` properties.
- On the fleet both land in MinIO; `index.html` is what
  [workflow](workflow.md)'s `PublishToSite` pushes to the gallery.

## Gotchas & notes

- **The ordering is invisible to the compiler, so the workflow states it.**
  `BuildMigrationMap` reads the cache directly; if run before `DownloadMigration` it
  raises. Nothing flows between the two steps, so the workflow writes `after data` —
  do not call the render facet standalone on an empty cache.
- **`force` does not reach the render.** The handler ignores `force`, so re-running
  the workflow with `force=true` re-downloads the series but the geometry cache
  (`world-countries.geojson`) is only fetched if missing. Delete it to force fresh
  geometry.
- **Fixed symmetric colour domain (±25 /1,000) clips extremes.** Micro-states with
  huge relative flows (e.g. Gulf states in boom years) saturate at the ramp ends by
  design so year-to-year colours stay comparable — the popup still shows the true
  number.
- **Honest scope: ~65 years, estimates.** The About modal and README state plainly
  that consistent per-country migration data does not exist for the early 20th
  century, so "100 years" isn't achievable from an open authoritative source; values
  are UN WPP–derived estimates.
- **The ISO join is `NAME`-independent but code-dependent.** A geometry file whose
  `ISO_A3`/`ADM0_A3` disagrees with the World Bank ISO3 (beyond the one
  `ISO_ALIASES` entry) drops silently to no-data grey — extend `ISO_ALIASES` if a
  country goes missing.

## Related specs

- [data-sources](data-sources.md) — produces the `migration-series.json` this
  feature joins against.
- [workflow](workflow.md) — the composed `BuildMigrationWorldMap` and the publish
  step that ships this `index.html`.
- [storage-and-cache](storage-and-cache.md) — the cache/output roots, local vs
  MinIO, and the env overrides used above.
