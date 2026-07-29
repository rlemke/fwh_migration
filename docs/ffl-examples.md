# FFL Examples — `migration`

Every numbered scenario on this page is a **complete, compilable FFL file**. Copy one
into `my.ffl` and run it against this domain's FFL:

```bash
fw ffl run --primary my.ffl \
  --library ~/fw_handlers/fwh_migration/src/migration/ffl/migration.ffl \
  --workflow my.migration.<WorkflowName>
```

A runner that serves the `migration` namespace must be up
(`fw runner start --domain migration`). Every block below is compile-checked
against `src/migration/ffl/migration.ffl`.

New to the language? Read [the FFL grammar](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md)
and the [canonical examples](https://github.com/rlemke/facetwork/tree/main/examples/canonical)
first — this page is the domain-specific companion to them.

---

## The facets at a glance

| Declaration | Signature | Does |
|---|---|---|
| `migration.sources.DownloadMigration` | `(force: Boolean = false) => (country_count: Int)` | World Bank `SM.POP.NETM` + `SP.POP.TOTL` for every country, 1960–2025 → cached series |
| `migration.maps.BuildMigrationMap` | `() => (html_path, geojson_path, country_count, year_min, year_max)` | Join onto Natural Earth geometry → per-1,000 rate → diverging year-slider choropleth |
| `migration.workflows.BuildMigrationWorldMap` | `(force: Boolean = false) => (status, html_path, country_count)` | The shipped entry point: download → build |

Both facets are `event facet`s — they run in a handler on a runner, not in the
compiler. Their `with Effect(...)` / `with Cost(...)` mixins are what
`fw_capabilities(effect=…, max_cost=…)` filters on.

---

## 1. Run what ships — no FFL to write

The domain already contains one entry-point workflow, so the fastest path is to run
it. Three equivalent front doors:

```bash
# a) seed it once, then run it by name from the CLI
fw ffl seed --include migration
fw ffl run --primary ~/fw_handlers/fwh_migration/src/migration/ffl/migration.ffl \
  --workflow migration.workflows.BuildMigrationWorldMap \
  --inputs '{"force": false}'

# b) dashboard: http://localhost:8080 → New run → BuildMigrationWorldMap
# c) MCP (from Claude): fw_catalog_match / fw_execute_workflow
```

Write FFL when you want to **change the shape** of the run — different sequencing,
error handling, extra steps, or composition with another domain. That is what the
rest of this page shows.

## 2. The smallest workflow you can write

The shipped workflow, by hand. Note the three things every FFL workflow needs: a
`namespace`, `use` for each namespace you call into, and a `yield` back to the
containing workflow.

```ffl
namespace my.migration {

    use migration.sources
    use migration.maps

    /** Download the World Bank series, then render the world map. */
    workflow MyMigrationMap() => (html_path: String, countries: Int) andThen {

        data = migration.sources.DownloadMigration(force = false)

        map = migration.maps.BuildMigrationMap() after data

        yield MyMigrationMap(html_path = map.html_path, countries = map.country_count)
    }
}
```

Three rules that trip people up, all visible above:

- `=>` must sit on the **same line** as the closing `)` of the parameter list.
- References are always `step.field` — `map.html_path`, never a bare `map`.
- `$.x` reads the **container's** attributes (here, the workflow's params); a step's
  own results are read by step name.

## 3. Parameters and `$` — pass a refresh flag through

`$.force` is the workflow's own parameter. `$` always means "my immediate
container", so inside a workflow body it is the workflow, and inside a step body it
is that step (`$$` walks one level out).

```ffl
namespace my.migration {

    use migration.sources
    use migration.maps

    /** Rebuild the map, optionally bypassing the World Bank cache. */
    workflow RefreshMigrationMap(force: Boolean = false) => (status: String, html_path: String) andThen {

        data = migration.sources.DownloadMigration(force = $.force)

        map = migration.maps.BuildMigrationMap() after data

        yield RefreshMigrationMap(status = "completed", html_path = map.html_path)
    }
}
```

Run it with `--inputs '{"force": true}'`.

## 4. Sequencing two steps that share no data

`BuildMigrationMap` reads the *cache* the download wrote — it needs no value from
it. But steps with no reference between them may run in any order (and in
parallel). The `after` clause makes the dependency explicit: name the upstream
step, and the runtime pins the order.

```ffl
namespace my.migration {

    use migration.sources
    use migration.maps

    /** Ordering is created by the reference, not by line order. */
    workflow OrderedBuild() => (html_path: String) andThen {

        data = migration.sources.DownloadMigration()

        // referencing data.country_count is what makes this run second
        map = migration.maps.BuildMigrationMap() after data

        yield OrderedBuild(html_path = map.html_path)
    }
}
```

## 5. Call-time mixins — timeouts, retries, credentials

A facet declares its defaults (`with Timeout(minutes = 10)` on both facets here);
the **call site** can add or override mixins for one particular use. This is the
main knob for tuning a shared facet to your run without forking it.

```ffl
namespace my.migration {

    use migration.sources
    use migration.maps

    /** Be patient with the World Bank API, and retry it twice. */
    workflow ResilientMigrationMap() => (html_path: String) andThen {

        data = migration.sources.DownloadMigration(force = true) with Timeout(minutes = 30) with Retry(maxAttempts = 3, backoffSeconds = 60)

        map = migration.maps.BuildMigrationMap() with Timeout(minutes = 15) after data

        yield ResilientMigrationMap(html_path = map.html_path)
    }
}
```

## 6. Survive a failed download with `catch`

`catch` attaches to a step and runs when that step errors after its retries are
exhausted. A `catch` block that yields ends the workflow with a partial result
instead of a hard failure — the pattern the `save_earth` domain uses for every
external download.

```ffl
namespace my.migration {

    use migration.sources
    use migration.maps

    /** Report a partial result instead of failing the run. */
    workflow BestEffortMap() => (status: String, html_path: String) andThen {

        data = migration.sources.DownloadMigration(force = true) catch {
            yield BestEffortMap(status = "download_failed", html_path = "")
        }

        map = migration.maps.BuildMigrationMap() after data

        yield BestEffortMap(status = "completed", html_path = map.html_path)
    }
}
```

## 7. Branch on a result with `when`

A `when` block hangs off the step whose result it inspects. Inside a case, `$` is
that step — so `$.country_count` is the download's return — and `$$` reaches the
workflow's own parameters. Every `when` needs a default case, and it must come last.

```ffl
namespace my.migration {

    use migration.sources
    use migration.maps

    /** Only render if the download actually returned a world's worth of countries. */
    workflow GuardedMap(min_countries: Int = 100) => (status: String, html_path: String) andThen {

        data = migration.sources.DownloadMigration() andThen when {
            case $.country_count >= $$.min_countries => {
                map = migration.maps.BuildMigrationMap()
                yield GuardedMap(status = "completed", html_path = map.html_path)
            }
            case _ => {
                yield GuardedMap(status = "too_few_countries", html_path = "")
            }
        }
    }
}
```

## 8. Reuse the shipped workflow from your own

Workflows compose like facets — call `BuildMigrationWorldMap` as a step and build
on top of its results. This is the cheapest way to extend a domain: don't fork its
workflow, wrap it.

```ffl
namespace my.migration {

    use migration.workflows

    /** Wrap the shipped workflow and re-shape its result. */
    workflow MigrationWithSummary() => (headline: String) andThen {

        built = migration.workflows.BuildMigrationWorldMap(force = false)

        yield MigrationWithSummary(
            headline = "net-migration map covers " ++ built.status)
    }
}
```

## 9. Compose across domains — publish the map

Facets from different domains compose in one workflow as long as a runner in the
fleet serves each namespace. Here the map is built by `migration` and published to
GitHub Pages by `census.Publish` (the generic publisher every map domain reuses).

```ffl
namespace my.migration {

    use migration.sources
    use migration.maps
    use census.Publish

    /** Build the map, then push it to the public maps site. */
    workflow BuildAndPublish(repo: String = "rlemke/facetwork-maps") => (pages_url: String) andThen {

        data = migration.sources.DownloadMigration()

        map = migration.maps.BuildMigrationMap() after data

        published = census.Publish.PublishWebBundle(
            repo = $.repo,
            prefixes = ["migration/output"],
            dests = ["world/net-migration"],
            labels = ["World net migration"],
            landing_title = "Facetwork maps")

        yield BuildAndPublish(pages_url = published.pages_url)
    }
}
```

Compile this one with **both** domains as libraries:

```bash
fw ffl run --primary my.ffl \
  --library ~/fw_handlers/fwh_migration/src/migration/ffl/migration.ffl \
  --library ~/fw_handlers/fwh_census_us/src/census_us/ffl/census.ffl \
  --workflow my.migration.BuildAndPublish
```

---

## Cheat sheet

| You want to… | Write |
|---|---|
| Read a workflow/step parameter | `$.name` (`$$.name` one level out) |
| Read a previous step's result | `stepname.field` |
| Order two independent steps | reference a field of the first from the second |
| Give one call more time / retries | `… with Timeout(minutes = 30) with Retry(maxAttempts = 3, backoffSeconds = 60)` |
| Handle a step failure | `step = Facet(…) catch { yield … }` |
| Branch | `step = Facet(…) andThen when { case <bool> => { … } case _ => { … } }` |
| Fan out over a list | `workflow W(items: Json) … andThen foreach item in $.items { … }` |
| Concatenate strings | `a ++ b` |

**Validate before you run:** `afl my.ffl --check`, or `fw_validate` from MCP. Every
error carries a `rule_id`; fetch `fw://docs/rules/{rule_id}` for a paired
wrong/right example.

## See also

- [`docs/README.md`](README.md) — per-feature specs for this domain
- [`docs/workflow.md`](workflow.md) — what the shipped workflow does, step by step
- [FFL grammar](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md) ·
  [canonical examples](https://github.com/rlemke/facetwork/tree/main/examples/canonical) ·
  [relative `$`-scoping](https://github.com/rlemke/facetwork/blob/main/docs/architecture/ffl-relative-scoping.md)
- `src/migration/ffl/migration.ffl` — the source of truth for every signature above
