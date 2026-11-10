import json
import os
import re
import tempfile
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path

from scripts import croft_watch as cw


class CroftWatchTests(unittest.TestCase):
    def article(self, **kwargs):
        base = {
            "title": "Tomb Raider: Legacy of Atlantis at Gamescom 2026",
            "url": "https://www.tombraider.com/news/video-games/sample-story",
            "canonical_url": "https://www.tombraider.com/news/video-games/sample-story",
            "date": "2026-09-02",
            "date_type": "published",
            "date_label": "Publicado: 2 septiembre 2026",
            "body": "Tomb Raider Legacy of Atlantis was presented at Gamescom. Lara Croft explores new puzzles and levels in the game.",
            "content_sha256": "abc123",
            "content_shingles": sorted(cw.shingles("Tomb Raider Legacy of Atlantis was presented at Gamescom. Lara Croft explores new puzzles and levels in the game.")),
        }
        base.update(kwargs)
        return base

    def test_01_url_normalization_removes_tracking(self):
        a = "https://www.tombraider.com/news/story?utm_source=x&ref=abc&id=4#top"
        b = "https://tombraider.com/news/story?id=4"
        self.assertEqual(cw.canonical_url(a), cw.canonical_url(b))

    def test_02_url_normalization_rejects_http(self):
        self.assertEqual(cw.canonical_url("http://example.com/news"), "")

    def test_03_url_normalization_sorts_query(self):
        self.assertEqual(cw.canonical_url("https://example.com/a?z=2&a=1"), cw.canonical_url("https://example.com/a?a=1&z=2"))

    def test_04_patch_versions_are_distinct(self):
        self.assertFalse(cw.title_is_duplicate("Tomb Raider Remastered Patch 3 Notes", "Tomb Raider Remastered Patch 4 Notes"))

    def test_05_same_patch_title_is_duplicate(self):
        self.assertTrue(cw.title_is_duplicate("Tomb Raider I-III Remastered: Challenge Mode Patch 4", "Tomb Raider I-III Remastered: Challenge Mode Patch 4"))

    def test_06_unrelated_regions_are_not_tomb_raider_relevance(self):
        self.assertFalse(cw.is_tomb_raider_relevant("Reimagining Greece", "An article about Greek islands, Peru and Egypt."))

    def test_07_franchise_named_article_is_relevant(self):
        self.assertTrue(cw.is_tomb_raider_relevant("Meet Natla", "Jacqueline Natla appears in Tomb Raider: Legacy of Atlantis."))

    def test_08_category_patch(self):
        self.assertEqual(cw.classify_article("Tomb Raider Patch 4 Notes", "Bug fixes"), "ACTUALIZACIONES Y PARCHES")

    def test_09_category_release(self):
        self.assertEqual(cw.classify_article("Tomb Raider: Legacy of Atlantis pre-orders", "Pre-orders now available"), "PRÓXIMOS PROYECTOS")

    def test_10_category_character(self):
        self.assertEqual(cw.classify_article("Meet Natla", "Actor and character profile for Tomb Raider"), "PERSONAJES Y UNIVERSO")

    def test_11_category_development(self):
        self.assertEqual(cw.classify_article("Combat Reimagined", "Tomb Raider gameplay and combat"), "DESARROLLO")

    def test_12_listing_page_rejected_by_path(self):
        self.assertTrue(cw.is_listing_page("https://www.tombraider.com/news/all", "All News", ""))

    def test_13_category_page_not_article(self):
        self.assertTrue(cw.is_listing_page("https://www.tombraider.com/news/community", "Community News", ""))

    def test_14_verified_source_requires_evidence(self):
        self.assertFalse(cw.source_is_verified({"official_status": "verified", "organization": "Studio"}))

    def test_15_verified_source_with_evidence(self):
        self.assertTrue(cw.source_is_verified({"official_status": "verified", "organization": "Studio", "evidence_url": "https://example.com/about"}))

    def test_16_source_host_scope(self):
        source = {"allowed_hosts": ["tombraider.com"]}
        self.assertTrue(cw.source_matches(source, "https://www.tombraider.com/news/a"))
        self.assertFalse(cw.source_matches(source, "https://tombraider-fans.example/news/a"))

    def test_17_article_path_discovery_scope(self):
        source = {"allowed_hosts": ["playtombraider.com"], "article_path_regex": [r"^/en-us/news/articles/[^/]+$"]}
        self.assertTrue(cw.link_is_article(source, "https://playtombraider.com/en-us/news/articles/meet-larson"))
        self.assertFalse(cw.link_is_article(source, "https://playtombraider.com/en-us/news"))

    def test_18_same_url_duplicate(self):
        a = self.article()
        item = {"url": a["url"], "title": a["title"]}
        duplicate, reason = cw.is_duplicate(a, [item], [])
        self.assertTrue(duplicate)
        self.assertEqual(reason, "url_ya_publicada_sin_huella_previa")

    def test_19_duplicate_tracking_url_same_canonical(self):
        a = self.article(url="https://www.tombraider.com/news/story?utm_source=one", canonical_url="https://www.tombraider.com/news/story?utm_source=one")
        item = {"url": "https://tombraider.com/news/story?utm_campaign=other", "title": "Different tracking"}
        duplicate, _ = cw.is_duplicate(a, [item], [])
        self.assertTrue(duplicate)

    def test_20_same_content_different_url_duplicate(self):
        a = self.article(url="https://www.tombraider.com/news/a", canonical_url="https://www.tombraider.com/news/a")
        item = {"url": "https://www.crystaldynamics.com/news/b", "title": "Syndicated announcement", "content_sha256": a["content_sha256"]}
        duplicate, reason = cw.is_duplicate(a, [item], [])
        self.assertTrue(duplicate)
        self.assertEqual(reason, "contenido_identico")

    def test_21_new_patch_version_not_suppressed_by_same_topic(self):
        a = self.article(title="Tomb Raider I-III Remastered: Challenge Mode Patch 4", content_sha256="newhash")
        item = {"url": "https://support.aspyr.com/hc/en-us/articles/patch3", "title": "Tomb Raider I-III Remastered: Challenge Mode Patch 3", "content_sha256": "oldhash"}
        duplicate, _ = cw.is_duplicate(a, [item], [])
        self.assertFalse(duplicate)

    def test_22_fact_already_documented_exactly(self):
        text = "Tomb Raider Legacy of Atlantis was presented at Gamescom. Lara Croft explores new puzzles and levels in the game."
        a = self.article(body=text, content_shingles=sorted(cw.shingles(text)))
        index = {"documents": [{"id": "doc-1", "title": "Gamescom", "text": text}]}
        documented, match = cw.compare_with_index(a, index)
        self.assertTrue(documented)
        self.assertEqual(match["coverage"], 1.0)

    def test_23_topic_only_not_enough_to_mark_documented(self):
        a = self.article(body="Tomb Raider Legacy of Atlantis new release date and four new enemy types in Egypt.", content_shingles=sorted(cw.shingles("Tomb Raider Legacy of Atlantis new release date and four new enemy types in Egypt.")))
        index = {"documents": [{"id": "doc-1", "title": "Legacy of Atlantis", "text": "Tomb Raider Legacy of Atlantis is a new game by Crystal Dynamics."}]}
        documented, _ = cw.compare_with_index(a, index)
        self.assertFalse(documented)

    def test_24_date_window_includes_start(self):
        self.assertTrue(cw.is_in_window("2026-08-12", 90, date(2026, 11, 10)))

    def test_25_date_window_excludes_previous_day(self):
        self.assertFalse(cw.is_in_window("2026-08-11", 90, date(2026, 11, 10)))

    def test_26_unknown_date_not_accepted(self):
        self.assertFalse(cw.is_in_window(None, 90, date(2026, 11, 10)))

    def test_27_safe_patch_summary_mentions_explicit_version(self):
        article = self.article(title="Tomb Raider I-III Remastered: Challenge Mode Patch 4", body="Fixed bugs across platforms.\n- Fixed secret pickup.\n- Fixed Lara's Home.")
        source = {"organization": "Aspyr"}
        summary = cw.safe_summary(article, source)
        self.assertIn("Patch 4", summary)
        self.assertIn("correcciones", summary)

    def test_28_unknown_english_article_goes_to_review_instead_of_invented_summary(self):
        article = self.article(title="An Unrecognized New Dev Diary", body="Tomb Raider: Catalyst is the topic of this new diary.")
        self.assertIsNone(cw.safe_summary(article, {"organization": "Official Studio"}))

    def test_29_feed_parsing_accepts_article_links(self):
        xml = b'''<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://www.tombraider.com/news/community/a-story</loc></url><url><loc>https://www.tombraider.com/news/all</loc></url></urlset>'''
        source = {"allowed_hosts": ["tombraider.com"], "article_path_regex": [r"^/news/(?!all$)[a-z0-9-]+/[^/]+$"]}
        links = cw.extract_feed_links(xml, "https://www.tombraider.com/sitemap.xml", source)
        self.assertEqual(links, ["https://tombraider.com/news/community/a-story"])

    def test_30_index_excludes_croft_watch_own_news_panel(self):
        index = cw.build_index(Path(__file__).resolve().parents[1] / "index.html")
        self.assertTrue(index["stats"]["tab_panels_indexed"] >= 15)
        self.assertFalse(any(d["id"] == "croft-news" for d in index["documents"]))

    def test_31_initial_news_are_14_sorted_and_unique(self):
        path = Path(__file__).resolve().parents[1] / "data/latest_news.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload["items"]
        self.assertEqual(len(items), 14)
        self.assertEqual(len({x["id"] for x in items}), 14)
        self.assertEqual(items, sorted(items, key=lambda x: x["date"], reverse=True))

    def test_32_initial_raider_records_date_is_corrected(self):
        path = Path(__file__).resolve().parents[1] / "data/latest_news.json"
        items = json.loads(path.read_text(encoding="utf-8"))["items"]
        row = next(x for x in items if "raider-records" in x["url"])
        self.assertEqual(row["date"], "2026-10-16")

    def test_33_html_has_news_tab_panel_and_renderer(self):
        html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
        for needle in ['data-tab-target="croft-news"', 'id="croft-news"', 'id="croft-watch-news-data"', 'id="croft-watch-renderer"']:
            self.assertIn(needle, html)

    def test_34_embedded_news_sync_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "index.html"
            p.write_text((Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
            items = json.loads((Path(__file__).resolve().parents[1] / "data/latest_news.json").read_text(encoding="utf-8"))["items"]
            self.assertFalse(cw.sync_embedded_news(p, items, backup=False))
            first = p.read_bytes()
            self.assertFalse(cw.sync_embedded_news(p, items, backup=False))
            self.assertEqual(first, p.read_bytes())

    def test_35_embedded_sync_exposes_new_article_in_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "index.html"
            p.write_text((Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
            items = json.loads((Path(__file__).resolve().parents[1] / "data/latest_news.json").read_text(encoding="utf-8"))["items"]
            new_item = dict(items[0])
            new_item.update({"id": "cw-test-new", "title": "Tomb Raider: Test Announcement", "url": "https://www.tombraider.com/news/video-games/test-announcement"})
            self.assertTrue(cw.sync_embedded_news(p, [new_item] + items, backup=False))
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
            data = json.loads(soup.find(id="croft-watch-news-data").string)
            self.assertEqual(data["items"][0]["id"], "cw-test-new")

    def test_36_atomic_write_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "folder" / "state.json"
            cw.atomic_write_text(p, "safe")
            self.assertEqual(p.read_text(), "safe")
            self.assertEqual(list(p.parent.iterdir()), [p])

    def test_37_restore_after_removing_croft_watch_is_byte_exact(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "index.html").read_text(encoding="utf-8")
        original = (root / "ORIGINAL_REFERENCE.html").read_text(encoding="utf-8")
        markers = ["STYLE", "TAB", "PANEL", "DATA", "RENDERER"]
        for marker in markers:
            html = re.sub(rf"<!-- CROFT_WATCH_{marker}_START -->.*?<!-- CROFT_WATCH_{marker}_END -->", "", html, flags=re.S)
        self.assertEqual(html, original)

    def test_38_both_html_copies_are_identical(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual((root / "index.html").read_bytes(), (root / "El_Archivo_Croft_V26.2_ENCICLOPEDIA_AMPLIADA.html").read_bytes())

    def test_39_no_empty_commit_guard_exists_in_workflow(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/croft-watch.yml").read_text(encoding="utf-8")
        self.assertIn("steps.publish.outputs.published == 'true'", workflow)
        self.assertIn("git diff --cached --quiet", workflow)

    def test_40_material_change_at_same_url_is_reprocessed(self):
        old = self.article()
        old_item = {
            "url": old["url"], "title": old["title"],
            "content_sha256": "old-hash",
            "content_shingles": sorted(cw.hashed_shingles("Old Tomb Raider article facts and old information.")),
        }
        updated = self.article(content_sha256="new-hash", body="Tomb Raider Legacy of Atlantis announces four new playable areas, a release window and fresh enemy types.")
        duplicate, reason = cw.is_duplicate(updated, [old_item], [])
        self.assertFalse(duplicate, reason)

    def test_41_sitemap_index_exposes_child_sitemaps(self):
        xml = b'''<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://www.tombraider.com/sitemap-news.xml</loc></sitemap></sitemapindex>'''
        source = {"allowed_hosts": ["tombraider.com"]}
        links = cw.extract_nested_sitemap_links(xml, "https://www.tombraider.com/sitemap.xml", source)
        self.assertEqual(links, ["https://tombraider.com/sitemap-news.xml"])

    def test_42_robots_404_means_no_published_rules_not_blocked(self):
        fetcher = cw.RespectfulFetcher(delay=0)
        with patch.object(fetcher, "_request", return_value=(404, b"", {})):
            allowed, reason = fetcher.can_fetch("https://example.test/news/article")
        self.assertTrue(allowed)
        self.assertEqual(reason, "robots_absent_404")

    def test_43_seed_history_contains_every_precarged_news_item(self):
        root = Path(__file__).resolve().parents[1]
        items = json.loads((root / "data/latest_news.json").read_text(encoding="utf-8"))["items"]
        history = [json.loads(line) for line in (root / "data/detection_history.jsonl").read_text(encoding="utf-8").splitlines()]
        published_ids = {row.get("news_id") for row in history if row.get("decision") == "published_seed"}
        self.assertEqual(published_ids, {item["id"] for item in items})

    def test_44_redirects_cannot_leave_the_official_host(self):
        from urllib.request import Request
        handler = cw.OfficialHostRedirectHandler()
        original = Request("https://www.tombraider.com/news/all")
        internal = handler.redirect_request(original, None, 301, "Moved", {}, "https://tombraider.com/news/all")
        external = handler.redirect_request(original, None, 302, "Found", {}, "https://unofficial-fans.example/news")
        self.assertIsNotNone(internal)
        self.assertIsNone(external)

    def test_45_seed_url_uses_later_observed_hash_for_duplicate_check(self):
        article = self.article()
        seed_item = {"url": article["url"], "title": article["title"]}
        fingerprint = {
            "url": article["url"], "title": article["title"],
            "checked_at": "2026-11-10T10:00:00Z",
            "content_sha256": article["content_sha256"],
            "content_shingles": sorted(cw.hashed_shingles(article["body"])),
        }
        duplicate, reason = cw.is_duplicate(article, [seed_item], [fingerprint])
        self.assertTrue(duplicate)
        self.assertEqual(reason, "url_sin_cambios_sustanciales")

    def test_46_seed_url_can_publish_later_substantial_change(self):
        original = self.article()
        seed_item = {"url": original["url"], "title": original["title"]}
        fingerprint = {
            "url": original["url"], "title": original["title"],
            "checked_at": "2026-11-10T10:00:00Z",
            "content_sha256": original["content_sha256"],
            "content_shingles": sorted(cw.hashed_shingles(original["body"])),
        }
        updated = self.article(
            body="Tomb Raider Legacy of Atlantis reveals a completely new release schedule, four additional enemy classes and new gameplay systems.",
            content_sha256="material-new-hash",
        )
        duplicate, reason = cw.is_duplicate(updated, [seed_item], [fingerprint])
        self.assertFalse(duplicate)
        self.assertEqual(reason, "url_actualizada_sustancialmente")

    def test_47_run_scan_publishes_once_and_omits_the_repeat(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            temp_data = temp_root / "data"
            temp_logs = temp_data / "logs"
            (temp_data / "backups").mkdir(parents=True)
            temp_logs.mkdir(parents=True)
            for name in ["index.html", "El_Archivo_Croft_V26.2_ENCICLOPEDIA_AMPLIADA.html"]:
                (temp_root / name).write_bytes((root / name).read_bytes())
            (temp_data / "sources.json").write_bytes((root / "data/sources.json").read_bytes())
            (temp_data / "latest_news.json").write_text(json.dumps({"schema_version": 1, "items": []}), encoding="utf-8")
            (temp_data / "croft_watch_state.json").write_text("{}", encoding="utf-8")
            (temp_data / "detection_history.jsonl").write_text("", encoding="utf-8")
            (temp_data / "review_queue.json").write_text(json.dumps({"schema_version": 1, "items": []}), encoding="utf-8")

            today = cw.utc_now().date().isoformat()
            body = (
                "Tomb Raider Remastered Patch 99 fixes a newly confirmed progression blocker "
                "in the Lost Valley challenge and corrects an inventory issue after loading "
                "a saved game on supported platforms."
            )
            candidate = {
                "title": "Tomb Raider Remastered: Patch 99 Notes",
                "url": "https://support.aspyr.com/hc/en-us/articles/999999-tomb-raider-remastered-patch-99-notes",
                "canonical_url": "https://support.aspyr.com/hc/en-us/articles/999999-tomb-raider-remastered-patch-99-notes",
                "date": today, "date_type": "published", "date_label": "Publicado: " + today,
                "body": body, "description": body, "author": "Aspyr",
                "image_url": None, "content_sha256": cw.sha256_text(cw.normalize_text(body)),
                "content_shingles": sorted(cw.hashed_shingles(body)), "raw_language": "en",
                "source_id": "aspyr_support", "source_name": "Aspyr Support — soporte oficial",
                "organization": "Aspyr", "official": True, "official_status": "verified",
                "source_evidence_url": "https://support.aspyr.com/hc/en-us/search?query=tomb%20raider",
            }
            with patch.object(cw, "ROOT", temp_root), patch.object(cw, "DATA", temp_data), \
                 patch.object(cw, "LOGS", temp_logs), patch.object(cw, "configure_logging", lambda: None):
                source_cfg = json.loads((temp_data / "sources.json").read_text(encoding="utf-8"))
                statuses = [{"source_id": item["id"], "status": "checked"} for item in source_cfg["sources"]]
                fake_scan = lambda sources, state, fetcher, initial: ([candidate], statuses, state)
                with patch.object(cw, "scan_sources", side_effect=fake_scan), \
                     patch.dict(os.environ, {"GITHUB_OUTPUT": str(temp_root / "github_output.txt")}):
                    first = cw.run_scan()
                    self.assertEqual(first["published_new"], 1)
                    self.assertTrue(first["html_changed"])
                    news = json.loads((temp_data / "latest_news.json").read_text(encoding="utf-8"))
                    self.assertEqual(len(news["items"]), 1)
                    after_first = (temp_root / "index.html").read_bytes()

                    second = cw.run_scan()
                    self.assertEqual(second["published_new"], 0)
                    self.assertFalse(second["html_changed"])
                    self.assertEqual(after_first, (temp_root / "index.html").read_bytes())
                    history_lines = (temp_data / "detection_history.jsonl").read_text(encoding="utf-8").splitlines()
                    self.assertEqual(len(history_lines), 2)
                    decisions = [json.loads(line)["decision"] for line in history_lines]
                    self.assertEqual(decisions, ["published", "omitted"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
