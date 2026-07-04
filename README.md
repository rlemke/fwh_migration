# fwh_migration

A Facetwork domain that builds a **world net-migration map over time** — a
diverging country choropleth with a **year slider (1960–2025) + play**:

- 🟢 **green** = net **immigration** (more people arrive than leave)
- 🔴 **red** = net **emigration** (more leave than arrive)

shaded by net migration **per 1,000 population**, so small countries with large
relative flows show up alongside the big ones. Click any country for its net
migration count + rate that year and its by-decade history.

**Live:** [rlemke.github.io/facetwork-maps/world/net-migration](https://rlemke.github.io/facetwork-maps/world/net-migration/)

## Data

- **World Bank** — Net migration (`SM.POP.NETM`) + Total population
  (`SP.POP.TOTL`), one open API call each (no key), joined onto Natural Earth
  country geometry by ISO3. Net migration = immigrants − emigrants (a UN World
  Population Prospects–derived estimate).
- **Honest scope:** ~65 years is the longest openly-available *global* migration
  series — consistent per-country data does **not** exist for the early 20th
  century, so "100 years" isn't possible from an authoritative open source.

## Workflow

```
migration.workflows.BuildMigrationWorldMap
  ├─ migration.sources.DownloadMigration   # WB net-migration + population, cached
  └─ migration.maps.BuildMigrationMap      # join → per-year rate → year-slider HTML
```

Output → `cache/migration/output/index.html` (MinIO on the fleet), published to
the facetwork-maps gallery via the generic `PublishToSite`.

## Layout

```
src/migration/
  _lib.py            # WB fetch + ISO3 join + diverging year-slider renderer
  storage.py         # backend-aware paths (local / MinIO), shared cache
  handlers/          # thin event-facet handlers over _lib
  ffl/migration.ffl  # DownloadMigration + BuildMigrationMap + BuildMigrationWorldMap
tests/               # offline (WB API + geometry mocked)
```

## Run

```bash
pip install -e .          # requests only
python -m pytest tests/ -q
```
