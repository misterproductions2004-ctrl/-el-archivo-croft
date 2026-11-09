
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup


# ============================================================
# CROFT WATCH V3.0 — EDITORIAL MONITOR
# ============================================================

VERSION = "3.0"

SOURCES = [
    {
        "name": "Tomb Raider Official",
        "url": "https://www.tombraider.com/news/all",
        "domains": ["www.tombraider.com", "tombraider.com"],
        "include_page": False,
        "scan_links": True,
    },
    {
        "name": "Crystal Dynamics",
        "url": "https://www.crystaldynamics.com/news-community/",
        "domains": ["www.crystaldynamics.com", "crystaldynamics.com"],
        "include_page": False,
        "scan_links": True,
    },
    {
        "name": "Netflix Tudum",
        "url": "https://www.netflix.com/tudum/tomb-raider-the-legend-of-lara-croft",
        "domains": ["www.netflix.com", "netflix.com"],
        "include_page": True,
        "scan_links": True,
    },
    {
        "name": "Amazon MGM Studios",
        "url": "https://www.aboutamazon.com/news/entertainment/tomb-raider-prime-video-phoebe-waller-bridge-sophie-turner",
        "domains": ["www.aboutamazon.com", "aboutamazon.com"],
        "include_page": True,
        "scan_links": True,
    },
    {
        "name": "Aspyr — Remastered IV-VI",
        "url": "https://support.aspyr.com/hc/en-us/sections/34244769732749-Updates",
        "domains": ["support.aspyr.com"],
        "include_page": False,
        "scan_links": True,
    },
    {
        "name": "Aspyr — Remastered I-III",
        "url": "https://support.aspyr.com/hc/en-us/sections/44234935752333-Updates",
        "domains": ["support.aspyr.com"],
        "include_page": False,
        "scan_links": True,
    },
    {
        "name": "Tomb Raider Gear Store — Collectibles",
        "url": "https://gear.tombraider.com/collections/collectibles",
        "domains": ["gear.tombraider.com"],
        "include_page": True,
        "scan_links": False,
        "snapshot": True,
    },
    {
        "name": "Tomb Raider Gear Store — Merchandise",
        "url": "https://gear.tombraider.com/collections/merch",
        "domains": ["gear.tombraider.com"],
        "include_page": True,
        "scan_links": False,
        "snapshot": True,
    },
    {
        "name": "Dark Horse Digital — Tomb Raider Comics",
        "url": "https://digital.darkhorse.com/series/345/tomb-raider",
        "domains": ["digital.darkhorse.com"],
        "include_page": True,
        "scan_links": False,
    },
]


STATE_FILE = Path("data/croft_watch_seen.json")
REPORT_FILE = Path("data/pendiente_revision.md")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; CroftWatch/3.0; "
        "+https://www.tombraider.com)"
    )
}

TIMEOUT = 30
MAX_LINKS_PER_SOURCE = 150
MIN_CONTENT_LENGTH = 180

CATEGORIES = {
    "NOTICIA": "🟢",
    "ACTUALIZACIÓN": "🔵",
    "CONTACTO": "🟡",
    "DESCARTADO": "⚫",
}

FRANCHISE_TERMS = [
    "tomb raider",
    "lara croft",
    "croft",
    "tombraider",
    "shadow of the tomb raider",
    "rise of the tomb raider",
    "legacy of atlantis",
    "tomb raider catalyst",
    "the legend of lara croft",
]

TOPIC_TERMS = [
    "game", "games", "gaming", "video game",
    "videogame", "remaster", "remastered", "remake",
    "release", "launch", "trailer", "gameplay",
    "development", "developer", "studio",
    "film", "movie", "cinema", "series",
    "season", "television", "tv", "netflix",
    "amazon", "prime video", "adaptation",
    "cast", "actor", "actress", "starring",
    "director", "producer", "writer",
    "comic", "comics", "graphic novel",
    "book", "novel", "publishing",
    "merchandise", "collectible", "collectibles",
    "figure", "statue", "collectors",
    "soundtrack", "event", "award", "interview",
    "anniversary", "announcement",
    "update", "patch", "expansion", "dlc",
    "official", "press release",
]

CONTACT_TITLE_TERMS = [
    "contact",
    "press contact",
    "media contact",
    "press inquiries",
    "media inquiries",
    "public relations",
    "press office",
    "media relations",
]

IGNORED_PATHS = [
    "/tag/", "/category/", "/author/",
    "/privacy", "/terms", "/login",
    "/account", "/search", "/cart",
    "/checkout", "/cdn-cgi/",
]

IGNORED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".svg", ".css", ".js", ".ico", ".woff",
    ".woff2", ".ttf", ".pdf",
)


# ============================================================
# UTILIDADES
# ============================================================

def normalize_text(value):
    return " ".join((value or "").split()).strip()


def contains_any(text, terms):
    text = (text or "").lower()
    return any(term in text for term in terms)


def normalize_url(url):
    url = urldefrag(url)[0]
    parsed = urlparse(url)

    if parsed.scheme != "https":
        return None

    return url.rstrip("/")


def load_seen():
    if not STATE_FILE.exists():
        return {}

    try:
        data = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

        # Compatibilidad con el historial V1/V2.
        if isinstance(data, list):
            return {
                url: {
                    "fingerprint": "",
                    "category": "NOTICIA",
                }
                for url in data
            }

        if isinstance(data, dict):
            return data.get("items", {})

    except (json.JSONDecodeError, OSError) as error:
        print(f"Advertencia al leer historial: {error}")

    return {}


def save_seen(seen):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": seen,
    }

    STATE_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def fetch_page(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
    )

    response.raise_for_status()

    final_url = normalize_url(response.url)

    if not final_url:
        raise ValueError("Redirección a una dirección no HTTPS.")

    return response, final_url


# ============================================================
# EXTRACCIÓN DE CONTENIDO
# ============================================================

def get_page_information(url):
    response, final_url = fetch_page(url)

    soup = BeautifulSoup(response.text, "html.parser")

    for element in soup([
        "script", "style", "noscript",
        "svg", "nav", "footer",
    ]):
        element.decompose()

    title = ""

    if soup.title:
        title = normalize_text(
            soup.title.get_text(" ")
        )

    for selector in [
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
    ]:
        element = soup.select_one(selector)

        if element and element.get("content"):
            title = normalize_text(element["content"])
            break

    description = ""

    for selector in [
        'meta[name="description"]',
        'meta[property="og:description"]',
    ]:
        element = soup.select_one(selector)

        if element and element.get("content"):
            description = normalize_text(element["content"])
            break

    main = (
        soup.find("main")
        or soup.find("article")
        or soup.body
        or soup
    )

    content = normalize_text(
        main.get_text(" ", strip=True)
    )

    canonical = soup.find("link", rel="canonical")

    canonical_url = (
        normalize_url(
            urljoin(final_url, canonical["href"])
        )
        if canonical and canonical.get("href")
        else final_url
    )

    dates = []

    for selector in [
        "time[datetime]",
        'meta[property="article:published_time"]',
        'meta[name="date"]',
        'meta[name="pubdate"]',
        'meta[property="article:modified_time"]',
    ]:
        for element in soup.select(selector):
            value = (
                element.get("datetime")
                or element.get("content")
            )

            if value:
                dates.append(value)

    dates = list(dict.fromkeys(dates))

    fingerprint_source = "|".join([
        title,
        description,
        content,
        " ".join(dates),
    ])

    fingerprint = hashlib.sha256(
        fingerprint_source.encode("utf-8")
    ).hexdigest()

    return {
        "url": final_url,
        "canonical": canonical_url,
        "title": title,
        "description": description,
        "content": content,
        "dates": dates,
        "fingerprint": fingerprint,
        "content_length": len(content),
        "html": response.text,
    }


# ============================================================
# DETECCIÓN DE ENLACES
# ============================================================

def get_candidates(source):
    candidates = {}

    if source.get("include_page"):
        candidates[source["url"]] = {
            "title": source["name"],
            "url": source["url"],
            "source": source["name"],
            "snapshot": source.get("snapshot", False),
        }

    if not source.get("scan_links", True):
        return list(candidates.values())

    response, _ = fetch_page(source["url"])
    soup = BeautifulSoup(response.text, "html.parser")

    for link in soup.find_all("a", href=True):
        raw_url = urljoin(source["url"], link["href"])
        url = normalize_url(raw_url)

        if not url:
            continue

        parsed = urlparse(url)

        if parsed.netloc.lower() not in source["domains"]:
            continue

        if parsed.path.lower().endswith(IGNORED_EXTENSIONS):
            continue

        if any(
            part in parsed.path.lower()
            for part in IGNORED_PATHS
        ):
            continue

        title = normalize_text(
            link.get_text(" ", strip=True)
        )

        if len(title) < 8:
            continue

        if url == source["url"].rstrip("/"):
            continue

        candidates[url] = {
            "title": title,
            "url": url,
            "source": source["name"],
            "snapshot": False,
        }

        if len(candidates) >= MAX_LINKS_PER_SOURCE:
            break

    return list(candidates.values())


# ============================================================
# CLASIFICACIÓN EDITORIAL
# ============================================================

def classify_item(item, page, previous):
    title = page["title"] or item["title"]
    url = page["url"]
    content = page["content"]
    description = page["description"]

    combined = " ".join([
        title,
        url,
        description,
        content[:12000],
    ]).lower()

    path = urlparse(url).path.lower()

    # Contactos: solo por ruta o título específico.
    # No basta con encontrar un correo dentro de una noticia.
    if (
        any(part in path for part in [
            "/contact",
            "/press-contact",
            "/media-contact",
        ])
        or contains_any(title.lower(), CONTACT_TITLE_TERMS)
    ):
        return "CONTACTO", "Página o información de contacto."

    # Contenido insuficiente.
    if (
        not page["title"]
        or page["content_length"] < MIN_CONTENT_LENGTH
    ):
        return "DESCARTADO", "Contenido insuficiente o inaccesible."

    # Relación con Tomb Raider.
    if not contains_any(combined, FRANCHISE_TERMS):
        return (
            "DESCARTADO",
            "Sin relación editorial demostrable con la franquicia."
        )

    # Relevancia temática.
    if not contains_any(combined, TOPIC_TERMS):
        return (
            "DESCARTADO",
            "Sin tema editorial reconocido."
        )

    old = previous.get(url)

    # Los catálogos oficiales se vigilan como páginas de referencia.
    if item.get("snapshot"):
        return (
            "ACTUALIZACIÓN",
            "Página de catálogo oficial vigilada como referencia."
        )

    # Cambios en páginas ya registradas.
    if old and old.get("fingerprint"):
        if old["fingerprint"] != page["fingerprint"]:
            return (
                "ACTUALIZACIÓN",
                "Cambió el contenido de una página registrada."
            )

    if old and not old.get("fingerprint"):
        return (
            "NOTICIA",
            "Primera verificación completa de una URL heredada."
        )

    return (
        "NOTICIA",
        "Nuevo contenido relacionado con Tomb Raider."
    )


# ============================================================
# INFORME
# ============================================================

def build_report(results, stats, checked_at, errors):
    lines = [
        "# CROFT WATCH V3.0",
        "## Informe de vigilancia editorial",
        "",
        f"Revisión: {checked_at}",
        f"Versión: {VERSION}",
        "",
        "> Informe automático. Todo elemento requiere revisión humana.",
        "",
        "## Fuentes configuradas",
        "",
    ]

    for source in SOURCES:
        lines.append(f"- {source['name']}: {source['url']}")

    lines.extend([
        "",
        "## Resumen",
        "",
        f"- Enlaces examinados: {stats['examined']}",
        f"- Noticias: {stats['NOTICIA']}",
        f"- Actualizaciones: {stats['ACTUALIZACIÓN']}",
        f"- Contactos: {stats['CONTACTO']}",
        f"- Descartados: {stats['DESCARTADO']}",
        "",
    ])

    descriptions = {
        "NOTICIA": "Anuncios oficiales y novedades.",
        "ACTUALIZACIÓN": "Cambios en páginas y catálogos oficiales.",
        "CONTACTO": "Correos y datos de prensa.",
        "DESCARTADO": "Enlaces sin contenido editorial suficiente.",
    }

    for category, emoji in CATEGORIES.items():
        lines.extend([
            f"## {emoji} {category}",
            "",
            f"> {descriptions[category]}",
            "",
        ])

        entries = [
            result for result in results
            if result["category"] == category
        ]

        if not entries:
            lines.extend([
                "Sin elementos nuevos o modificados.",
                "",
            ])
            continue

        for item in entries:
            lines.extend([
                f"### {item['title'] or 'Sin título'}",
                "",
                f"- Fuente: {item['source']}",
                f"- Enlace: {item['url']}",
                f"- Motivo: {item['reason']}",
            ])

            if item.get("dates"):
                lines.append(
                    f"- Fecha detectada: {', '.join(item['dates'])}"
                )
            else:
                lines.append(
                    "- Fecha detectada: No identificada."
                )

            lines.extend([
                "- Estado: Pendiente de revisión humana.",
                "",
            ])

    lines.extend([
        "## Errores de consulta",
        "",
    ])

    if errors:
        for error in errors:
            lines.append(f"- {error}")
    else:
        lines.append("Ninguno.")

    lines.extend([
        "",
        "## Seguridad editorial",
        "",
        "- No se modificó index.html.",
        "- No se publicaron noticias automáticamente.",
        "- No se aprobaron rumores ni filtraciones.",
        "- La clasificación automática requiere revisión humana.",
        "- Las fuentes inaccesibles deben revisarse manualmente.",
        "",
    ])

    return "\n".join(lines)


# ============================================================
# PROCESO PRINCIPAL
# ============================================================

def main():
    previous = load_seen()
    updated = dict(previous)

    results = []
    errors = []

    stats = {
        "examined": 0,
        "NOTICIA": 0,
        "ACTUALIZACIÓN": 0,
        "CONTACTO": 0,
        "DESCARTADO": 0,
    }

    checked_at = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    print(f"=== CROFT WATCH V{VERSION} ===")

    for source in SOURCES:
        print(f"\nRevisando: {source['name']}")

        try:
            candidates = get_candidates(source)

        except (
            requests.RequestException,
            ValueError,
        ) as error:
            errors.append(f"{source['name']}: {error}")
            print(f"Error en fuente: {error}")
            continue

        print(f"Enlaces encontrados: {len(candidates)}")

        for candidate in candidates:
            stats["examined"] += 1

            try:
                page = get_page_information(candidate["url"])

                candidate["url"] = page["url"]

                category, reason = classify_item(
                    candidate,
                    page,
                    updated,
                )

                old = updated.get(candidate["url"])

                # CORRECCIÓN DE DUPLICADOS:
                # No repetir ninguna categoría si no ha cambiado.
                if (
                    old
                    and old.get("fingerprint")
                    == page["fingerprint"]
                ):
                    continue

                result = {
                    **candidate,
                    "title": page["title"] or candidate["title"],
                    "category": category,
                    "reason": reason,
                    "dates": page["dates"],
                }

                results.append(result)
                stats[category] += 1

                updated[candidate["url"]] = {
                    "fingerprint": page["fingerprint"],
                    "category": category,
                    "title": page["title"],
                    "source": candidate["source"],
                    "last_seen": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }

                print(
                    f"[{category}] "
                    f"{result['title'][:75]}"
                )

            except (
                requests.RequestException,
                ValueError,
                KeyError,
            ) as error:
                errors.append(
                    f"{candidate['url']}: {error}"
                )
                print(f"Error verificando enlace: {error}")

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    save_seen(updated)

    report = build_report(
        results,
        stats,
        checked_at,
        errors,
    )

    REPORT_FILE.write_text(
        report,
        encoding="utf-8",
    )

    print("\n=== RESULTADO CROFT WATCH ===")
    print(f"Enlaces examinados: {stats['examined']}")

    for category, count in stats.items():
        if category != "examined":
            print(f"{category}: {count}")

    print(f"Errores: {len(errors)}")
    print(f"Informe: {REPORT_FILE}")
    print("La enciclopedia no ha sido modificada.")


if __name__ == "__main__":
    main()
