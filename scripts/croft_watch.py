#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Croft Watch: vigilancia editorial para El Archivo Croft.

El motor es conservador: solo rastrea fuentes verificadas, respeta robots.txt,
no publica páginas de listado y nunca inventa un resumen. Los artículos para
los que no existe una regla de síntesis fiable se guardan en review_queue.json.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LOGS = DATA / "logs"
USER_AGENT = "CroftWatch/1.0 (+https://github.com/misterproductions2004-ctrl/-el-archivo-croft; respectful official-news monitor)"
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
TRACKING_PREFIXES = ("utm_", "vero_")
STOP_WORDS = set("""a al algo algunas algunos ante antes como con contra cual cuando de del desde donde dos el ella ellas ellos en entre era es esa ese eso esta estaba estas este esto estos fue ha hasta hay la las le les lo los más mas me mi mis mucha mucho muy ni no nos o os otra otro para pero por porque que se sin sobre son su sus también te tiene todo tras tu tus un una unas uno unos y ya the a an and are as at be by for from has have in into is it its of on or that the their then this to was were will with you your""".split())

FRANCHISE_TERMS = (
    "tomb raider", "lara croft", "legacy of atlantis", "tomb raider: catalyst",
    "the legend of lara croft", "tomb raider i-iii", "tomb raider iv-vi",
    "rise of the tomb raider", "shadow of the tomb raider", "tomb raider: anniversary",
)
CHARACTER_TERMS = ("jacqueline natla", "natla", "larson", "pierre dupont", "sam nishimura", "jonah maiava")
GAME_TERMS = (
    "tomb raider (1996)", "tomb raider ii", "tomb raider iii", "the last revelation",
    "chronicles", "angel of darkness", "legend", "anniversary", "underworld", "survivor trilogy",
    "catalyst", "legacy of atlantis", "remastered",
)
ENTITY_VOCABULARY = [
    "Lara Croft", "Tomb Raider", "Tomb Raider: Catalyst", "Tomb Raider: Legacy of Atlantis",
    "Jacqueline Natla", "Larson", "Pierre Dupont", "Sam Nishimura", "Jonah Maiava",
    "Amanda Evert", "Werner von Croy", "Zip", "Winston", "Qualopec", "Tihocan",
    "Atlantis", "St. Francis’ Folly", "Lost Valley", "Croft Manor", "Crystal Dynamics",
    "Aspyr", "Amazon Game Studios", "Flying Wild Hog", "Core Design",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as exc:
        logging.error("No se pudo leer %s: %s", path, exc)
        return default


def canonical_url(url: str) -> str:
    """Normaliza URL sin borrar rutas/locales que puedan distinguir artículos."""
    try:
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower() or "https"
        if scheme != "https" or not parts.hostname:
            return ""
        host = parts.hostname.lower()
        if host.startswith("www."):
            host = host[4:]
        port = f":{parts.port}" if parts.port and parts.port != 443 else ""
        path = re.sub(r"/{2,}", "/", parts.path or "/")
        if path != "/":
            path = path.rstrip("/")
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            key_l = key.lower()
            if key_l in TRACKING_KEYS or key_l.startswith(TRACKING_PREFIXES):
                continue
            query.append((key, value))
        query.sort()
        return urlunsplit(("https", host + port, path, urlencode(query, doseq=True), ""))
    except (ValueError, AttributeError):
        return ""


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def normalize_text(value: str) -> str:
    value = unescape(value or "")
    value = strip_accents(value).lower()
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"\b(?:advertisement|advertising|cookie preferences|privacy choices|back to top|read more|load more)\b", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def words(value: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+(?:['’-][a-z0-9]+)?", normalize_text(value)) if len(w) > 2 and w not in STOP_WORDS]


def shingles(value: str, size: int = 5) -> set[str]:
    tokens = words(value)
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + size]) for i in range(len(tokens) - size + 1)}


def hashed_shingles(value: str, size: int = 5) -> set[str]:
    """Huellas no reversibles de grupos de palabras; no conserva extractos literales."""
    return {sha256_text(part) for part in shingles(value, size)}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def coverage(left: set[str], right: set[str]) -> float:
    """Fracción del contenido nuevo (left) cubierta por el texto de referencia (right)."""
    if not left:
        return 0.0
    return len(left & right) / len(left)


def extract_patch_version(title: str) -> str | None:
    match = re.search(r"\bpatch\s*([0-9]+(?:\.[0-9]+)*)\b", title, re.I)
    return match.group(1) if match else None


def title_is_duplicate(title_a: str, title_b: str, threshold: float = 0.93) -> bool:
    """Evita confundir dos parches/versiones distintas aunque el resto del título coincida."""
    patch_a, patch_b = extract_patch_version(title_a), extract_patch_version(title_b)
    if patch_a and patch_b and patch_a != patch_b:
        return False
    a, b = normalize_text(title_a), normalize_text(title_b)
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def event_key(title: str, published_date: str | None, patch_version: str | None = None) -> str:
    clean = normalize_text(title)
    clean = re.sub(r"\b(tomb raider|lara croft)\b", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return sha256_text("|".join([clean, published_date or "", patch_version or ""]))[:24]


def source_matches(source: dict[str, Any], url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    allowed = [x.lower() for x in source.get("allowed_hosts", [])]
    return any(host == item or host.endswith("." + item) for item in allowed)


def source_is_verified(source: dict[str, Any]) -> bool:
    return source.get("official_status") == "verified" and bool(source.get("evidence_url")) and bool(source.get("organization"))


def is_tomb_raider_relevant(title: str, body: str) -> bool:
    combined = normalize_text(title + " " + body)
    return any(term in combined for term in FRANCHISE_TERMS)


def is_listing_page(url: str, title: str, body: str = "") -> bool:
    path = urlsplit(url).path.lower().rstrip("/")
    blocked_paths = {
        "/news", "/news/all", "/news-community", "/community", "/hc/en-us",
        "/hc/en-us/categories", "/hc/en-us/sections", "/en-us/news", "/en-gb/news",
    }
    if path in blocked_paths or path.endswith("/news/all") or path.endswith("/news-community"):
        return True
    if re.search(r"\b(latest news|all news|news & community|news)\b", title.strip(), re.I) and len(body) < 1000:
        return True
    return False


def parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except ValueError:
        pass
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _walk_jsonld(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_jsonld(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_jsonld(value)


def extract_article(html_text: str, url: str, source: dict[str, Any]) -> dict[str, Any]:
    soup = BeautifulSoup(html_text, "html.parser")
    jsonld_objects = []
    for script_node in soup.find_all("script", type="application/ld+json"):
        try:
            raw_jsonld = json.loads(script_node.string or script_node.get_text())
            jsonld_objects.extend(list(_walk_jsonld(raw_jsonld)))
        except (json.JSONDecodeError, TypeError):
            continue
    for element in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form"]):
        element.decompose()

    def meta(*names: str) -> str | None:
        for name in names:
            found = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if found and found.get("content"):
                return str(found["content"]).strip()
        return None

    title = (meta("og:title", "twitter:title") or (soup.h1.get_text(" ", strip=True) if soup.h1 else None)
             or (soup.title.get_text(" ", strip=True) if soup.title else ""))
    title = re.sub(r"\s*[|–-]\s*(News|Tomb Raider|Aspyr Support).*$", "", title, flags=re.I).strip()
    description = meta("og:description", "description", "twitter:description") or ""
    image = meta("og:image", "twitter:image")
    author = meta("author", "article:author")
    published = parse_iso_date(meta("article:published_time", "datePublished", "publish-date"))
    modified = parse_iso_date(meta("article:modified_time", "dateModified", "last-modified"))
    time_node = soup.find("time")
    visible_time = None
    if time_node:
        visible_time = parse_iso_date(time_node.get("datetime") or time_node.get_text(" ", strip=True))
        time_context = (time_node.parent.get_text(" ", strip=True) if time_node.parent else time_node.get_text(" ", strip=True))
        if not published and visible_time:
            if re.search(r"\b(updated|actualizado)\b", time_context, re.I):
                modified = modified or visible_time
            else:
                published = visible_time
    jsonld_date_modified = None
    for obj in jsonld_objects:
        published = published or parse_iso_date(obj.get("datePublished"))
        jsonld_date_modified = jsonld_date_modified or parse_iso_date(obj.get("dateModified"))
        author = author or (obj.get("author", {}).get("name") if isinstance(obj.get("author"), dict) else None)
    modified = modified or jsonld_date_modified

    container = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = []
    for element in container.find_all(["p", "li", "blockquote"]):
        line = re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()
        if len(line) >= 35 and line not in paragraphs:
            paragraphs.append(line)
    body = "\n".join(paragraphs)
    if len(body) < 120:
        body = re.sub(r"\s+", " ", container.get_text(" ", strip=True))
    body = body[:80000]
    if not published and not modified:
        date_match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b", body[:1200], re.I)
        if date_match:
            try:
                parsed_date = datetime.strptime(date_match.group(0), "%B %d, %Y").date().isoformat()
                if re.search(r"\b(updated|actualizado)\b", body[:350], re.I):
                    modified = parsed_date
                else:
                    published = parsed_date
            except ValueError:
                pass
    if not description and body:
        description = body[:400]
    date_type = "published" if published else ("updated" if modified else "unknown")
    article_date = published or modified
    date_label = None
    if article_date:
        dt = date.fromisoformat(article_date)
        months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        prefix = "Publicado" if date_type == "published" else "Última actualización"
        date_label = f"{prefix}: {dt.day} {months[dt.month - 1]} {dt.year}"

    links = []
    for anchor in soup.find_all("a", href=True):
        absolute = canonical_url(urljoin(url, str(anchor["href"])))
        if absolute and source_matches(source, absolute):
            links.append(absolute)
    unique_links = list(dict.fromkeys(links))
    return {
        "title": title, "description": description, "body": body,
        "date": article_date, "date_type": date_type, "date_label": date_label,
        "author": author, "image_url": image if image and image.startswith("https://") else None,
        "links": unique_links, "canonical_url": canonical_url(url),
        "content_sha256": sha256_text(normalize_text(body)),
        "content_shingles": sorted(hashed_shingles(body)),
        "raw_language": soup.html.get("lang") if soup.html else None,
    }


def classify_article(title: str, body: str) -> str:
    text = normalize_text(title + " " + body[:3500])
    if re.search(r"\b(patch|hotfix|update notes|patch notes|bug fixes)\b", text):
        return "ACTUALIZACIONES Y PARCHES"
    if re.search(r"\b(movie|film|television|tv series|live action|animated series|netflix|prime video)\b", text):
        return "CINE Y TELEVISIÓN"
    if re.search(r"\b(comic|comics|graphic novel|novel|book|publishing)\b", text):
        return "CÓMICS Y LIBROS"
    if re.search(r"\b(gamescom|game awards|convention|showcase|event|streaming)\b", text):
        return "EVENTOS OFICIALES"
    if re.search(r"\b(pre[ -]?orders?|release date|launches|available on|wishlist|coming soon)\b", text):
        return "PRÓXIMOS PROYECTOS"
    if re.search(r"\b(meet |voice|actor|actress|portrays|plays |character)\b", text):
        return "PERSONAJES Y UNIVERSO"
    if re.search(r"\b(development|design|combat|traversal|creatures|enemies|puzzles|reimagining)\b", text):
        return "DESARROLLO"
    return "OTROS ANUNCIOS"


def safe_summary(article: dict[str, Any], source: dict[str, Any]) -> str | None:
    """Genera únicamente resúmenes deterministas soportados por reglas explícitas."""
    title = article.get("title", "").strip()
    body = article.get("body", "")
    norm = normalize_text(title + " " + body)
    patch = extract_patch_version(title)
    if patch:
        product = title.split(" - Patch", 1)[0].split(": Patch", 1)[0].strip()
        bullet_count = len(re.findall(r"(?m)^\s*(?:[-*•]|\d+\.)\s+", body))
        details = f" Las notas incluyen {bullet_count} puntos enumerados." if bullet_count else ""
        return (f"La página de soporte de {source['organization']} publicó las notas de Patch {patch} para {product}. "
                f"La publicación documenta los cambios y correcciones de esa versión; consulta la fuente original para el listado completo.{details}")
    if "pre-order" in norm or "preorder" in norm:
        if "legacy of atlantis" in norm:
            date_match = re.search(r"\b(February|March|April|May|June|July|August|September|October|November|December|January)\s+\d{1,2},\s+20\d{2}\b", body, re.I)
            release = date_match.group(0) if date_match else None
            switch2 = "nintendo switch 2" in norm
            platforms = [p for p in ["PlayStation 5", "Xbox Series X|S", "PC (Steam)", "Nintendo Switch 2"] if p.lower() in norm]
            details = (" en Nintendo Switch 2" if switch2 else "")
            date_text = f" La página indica como fecha de lanzamiento {release}." if release else ""
            platform_text = f" También enumera las plataformas {', '.join(platforms)}." if platforms else ""
            return f"La fuente oficial anunció que las reservas de Tomb Raider: Legacy of Atlantis están disponibles{details}.{date_text}{platform_text} La tarjeta conserva el enlace al anuncio original para consultar las condiciones y ediciones."
    known_rules = {
        "tomb raider turns 30": "El sitio oficial celebró el 30.º aniversario de Tomb Raider y anunció una colección musical Lo‑Fi junto a ThatNorskChick. También adelantó la llegada de más de 500 pistas oficiales de bandas sonoras a plataformas de streaming durante noviembre de 2026.",
        "raider records": "El portal oficial presentó Raider Records, un seguimiento de los puzles Tomb Door de Tomb Raider: Legacy of Atlantis. La página reúne pistas y secuencias, actualiza el número de símbolos descubiertos y muestra el estado de los desafíos.",
    }
    for key, summary in known_rules.items():
        if key in normalize_text(title):
            return summary
    return None


def build_index(html_path: Path) -> dict[str, Any]:
    raw = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    documents: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    for panel in soup.select(".tab-content"):
        if panel.get("id") == "croft-news":
            continue
        panel_id = panel.get("id") or f"section-{len(sections)+1}"
        heading = panel.find(["h1", "h2", "h3"])
        panel_title = heading.get_text(" ", strip=True) if heading else panel_id
        panel_text = re.sub(r"\s+", " ", panel.get_text(" ", strip=True)).strip()
        if panel_text:
            docs = [{"id": panel_id, "kind": "tab", "title": panel_title, "text": panel_text}]
            for n, details in enumerate(panel.find_all("details"), 1):
                summary = details.find("summary")
                detail_title = summary.get_text(" ", strip=True) if summary else f"{panel_title} · ficha {n}"
                detail_text = re.sub(r"\s+", " ", details.get_text(" ", strip=True)).strip()
                if len(detail_text) >= 80:
                    detail_id = details.get("id") or f"{panel_id}-detail-{n}"
                    docs.append({"id": detail_id, "kind": "detail", "title": detail_title, "text": detail_text})
            documents.extend(docs)
            sections.append({"id": panel_id, "title": panel_title, "document_count": len(docs), "characters": len(panel_text)})
    headings = []
    for node in soup.select("h1,h2,h3,h4"):
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if text and node.find_parent(id="croft-news") is None:
            headings.append(text)
    entities = []
    corpus = "\n".join(d["text"] for d in documents)
    folded = normalize_text(corpus)
    for name in ENTITY_VOCABULARY:
        if normalize_text(name) in folded:
            entities.append(name)
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "html_file": html_path.name,
        "html_sha256": sha256_text(raw),
        "stats": {
            "tab_panels_indexed": len(sections),
            "details_indexed": sum(1 for d in documents if d["kind"] == "detail"),
            "documents_indexed": len(documents),
            "headings_indexed": len(headings),
            "entities_recognized": len(entities),
            "visible_text_characters": sum(len(d["text"]) for d in documents if d["kind"] == "tab"),
        },
        "sections": sections,
        "headings": headings,
        "entities": entities,
        "documents": documents,
    }


def compare_with_index(article: dict[str, Any], index: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    candidate = shingles(article.get("body", ""))
    best = {"similarity": 0.0, "coverage": 0.0, "document_id": None, "document_title": None}
    if len(candidate) < 8:
        return False, best
    for doc in index.get("documents", []):
        reference = set(shingles(doc.get("text", "")))
        score = jaccard(candidate, reference)
        covered = coverage(candidate, reference)
        if score > best["similarity"] or covered > best["coverage"]:
            best = {"similarity": round(score, 4), "coverage": round(covered, 4), "document_id": doc.get("id"), "document_title": doc.get("title")}
    documented = best["coverage"] >= 0.90 and best["similarity"] >= 0.72
    return documented, best


def is_duplicate(article: dict[str, Any], news_items: list[dict[str, Any]], history: list[dict[str, Any]]) -> tuple[bool, str]:
    url = canonical_url(article.get("canonical_url") or article.get("url", ""))
    title = article.get("title", "")
    current_hash = article.get("content_sha256")
    current_shingles = set(article.get("content_shingles") or hashed_shingles(article.get("body", "")))
    current_patch = extract_patch_version(title)

    same_url_items = [item for item in news_items if url and canonical_url(item.get("url", "")) == url]
    same_url_history = [record for record in history if url and canonical_url(record.get("url", "")) == url]
    same_url_entries = same_url_items + same_url_history
    materially_changed_same_url = False

    if same_url_entries:
        old_patches = {extract_patch_version(entry.get("title", "")) for entry in same_url_entries}
        patch_is_new = bool(current_patch and any(old and old != current_patch for old in old_patches))
        if not patch_is_new:
            fingerprinted = [entry for entry in same_url_entries if entry.get("content_sha256")]
            fingerprinted.sort(key=lambda entry: (
                entry.get("checked_at") or entry.get("detected_at") or entry.get("published_to_archive_at") or ""
            ))
            baseline = fingerprinted[-1] if fingerprinted else None
            if current_hash and baseline:
                old_hash = baseline.get("content_sha256")
                old_shingles = set(baseline.get("content_shingles", []))
                if current_hash == old_hash or (old_shingles and jaccard(current_shingles, old_shingles) >= 0.88):
                    return True, "url_sin_cambios_sustanciales"
                materially_changed_same_url = True
            else:
                return True, "url_ya_publicada_sin_huella_previa"
        else:
            materially_changed_same_url = True

    for item in news_items:
        if url and canonical_url(item.get("url", "")) == url:
            continue
        if item.get("event_key") and item.get("event_key") == event_key(title, article.get("date"), current_patch):
            return True, "mismo_evento_entre_fuentes"
        if title_is_duplicate(title, item.get("title", "")):
            old_patch = extract_patch_version(item.get("title", ""))
            if not (current_patch and old_patch and current_patch != old_patch):
                return True, "titular_duplicado"
        if current_hash and current_hash == item.get("content_sha256"):
            return True, "contenido_identico"
        old_shingles = set(item.get("content_shingles", []))
        if old_shingles and jaccard(current_shingles, old_shingles) >= 0.88:
            return True, "contenido_equivalente_entre_fuentes"

    for record in history:
        if url and canonical_url(record.get("url", "")) == url:
            continue
        if record.get("content_sha256") and current_hash == record.get("content_sha256"):
            return True, "huella_de_contenido_ya_examinada"
        old_title = record.get("title", "")
        if old_title and title_is_duplicate(title, old_title):
            old_patch = extract_patch_version(old_title)
            if not (current_patch and old_patch and current_patch != old_patch):
                return True, "titular_ya_examinado"

    if materially_changed_same_url:
        return False, "url_actualizada_sustancialmente"
    return False, "novedad_no_duplicada"


class OfficialHostRedirectHandler(HTTPRedirectHandler):
    """Permite redirecciones dentro del mismo host (con o sin www), nunca a terceros."""
    @staticmethod
    def _normalized_host(url: str) -> str:
        host = (urlsplit(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self._normalized_host(req.full_url) != self._normalized_host(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class RespectfulFetcher:
    def __init__(self, timeout: int = 20, delay: float = 1.0):
        self.timeout = timeout
        self.delay = delay
        self.last_request_by_host: dict[str, float] = {}
        self.robots: dict[str, tuple[bool, RobotFileParser | None]] = {}
        self.sitemaps: dict[str, list[str]] = {}

    def _wait(self, host: str) -> None:
        previous = self.last_request_by_host.get(host, 0.0)
        remaining = self.delay - (time.monotonic() - previous)
        if remaining > 0:
            time.sleep(remaining)
        self.last_request_by_host[host] = time.monotonic()

    def _request(self, url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes, dict[str, str]]:
        host = urlsplit(url).hostname or ""
        self._wait(host)
        request_headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.7"}
        request_headers.update(headers or {})
        req = Request(url, headers=request_headers)
        try:
            opener = build_opener(OfficialHostRedirectHandler())
            with opener.open(req, timeout=self.timeout) as response:
                response_headers = dict(response.headers.items())
                response_headers["X-CroftWatch-Final-URL"] = response.geturl()
                return response.status, response.read(3_500_000), response_headers
        except HTTPError as exc:
            response_headers = dict(exc.headers.items()) if exc.headers else {}
            response_headers["X-CroftWatch-Final-URL"] = exc.geturl()
            return exc.code, exc.read(1_000_000), response_headers
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"No se pudo consultar {url}: {exc}") from exc

    def can_fetch(self, url: str) -> tuple[bool, str]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self.robots:
            allowed, _ = self.robots[origin]
            return allowed, "robots_cache"
        robots_url = origin + "/robots.txt"
        try:
            status, body, _ = self._request(robots_url)
            if status == 404:
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse([])
                self.robots[origin] = (True, parser)
                self.sitemaps[origin] = []
                return True, "robots_absent_404"
            if status != 200:
                self.robots[origin] = (False, None)
                return False, f"robots_http_{status}"
            lines = body.decode("utf-8", errors="replace").splitlines()
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(lines)
            self.sitemaps[origin] = [line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("sitemap:") and ":" in line]
            allowed = parser.can_fetch(USER_AGENT, url)
            self.robots[origin] = (allowed, parser)
            return allowed, "robots_allowed" if allowed else "robots_disallow"
        except Exception as exc:
            self.robots[origin] = (False, None)
            return False, f"robots_unavailable:{exc}"

    def get(self, url: str, previous: dict[str, Any] | None = None, check_robots: bool = True) -> dict[str, Any]:
        previous = previous or {}
        if check_robots:
            allowed, reason = self.can_fetch(url)
            if not allowed:
                return {"status": 0, "body": b"", "headers": {}, "blocked": True, "reason": reason}
        headers = {}
        if previous.get("etag"):
            headers["If-None-Match"] = previous["etag"]
        if previous.get("last_modified"):
            headers["If-Modified-Since"] = previous["last_modified"]
        status, body, response_headers = self._request(url, headers)
        return {
            "status": status, "body": body, "headers": response_headers,
            "etag": response_headers.get("ETag"),
            "last_modified": response_headers.get("Last-Modified"),
            "final_url": response_headers.get("X-CroftWatch-Final-URL", url),
            "blocked": False, "reason": "http_response",
        }


def link_is_article(source: dict[str, Any], url: str) -> bool:
    if not source_matches(source, url):
        return False
    path = urlsplit(url).path
    return any(re.search(pattern, path, re.I) for pattern in source.get("article_path_regex", []))


def extract_feed_links(xml_bytes: bytes, feed_url: str, source: dict[str, Any]) -> list[str]:
    """Devuelve URLs de sitemap, RSS o Atom sin tratar el propio feed como noticia."""
    result: list[str] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return result
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1].lower()
        value = None
        if tag == "loc" and node.text:
            value = node.text.strip()
        elif tag == "link":
            href = node.attrib.get("href")
            rel = node.attrib.get("rel", "alternate").lower()
            if href and rel in {"alternate", ""}:
                value = href
            elif node.text and node.text.strip().startswith("https://"):
                value = node.text.strip()
        if value:
            absolute = canonical_url(urljoin(feed_url, value))
            if absolute and link_is_article(source, absolute):
                result.append(absolute)
    return list(dict.fromkeys(result))


def extract_nested_sitemap_links(xml_bytes: bytes, sitemap_url: str, source: dict[str, Any]) -> list[str]:
    """Extrae sitemaps hijos desde sitemapindex sin confundirlos con artículos."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    if root.tag.rsplit("}", 1)[-1].lower() != "sitemapindex":
        return []
    links = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() != "loc" or not node.text:
            continue
        absolute = canonical_url(urljoin(sitemap_url, node.text.strip()))
        if absolute and source_matches(source, absolute):
            links.append(absolute)
    return list(dict.fromkeys(links))


def discover_alternate_feeds(html_bytes: bytes, page_url: str, source: dict[str, Any]) -> list[str]:
    soup = BeautifulSoup(html_bytes, "html.parser")
    feeds = []
    for node in soup.find_all("link", href=True):
        kind = (node.get("type") or "").lower()
        rel = [str(x).lower() for x in (node.get("rel") or [])]
        if "alternate" in rel and ("rss" in kind or "atom" in kind or "xml" in kind):
            url = canonical_url(urljoin(page_url, str(node["href"])))
            if url and source_matches(source, url):
                feeds.append(url)
    return list(dict.fromkeys(feeds))


def scan_sources(sources: dict[str, Any], state: dict[str, Any], fetcher: RespectfulFetcher, initial: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    source_results: list[dict[str, Any]] = []
    cache = state.setdefault("http_cache", {})
    discovered = state.setdefault("discovered_urls", {})
    for source in sources.get("sources", []):
        source_id = source["id"]
        if not source_is_verified(source):
            source_results.append({"source_id": source_id, "status": "skipped_unverified", "reason": "Fuente no verificada"})
            continue
        source_seen_urls: list[str] = []
        listing_ok = 0
        listing_errors = []
        for listing_url in source.get("listing_urls", []):
            key = canonical_url(listing_url)
            try:
                response = fetcher.get(listing_url, cache.get(key))
                if response["blocked"]:
                    listing_errors.append(response["reason"])
                    continue
                if not source_matches(source, response.get("final_url", listing_url)):
                    listing_errors.append("redirect_fuera_del_host_oficial")
                    continue
                if response["status"] == 304:
                    listing_ok += 1
                    source_seen_urls.extend(discovered.get(source_id, []))
                    continue
                if response["status"] != 200:
                    listing_errors.append(f"HTTP {response['status']}: {listing_url}")
                    continue
                cache[key] = {"etag": response.get("etag"), "last_modified": response.get("last_modified"), "checked_at": iso_now()}
                listing = extract_article(response["body"].decode("utf-8", errors="replace"), listing_url, source)
                page_soup = BeautifulSoup(response["body"], "html.parser")
                for a in page_soup.find_all("a", href=True):
                    link = canonical_url(urljoin(listing_url, str(a["href"])))
                    if link and link_is_article(source, link) and not is_listing_page(link, a.get_text(" ", strip=True)):
                        source_seen_urls.append(link)
                feed_urls = discover_alternate_feeds(response["body"], listing_url, source)
                origin = f"{urlsplit(listing_url).scheme}://{urlsplit(listing_url).netloc}"
                feed_urls.extend(fetcher.sitemaps.get(origin, []))
                feed_queue = list(dict.fromkeys(feed_urls))[:8]
                processed_feeds: set[str] = set()
                while feed_queue and len(processed_feeds) < 12:
                    feed_url = feed_queue.pop(0)
                    feed_key = canonical_url(feed_url)
                    if not feed_key or feed_key in processed_feeds or not source_matches(source, feed_url):
                        continue
                    processed_feeds.add(feed_key)
                    feed_response = fetcher.get(feed_url, cache.get(feed_key))
                    if feed_response["blocked"] or not source_matches(source, feed_response.get("final_url", feed_url)):
                        listing_errors.append("feed_bloqueado_o_redirigido_fuera_del_host_oficial")
                        continue
                    if feed_response["status"] == 200:
                        cache[feed_key] = {"etag": feed_response.get("etag"), "last_modified": feed_response.get("last_modified"), "checked_at": iso_now()}
                        source_seen_urls.extend(extract_feed_links(feed_response["body"], feed_url, source))
                        for nested in extract_nested_sitemap_links(feed_response["body"], feed_url, source):
                            if nested not in processed_feeds and nested not in feed_queue:
                                feed_queue.append(nested)
                listing_ok += 1
            except Exception as exc:
                listing_errors.append(str(exc))
        source_seen_urls = list(dict.fromkeys(source_seen_urls))[:int(source.get("max_articles_per_scan", 80))]
        if source_seen_urls:
            discovered[source_id] = source_seen_urls
        for article_url in source_seen_urls:
            key = canonical_url(article_url)
            try:
                response = fetcher.get(article_url, cache.get(key))
                if response["blocked"]:
                    candidates.append({"source_id": source_id, "url": article_url, "blocked": True, "reason": response["reason"]})
                    continue
                if not source_matches(source, response.get("final_url", article_url)):
                    candidates.append({"source_id": source_id, "url": article_url, "blocked": True, "reason": "redirect_fuera_del_host_oficial"})
                    continue
                if response["status"] == 304:
                    continue
                if response["status"] != 200:
                    candidates.append({"source_id": source_id, "url": article_url, "error": f"HTTP {response['status']}"})
                    continue
                cache[key] = {"etag": response.get("etag"), "last_modified": response.get("last_modified"), "checked_at": iso_now()}
                article = extract_article(response["body"].decode("utf-8", errors="replace"), article_url, source)
                article.update({"url": article_url, "source_id": source_id, "source_name": source["name"],
                                "organization": source["organization"], "official": True,
                                "official_status": "verified", "source_evidence_url": source["evidence_url"]})
                if is_listing_page(article_url, article.get("title", ""), article.get("body", "")):
                    article["rejection_reason"] = "pagina_de_listado"
                elif not is_tomb_raider_relevant(article.get("title", ""), article.get("body", "")):
                    article["rejection_reason"] = "sin_relacion_inequivoca_con_tomb_raider"
                candidates.append(article)
            except Exception as exc:
                candidates.append({"source_id": source_id, "url": article_url, "error": str(exc)})
        source_results.append({
            "source_id": source_id,
            "status": "checked" if listing_ok else "inaccessible",
            "listings_checked": listing_ok,
            "articles_discovered": len(source_seen_urls),
            "errors": listing_errors,
            "last_checked_at": iso_now(),
        })
    return candidates, source_results, state


def is_in_window(article_date: str | None, days: int = 90, today: date | None = None) -> bool:
    if not article_date:
        return False
    try:
        d = date.fromisoformat(article_date[:10])
    except ValueError:
        return False
    current = today or utc_now().date()
    return current - timedelta(days=days) <= d <= current


def news_item_from_article(article: dict[str, Any], summary: str, category: str) -> dict[str, Any]:
    url = canonical_url(article.get("url", ""))
    version = extract_patch_version(article.get("title", ""))
    key = event_key(article.get("title", ""), article.get("date"), version)
    stable_seed = "|".join([url, article.get("date") or "", article.get("content_sha256") or key])
    ident = "cw-" + sha256_text(stable_seed)[:16]
    date_label = article.get("date_label") or article.get("date") or "Fecha no disponible"
    return {
        "id": ident,
        "event_key": key,
        "title": article.get("title", "Publicación oficial"),
        "date": article.get("date"),
        "source_published_date": article.get("date") if article.get("date_type") == "published" else None,
        "date_type": article.get("date_type", "unknown"),
        "date_label": date_label,
        "source_name": article.get("source_name"),
        "organization": article.get("organization"),
        "author": article.get("author"),
        "url": url,
        "image_url": article.get("image_url"),
        "category": category,
        "summary_es": summary,
        "official": True,
        "official_status": "verified",
        "source_id": article.get("source_id"),
        "source_evidence_url": article.get("source_evidence_url"),
        "detected_at": iso_now(),
        "published_to_archive_at": iso_now(),
        "content_sha256": article.get("content_sha256"),
        "content_shingles": article.get("content_shingles", []),
        "related_entities": [n for n in ENTITY_VOCABULARY if normalize_text(n) in normalize_text(article.get("title", "") + " " + article.get("body", ""))],
        "original_language": article.get("raw_language") or "unknown",
    }


def sync_embedded_news(html_path: Path, items: list[dict[str, Any]], backup: bool = True) -> bool:
    raw = html_path.read_text(encoding="utf-8")
    payload = json.dumps({"schema_version": 1, "items": items}, ensure_ascii=True, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    pattern = re.compile(r'(<script\b[^>]*id=["\']croft-watch-news-data["\'][^>]*>).*?(</script>)', re.I | re.S)
    updated, count = pattern.subn(lambda m: m.group(1) + payload + m.group(2), raw, count=1)
    if count != 1:
        raise RuntimeError(f"No se encontró el bloque de datos incrustado en {html_path}")
    if updated == raw:
        return False
    if backup:
        backup_dir = DATA / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{html_path.stem}.{utc_now().strftime('%Y%m%dT%H%M%SZ')}.bak.html"
        atomic_write_text(backup_path, raw)
    atomic_write_text(html_path, updated)
    return True


def add_history(history_path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    history_path.parent.mkdir(parents=True, exist_ok=True)
    existing = history_path.read_text(encoding="utf-8") if history_path.exists() else ""
    lines = existing.splitlines()
    for record in records:
        lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
    atomic_write_text(history_path, "\n".join(lines) + "\n")


def configure_logging() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOGS / "croft-watch.log", encoding="utf-8")],
    )


def run_scan(force_initial: bool = False, offline: bool = False, dry_run: bool = False) -> dict[str, Any]:
    configure_logging()
    sources_path = DATA / "sources.json"
    sources = load_json(sources_path, {"sources": []})
    state_path = DATA / "croft_watch_state.json"
    state = load_json(state_path, {"schema_version": 1, "initial_scan_completed": False, "http_cache": {}, "discovered_urls": {}, "history": []})
    latest_path = DATA / "latest_news.json"
    latest = load_json(latest_path, {"schema_version": 1, "items": []})
    items = latest.get("items", [])
    index_path = DATA / "archivo_croft_index.json"
    index = build_index(ROOT / "index.html")
    if not dry_run:
        atomic_write_json(index_path, index)
    history_path = DATA / "detection_history.jsonl"
    history = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            try:
                history.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    first_scan = force_initial or not state.get("initial_scan_completed", False)
    fetcher = RespectfulFetcher()
    candidates, source_results = [], []
    if offline:
        source_results = [{"source_id": s["id"], "status": "not_run", "reason": "modo offline"} for s in sources.get("sources", [])]
    else:
        candidates, source_results, state = scan_sources(sources, state, fetcher, first_scan)

    window_days = 90 if first_scan else 3
    new_items: list[dict[str, Any]] = []
    new_history: list[dict[str, Any]] = []
    review_queue = load_json(DATA / "review_queue.json", {"schema_version": 1, "items": []})
    review_items = review_queue.get("items", [])
    review_urls = {canonical_url(x.get("url", "")) for x in review_items}
    rejected = Counter()
    for article in candidates:
        if article.get("blocked") or article.get("error"):
            rejected["blocked_or_error"] += 1
            new_history.append({"checked_at": iso_now(), "url": article.get("url"), "source_id": article.get("source_id"), "decision": "inaccessible", "reason": article.get("reason") or article.get("error")})
            continue
        if article.get("rejection_reason"):
            rejected[article["rejection_reason"]] += 1
            new_history.append({"checked_at": iso_now(), "url": article.get("url"), "title": article.get("title"), "source_id": article.get("source_id"), "decision": "omitted", "reason": article["rejection_reason"], "content_sha256": article.get("content_sha256"), "content_shingles": article.get("content_shingles", [])})
            continue
        if not article.get("date") or not is_in_window(article["date"], days=window_days):
            rejected["outside_window_or_no_date"] += 1
            new_history.append({"checked_at": iso_now(), "url": article.get("url"), "title": article.get("title"), "source_id": article.get("source_id"), "decision": "omitted", "reason": "fuera_de_ventana_o_sin_fecha", "content_sha256": article.get("content_sha256"), "content_shingles": article.get("content_shingles", [])})
            continue
        duplicate, reason = is_duplicate(article, items + new_items, history + new_history)
        if duplicate:
            rejected[reason] += 1
            new_history.append({"checked_at": iso_now(), "url": article.get("url"), "title": article.get("title"), "source_id": article.get("source_id"), "decision": "omitted", "reason": reason, "content_sha256": article.get("content_sha256"), "content_shingles": article.get("content_shingles", [])})
            continue
        documented, match = compare_with_index(article, index)
        if documented:
            rejected["already_documented_in_encyclopedia"] += 1
            new_history.append({"checked_at": iso_now(), "url": article.get("url"), "title": article.get("title"), "source_id": article.get("source_id"), "decision": "omitted", "reason": "informacion_ya_documentada", "index_match": match, "content_sha256": article.get("content_sha256"), "content_shingles": article.get("content_shingles", [])})
            continue
        source = next((s for s in sources.get("sources", []) if s.get("id") == article.get("source_id")), None)
        if not source or not source_is_verified(source) or not source_matches(source, article.get("url", "")):
            rejected["source_not_verified"] += 1
            new_history.append({"checked_at": iso_now(), "url": article.get("url"), "title": article.get("title"), "decision": "omitted", "reason": "source_not_verified"})
            continue
        summary = safe_summary(article, source)
        if not summary:
            if canonical_url(article.get("url", "")) not in review_urls:
                review_items.append({
                    "title": article.get("title"), "date": article.get("date"), "url": canonical_url(article.get("url", "")),
                    "source_id": article.get("source_id"), "source_name": article.get("source_name"),
                    "reason": "No existe una regla de resumen en español suficientemente fiel; no se inventa ni se traduce de forma opaca.",
                    "detected_at": iso_now(), "content_sha256": article.get("content_sha256"),
                    "category_suggestion": classify_article(article.get("title", ""), article.get("body", "")),
                })
                review_urls.add(canonical_url(article.get("url", "")))
            rejected["requires_safe_spanish_summary"] += 1
            new_history.append({"checked_at": iso_now(), "url": article.get("url"), "title": article.get("title"), "source_id": article.get("source_id"), "decision": "queued_for_review", "reason": "no_summary_rule", "content_sha256": article.get("content_sha256"), "content_shingles": article.get("content_shingles", [])})
            continue
        category = classify_article(article.get("title", ""), article.get("body", ""))
        item = news_item_from_article(article, summary, category)
        new_items.append(item)
        new_history.append({"checked_at": iso_now(), "url": article.get("url"), "title": article.get("title"), "source_id": article.get("source_id"), "decision": "published", "reason": "novelty_verified", "content_sha256": article.get("content_sha256"), "content_shingles": article.get("content_shingles", []), "news_id": item["id"]})

    all_items = sorted(items + new_items, key=lambda x: (x.get("date") or "0000-00-00", x.get("published_to_archive_at") or ""), reverse=True)
    changed = bool(new_items)
    if changed and not dry_run:
        latest["generated_at"] = iso_now()
        latest["items"] = all_items
        atomic_write_json(latest_path, latest)
        for html_path in [ROOT / "index.html", ROOT / "El_Archivo_Croft_V26.2_ENCICLOPEDIA_AMPLIADA.html"]:
            if html_path.exists():
                sync_embedded_news(html_path, all_items)
    if not dry_run:
        atomic_write_json(DATA / "review_queue.json", {"schema_version": 1, "generated_at": iso_now(), "items": review_items})
        add_history(history_path, new_history)
        state["last_attempt_at"] = iso_now()
        state["last_successful_scan_at"] = iso_now() if all(r.get("status") in {"checked", "not_run", "skipped_unverified"} for r in source_results) else state.get("last_successful_scan_at")
        state["last_window_days"] = window_days
        state["last_source_results"] = source_results
        state["last_decision_counts"] = dict(rejected)
        state["last_published_count"] = len(new_items)
        state["initial_scan_completed"] = bool(first_scan and not offline and all(r.get("status") == "checked" for r in source_results if r.get("status") != "skipped_unverified")) or bool(state.get("initial_scan_completed"))
        atomic_write_json(state_path, state)

    result = {
        "initial_scan": first_scan,
        "window_days": window_days,
        "sources": source_results,
        "candidates_examined": len(candidates),
        "published_new": len(new_items),
        "queued_for_review": rejected.get("requires_safe_spanish_summary", 0),
        "omitted": dict(rejected),
        "html_changed": changed,
    }
    logging.info("Resumen de ejecución: %s", json.dumps(result, ensure_ascii=False))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"published={'true' if changed else 'false'}\n")
            handle.write(f"published_count={len(new_items)}\n")
            handle.write(f"initial_scan={'true' if first_scan else 'false'}\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Croft Watch — monitor oficial de Tomb Raider")
    parser.add_argument("--initial", action="store_true", help="fuerza el análisis de la ventana histórica de 90 días")
    parser.add_argument("--index-only", action="store_true", help="reconstruye el índice desde index.html sin consultar la web")
    parser.add_argument("--offline", action="store_true", help="ejecuta el motor sin consultas de red (diagnóstico)")
    parser.add_argument("--dry-run", action="store_true", help="no escribe archivos publicables ni historial")
    args = parser.parse_args()
    if args.index_only:
        index = build_index(ROOT / "index.html")
        atomic_write_json(DATA / "archivo_croft_index.json", index)
        print(json.dumps(index["stats"], ensure_ascii=False, indent=2))
        return 0
    try:
        result = run_scan(force_initial=args.initial, offline=args.offline, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        logging.exception("La ejecución terminó con error")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())