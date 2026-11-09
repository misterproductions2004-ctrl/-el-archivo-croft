
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SOURCES = [
    {
        "name": "Tomb Raider Official",
        "url": "https://www.tombraider.com/news/all",
        "domain": "www.tombraider.com",
    },
    {
        "name": "Crystal Dynamics",
        "url": "https://www.crystaldynamics.com/news-community/",
        "domain": "www.crystaldynamics.com",
    },
]

STATE_FILE = Path("data/croft_watch_seen.json")
REPORT_FILE = Path("data/pendiente_revision.md")

HEADERS = {
    "User-Agent": "CroftWatch/1.0 (official news monitor)"
}


def load_seen():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return []


def get_candidates(source):
    response = requests.get(
        source["url"],
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = {}

    for link in soup.find_all("a", href=True):
        title = " ".join(link.get_text(" ", strip=True).split())
        url = urljoin(source["url"], link["href"])
        parsed = urlparse(url)

        if parsed.scheme != "https":
            continue

        if parsed.netloc.lower() != source["domain"]:
            continue

        if not title or len(title) < 12:
            continue

        if url.rstrip("/") == source["url"].rstrip("/"):
            continue

        if any(part in parsed.path.lower() for part in [
            "/tag/", "/category/", "/author/",
            "/privacy", "/terms", "/login"
        ]):
            continue

        candidates[url] = {
            "title": title,
            "url": url,
            "source": source["name"],
        }

    return list(candidates.values())


def main():
    seen = set(load_seen())
    new_items = []
    checked_at = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    for source in SOURCES:
        try:
            print(f"Revisando: {source['name']}")
            candidates = get_candidates(source)

            for item in candidates:
                if item["url"] not in seen:
                    new_items.append(item)
                    seen.add(item["url"])

        except requests.RequestException as error:
            print(f"Error consultando {source['name']}: {error}")

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    STATE_FILE.write_text(
        json.dumps(sorted(seen), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if new_items:
        report = [
            "# Croft Watch — Pendiente de revisión editorial",
            "",
            f"Revisión: {checked_at}",
            "",
            "> Estos enlaces son candidatos. Todavía deben verificarse "
            "abriendo cada publicación y comprobando su contenido, "
            "fecha y autoría oficial.",
            "",
        ]

        for item in new_items:
            report.extend([
                f"## {item['title']}",
                "",
                f"- Fuente: {item['source']}",
                f"- Enlace: {item['url']}",
                "- Estado: Pendiente de verificación y aprobación.",
                "",
            ])

        REPORT_FILE.write_text(
            "\n".join(report),
            encoding="utf-8",
        )

        print(f"Se encontraron {len(new_items)} candidatos nuevos.")
    else:
        print("No se encontraron candidatos nuevos.")

    print("La enciclopedia no ha sido modificada.")


if __name__ == "__main__":
    main()

