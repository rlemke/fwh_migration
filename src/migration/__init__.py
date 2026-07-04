"""Migration domain — Facetwork workflow + handlers for a world net-migration map.

Builds a diverging world country choropleth with a YEAR SLIDER (1960–2025) from
the World Bank's Net migration (SM.POP.NETM) + Total population (SP.POP.TOTL)
indicators: green = net immigration (a country gains people), red = net
emigration (loses people). Discovered by the Facetwork runner via the
``facetwork.domains`` entry point in pyproject.toml::

    [project.entry-points."facetwork.domains"]
    migration = "migration:domain"
"""

from __future__ import annotations

from pathlib import Path

from facetwork.domains import DomainPackage

from .handlers import register_all_registry_handlers

domain = DomainPackage(
    name="migration",
    ffl_dir=Path(__file__).parent / "ffl",
    register_handlers=register_all_registry_handlers,
)
