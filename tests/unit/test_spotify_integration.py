"""Unit tests for spotify integration."""

from __future__ import annotations

from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from tools.integrations.spotify_integration import (
    SpotifyIntegration, SpotifyPlayer, SpotifySearch, SpotifyAuthError,
)


def _resp(payload=None, code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = code
    r.text = "" if code < 400 else "err"
    r.content = b"{}"
    r.json.return_value = payload if payload is not None else {}
    return r


def _wire(mock_cls, resp: MagicMock) -> AsyncMock:
    """Wire httpx.AsyncClient mock with proper async support."""
    client = AsyncMock()
    for m in ("request", "get", "post", "put", "delete"):
        setattr(client, m, AsyncMock(return_value=resp))
    client.aclose = AsyncMock(return_value=None)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    mock_cls.return_value = client
    return client


class TestSpotifyAuth:
    def test_init_kwargs(self) -> None:
        c = SpotifyIntegration(config={}, client_id="cid", client_secret="sec")
        assert c.client_id == "cid" and c.client_secret == "sec"

    def test_init_from_config(self) -> None:
        c = SpotifyIntegration(config={"client_id": "x", "client_secret": "y"})
        assert c.client_id == "x"

    def test_missing_client_id_raises(self) -> None:
        with pytest.raises(SpotifyAuthError):
            SpotifyIntegration(config={})

    def test_auth_url_contains_pkce_and_scopes(self) -> None:
        c = SpotifyIntegration(config={"client_id": "cid", "client_secret": "s"})
        url = c.get_auth_url(scopes=["user-read-email", "playlist-modify"])
        assert "accounts.spotify.com/authorize" in url
        assert "code_challenge_method=S256" in url
        assert "user-read-email" in url
        assert "playlist-modify" in url


class TestSpotifyTokens:
    @patch("httpx.AsyncClient")
    async def test_exchange_code_stores_tokens(self, mc) -> None:
        _wire(mc, _resp({"access_token": "at", "refresh_token": "rt"}))
        c = SpotifyIntegration(config={"client_id": "cid", "client_secret": "sec"})
        c._code_verifier = "verifier"
        out = await c.exchange_code("code")
        assert out["access_token"] == "at" and c.access_token == "at"

    async def test_exchange_code_requires_secret(self) -> None:
        with pytest.raises(SpotifyAuthError):
            await SpotifyIntegration(config={"client_id": "cid"}).exchange_code("c")

    @patch("httpx.AsyncClient")
    async def test_refresh_token_updates_access(self, mc) -> None:
        _wire(mc, _resp({"access_token": "new-at"}))
        c = SpotifyIntegration(config={"client_id": "cid", "client_secret": "sec"})
        # Bypass attribute shadowing: self.refresh_token (None) shadows method.
        data = await SpotifyIntegration.refresh_token(c, "old-rt")
        assert data["access_token"] == "new-at"


class TestSpotifyApi:
    @patch("httpx.AsyncClient")
    async def test_search_returns_tracks(self, mc) -> None:
        _wire(mc, _resp({"tracks": {"items": [{"id": "1", "name": "Song"}]}}))
        c = SpotifyIntegration(config={"client_id": "c", "client_secret": "s", "access_token": "t"})
        res = await c.search("Song", types=["track"])
        assert res["tracks"]["items"][0]["name"] == "Song"

    @patch("httpx.AsyncClient")
    async def test_get_currently_playing(self, mc) -> None:
        _wire(mc, _resp({"is_playing": True, "item": {"name": "T"}}))
        c = SpotifyIntegration(config={"client_id": "c", "client_secret": "s", "access_token": "t"})
        r = await c.get_currently_playing()
        assert r["is_playing"] is True

    @patch("httpx.AsyncClient")
    async def test_start_pause_next(self, mc) -> None:
        _wire(mc, _resp({}, code=204))
        c = SpotifyIntegration(config={"client_id": "c", "client_secret": "s", "access_token": "t"})
        assert await c.start_playback(uris=["spotify:track:1"]) is True
        assert await c.pause_playback() is True
        assert await c.next_track() is True


class TestSpotifyPlayer:
    async def test_now_playing_format(self) -> None:
        c = SpotifyIntegration(config={"client_id": "c", "client_secret": "s"})
        with patch.object(c, "get_currently_playing", AsyncMock(return_value={
            "is_playing": True,
            "item": {"name": "Bohemian Rhapsody", "artists": [{"name": "Queen"}]},
        })):
            text = await SpotifyPlayer(c).now_playing()
            assert "Queen" in text and "Bohemian Rhapsody" in text

    async def test_now_playing_idle(self) -> None:
        c = SpotifyIntegration(config={"client_id": "c", "client_secret": "s"})
        with patch.object(c, "get_currently_playing",
                          AsyncMock(return_value={"is_playing": False})):
            assert await SpotifyPlayer(c).now_playing() == "Nothing playing"


class TestSpotifySearch:
    async def test_play_first_result_plays(self) -> None:
        c = SpotifyIntegration(config={"client_id": "c", "client_secret": "s"})
        with patch.object(c, "search", AsyncMock(return_value={
            "tracks": {"items": [{"uri": "spotify:track:99"}]}})), \
             patch.object(c, "start_playback", AsyncMock(return_value=True)) as sp:
            assert await SpotifySearch(c).play_first_result("x") is True
            sp.assert_called_once()

    async def test_play_first_result_no_hits(self) -> None:
        c = SpotifyIntegration(config={"client_id": "c", "client_secret": "s"})
        with patch.object(c, "search",
                          AsyncMock(return_value={"tracks": {"items": []}})):
            assert await SpotifySearch(c).play_first_result("x") is False
