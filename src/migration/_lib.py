"""World Bank net-migration world map — download, join, render (year slider).

Pipeline (all backend-aware via :mod:`migration.storage`):

1. ``download_migration`` — fetch the World Bank **Net migration**
   (``SM.POP.NETM``) and **Total population** (``SP.POP.TOTL``) indicators for
   every country, 1960-2025, from the open World Bank API (one call each, no
   token), and cache a compact per-country series JSON.
2. ``build_migration_map`` — join the series onto Natural Earth country geometry
   by ISO3, compute **net migration per 1,000 population** for each year, and
   render a diverging MapLibre world choropleth with a YEAR SLIDER + play:
   green = net immigration (a country gains people), red = net emigration (loses
   people). A provenance footer + "About this data" modal match the gallery.

Net migration is immigrants minus emigrants: a positive value means more people
arrived than left that year; negative means more left than arrived. It is the
single openly-fetchable metric with the longest global history (~65 years).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from html import escape

from . import storage as cstore

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

logger = logging.getLogger("migration")

WB_BASE = "https://api.worldbank.org/v2"
NET_INDICATOR = "SM.POP.NETM"   # Net migration (immigrants - emigrants)
POP_INDICATOR = "SP.POP.TOTL"   # Total population
YEAR_MIN, YEAR_MAX = 1960, 2025
WORLD_GEOJSON_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_admin_0_countries.geojson"
)
FFL_URL = "https://github.com/rlemke/fwh_migration/blob/main/src/migration/ffl/migration.ffl"
USER_AGENT = "facetwork-migration/1.0 (+https://github.com/rlemke/facetwork)"

# World Bank ISO3 → Natural Earth join code (only the few that differ).
ISO_ALIASES = {"XKX": "KOS"}

# Diverging ramp on net migration per 1,000 population. Fixed symmetric domain so
# colours are comparable across years (the animation stays meaningful): dark red
# = strong net emigration, white ~ balanced, dark green = strong net immigration.
RATE_DOMAIN = 25.0
RAMP = [
    [-25.0, "#67001f"], [-10.0, "#b2182b"], [-3.0, "#ef8a62"],
    [0.0, "#f7f7f7"],
    [3.0, "#7fbf7b"], [10.0, "#1b7837"], [25.0, "#00441b"],
]
NODATA = "#e0e0e0"


@dataclass
class MigrationMapResult:
    geojson_path: str
    html_path: str
    country_count: int
    year_min: int
    year_max: int


# ---------------------------------------------------------------------------
# Download + cache
# ---------------------------------------------------------------------------


def _fetch_indicator(indicator: str) -> dict[str, dict[str, float]]:
    """Return {iso3: {year: value}} for a World Bank indicator, all countries."""
    if requests is None:
        raise RuntimeError("requests is required to fetch World Bank data")
    url = f"{WB_BASE}/country/all/indicator/{indicator}"
    params = {"format": "json", "per_page": 25000, "date": f"{YEAR_MIN}:{YEAR_MAX}"}
    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=(30, 120))
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise RuntimeError(f"World Bank {indicator}: unexpected response shape")
    out: dict[str, dict[str, float]] = {}
    names: dict[str, str] = {}
    for row in payload[1]:
        iso = row.get("countryiso3code")
        val = row.get("value")
        yr = row.get("date")
        if not iso or val is None or yr is None:
            continue
        out.setdefault(iso, {})[yr] = float(val)
        names[iso] = (row.get("country") or {}).get("value", iso)
    logger.info("World Bank %s: %d entities", indicator, len(out))
    _fetch_indicator._names = names  # type: ignore[attr-defined]
    return out


def download_migration(*, force: bool = False) -> int:
    """Fetch net-migration + population series and cache. Returns country count."""
    cache_key = cstore.join(cstore.cache_root(), "migration-series.json")
    if not force and cstore.exists(cache_key):
        with cstore.open_read(cache_key) as f:
            blob = json.load(f)
        return len(blob.get("countries", {}))

    net = _fetch_indicator(NET_INDICATOR)
    names = dict(getattr(_fetch_indicator, "_names", {}))
    pop = _fetch_indicator(POP_INDICATOR)

    countries: dict[str, dict] = {}
    for iso, series in net.items():
        countries[iso] = {
            "name": names.get(iso, iso),
            "net": series,
            "pop": pop.get(iso, {}),
        }
    blob = {"indicator": NET_INDICATOR, "year_min": YEAR_MIN, "year_max": YEAR_MAX,
            "countries": countries}
    with cstore.open_write(cache_key, "w") as f:
        json.dump(blob, f, separators=(",", ":"))
    logger.info("cached net-migration series: %d entities", len(countries))
    return len(countries)


def _load_series() -> dict:
    cache_key = cstore.join(cstore.cache_root(), "migration-series.json")
    if not cstore.exists(cache_key):
        raise RuntimeError("migration series not cached — run DownloadMigration first")
    with cstore.open_read(cache_key) as f:
        return json.load(f)


def _world_geojson() -> dict:
    cache_key = cstore.join(cstore.cache_root(), "world-countries.geojson")
    if cstore.exists(cache_key):
        with cstore.open_read(cache_key) as f:
            return json.load(f)
    if requests is None:
        raise RuntimeError("requests is required to download world geometry")
    resp = requests.get(WORLD_GEOJSON_URL, headers={"User-Agent": USER_AGENT}, timeout=(30, 120))
    resp.raise_for_status()
    gj = resp.json()
    with cstore.open_write(cache_key, "w") as f:
        json.dump(gj, f, separators=(",", ":"))
    return gj


# ---------------------------------------------------------------------------
# Join + build
# ---------------------------------------------------------------------------


def build_migration_map(*, force: bool = False) -> MigrationMapResult:
    """Join the cached series onto world geometry + render the year-slider map."""
    blob = _load_series()
    countries = blob["countries"]
    # Re-key by the Natural Earth join code (apply the WB→NE ISO aliases).
    by_iso = {ISO_ALIASES.get(iso, iso): rec for iso, rec in countries.items()}
    world = _world_geojson()

    years = list(range(YEAR_MIN, YEAR_MAX + 1))
    matched = 0
    for ft in world["features"]:
        props = ft["properties"]
        name = props.get("NAME", "")
        iso = props.get("ISO_A3")
        if not iso or iso == "-99":
            iso = props.get("ADM0_A3")
        rec = by_iso.get(iso)
        new: dict[str, object] = {}
        if rec:
            matched += 1
            net = rec.get("net", {})
            pop = rec.get("pop", {})
            for y in years:
                ys = str(y)
                v = net.get(ys)
                if v is None:
                    continue
                new[f"c_{y}"] = int(round(v))          # net count that year
                p = pop.get(ys)
                if p and p > 0:
                    new[f"r_{y}"] = round(v / p * 1000.0, 2)  # net per 1,000 people
        ft["properties"] = {"NAME": name, **new}

    fc = {"type": "FeatureCollection", "features": world["features"]}
    html = _render_html(fc, years=years)

    out_dir = cstore.output_root()
    geojson_path = cstore.join(out_dir, "migration.geojson")
    html_path = cstore.join(out_dir, "index.html")
    with cstore.open_write(geojson_path, "w") as f:
        json.dump(fc, f, separators=(",", ":"))
    with cstore.open_write(html_path, "w") as f:
        f.write(html)
    logger.info("migration map: %d countries matched, %d-%d", matched, YEAR_MIN, YEAR_MAX)
    return MigrationMapResult(geojson_path, html_path, matched, YEAR_MIN, YEAR_MAX)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _attribution() -> str:
    from datetime import UTC, datetime
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    call = "migration.workflows.BuildMigrationWorldMap"
    return (
        '<div style="position:fixed;bottom:10px;left:10px;z-index:9999;'
        "background:rgba(255,255,255,0.92);border-radius:6px;padding:6px 10px;"
        "box-shadow:0 1px 4px rgba(0,0,0,0.2);font:11px system-ui,sans-serif;color:#444;"
        'max-width:460px">Generated by Facetwork workflow '
        '<code style="background:#f0f0f0;padding:0 3px;border-radius:3px">'
        f"{escape(call)}</code> &middot; "
        f'<a href="{escape(FFL_URL)}" target="_blank" rel="noopener" '
        'style="color:#1565c0;text-decoration:none">view FFL</a>'
        f' &middot; <a href="{escape(FFL_URL.split("/blob/")[0])}" target="_blank" '
        'rel="noopener" style="color:#1565c0;text-decoration:none">source repo</a>'
        f" &middot; generated {ts}</div>"
    )


def _search_css() -> str:
    return (
        ".rsearch{position:absolute;top:10px;left:50%;transform:translateX(-50%);"
        "z-index:6;width:300px;max-width:70%}"
        ".rsearch input{width:100%;box-sizing:border-box;padding:7px 11px;border:1px solid #aaa;"
        "border-radius:6px;font-size:13px;box-shadow:0 2px 6px rgba(0,0,0,.2)}"
        ".rsearch .res{background:#fff;border-radius:0 0 6px 6px;box-shadow:0 2px 6px rgba(0,0,0,.2);"
        "max-height:240px;overflow:auto}"
        ".rsearch .res div{padding:6px 11px;cursor:pointer;font-size:12px;border-top:1px solid #f0f0f0}"
        ".rsearch .res div:hover{background:#f3f3f3}"
    )


def _search_box() -> str:
    return (
        '<div class="rsearch"><input id="rsin" placeholder="Find a country by name…" '
        'autocomplete="off"><div class="res" id="rsres"></div></div>'
    )


def _search_js() -> str:
    return (
        "(function(){"
        "function fbbox(g){let a=[180,90,-180,-90];const w=c=>{if(typeof c[0]==='number'){"
        "a[0]=Math.min(a[0],c[0]);a[1]=Math.min(a[1],c[1]);a[2]=Math.max(a[2],c[0]);a[3]=Math.max(a[3],c[1]);}"
        "else c.forEach(w);};w(g.coordinates);return a;}"
        "const idx=DATA.features.map(f=>({n:String((f.properties||{})['NAME']||''),f})).filter(x=>x.n);"
        "const inp=document.getElementById('rsin'),res=document.getElementById('rsres');if(!inp)return;"
        "inp.addEventListener('input',()=>{const q=inp.value.trim().toLowerCase();res.innerHTML='';"
        "if(q.length<2)return;"
        "idx.filter(x=>x.n.toLowerCase().includes(q)).slice(0,12).forEach(x=>{"
        "const d=document.createElement('div');d.textContent=x.n;"
        "d.addEventListener('click',()=>{const b=fbbox(x.f.geometry);"
        "map.fitBounds([[b[0],b[1]],[b[2],b[3]]],{padding:40,maxZoom:6,duration:700});"
        "res.innerHTML='';inp.value=x.n;popupFor(x.f,[(b[0]+b[2])/2,(b[1]+b[3])/2]);});res.appendChild(d);});});"
        "document.addEventListener('click',e=>{if(!e.target.closest('.rsearch'))res.innerHTML='';});"
        "})();"
    )


def _modal_css() -> str:
    return (
        ".infobtn{margin-top:8px;width:100%;padding:7px;font-size:13px;cursor:pointer;"
        "background:#fff8e1;border:1px solid #f6c343;border-radius:4px;color:#5d4b00}"
        ".infobtn:hover{background:#fff2c4}"
        ".modal{position:absolute;inset:0;z-index:5;background:rgba(0,0,0,.45);display:flex;"
        "align-items:center;justify-content:center}"
        ".modalcard{background:#fff;max-width:460px;margin:16px;padding:18px 20px 20px;"
        "border-radius:10px;box-shadow:0 4px 24px rgba(0,0,0,.4);position:relative;"
        "font:13px/1.5 system-ui,sans-serif;max-height:80vh;overflow:auto}"
        ".modalcard h2{margin:0 0 8px;font-size:16px} .modalbody{color:#333} .modalbody b{color:#111}"
        ".modalclose{position:absolute;top:6px;right:10px;border:none;background:none;font-size:24px;"
        "line-height:1;cursor:pointer;color:#999} .modalclose:hover{color:#444}"
    )


def _about_html() -> str:
    repo = escape(FFL_URL.split("/blob/")[0])
    return (
        '<p style="margin:0 0 10px"><b>Net migration</b> is immigrants minus emigrants: '
        "shaded <b style='color:#1b7837'>green</b> where more people arrive than leave (net "
        "immigration) and <b style='color:#b2182b'>red</b> where more leave than arrive (net "
        "emigration), per 1,000 population. Drag the year slider (1960–2025) or press play; "
        "click a country for its numbers and history.</p>"
        '<p style="margin:0 0 10px"><b>Source:</b> World Bank — Net migration '
        "(<code>SM.POP.NETM</code>) and Total population (<code>SP.POP.TOTL</code>), derived "
        "from the UN World Population Prospects. Values are estimates; ~65 years is the longest "
        "openly-available global migration series (consistent per-country data does not exist "
        "for the early 20th century).</p>"
        '<p style="margin:0">Generated by Facetwork workflow '
        "<code>migration.workflows.BuildMigrationWorldMap</code> &middot; "
        f'<a href="{escape(FFL_URL)}" target="_blank" rel="noopener">view FFL</a> &middot; '
        f'<a href="{repo}" target="_blank" rel="noopener">source repo</a>.</p>'
    )


def _modal_markup() -> str:
    return (
        '<div id="infomodal" class="modal"><div class="modalcard">'
        '<button id="infoclose" class="modalclose">&times;</button>'
        '<h2>About this data</h2>'
        f'<div class="modalbody">{_about_html()}</div></div></div>'
    )


def _modal_js() -> str:
    return (
        "const _im=document.getElementById('infomodal');"
        "if(_im){const ib=document.getElementById('infobtn'),ic=document.getElementById('infoclose');"
        "if(ib)ib.onclick=()=>{_im.style.display='flex';};"
        "if(ic)ic.onclick=()=>{_im.style.display='none';};"
        "_im.onclick=e=>{if(e.target===_im)_im.style.display='none';};}"
    )


def _render_html(fc: dict, *, years: list[int]) -> str:
    data_js = json.dumps(fc, separators=(",", ":"))
    ramp_js = json.dumps(RAMP)
    y0, y1 = years[0], years[-1]
    # decade anchors for the per-country history row in the popup
    decades = [y for y in years if y % 10 == 0] + ([y1] if y1 % 10 else [])
    decades_js = json.dumps(sorted(set(decades)))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Net migration by country, {y0}-{y1}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  html,body,#map{{margin:0;height:100%;width:100%;font-family:system-ui,sans-serif}}
  .panel{{position:absolute;z-index:1;background:rgba(255,255,255,.94);padding:10px 12px;
    border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);font-size:12px}}
  #ctl{{top:10px;left:10px;max-width:340px}}
  #ctl h3{{margin:0 0 6px;font-size:14px}}
  #legend{{bottom:18px;right:10px}}
  #legend .bar{{height:12px;width:220px;border-radius:2px;margin:5px 0 2px;
    background:linear-gradient(to right,#67001f,#b2182b,#ef8a62,#f7f7f7,#7fbf7b,#1b7837,#00441b)}}
  #legend .tk{{display:flex;justify-content:space-between;font-size:10px;color:#555}}
  #tl{{bottom:14px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:10px;
    width:min(560px,80vw)}}
  #tl input[type=range]{{flex:1}} #tl #yr{{font-weight:700;min-width:46px;text-align:center}}
  #tl button{{border:1px solid #aaa;background:#fff;border-radius:5px;padding:4px 10px;cursor:pointer;font-size:14px}}
  .maplibregl-popup-content{{max-width:300px;font-size:12px}}
  .maplibregl-popup-content h4{{margin:0 0 4px;font-size:13px}}
  table.m{{border-collapse:collapse;margin-top:4px}} table.m td{{padding:1px 6px 1px 0}}
  table.m td.v{{text-align:right}}
  {_search_css()}
  {_modal_css()}
</style></head>
<body>
<div id="map"></div>
{_search_box()}
<div id="ctl" class="panel">
  <h3>Net migration by country</h3>
  <div style="color:#555">Immigrants minus emigrants, per 1,000 people.
  <b style="color:#1b7837">Green</b> = a country gains people (net immigration);
  <b style="color:#b2182b">red</b> = it loses people (net emigration). Move the year
  slider or press play; click a country for details. Source: World Bank.</div>
  <button id="infobtn" class="infobtn">&#8505;&#65039; About this data</button>
</div>
<div id="legend" class="panel">
  <b>Net migration / 1,000</b><div class="bar"></div>
  <div class="tk"><span>−{int(RATE_DOMAIN)} (leaving)</span><span>0</span><span>+{int(RATE_DOMAIN)} (arriving)</span></div>
</div>
<div id="tl" class="panel">
  <button id="play" title="Play">&#9654;</button>
  <span id="yr">{y1}</span>
  <input id="year" type="range" min="{y0}" max="{y1}" step="1" value="{y1}">
</div>
{_modal_markup()}
{_attribution()}
<script>
const DATA={data_js}, RAMP={ramp_js}, DECADES={decades_js};
const Y0={y0}, Y1={y1};
let year={y1};
const fmtc=v=>(v===null||v===undefined)?'—':(v>0?'+':'')+Math.round(v).toLocaleString();
const fmtr=v=>(v===null||v===undefined)?'—':(v>0?'+':'')+(Math.round(v*10)/10)+' /1k';
function colorExpr(y){{
  const k='r_'+y;
  const expr=['interpolate',['linear'],['get',k]];
  for(const [t,c] of RAMP) expr.push(t,c);
  return ['case',['==',['get',k],null],'{NODATA}',expr];
}}
const map=new maplibregl.Map({{container:'map',style:{{version:8,
  sources:{{bm:{{type:'raster',tiles:['https://a.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png','https://b.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png'],tileSize:256,attribution:'&copy; OpenStreetMap &copy; CARTO &middot; World Bank'}}}},
  layers:[{{id:'bm',type:'raster',source:'bm'}}]}},center:[14,20],zoom:1.4}});
map.addControl(new maplibregl.NavigationControl());
const slider=document.getElementById('year'), ylab=document.getElementById('yr');
function popupFor(f,lngLat){{
  const p=f.properties||{{}};
  let hist=''; for(const d of DECADES){{ const v=p['c_'+d];
    hist+=`<tr><td>${{d}}</td><td class="v">${{fmtc(v)}}</td></tr>`; }}
  const r=p['r_'+year], c=p['c_'+year];
  new maplibregl.Popup({{closeButton:true,maxWidth:'300px'}}).setLngLat(lngLat)
    .setHTML(`<h4>${{p.NAME||'Country'}}</h4>`
      +`<table class="m"><tr><td>Net migration ${{year}}</td><td class="v">${{fmtc(c)}}</td></tr>`
      +`<tr><td>per 1,000 people</td><td class="v">${{fmtr(r)}}</td></tr></table>`
      +`<div style="margin-top:5px;color:#555">Net migration (count) by decade:</div>`
      +`<table class="m">${{hist}}</table>`).addTo(map);
}}
map.on('load',()=>{{
  map.addSource('c',{{type:'geojson',data:DATA}});
  map.addLayer({{id:'fill',type:'fill',source:'c',paint:{{'fill-color':colorExpr(year),'fill-opacity':0.85}}}});
  map.addLayer({{id:'line',type:'line',source:'c',paint:{{'line-color':'#888','line-width':0.3}}}});
  function apply(){{ ylab.textContent=year; map.setPaintProperty('fill','fill-color',colorExpr(year)); }}
  slider.oninput=()=>{{ year=+slider.value; apply(); }};
  map.on('click','fill',e=>popupFor(e.features[0],e.lngLat));
  map.on('mouseenter','fill',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','fill',()=>map.getCanvas().style.cursor='');
  // play/pause the year animation
  let timer=null; const btn=document.getElementById('play');
  btn.onclick=()=>{{ if(timer){{clearInterval(timer);timer=null;btn.innerHTML='&#9654;';return;}}
    btn.innerHTML='&#10073;&#10073;';
    timer=setInterval(()=>{{ year=year>=Y1?Y0:year+1; slider.value=year; apply();
      if(year>=Y1){{}} }},450); }};
}});
{_search_js()}
{_modal_js()}
</script></body></html>"""
