<!-- SPEC TEMPLATE — every docs/<feature>.md follows this shape so the set reads
consistently. Delete this comment in real specs. Keep sections in this order;
omit a section only if it genuinely does not apply (say so in one line rather
than dropping the heading silently). Ground every claim in the actual FFL
docstrings / handler code / _lib — do not invent behaviour. -->

# <Feature Name>

**Namespace(s):** `migration.<ns>` · **FFL:** `src/migration/ffl/migration.ffl` ·
**Handlers:** `src/migration/handlers/migration_handlers.py` ·
**Library:** `src/migration/_lib.py` · **Storage:** `src/migration/storage.py`

## Overview
One or two paragraphs: what this feature is for, the request it answers, and where
it sits in the pipeline (World Bank download → ISO3 join → per-year rate → render).

## How it works
The algorithm / data flow, step by step. Name the concrete functions and the shape
of the data at each (WB JSON → `{iso3: {year: value}}` series → joined GeoJSON →
year-slider HTML). Name the indicator codes (`SM.POP.NETM`, `SP.POP.TOTL`) and the
property keys (`c_<year>` net count, `r_<year>` rate per 1,000) where relevant.

## Fan-out
Does it fan out across the fleet? This domain is small (world-scale, two sequential
steps): most features are **single-task — no fan-out**. Say so and why (one open
API call per indicator, one render pass) rather than dropping the heading.

## Data & fields
What data it reads and which fields/columns it keys on — be specific (World Bank
`countryiso3code` / `date` / `value`; Natural Earth `ISO_A3` / `ADM0_A3` / `NAME`;
the `ISO_ALIASES` bridge). Name the join key and the emitted property schema. If the
feature does no data shaping, say so.

## External libraries / binaries
Every non-stdlib dependency this feature relies on and what for — e.g. `requests`
(the only pip dependency, World Bank + Natural Earth HTTP), MapLibre GL (a CDN
`<script>`/`<link>`, **not** a pip dep), CARTO basemap tiles. Distinguish a **pip**
dependency from a **CDN/browser** one from a Facetwork-runtime import.

## Facets & workflows
The key event facets and workflows, with signatures and a one-line purpose taken
from the FFL docstrings. Mark event facets (need a handler) vs pure facets, and
note `Effect`/`Cost`/`Timeout` mixins where present.

## Cache / output
The cache/output roots from `storage.py` (`cache/migration/cache/` +
`cache/migration/output/` on the fleet, local dirs otherwise), the cache-key
filenames, and the output artifact(s) and format (series JSON / GeoJSON / HTML map).
Note whether outputs go to local disk, MinIO/S3, or the published site.

## Gotchas & notes
Known pitfalls, rate limits, honest-scope caveats, or non-obvious constraints
(worth capturing anything a future maintainer would trip on).

## Related specs
Links to the specs this feature composes with or depends on.
