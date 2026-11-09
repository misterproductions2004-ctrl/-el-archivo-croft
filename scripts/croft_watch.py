#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import (
    parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlunparse,
)
import requests
from bs4 import BeautifulSoup

VERSION = "3.2"
ROOT = Path(__file__).resolve().parents[1]
HTML_FILE = ROOT / "index.html"
DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "croft_watch_seen.json"
INDEX_FILE = DATA_DIR / "archivo_croft_index.json"
REPORT_FILE = DATA_DIR / "pendiente_revision.md"

TIMEOUT = 25
RETRIES = 3
MAX_LINKS_PER_SOURCE = 120
RECENT_DAYS = 90
MIN_ARTICLE_TEXT = 240
USER_AGENT = "CroftWatch/3.2 (+editorial monitoring; human review required)"

SOURCES = [
    {
        "name": "Tomb Raider Official",
        "url": "https://www.tombraider.com/news/all",
        "domains": {"www.tombraider.com", "tombraider.com"},
        "kind": "editorial",
        "include_page": False,
        "path_ok": lambda p: (
            p.startswith("/news/")
            and p not in {
                "/news/all", "/news/community", "/news/video-games",
                "/news/collaborations", "/news/movies-and-tv",
                "/news/merch", "/news/books", "/news/cosplay",
                "/news/community-creations",
            }
            and len([part for part in p.strip("/").split("/") if part]) >= 3
        ),
    },
    {
        "name": "Crystal Dynamics",
        "url": "https://www.crystaldynamics.com/news-community/",
        "domains": {"www.crystaldynamics.com", "crystaldynamics.com"},
        "kind": "editorial",
        "include_page": False,
        "path_ok": lambda p: (
            (p.startswith("/news/") or p.startswith("/community/"))
            and len([part for part in p.strip("/").split("/") if part]) >= 2
        ),
    },
    {
        "name": "Netflix Tudum",
        "url": "https://www.netflix.com/tudum/articles/tomb-raider-legend-of-lara-croft",
        "domains": {"www.netflix.com", "netflix.com"},
        "kind": "editorial",
        "include_page": True,
        "path_ok": lambda p: (
            p.startswith("/tudum/articles/")
            and any(term in p.lower() for term in ("tomb-raider", "lara-croft"))
        ),
    },
    {
        "name": "Amazon MGM Studios",
        "url": "https://www.aboutamazon.com/news/entertainment/tomb-raider-prime-video-phoebe-waller-bridge-sophie-turner",
        "domains": {"www.aboutamazon.com", "aboutamazon.com"},
        "kind": "editorial",
        "include_page": True,
        "path_ok": lambda p: (
            p.startswith("/news/entertainment/")
            and any(term in p.lower() for term in ("tomb-raider", "lara-croft"))
        ),
    },
    {
        "name": "Aspyr - Remastered IV-VI",
        "url": "https://support.aspyr.com/hc/en-us/sections/34244769732749-Updates",
        "domains": {"support.aspyr.com"},
        "kind": "patch",
        "include_page": False,
        "path_ok": lambda p: p.startswith("/hc/en-us/articles/") and "tomb-raider" in p.lower(),
    },
    {
        "name": "Aspyr - Remastered I-III",
        "url": "https://support.aspyr.com/hc/en-us/sections/44234935752333-Updates",
        "domains": {"support.aspyr.com"},
        "kind": "patch",
        "include_page": False,
        "path_ok": lambda p: p.startswith("/hc/en-us/articles/") and "tomb-raider" in p.lower(),
    },
    {
        "name": "Tomb Raider Gear Store - Collectibles",
        "url": "https://gear.tombraider.com/collections/collectibles",
        "domains": {"gear.tombraider.com"},
        "kind": "catalog",
        "include_page": False,
        "path_ok": lambda p: p.startswith("/products/"),
    },
    {
        "name": "Tomb Raider Gear Store - Merchandise",
        "url": "https://gear.tombraider.com/collections/merch",
        "domains": {"gear.tombraider.com"},
        "kind": "catalog",
        "include_page": False,
        "path_ok": lambda p: p.startswith("/products/"),
    },
    {
        "name": "Dark Horse Digital - Tomb Raider Comics",
        "url": "https://digital.darkhorse.com/series/345/tomb-raider",
        "domains": {"digital.darkhorse.com"},
        "kind": "comics",
        "include_page": False,
        "path_ok": lambda p: p.startswith("/books/") or p.startswith("/series/345/"),
    },
]

STOP_WORDS = set("""
the and for with from this that your you tomb raider lara croft official news
update updates a an of in on to at is are by as el la los las de del y en para
con un una unos unas por para this that their into about from have has was were
""".split())

FRANCHISE_TERMS = (
    "tomb raider", "lara croft", "legacy of atlantis", "tomb raider catalyst",
    "angel of darkness", "last revelation", "survivor trilogy", "tomb raider i-iii",
    "tomb raider iv-vi", "croft manor",
)

NAVIGATION_TITLES = {
    "featured news", "news", "all news", "latest news", "community",
    "video games", "collaborations", "movies and tv", "merch", "books",
    "cosplay", "community creations", "view all", "all products",
}

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})


def now_utc():
    return datetime.now(timezone.utc)


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_text(value):
    value = (value or "").lower().replace("’", "'").replace("–", "-").replace("—", "-")
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^a-z0-9áéíóúüñ]+", " ", value)
    return clean_text(value)


def tokens(value):
    return {w for w in normalize_text(value).split() if len(w) > 2 and w not in STOP_WORDS}


def jaccard(a, b):
    aa, bb = tokens(a), tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def normalize_url(url):
    url = urldefrag(url)[0]
    p = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")
             and k.lower() not in {"fbclid", "gclid", "variant", "selling_plan"}]
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", "", urlencode(query), ""))


def request_page(url):
    last_error = None
    for attempt in range(RETRIES):
        try:
            response = session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last_error


def allowed_url(url, source):
    p = urlparse(url)
    host = p.netloc.lower().split(":")[0]
    return host in source["domains"] and source["path_ok"](p.path.lower())


def parse_datetime(raw):
    if not raw:
        return None
    raw = clean_text(raw)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def extract_date(soup):
    selectors = [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "datePublished"}),
        ("meta", {"itemprop": "datePublished"}),
        ("meta", {"name": "pubdate"}),
        ("meta", {"name": "publish-date"}),
        ("time", {}),
    ]
    for tag_name, attrs in selectors:
        for tag in soup.find_all(tag_name, attrs=attrs, limit=8):
            raw = tag.get("content") or tag.get("datetime") or tag.get_text(" ", strip=True)
            dt = parse_datetime(raw)
            if dt:
                return dt.isoformat()
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text())
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        for obj in stack:
            if isinstance(obj, dict):
                for key in ("datePublished", "dateCreated"):
                    dt = parse_datetime(obj.get(key))
                    if dt:
                        return dt.isoformat()
    return ""


def extract_page(url, source):
    response = request_page(url)
    final_url = normalize_url(response.url)
    final_host = urlparse(final_url).netloc.lower()
    if final_host not in source["domains"]:
        raise ValueError("Redireccion fuera del dominio autorizado")
    soup = BeautifulSoup(response.text, "html.parser")
    published = extract_date(soup)

    for node in soup.select("script, style, noscript, nav, footer, header, form, svg, iframe, aside"):
        node.decompose()

    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ", strip=True)) if h1 else ""
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))

    description = ""
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            description = clean_text(tag["content"])
            break

    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = clean_text(main.get_text(" ", strip=True))
    title_key = normalize_text(title)
    is_navigation = title_key in {normalize_text(x) for x in NAVIGATION_TITLES}
    content_for_hash = normalize_text(title + " " + description + " " + text)
    fingerprint = hashlib.sha256(content_for_hash.encode("utf-8")).hexdigest()

    return {
        "url": final_url, "title": title[:300], "description": description[:1200],
        "text": text[:35000], "date": published, "fingerprint": fingerprint,
        "length": len(text), "is_navigation": is_navigation,
    }


def extract_candidates(source):
    found = [source["url"]] if source.get("include_page") else []
    response = request_page(source["url"])
    soup = BeautifulSoup(response.text, "html.parser")
    for link in soup.find_all("a", href=True):
        href = normalize_url(urljoin(response.url, link["href"]))
        if allowed_url(href, source):
            found.append(href)
    unique, seen = [], set()
    for url in found:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique[:MAX_LINKS_PER_SOURCE]


def html_knowledge_index(html_path):
    if not html_path.exists():
        raise FileNotFoundError(
            f"No existe {html_path}. El HTML vigente debe estar en la raiz y llamarse index.html."
        )
    raw = html_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")
    records, seen = [], set()
    selectors = ".searchable, .relic-card, [data-kind], article.searchable, article.relic-card"

    for node in soup.select(selectors):
        heading = node.find(["h1", "h2", "h3", "h4"])
        data_title = clean_text(node.get("data-title", ""))
        title = clean_text(heading.get_text(" ", strip=True)) if heading else data_title
        if not title:
            continue
        paragraphs = []
        for el in node.find_all(["p", "li"], limit=15):
            value = clean_text(el.get_text(" ", strip=True))
            if value and value not in paragraphs:
                paragraphs.append(value)
        content = clean_text(" ".join([
            title, data_title, node.get("data-search", ""),
            node.get("data-description", ""), *paragraphs,
        ]))
        if len(content) < 45:
            continue
        key = hashlib.sha1(normalize_text(title + " " + content).encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        links = [normalize_url(urljoin("https://local.invalid", a["href"]))
                 for a in node.find_all("a", href=True)
                 if a["href"].startswith(("http://", "https://"))]
        records.append({
            "title": title[:300], "content": content[:6000],
            "kind": clean_text(node.get("data-kind", "")),
            "medium": clean_text(node.get("data-medium", "")),
            "links": links[:15],
        })

    metadata = {
        "html_file": html_path.name,
        "html_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "html_title": clean_text(soup.title.get_text(" ", strip=True)) if soup.title else "",
        "records": len(records),
        "record_method": "Solo .searchable, .relic-card y [data-kind]; sin indexar articulos/secciones generales",
        "generated_at": now_utc().isoformat(),
    }
    return metadata, records


def compare_with_encyclopedia(item, records):
    candidate_url = normalize_url(item["url"])
    candidate_title = item["title"]
    candidate_text = (candidate_title + " " + item["description"] + " " + item["text"][:5000])
    best, best_score, exact = None, 0.0, None
    candidate_tokens = tokens(candidate_title)

    for record in records:
        if candidate_url in record.get("links", []):
            exact = record
            break
        title_score = jaccard(candidate_title, record["title"])
        body_score = jaccard(candidate_text[:4500], record["content"][:4500])
        sequence_score = SequenceMatcher(None, normalize_text(candidate_title), normalize_text(record["title"])).ratio()
        shared = candidate_tokens & tokens(record["title"] + " " + record["content"][:1000])
        if len(shared) < 2 and title_score < 0.70:
            score = min(title_score, 0.25)
        else:
            score = max(title_score, (body_score * 0.65 + sequence_score * 0.35))
        if score > best_score:
            best, best_score = record, score

    if exact:
        return "DUPLICADO", 1.0, exact["title"], "La URL ya esta vinculada desde una ficha del HTML."
    if best and best_score >= 0.88:
        return "DUPLICADO", best_score, best["title"], "Coincidencia textual muy alta; revisar antes de descartar."
    if best and best_score >= 0.38:
        return "RELACIONADO", best_score, best["title"], "Hay una ficha tematicamente cercana; comprobar si aporta datos nuevos."
    return "SIN COINCIDENCIA", best_score, best["title"] if best else "", "No se encontro una ficha con relacion tematica suficiente."


def classify(item, source, match, old):
    title = normalize_text(item["title"])
    if item.get("is_navigation") or title in {normalize_text(x) for x in NAVIGATION_TITLES}:
        return "DESCARTADO", "Pagina de navegacion/categoria; no es una publicacion individual."
    if source["kind"] == "catalog":
        if old:
            return "CATALOGO", "Cambio detectado en producto/catalogo; no es una novedad editorial de la enciclopedia."
        return "BASE CATALOGO", "Producto registrado como referencia comercial; no se incluye como noticia editorial."
    if source["kind"] == "patch" and item["length"] < MIN_ARTICLE_TEXT:
        return "DESCARTADO", "Pagina de soporte demasiado breve o sin contenido verificable."
    if item["length"] < MIN_ARTICLE_TEXT:
        return "DESCARTADO", "Contenido insuficiente para una ficha editorial."
    combined = normalize_text(item["title"] + " " + item["description"] + " " + item["text"][:8000])
    if not any(term in combined for term in FRANCHISE_TERMS):
        return "DESCARTADO", "No se encontro relacion suficiente con Tomb Raider."
    if match[0] == "DUPLICADO":
        return "DUPLICADO", match[3]
    dt = parse_datetime(item["date"])
    if not dt:
        return "FECHA PENDIENTE", "No se pudo verificar una fecha de publicacion fiable."
    if (now_utc() - dt).days > RECENT_DAYS:
        return "HISTORICO", f"Publicacion anterior a {RECENT_DAYS} dias ({dt.date()}); se conserva como hallazgo historico."
    if match[0] == "RELACIONADO":
        return "AMPLIACION", match[3]
    if old and old.get("fingerprint") != item["fingerprint"]:
        return "ACTUALIZACION", "El contenido de una URL ya vigilada ha cambiado desde la ultima revision."
    return "NUEVO", "Publicacion individual relacionada con Tomb Raider sin coincidencia suficiente en el HTML."


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            items = data.get("items", data)
            if not isinstance(items, dict):
                return {}
            migrated = {}
            for old_url, value in items.items():
                if isinstance(old_url, str) and old_url.startswith(("http://", "https://")):
                    migrated[normalize_url(old_url)] = value
                else:
                    migrated[old_url] = value
            return migrated
    except Exception as exc:
        print(f"[AVISO] Historial no legible; se inicia uno nuevo: {exc}")
    return {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def md_escape(value):
    return clean_text(str(value or "")).replace("|", "\\|").replace("\n", " ")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Croft Watch V{VERSION} iniciando...")
    metadata, knowledge = html_knowledge_index(HTML_FILE)
    save_json(INDEX_FILE, {"metadata": metadata, "records": knowledge})
    print(f"Fichas/unidades indexadas: {metadata['records']} | {metadata['html_title']}")

    state = load_state()
    updated_state = dict(state)
    results, errors = [], []
    examined = unchanged = duplicate_count = discarded_count = catalog_baseline = catalog_changes = 0
    seen_this_run = set()

    for source in SOURCES:
        print(f"Explorando: {source['name']}")
        try:
            candidates = extract_candidates(source)
        except Exception as exc:
            errors.append((source["name"], source["url"], str(exc)))
            print(f"[ERROR FUENTE] {source['name']}: {exc}")
            continue

        for candidate_url in candidates:
            try:
                item = extract_page(candidate_url, source)
                canonical = normalize_url(item["url"])
                if canonical in seen_this_run:
                    duplicate_count += 1
                    continue
                seen_this_run.add(canonical)
                examined += 1
                old = state.get(canonical) or state.get(candidate_url) or {}
                match = compare_with_encyclopedia(item, knowledge)
                category, reason = classify(item, source, match, old)
                first_seen = old.get("first_seen", now_utc().isoformat())
                record = {
                    **item, "source": source["name"], "category": category,
                    "reason": reason, "match_category": match[0],
                    "match_score": round(match[1], 3), "matched_entry": match[2],
                    "first_seen": first_seen, "last_seen": now_utc().isoformat(),
                }
                updated_state[canonical] = {
                    "fingerprint": item["fingerprint"], "title": item["title"],
                    "first_seen": first_seen, "last_seen": now_utc().isoformat(),
                    "category": category, "source": source["name"],
                }

                if category == "DUPLICADO":
                    duplicate_count += 1
                elif category == "DESCARTADO":
                    discarded_count += 1
                elif category == "BASE CATALOGO":
                    catalog_baseline += 1
                elif category == "CATALOGO":
                    if old.get("fingerprint") != item["fingerprint"]:
                        catalog_changes += 1
                        results.append(record)
                    else:
                        unchanged += 1
                elif old and old.get("fingerprint") == item["fingerprint"]:
                    unchanged += 1
                else:
                    results.append(record)

            except Exception as exc:
                errors.append((source["name"], candidate_url, str(exc)))
                print(f"[ERROR] {candidate_url}: {exc}")
            time.sleep(0.25)

    save_json(STATE_FILE, {"version": VERSION, "items": updated_state})
    counts = Counter(item["category"] for item in results)
    lines = [
        f"# CROFT WATCH V{VERSION}", "## Informe de vigilancia editorial", "",
        f"Revision: {now_utc().strftime('%Y-%m-%d %H:%M UTC')}", f"Version: {VERSION}", "",
        "> Informe automatico. Todo elemento requiere revision humana.",
        "> index.html se consulta en modo lectura; nunca se modifica ni publica.", "",
        "## Comparacion con El Archivo Croft",
        f"- Archivo examinado: `{metadata['html_file']}`",
        f"- Titulo interno: {metadata['html_title'] or 'No identificado'}",
        f"- Unidades indexadas: {metadata['records']}",
        f"- Metodo de indice: {metadata['record_method']}",
        f"- SHA-256: `{metadata['html_sha256']}`",
    ]

    title_version = re.search(r"v\s*26\.\d+", metadata["html_title"], re.I)
    if title_version and title_version.group(0).replace(" ", "").lower() != "v26.2":
        lines.append(f"- ADVERTENCIA: el titulo interno indica `{title_version.group(0)}`; comprobar que index.html sea la version vigente V26.2.")

    lines += [
        "", "## Resumen",
        f"- Paginas examinadas: {examined}",
        f"- Nuevos: {counts['NUEVO']}",
        f"- Ampliaciones potenciales: {counts['AMPLIACION']}",
        f"- Actualizaciones editoriales: {counts['ACTUALIZACION']}",
        f"- Hallazgos historicos: {counts['HISTORICO']}",
        f"- Fechas pendientes: {counts['FECHA PENDIENTE']}",
        f"- Cambios de catalogo detectados: {catalog_changes}",
        f"- Productos incorporados al baseline (no editoriales): {catalog_baseline}",
        f"- Duplicados omitidos: {duplicate_count}",
        f"- Descartados: {discarded_count}",
        f"- Sin cambios: {unchanged}",
        f"- Errores de consulta: {len(errors)}", "",
    ]

    order = ["NUEVO", "AMPLIACION", "ACTUALIZACION", "HISTORICO", "FECHA PENDIENTE", "CATALOGO"]
    labels = {
        "NUEVO": "NUEVO", "AMPLIACION": "AMPLIACION POTENCIAL",
        "ACTUALIZACION": "ACTUALIZACION EDITORIAL", "HISTORICO": "DESCUBRIMIENTO HISTORICO",
        "FECHA PENDIENTE": "FECHA PENDIENTE", "CATALOGO": "CAMBIO DE CATALOGO (NO EDITORIAL)",
    }

    for category in order:
        subset = [x for x in results if x["category"] == category]
        lines += [f"## {labels[category]}", ""]
        if not subset:
            lines += ["Sin elementos en esta categoria.", ""]
            continue

        for item in subset:
            lines += [
                f"### {md_escape(item['title'] or 'Titulo no identificado')}",
                f"- Fuente: {md_escape(item['source'])}",
                f"- Enlace: {item['url']}",
                f"- Fecha de publicacion: {item['date'] or 'No identificada'}",
                f"- Motivo: {md_escape(item['reason'])}",
                f"- Coincidencia orientativa: {item['match_score']:.0%}",
            ]
            if item["matched_entry"]:
                lines.append(f"- Ficha cercana (no confirmada): {md_escape(item['matched_entry'])}")
            excerpt = clean_text(item["description"] or item["text"][:350])
            if excerpt:
                lines.append(f"- Extracto: {md_escape(excerpt[:500])}")
            lines += ["- Estado: Pendiente de revision humana.", ""]

    lines += ["## Errores de consulta", ""]
    if errors:
        for source_name, url, error in errors:
            lines.append(f"- {md_escape(source_name)} — {url}: {md_escape(error)}")
    else:
        lines.append("Sin errores.")

    lines += [
        "", "## Seguridad editorial",
        "- index.html se abrio unicamente en modo lectura.",
        "- El script no contiene ninguna instruccion para escribir o reemplazar index.html.",
        "- No se publicaron noticias automaticamente.",
        "- Las categorias y paginas de navegacion se excluyen.",
        "- Las tiendas se vigilan como catalogo comercial separado.",
        "- Las variantes de un mismo producto se normalizan para reducir duplicados.",
        "- Las coincidencias son orientativas; requieren revision humana.", "",
    ]

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Informe creado: {REPORT_FILE}")
    print(f"Pendientes editoriales: {sum(counts[c] for c in order if c != 'CATALOGO')} | Errores: {len(errors)}")


if __name__ == "__main__":
    main()
