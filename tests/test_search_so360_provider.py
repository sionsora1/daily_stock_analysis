"""
Tests for the 360 News direct search provider.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import SearchService, So360NewsSearchProvider


class TestSo360NewsSearchProvider(unittest.TestCase):
    def _response(self, *, status_code: int = 200, content: bytes = b"", text: str = "") -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.content = content
        resp.text = text
        resp.headers = {"content-type": "text/html; charset=utf-8"}
        return resp

    @patch("src.search_service._get_with_retry")
    def test_provider_parses_news_results_from_html(self, mock_get) -> None:
        mock_get.return_value = self._response(
            content=(
                """
                <html>
                  <body>
                    <ul id="news">
                      <li class="full-txt res-list pure-txt" data-url="https://www.360kuai.com/pc/abc">
                        <a title="贵州茅台最新新闻" href="https://www.360kuai.com/pc/abc">
                          <h3 class="g-title js-title">
                            <div class="g-title-inner">
                              <div class="g-txt-inner g-ellipsis">贵州茅台最新新闻</div>
                            </div>
                          </h3>
                          <div class="g-figure-layout-h">
                            <div class="g-figure-caption">
                              <p class="summary g-ellipsis3">贵州茅台的新闻摘要。</p>
                              <p class="g-linkinfo info b-info">
                                <span class="g-linkinfo-txt g-c-gray time">2026-07-05 15:03</span>
                              </p>
                            </div>
                          </div>
                        </a>
                      </li>
                    </ul>
                  </body>
                </html>
                """.encode("utf-8")
            )
        )

        provider = So360NewsSearchProvider()
        response = provider.search("贵州茅台 新闻", max_results=5, days=3)

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "360 News")
        self.assertEqual(len(response.results), 1)
        result = response.results[0]
        self.assertGreater(len(result.title), 0)
        self.assertEqual(result.url, "https://www.360kuai.com/pc/abc")
        self.assertEqual(result.source, "360kuai.com")
        self.assertEqual(result.published_date, "2026-07-05 15:03")
        self.assertGreater(len(result.snippet), 0)
        mock_get.assert_called_once()

    def test_search_service_includes_360_provider_without_keys(self) -> None:
        service = SearchService(
            bocha_keys=[],
            tavily_keys=[],
            brave_keys=[],
            serpapi_keys=[],
            minimax_keys=[],
            searxng_base_urls=[],
            searxng_public_instances_enabled=False,
            anspire_keys=[],
        )

        self.assertTrue(service.is_available)
        providers = service._iter_news_priority_providers()
        self.assertTrue(any(isinstance(provider, So360NewsSearchProvider) for provider in providers))
        self.assertIsInstance(providers[0], So360NewsSearchProvider)
