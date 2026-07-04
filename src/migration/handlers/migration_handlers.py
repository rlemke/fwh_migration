"""Event facet handlers for the migration domain — thin layers over ``_lib``."""

from __future__ import annotations

import os
from typing import Any

from .._lib import build_migration_map, download_migration

SRC = "migration.sources"
MAPS = "migration.maps"


def handle_download_migration(params: dict[str, Any]) -> dict[str, Any]:
    """Download World Bank net-migration + population and cache the per-country series."""
    step_log = params.get("_step_log")
    try:
        n = download_migration(force=bool(params.get("force")))
        if step_log:
            step_log(f"DownloadMigration: {n} countries", level="success")
        return {"country_count": n}
    except Exception as exc:
        if step_log:
            step_log(f"DownloadMigration: {exc}", level="error")
        raise


def handle_build_migration_map(params: dict[str, Any]) -> dict[str, Any]:
    """Join the cached series onto world geometry + render the year-slider choropleth."""
    step_log = params.get("_step_log")
    try:
        res = build_migration_map()
        if step_log:
            step_log(
                f"BuildMigrationMap: {res.country_count} countries, "
                f"{res.year_min}-{res.year_max} -> {res.html_path}",
                level="success",
            )
        return {
            "html_path": res.html_path,
            "geojson_path": res.geojson_path,
            "country_count": res.country_count,
            "year_min": res.year_min,
            "year_max": res.year_max,
        }
    except Exception as exc:
        if step_log:
            step_log(f"BuildMigrationMap: {exc}", level="error")
        raise


_DISPATCH: dict[str, Any] = {
    f"{SRC}.DownloadMigration": handle_download_migration,
    f"{MAPS}.BuildMigrationMap": handle_build_migration_map,
}


def handle(payload: dict) -> dict:
    facet = payload["_facet_name"]
    handler = _DISPATCH.get(facet)
    if handler is None:
        raise ValueError(f"Unknown facet: {facet}")
    return handler(payload)


def register_handlers(runner) -> None:
    for facet_name in _DISPATCH:
        runner.register_handler(
            facet_name=facet_name,
            module_uri=f"file://{os.path.abspath(__file__)}",
            entrypoint="handle",
        )


def register_poller(poller) -> None:
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)
