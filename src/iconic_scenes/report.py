"""Static results page: site/index.html, next to the stills in site/img/."""
import html
import json
from datetime import date

from . import __version__, config, export


def card(r: dict) -> str:
    e = html.escape
    alts = "".join(f'<a href="{e(r["still_path"] + a)}" target="_blank"><img src="{e(r["still_path"] + a)}" alt="autre image candidate" loading="lazy"></a>'
                   for a in (r["alt1_file"], r["alt2_file"]) if a)
    who = f"{r['actor']} ({r['character']})" if r["character"] else r["actor"]
    return f"""
<article class="card">
  <a class="still" href="{e(r['still_path'] + r['still_file'])}" target="_blank"><img src="{e(r['still_path'] + r['still_file'])}" alt="{e(r['title'])}" loading="lazy"></a>
  <div class="body">
    <blockquote lang="{e(r['lang'])}">{e(r['quote'])}</blockquote>
    <p class="film">{e(r['title'])} <span>({e(str(r['year']))})</span></p>
    <p class="who">{e(who)}</p>
    <p class="sub"><span class="tc">{r['timecode']}</span> {e(r['subtitle_text'])}</p>
    <p class="meta">{export.SOURCES[r['source']]} · correspondance {r['match_score']:.0f} % · visages {r['faces']} · netteté {r['sharpness']:.0f} · {r['source_height']}p{' HDR→SDR' if r['hdr'] else ''} ·
      <a href="https://www.themoviedb.org/movie/{r['tmdb_id']}" target="_blank">TMDb {r['tmdb_id']}</a></p>
    <div class="alts">{alts}</div>
  </div>
</article>"""


def write() -> str:
    results = [r for r in export.rows() if r["status"] != "not run"]
    export.write()
    ok = [r for r in results if r["status"] == "ok"]
    ko = [r for r in results if r["status"] != "ok"]
    why = {"line not found": "réplique introuvable dans les sous-titres disponibles", "not in Plex": "film absent de Plex"}
    misses = "".join(f"<li><b>{html.escape(r['title'])}</b> ({r['year']}) : {why.get(r['status'], html.escape(r['status']))}</li>" for r in ko)
    page = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scènes cultes</title>
<style>
:root {{ --bg:#111; --card:#1b1b1b; --fg:#eee; --mute:#9a9a9a; --accent:#f5c518; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, sans-serif; }}
header {{ padding:28px 16px 8px; max-width:1500px; margin:auto; }}
h1 {{ margin:0 0 6px; font-size:28px; }} h1 span {{ color:var(--accent); }}
header p {{ color:var(--mute); margin:4px 0; max-width:900px; }}
main {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(min(100%, 420px), 1fr)); gap:18px; padding:16px; max-width:1500px; margin:auto; }}
.card {{ background:var(--card); border-radius:10px; overflow:hidden; display:flex; flex-direction:column; }}
.still img {{ width:100%; display:block; aspect-ratio:16/9; object-fit:cover; background:#000; }}
.body {{ padding:12px 14px 14px; }}
blockquote {{ margin:0 0 8px; font-size:18px; font-style:italic; }}
blockquote::before {{ content:"« "; color:var(--accent); }} blockquote::after {{ content:" »"; color:var(--accent); }}
.film {{ margin:0; font-weight:600; }} .film span {{ color:var(--mute); font-weight:400; }}
.who {{ margin:0 0 8px; color:var(--mute); }}
.sub {{ margin:0 0 6px; font-size:13px; color:#cfcfcf; }}
.tc {{ font-family:ui-monospace, monospace; color:var(--accent); margin-right:6px; }}
.meta {{ margin:0; font-size:12px; color:var(--mute); }} .meta a {{ color:var(--mute); }}
.alts {{ display:flex; gap:6px; margin-top:8px; }} .alts img {{ width:96px; aspect-ratio:16/9; object-fit:cover; border-radius:4px; opacity:.75; }}
.alts img:hover {{ opacity:1; }}
section.misses {{ max-width:1500px; margin:auto; padding:0 16px 40px; color:var(--mute); }}
</style></head>
<body>
<header>
  <h1>Scènes <span>cultes</span></h1>
  <p>{len(ok)} répliques célèbres retrouvées dans les films de la bibliothèque Plex, sur {len(results)} essayées, chacune avec la meilleure image de sa scène.
     Aucun modèle de langage : la réplique est alignée sur la piste de sous-titres par rapidfuzz, les images sont extraites par ffmpeg,
     et l'image retenue est choisie sur la netteté (Laplacien, Tenengrad), les visages et leur cadrage (détecteur YuNet), l'exposition et l'éloignement des changements de plan.
     Les deux vignettes sont les images classées juste après. Le minutage est celui de l'image retenue.</p>
  <p>iconic-scenes {__version__} · {date.today().isoformat()}</p>
</header>
<main>{''.join(card(r) for r in ok)}</main>
<section class="misses"><h2>Non retrouvées</h2><ul>{misses or '<li>aucune</li>'}</ul></section>
</body></html>"""
    out = config.SITE / "index.html"
    out.write_text(page, encoding="utf-8")
    return str(out)
