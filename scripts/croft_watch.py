
#!/usr/bin/env python3
# CROFT WATCH V3.1
# Compara novedades web con El Archivo Croft.
# Solo lectura sobre index.html: nunca modifica la enciclopedia.

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import (
    urljoin, urlparse, urldefrag, parse_qsl,
    urlencode, urlunparse
)

import requests
from bs4 import BeautifulSoup

VERSION = "3.1"
ROOT = Path(__file__).resolve().parents[1]
HTML_FILE = Path(os.getenv("CROFT_HTML_FILE", str(ROOT / "index.html")))

DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "croft_watch_seen.json"
INDEX_FILE = DATA_DIR / "archivo_croft_index.json"
REPORT_FILE = DATA_DIR / "pendiente_revision.md"

TIMEOUT = 22
MAX_LINKS_PER_SOURCE = 100
RECENT_DAYS = 60
MIN_TEXT_LENGTH = 180

USER_AGENT = (
    "CroftWatch/3.1 "
    "(+editorial monitoring; human review required)"
)

SOURCES = [
    {
        "name": "Tomb Raider Official",
        "url": "https://www.tombraider.com/news/all",
        "domains": {"tombraider.com", "www.tombraider.com"},
        "path_ok": lambda p: (
            p.startswith("/news/") or p == "/news/all"
        ),
        "include_page": True,
    },
    {
        "name": "Crystal Dynamics",
        "url": "https://www.crystaldynamics.com/news-community/",
        "domains": {
            "crystaldynamics.com",
            "www.crystaldynamics.com"
        },
        "path_ok": lambda p: (
            p.startswith("/news") or p.startswith("/community")
        ),
        "include_page": True,
    },
    {
        "name": "Netflix Tudum",
        "url": "https://www.netflix.com/tudum/articles/tomb-raider-legend-of-lara-croft",
        "domains": {"netflix.com", "www.netflix.com"},
        "path_ok": lambda p: (
            p.startswith("/tudum/articles/")
            and any(k in p.lower() for k in ("tomb-raider", "lara-croft"))
        ),
        "include_page": True,
    },
    {
        "name": "Amazon MGM Studios",
        "url": "https://www.aboutamazon.com/news/entertainment/tomb-raider-prime-video-phoebe-waller-bridge-sophie-turner",
        "domains": {"aboutamazon.com", "www.aboutamazon.com"},
        "path_ok": lambda p: (
            p.startswith("/news/entertainment/")
            and any(k in p.lower() for k in ("tomb-raider", "lara-croft"))
        ),
        "include_page": True,
    },
    {
        "name": "Aspyr - Remastered IV-VI",
        "url": "https://support.aspyr.com/hc/en-us/sections/34244769732749-Updates",
        "domains": {"support.aspyr.com"},
        "path_ok": lambda p: (
            p.startswith("/hc/en-us/articles/")
            and "tomb-raider" in p.lower()
        ),
        "include_page": False,
    },
    {
        "name": "Aspyr - Remastered I-III",
        "url": "https://support.aspyr.com/hc/en-us/sections/44234935752333-Updates",
        "domains": {"support.aspyr.com"},
        "path_ok": lambda p: (
            p.startswith("/hc/en-us/articles/")
            and "tomb-raider" in p.lower()
        ),
        "include_page": False,
    },
    {
        "name": "Tomb Raider Gear Store - Collectibles",
        "url": "https://gear.tombraider.com/collections/collectibles",
        "domains": {"gear.tombraider.com"},
        "path_ok": lambda p: (
            p.startswith("/collections/collectibles")
            or p.startswith("/products/")
        ),
        "include_page": True,
        "snapshot": True,
    },
    {
        "name": "Tomb Raider Gear Store - Merchandise",
        "url": "https://gear.tombraider.com/collections/merch",
        "domains": {"gear.tombraider.com"},
        "path_ok": lambda p: (
            p.startswith("/collections/merch")
            or p.startswith("/products/")
        ),
        "include_page": True,
        "snapshot": True,
    },
    {
        "name": "Dark Horse Digital - Tomb Raider Comics",
        "url": "https://digital.darkhorse.com/series/345/tomb-raider",
        "domains": {"digital.darkhorse.com"},
        "path_ok": lambda p: (
            p.startswith("/series/345/") or p.startswith("/books/")
        ),
        "include_page": True,
        "snapshot": True,
    },
]

FRANCHISE_TERMS = {
    "tomb raider",
    "lara croft",
    "croft",
    "survivor trilogy",
    "legacy of atlantis",
    "angel of darkness",
    "last revelation",
}

STOP_WORDS = {
    "the", "and", "for", "with", "from", "this", "that",
    "your", "you", "tomb", "raider", "lara", "croft",
    "official", "news", "update", "updates", "a", "an",
    "of", "in", "on", "to", "at", "is", "are", "by",
    "as", "el", "la", "los", "las", "de", "del", "y",
    "en", "para", "con",
}

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def now_utc():
    return datetime.now(timezone.utc)


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_text(value):
    value = (value or "").lower()
    value = value.replace("’", "'")
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^a-z0-9áéíóúüñ]+", " ", value)
    return clean_text(value)


def tokens(value):
    return {
        word
        for word in normalize_text(value).split()
        if len(word) > 2 and word not in STOP_WORDS
    }


def token_similarity(a, b):
    ta = tokens(a)
    tb = tokens(b)

    if not ta or not tb:
        return 0.0

    return len(ta & tb) / max(1, len(ta | tb))


def normalize_url(url):
    url = urldefrag(url)[0]
    parsed = urlparse(url)

    query = [
        (key, value)
        for key, value in parse_qsl(
            parsed.query,
            keep_blank_values=True
        )
        if not key.lower().startswith("utm_")
        and key.lower() not in {"fbclid", "gclid"}
    ]

    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/") or "/",
        "",
        urlencode(query),
        "",
    ))


def allowed_url(url, source):
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]

    return (
        host in source["domains"]
        and source["path_ok"](parsed.path.lower())
    )


def extract_date(soup):
    candidates = []

    date_fields = [
        ("property", "article:published_time"),
        ("property", "og:published_time"),
        ("name", "datePublished"),
        ("itemprop", "datePublished"),
        ("name", "pubdate"),
        ("name", "publish-date"),
        ("property", "article:modified_time"),
        ("itemprop", "dateModified"),
    ]

    for key, attr in date_fields:
        tag = soup.find("meta", attrs={key: attr})

        if tag and tag.get("content"):
            candidates.append(tag["content"].strip())

    for tag in soup.find_all("time", limit=4):
        value = tag.get("datetime") or tag.get_text(" ", strip=True)

        if value:
            candidates.append(value)

    for raw in candidates:
        try:
            dt = datetime.fromisoformat(
                raw.replace("Z", "+00:00")
            )

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt.astimezone(timezone.utc).isoformat()

        except (ValueError, TypeError):
            continue

    return ""


def extract_page(url, source):
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()

    final_url = normalize_url(response.url)
    final_host = urlparse(final_url).netloc.lower()

    if final_host not in source["domains"]:
        raise ValueError(
            "Redirección fuera del dominio autorizado"
        )

    soup = BeautifulSoup(response.text, "html.parser")

    for node in soup.select(
        "script, style, noscript, nav, footer, header, "
        "form, svg, iframe"
    ):
        node.decompose()

    title = ""

    if soup.title:
        title = clean_text(
            soup.title.get_text(" ", strip=True)
        )

    h1 = soup.find("h1")

    if h1:
        title = (
            clean_text(h1.get_text(" ", strip=True))
            or title
        )

    description = ""

    for attrs in (
        {"name": "description"},
        {"property": "og:description"},
    ):
        tag = soup.find("meta", attrs=attrs)

        if tag and tag.get("content"):
            description = clean_text(tag["content"])
            break

    main = (
        soup.find("main")
        or soup.find("article")
        or soup.body
        or soup
    )

    text = clean_text(main.get_text(" ", strip=True))

    fingerprint_content = normalize_text(
        title + " " + description + " " + text
    )

    fingerprint = hashlib.sha256(
        fingerprint_content.encode("utf-8")
    ).hexdigest()

    return {
        "url": final_url,
        "title": title[:300],
        "description": description[:1000],
        "text": text[:30000],
        "date": extract_date(soup),
        "fingerprint": fingerprint,
        "length": len(text),
    }


def extract_candidates(source):
    found = []

    if source.get("include_page"):
        found.append(source["url"])

    try:
        response = session.get(
            source["url"],
            timeout=TIMEOUT
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for link in soup.find_all("a", href=True):
            url = normalize_url(
                urljoin(response.url, link["href"])
            )

            if allowed_url(url, source):
                found.append(url)

    except Exception as exc:
        print(
            f"[AVISO] No se pudo explorar "
            f"{source['name']}: {exc}"
        )

    unique = []
    seen = set()

    for url in found:
        if url not in seen:
            seen.add(url)
            unique.append(url)

    return unique[:MAX_LINKS_PER_SOURCE]


def html_knowledge_index(html_path):
    if not html_path.exists():
        raise FileNotFoundError(
            f"No existe {html_path}. "
            "Copia la enciclopedia vigente al repositorio "
            "con el nombre index.html."
        )

    raw = html_path.read_text(
        encoding="utf-8",
        errors="replace"
    )

    soup = BeautifulSoup(raw, "html.parser")
    records = []
    selectors = soup.select(
        ".searchable, .relic-card, article"
    )

    seen = set()

    for node in selectors:
        title_node = node.find(["h1", "h2", "h3", "h4"])

        title = (
            clean_text(title_node.get_text(" ", strip=True))
            if title_node
            else ""
        )

        desc_parts = []

        for element in node.find_all(["p", "li"], limit=12):
            value = clean_text(
                element.get_text(" ", strip=True)
            )

            if value and value not in desc_parts:
                desc_parts.append(value)

        data_title = clean_text(node.get("data-title", ""))
        data_search = clean_text(node.get("data-search", ""))
        data_desc = clean_text(node.get("data-description", ""))

        links = [
            normalize_url(link["href"])
            for link in node.find_all("a", href=True)
            if link["href"].startswith(("http://", "https://"))
        ]

        label = (
            title
            or data_title
            or (desc_parts[0][:140] if desc_parts else "")
        )

        content = " ".join([
            label,
            data_title,
            data_search,
            data_desc,
            *desc_parts,
        ])

        if not clean_text(content):
            continue

        key = hashlib.sha1(
            normalize_text(content).encode("utf-8")
        ).hexdigest()

        if key in seen:
            continue

        seen.add(key)

        records.append({
            "title": label[:300],
            "content": clean_text(content)[:5000],
            "kind": clean_text(node.get("data-kind", "")),
            "medium": clean_text(node.get("data-medium", "")),
            "links": links[:10],
            "tokens": sorted(tokens(content)),
        })

    # Registrar secciones informativas adicionales.
    for section in soup.find_all("section"):
        heading = section.find(["h2", "h3"])

        if not heading:
            continue

        title = clean_text(
            heading.get_text(" ", strip=True)
        )

        body = clean_text(
            section.get_text(" ", strip=True)
        )

        if len(body) < 100:
            continue

        key = hashlib.sha1(
            normalize_text(title + body).encode("utf-8")
        ).hexdigest()

        if key in seen:
            continue

        seen.add(key)

        records.append({
            "title": title[:300],
            "content": body[:5000],
            "kind": "section",
            "medium": "",
            "links": [],
            "tokens": sorted(tokens(title + " " + body)),
        })

    metadata = {
        "html_file": html_path.name,
        "html_sha256": hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest(),
        "html_title": (
            clean_text(soup.title.get_text(" ", strip=True))
            if soup.title
            else ""
        ),
        "records": len(records),
        "generated_at": now_utc().isoformat(),
    }

    return metadata, records


def compare_with_encyclopedia(item, records):
    candidate_text = " ".join([
        item["title"],
        item["description"],
        item["text"][:5000],
    ])

    candidate_url = normalize_url(item["url"])

    best = None
    best_score = 0.0
    exact_url = None

    for record in records:
        if candidate_url in record.get("links", []):
            exact_url = record
            break

        score = max(
            token_similarity(
                item["title"],
                record["title"]
            ),
            token_similarity(
                candidate_text[:3500],
                record["content"][:3500]
            ),
            SequenceMatcher(
                None,
                normalize_text(item["title"]),
                normalize_text(record["title"])
            ).ratio(),
        )

        if score > best_score:
            best_score = score
            best = record

    if exact_url:
        return (
            "DUPLICADO",
            1.0,
            exact_url["title"],
            "La misma URL ya aparece en la enciclopedia."
        )

    if best and best_score >= 0.82:
        return (
            "DUPLICADO",
            best_score,
            best["title"],
            "Coincidencia muy alta con contenido ya documentado."
        )

    if best and best_score >= 0.48:
        return (
            "AMPLIACIÓN",
            best_score,
            best["title"],
            "Tema relacionado con una ficha existente; "
            "revisar qué aporta de nuevo."
        )

    return (
        "NUEVO",
        best_score,
        best["title"] if best else "",
        "No se encontró una coincidencia suficiente "
        "en la enciclopedia."
    )


def parse_date(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).astimezone(timezone.utc)

    except Exception:
        return None


def classify(item, source, match):
    title = normalize_text(item["title"])

    body = normalize_text(
        item["description"] + " " + item["text"][:7000]
    )

    combined = title + " " + body

    if any(
        term in title
        for term in (
            "contact",
            "press contact",
            "support",
            "help center",
        )
    ):
        return (
            "DESCARTADO",
            "Página de contacto/soporte; no es una noticia editorial."
        )

    if item["length"] < MIN_TEXT_LENGTH:
        return (
            "DESCARTADO",
            "Contenido demasiado breve o página de navegación."
        )

    if not any(
        term in combined for term in FRANCHISE_TERMS
    ):
        return (
            "DESCARTADO",
            "No se encontró relación suficiente con Tomb Raider."
        )

    if match[0] == "DUPLICADO":
        return "DUPLICADO", match[3]

    if source.get("snapshot"):
        return (
            "ACTUALIZACIÓN",
            "Página de catálogo vigilada; comparar cambios del catálogo."
        )

    if match[0] == "AMPLIACIÓN":
        return "AMPLIACIÓN", match[3]

    dt = parse_date(item["date"])

    if dt and (now_utc() - dt).days > RECENT_DAYS:
        return (
            "HISTÓRICO",
            f"Descubrimiento antiguo ({dt.date()}); "
            "no se presenta como noticia reciente."
        )

    if not dt:
        return (
            "FECHA PENDIENTE",
            "No se pudo verificar la fecha de publicación."
        )

    return (
        "NUEVO",
        "Contenido relacionado que no aparece documentado en el HTML."
    )


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        data = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

        if isinstance(data, dict):
            return data.get("items", data)

    except Exception as exc:
        print(f"[AVISO] No se pudo leer el historial: {exc}")

    return {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def md_escape(value):
    return clean_text(value).replace("|", "\\|")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Croft Watch V{VERSION} iniciando...")

    metadata, knowledge = html_knowledge_index(HTML_FILE)

    save_json(
        INDEX_FILE,
        {
            "metadata": metadata,
            "records": knowledge,
        }
    )

    print(
        f"Índice del HTML: {metadata['records']} registros "
        f"| {metadata['html_title']}"
    )

    state = load_state()
    updated_state = dict(state)

    results = []
    errors = []

    examined = 0
    duplicate_count = 0
    discarded_count = 0
    unchanged_count = 0

    for source in SOURCES:
        print(f"Explorando: {source['name']}")

        candidates = extract_candidates(source)

        for url in candidates:
            try:
                item = extract_page(url, source)
                examined += 1

                old = (
                    state.get(item["url"])
                    or state.get(url)
                    or {}
                )

                if (
                    old
                    and old.get("fingerprint")
                    == item["fingerprint"]
                ):
                    unchanged_count += 1
                    continue

                match = compare_with_encyclopedia(
                    item,
                    knowledge
                )

                category, reason = classify(
                    item,
                    source,
                    match
                )

                record = {
                    **item,
                    "source": source["name"],
                    "category": category,
                    "reason": reason,
                    "match_category": match[0],
                    "match_score": round(match[1], 3),
                    "matched_entry": match[2],
                    "first_seen": old.get(
                        "first_seen",
                        now_utc().isoformat()
                    ),
                    "last_seen": now_utc().isoformat(),
                }

                updated_state[item["url"]] = {
                    "fingerprint": item["fingerprint"],
                    "title": item["title"],
                    "first_seen": record["first_seen"],
                    "last_seen": record["last_seen"],
                    "category": category,
                }

                if category == "DUPLICADO":
                    duplicate_count += 1

                elif category == "DESCARTADO":
                    discarded_count += 1

                else:
                    results.append(record)

            except Exception as exc:
                errors.append((
                    source["name"],
                    url,
                    str(exc)
                ))

                print(f"[ERROR] {url}: {exc}")

            time.sleep(0.35)

    save_json(
        STATE_FILE,
        {
            "version": VERSION,
            "items": updated_state,
        }
    )

    counts = Counter(
        item["category"] for item in results
    )

    lines = [
        f"# CROFT WATCH V{VERSION}",
        "## Informe de vigilancia editorial",
        "",
        f"Revisión: {now_utc().strftime('%Y-%m-%d %H:%M UTC')}",
        f"Versión: {VERSION}",
        "",
        "> Informe automático. Todo elemento requiere revisión humana.",
        "> La enciclopedia no se modifica.",
        "",
        "## Comparación con El Archivo Croft",
        f"- Archivo examinado: `{metadata['html_file']}`",
        f"- Título interno: {metadata['html_title'] or 'No identificado'}",
        f"- Registros indexados: {metadata['records']}",
        f"- SHA-256: `{metadata['html_sha256']}`",
        "",
        "## Resumen",
        f"- Enlaces examinados: {examined}",
        f"- Elementos nuevos: {counts['NUEVO']}",
        f"- Ampliaciones potenciales: {counts['AMPLIACIÓN']}",
        f"- Actualizaciones: {counts['ACTUALIZACIÓN']}",
        f"- Descubrimientos históricos: {counts['HISTÓRICO']}",
        f"- Fechas pendientes: {counts['FECHA PENDIENTE']}",
        f"- Duplicados omitidos: {duplicate_count}",
        f"- Descartados: {discarded_count}",
        f"- Sin cambios desde revisión anterior: {unchanged_count}",
        f"- Errores de consulta: {len(errors)}",
        "",
    ]

    order = [
        "NUEVO",
        "AMPLIACIÓN",
        "ACTUALIZACIÓN",
        "HISTÓRICO",
        "FECHA PENDIENTE",
    ]

    labels = {
        "NUEVO": "🟢 NUEVO",
        "AMPLIACIÓN": "🔵 AMPLIACIÓN POTENCIAL",
        "ACTUALIZACIÓN": "🟣 ACTUALIZACIÓN",
        "HISTÓRICO": "🟠 DESCUBRIMIENTO HISTÓRICO",
        "FECHA PENDIENTE": "🟡 FECHA PENDIENTE",
    }

    for category in order:
        subset = [
            item for item in results
            if item["category"] == category
        ]

        lines += [
            f"## {labels[category]}",
            "",
        ]

        if not subset:
            lines += [
                "Sin elementos nuevos en esta categoría.",
                "",
            ]
            continue

        for item in subset:
            lines += [
                f"### {md_escape(item['title'] or 'Título no identificado')}",
                f"- Fuente: {md_escape(item['source'])}",
                f"- Enlace: {item['url']}",
                f"- Fecha: {item['date'] or 'No identificada'}",
                f"- Motivo: {md_escape(item['reason'])}",
                f"- Coincidencia con HTML: {item['match_score']:.0%}",
            ]

            if item["matched_entry"]:
                lines.append(
                    "- Ficha relacionada: "
                    + md_escape(item["matched_entry"])
                )

            excerpt = clean_text(
                item["description"] or item["text"][:350]
            )

            if excerpt:
                lines.append(
                    f"- Extracto: {md_escape(excerpt[:450])}"
                )

            lines += [
                "- Estado: Pendiente de revisión humana.",
                "",
            ]

    lines += [
        "## Errores de consulta",
        "",
    ]

    if errors:
        for source_name, url, error in errors:
            lines.append(
                f"- {md_escape(source_name)} — {url}: "
                f"{md_escape(error)}"
            )
    else:
        lines.append("Sin errores.")

    lines += [
        "",
        "## Seguridad editorial",
        "- index.html se abrió únicamente en modo lectura.",
        "- No se modificó ningún archivo de la enciclopedia.",
        "- No se publicaron noticias automáticamente.",
        "- Los duplicados se conservaron en el historial.",
        "- Las clasificaciones requieren revisión humana.",
        "",
    ]

    REPORT_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )

    print(f"Informe creado: {REPORT_FILE}")
    print(
        f"Elementos pendientes: {len(results)} "
        f"| Errores: {len(errors)}"
    )


if __name__ == "__main__":
    main()
