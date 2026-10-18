"""Unit tests for collector's robots gate (no live site access)."""
import asyncio
from types import SimpleNamespace
from urllib.robotparser import RobotFileParser

from collector.pipeline import Robots, check_robots, USER_AGENT


URL = "https://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6&p=6:0"


def test_robots_confirmed_missing_is_permitted():
    assert Robots(None, "strict", "missing_http_404").permits(URL)
    assert Robots(None, "strict", "missing_http_410").permits(URL)


def test_unreachable_not_bypassed_even_with_warn():
    assert not Robots(None, "strict", "robots_http_503").permits(URL)
    assert not Robots(None, "warn", "robots_http_503").permits(URL)
    assert not Robots(None, "warn", "robots_error: TimeoutError").permits(URL)


def test_explicit_disallow_still_denied():
    parser = RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /Spill/"])
    assert not Robots(parser, "strict", "checked").permits(URL)
    assert not Robots(parser, "warn", "checked").permits(URL)


def test_check_robots_async_404():
    class FakeResponse:
        status = 404
    class FakeRequest:
        async def get(self, *args, **kwargs):
            return FakeResponse()
    context = SimpleNamespace(request=FakeRequest())
    result = asyncio.run(check_robots(context, "strict"))
    assert result.status == "missing_http_404"
    assert result.permits(URL)


def test_check_robots_async_503():
    class FakeResponse:
        status = 503
    class FakeRequest:
        async def get(self, *args, **kwargs):
            return FakeResponse()
    context = SimpleNamespace(request=FakeRequest())
    result = asyncio.run(check_robots(context, "strict"))
    assert result.status == "robots_http_503"
    assert not result.permits(URL)
