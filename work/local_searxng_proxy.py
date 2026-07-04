from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import unescape
from urllib.parse import parse_qs, quote_plus, urlparse
from xml.etree import ElementTree as ET

import requests


HOST = os.environ.get("LOCAL_SEARXNG_PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("LOCAL_SEARXNG_PROXY_PORT", "8899"))
TIMEOUT = float(os.environ.get("LOCAL_SEARXNG_PROXY_TIMEOUT", "15"))


def _google_news_rss_url(query: str) -> str:
    q = quote_plus(query.strip())
    return (
        "https://news.google.com/rss/search"
        f"?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )


def _clean_text(value: str) -> str:
    if not value:
        return ""
    text = unescape(value)
    text = text.replace("\r", " ").replace("\n", " ")
    return " ".join(text.split())


def _extract_source_url(item: ET.Element) -> str:
    source = item.find("source")
    if source is not None:
        url = source.attrib.get("url", "").strip()
        if url:
            return url
    link = item.findtext("link", default="").strip()
    return link


def _extract_published_date(item: ET.Element) -> str | None:
    pub_date = item.findtext("pubDate", default="").strip()
    if not pub_date:
        return None
    try:
        dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
        return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return pub_date


def _fetch_results(query: str) -> list[dict[str, str]]:
    rss_url = _google_news_rss_url(query)
    response = requests.get(
        rss_url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    channel = root.find("channel")
    if channel is None:
        return []

    results: list[dict[str, str]] = []
    for item in channel.findall("item"):
        title = _clean_text(item.findtext("title", default=""))
        link = item.findtext("link", default="").strip()
        description = _clean_text(item.findtext("description", default=""))
        source_url = _extract_source_url(item)
        published = _extract_published_date(item)

        if not title or not link:
            continue

        results.append(
            {
                "title": title,
                "content": description,
                "description": description,
                "url": link,
                "source": urlparse(source_url or link).netloc.replace("www.", "") or "google-news",
                "publishedDate": published or "",
            }
        )
        if len(results) >= 20:
            break

    return results


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalSearXNGProxy/1.0"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/health", "/_health"}:
            self._send_json(200, {"status": "ok"})
            return

        if parsed.path != "/search":
            self._send_json(404, {"error": "not found"})
            return

        query = parse_qs(parsed.query).get("q", [""])[0].strip()
        if not query:
            self._send_json(400, {"error": "missing q"})
            return

        try:
            results = _fetch_results(query)
            payload = {
                "query": query,
                "number_of_results": len(results),
                "results": results,
            }
            self._send_json(200, payload)
        except requests.HTTPError as exc:
            self._send_json(
                502,
                {
                    "error": f"upstream HTTP error: {exc.response.status_code if exc.response else 'unknown'}",
                },
            )
        except Exception as exc:
            self._send_json(502, {"error": f"upstream fetch failed: {exc}"})

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        sys.stdout.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), fmt % args))


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Local SearXNG proxy listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
