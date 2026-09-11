"""Spotify Web API integration.

Implements music playback control, search, and user data retrieval
against Spotify's Web API (``https://api.spotify.com/v1``).

Features:
- OAuth 2.0 Authorization Code Flow authentication
- Playback control (play, pause, next, previous, seek, volume)
- Search (tracks, artists, albums, playlists)
- User playlists and recommendations
- Device management

Configuration keys:
- ``client_id`` (str, required): Spotify app client ID
- ``client_secret`` (str, optional): For server-side token exchange
- ``redirect_uri`` (str, optional): OAuth callback URL
- ``access_token`` (str, optional): Pre-obtained access token
- ``refresh_token`` (str, optional): Pre-obtained refresh token
"""

from __future__ import annotations

import base64
import logging
import secrets
import urllib.parse
from typing import Any, Literal

import httpx

from tools.integrations.base import (
    AuthError,
    BaseIntegration,
    IntegrationError,
    NotFoundError,
    RateLimitError,
    ReceiveCallback,
    safe_call,
    sleep_for,
)
from tools.integrations.registry import register_integration

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.spotify.com/v1"
DEFAULT_AUTH_BASE = "https://accounts.spotify.com"
DEFAULT_REDIRECT_URI = "http://localhost:8888/callback"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3

DEFAULT_SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-top-read",
    "user-read-recently-played",
    "playlist-read-private",
    "playlist-read-collaborative",
]

MOOD_GENRE_MAP = {
    "focus": ["instrumental", "ambient", "classical"],
    "energize": ["electronic", "dance", "hip-hop"],
    "relax": ["jazz", "soul", "chill"],
    "party": ["pop", "dance", "party"],
}


class SpotifyAPIError(IntegrationError):
    """Raised when the Spotify API returns an error response."""


class SpotifyAuthError(AuthError):
    """Raised when Spotify OAuth authentication fails."""


class SpotifyNotPlayingError(IntegrationError):
    """Raised when no track is currently playing."""


@register_integration("spotify")
class SpotifyIntegration(BaseIntegration):
    """Spotify Web API integration."""

    platform_name = "spotify"

    def __init__(
        self,
        config: dict[str, Any],
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str = DEFAULT_REDIRECT_URI,
    ) -> None:
        super().__init__(config)
        self.client_id = (
            client_id
            or config.get("client_id")
            or _require_config(config, "client_id")
        )
        self.client_secret = client_secret or config.get("client_secret") or ""
        self.redirect_uri = redirect_uri or config.get("redirect_uri", DEFAULT_REDIRECT_URI)
        self.access_token: str | None = config.get("access_token")
        self.refresh_token: str | None = config.get("refresh_token")
        self.api_base: str = config.get("api_base", DEFAULT_API_BASE).rstrip("/")
        self.auth_base: str = config.get("auth_base", DEFAULT_AUTH_BASE).rstrip("/")
        self.timeout: float = float(config.get("timeout", DEFAULT_TIMEOUT))
        self.max_retries: int = int(config.get("max_retries", DEFAULT_MAX_RETRIES))
        self._client: httpx.AsyncClient | None = None
        self._code_verifier: str | None = None

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"User-Agent": "ZelooSpotifyIntegration/1.0"}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                timeout=self.timeout,
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        await super().close()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        use_auth: bool = True,
    ) -> dict[str, Any]:
        """Issue an HTTP request to the Spotify API.

        Handles rate limiting, authentication errors, and server errors
        with automatic retries.
        """
        client = await self._get_client()
        attempts = self.max_retries + 1
        last_error: Exception | None = None

        headers: dict[str, str] = {}
        if use_auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        for attempt in range(1, attempts + 1):
            try:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers if headers else None,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Spotify HTTP error on %s %s (attempt %s/%s): %s",
                    method,
                    path,
                    attempt,
                    attempts,
                    exc,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            if response.status_code == 401:
                if self.refresh_token:
                    token_data = await self.refresh_token(self.refresh_token)
                    self.access_token = token_data.get("access_token")
                    if self.access_token:
                        headers["Authorization"] = f"Bearer {self.access_token}"
                        continue
                raise SpotifyAuthError(f"Spotify auth failure: {response.text}")

            if response.status_code == 403:
                raise SpotifyAuthError(f"Spotify forbidden: {response.text}")

            if response.status_code == 404:
                raise NotFoundError(f"Spotify resource not found: {path}")

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 1.0))
                logger.info("Spotify rate-limited, sleeping %.2fs", retry_after)
                await sleep_for(retry_after)
                if attempt < attempts:
                    continue
                raise RateLimitError(
                    f"Spotify rate limit exceeded for {path}",
                    retry_after=retry_after,
                )

            if 500 <= response.status_code < 600:
                last_error = SpotifyAPIError(
                    f"Spotify server error {response.status_code}: {response.text}"
                )
                logger.warning(
                    "Spotify server error %s on %s (attempt %s/%s)",
                    response.status_code,
                    path,
                    attempt,
                    attempts,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            if response.status_code >= 400:
                try:
                    err_data = response.json()
                    error_msg = err_data.get("error", {}).get("message", response.text)
                except Exception:
                    error_msg = response.text
                raise SpotifyAPIError(f"Spotify API error {response.status_code}: {error_msg}")

            if not response.content:
                return {}
            try:
                return response.json()
            except Exception as exc:
                raise SpotifyAPIError(f"Invalid Spotify response: {exc}") from exc

        assert last_error is not None
        raise SpotifyAPIError(f"Spotify request failed after retries: {last_error}")

    # ------------------------------------------------------------------
    # OAuth authentication
    # ------------------------------------------------------------------
    def get_auth_url(self, scopes: list[str] | None = None) -> str:
        """Generate the OAuth authorization URL.

        Returns the URL that the user should visit to authorize the app.
        """
        if scopes is None:
            scopes = DEFAULT_SCOPES

        self._code_verifier = secrets.token_urlsafe(64)
        scope_str = " ".join(scopes)
        state = secrets.token_urlsafe(16)

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": scope_str,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": _generate_code_challenge(self._code_verifier),
        }

        auth_url = f"{self.auth_base}/authorize?{urllib.parse.urlencode(params)}"
        logger.info("Generated Spotify auth URL with scopes: %s", scopes)
        return auth_url

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange an authorization code for access tokens."""
        if not self.client_secret:
            raise SpotifyAuthError("client_secret is required for code exchange")

        token_url = f"{self.auth_base}/api/token"
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        if self._code_verifier:
            data["code_verifier"] = self._code_verifier
            self._code_verifier = None

        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(token_url, data=data, headers=headers)

        if response.status_code >= 400:
            raise SpotifyAuthError(
                f"Token exchange failed: {response.status_code} - {response.text}"
            )

        token_data = response.json()
        self.access_token = token_data.get("access_token")
        self.refresh_token = token_data.get("refresh_token")

        logger.info("Successfully exchanged code for access token")
        return token_data

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh an expired access token."""
        if not self.client_secret:
            raise SpotifyAuthError("client_secret is required for token refresh")

        token_url = f"{self.auth_base}/api/token"
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(token_url, data=data, headers=headers)

        if response.status_code >= 400:
            raise SpotifyAuthError(
                f"Token refresh failed: {response.status_code} - {response.text}"
            )

        token_data = response.json()
        self.access_token = token_data.get("access_token")
        if token_data.get("refresh_token"):
            self.refresh_token = token_data["refresh_token"]

        logger.info("Successfully refreshed access token")
        return token_data

    # ------------------------------------------------------------------
    # User profile
    # ------------------------------------------------------------------
    async def get_current_user(self) -> dict[str, Any]:
        """Get the current authenticated user's profile."""
        async def _do() -> dict[str, Any]:
            return await self._request("GET", "/me")
        return await safe_call(_do) or {"ok": False, "error": "unknown"}

    async def get_user_top_tracks(
        self,
        limit: int = 10,
        time_range: str = "medium_term",
    ) -> dict[str, Any]:
        """Get the user's top tracks."""
        async def _do() -> dict[str, Any]:
            return await self._request(
                "GET",
                "/me/top/tracks",
                params={"limit": limit, "time_range": time_range},
            )
        return await safe_call(_do) or {"ok": False, "items": []}

    async def get_user_top_artists(
        self,
        limit: int = 10,
        time_range: str = "medium_term",
    ) -> dict[str, Any]:
        """Get the user's top artists."""
        async def _do() -> dict[str, Any]:
            return await self._request(
                "GET",
                "/me/top/artists",
                params={"limit": limit, "time_range": time_range},
            )
        return await safe_call(_do) or {"ok": False, "items": []}

    async def get_recently_played(self, limit: int = 50) -> dict[str, Any]:
        """Get the user's recently played tracks."""
        async def _do() -> dict[str, Any]:
            return await self._request(
                "GET",
                "/me/player/recently-played",
                params={"limit": limit},
            )
        return await safe_call(_do) or {"ok": False, "items": []}

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------
    async def get_currently_playing(self) -> dict[str, Any]:
        """Get the currently playing track."""
        async def _do() -> dict[str, Any]:
            return await self._request("GET", "/me/player/currently-playing")
        result = await safe_call(_do)
        return result if result else {"is_playing": False}

    async def start_playback(
        self,
        device_id: str | None = None,
        context_uri: str | None = None,
        uris: list[str] | None = None,
        offset: dict[str, Any] | None = None,
    ) -> bool:
        """Start or resume playback."""
        async def _do() -> dict[str, Any]:
            params: dict[str, Any] | None = None
            if device_id:
                params = {"device_id": device_id}

            json_body: dict[str, Any] = {}
            if context_uri:
                json_body["context_uri"] = context_uri
            if uris:
                json_body["uris"] = uris
            if offset:
                json_body["offset"] = offset

            await self._request(
                "PUT",
                "/me/player/play",
                params=params,
                json_body=json_body if json_body else None,
            )
            return {"ok": True}

        result = await safe_call(_do)
        return result.get("ok", False)

    async def pause_playback(self, device_id: str | None = None) -> bool:
        """Pause playback."""
        async def _do() -> dict[str, Any]:
            params: dict[str, Any] | None = None
            if device_id:
                params = {"device_id": device_id}
            await self._request("PUT", "/me/player/pause", params=params)
            return {"ok": True}

        result = await safe_call(_do)
        return result.get("ok", False)

    async def next_track(self, device_id: str | None = None) -> bool:
        """Skip to the next track."""
        async def _do() -> dict[str, Any]:
            params: dict[str, Any] | None = None
            if device_id:
                params = {"device_id": device_id}
            await self._request("POST", "/me/player/next", params=params)
            return {"ok": True}

        result = await safe_call(_do)
        return result.get("ok", False)

    async def previous_track(self, device_id: str | None = None) -> bool:
        """Skip to the previous track."""
        async def _do() -> dict[str, Any]:
            params: dict[str, Any] | None = None
            if device_id:
                params = {"device_id": device_id}
            await self._request("POST", "/me/player/previous", params=params)
            return {"ok": True}

        result = await safe_call(_do)
        return result.get("ok", False)

    async def seek_track(
        self,
        position_ms: int,
        device_id: str | None = None,
    ) -> bool:
        """Seek to a position in the current track."""
        async def _do() -> dict[str, Any]:
            params: dict[str, Any] = {"position_ms": position_ms}
            if device_id:
                params["device_id"] = device_id
            await self._request("PUT", "/me/player/seek", params=params)
            return {"ok": True}

        result = await safe_call(_do)
        return result.get("ok", False)

    async def set_volume(
        self,
        volume_percent: int,
        device_id: str | None = None,
    ) -> bool:
        """Set playback volume (0-100)."""
        volume = max(0, min(100, volume_percent))

        async def _do() -> dict[str, Any]:
            params: dict[str, Any] = {"volume_percent": volume}
            if device_id:
                params["device_id"] = device_id
            await self._request("PUT", "/me/player/volume", params=params)
            return {"ok": True}

        result = await safe_call(_do)
        return result.get("ok", False)

    async def shuffle(self, state: bool, device_id: str | None = None) -> bool:
        """Toggle shuffle mode."""
        async def _do() -> dict[str, Any]:
            params: dict[str, Any] = {"state": str(state).lower()}
            if device_id:
                params["device_id"] = device_id
            await self._request("PUT", "/me/player/shuffle", params=params)
            return {"ok": True}

        result = await safe_call(_do)
        return result.get("ok", False)

    async def repeat(
        self,
        state: Literal["off", "track", "context"],
        device_id: str | None = None,
    ) -> bool:
        """Set repeat mode."""
        async def _do() -> dict[str, Any]:
            params: dict[str, Any] = {"state": state}
            if device_id:
                params["device_id"] = device_id
            await self._request("PUT", "/me/player/repeat", params=params)
            return {"ok": True}

        result = await safe_call(_do)
        return result.get("ok", False)

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------
    async def get_available_devices(self) -> list[dict[str, Any]]:
        """Get available playback devices."""
        async def _do() -> dict[str, Any]:
            return await self._request("GET", "/me/player/devices")
        result = await safe_call(_do)
        return result.get("devices", []) if isinstance(result, dict) else []

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        types: list[str] = ["track"],
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search for tracks, artists, albums, or playlists."""
        async def _do() -> dict[str, Any]:
            return await self._request(
                "GET",
                "/search",
                params={
                    "q": query,
                    "type": ",".join(types),
                    "limit": limit,
                },
            )
        return await safe_call(_do) or {"tracks": {"items": []}}

    # ------------------------------------------------------------------
    # Playlists
    # ------------------------------------------------------------------
    async def get_user_playlists(self, limit: int = 20) -> dict[str, Any]:
        """Get the current user's playlists."""
        async def _do() -> dict[str, Any]:
            return await self._request(
                "GET",
                "/me/playlists",
                params={"limit": limit},
            )
        return await safe_call(_do) or {"items": []}

    async def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Get a playlist by ID."""
        async def _do() -> dict[str, Any]:
            return await self._request("GET", f"/playlists/{playlist_id}")
        return await safe_call(_do) or {"ok": False, "error": "playlist not found"}

    async def play_playlist(
        self,
        playlist_id: str,
        device_id: str | None = None,
    ) -> bool:
        """Start playback of a playlist."""
        return await self.start_playback(
            device_id=device_id,
            context_uri=f"spotify:playlist:{playlist_id}",
        )

    # ------------------------------------------------------------------
    # Audio features and recommendations
    # ------------------------------------------------------------------
    async def get_audio_features(
        self,
        track_ids: list[str],
    ) -> dict[str, Any]:
        """Get audio features for multiple tracks."""
        async def _do() -> dict[str, Any]:
            ids_param = ",".join(track_ids[:100])
            return await self._request(
                "GET",
                "/audio-features",
                params={"ids": ids_param},
            )
        return await safe_call(_do) or {"audio_features": []}

    async def get_recommendations(
        self,
        seed_tracks: list[str] | None = None,
        seed_artists: list[str] | None = None,
        seed_genres: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get track recommendations based on seeds."""
        async def _do() -> dict[str, Any]:
            params: dict[str, Any] = {"limit": limit}
            if seed_tracks:
                params["seed_tracks"] = ",".join(seed_tracks[:5])
            if seed_artists:
                params["seed_artists"] = ",".join(seed_artists[:5])
            if seed_genres:
                params["seed_genres"] = ",".join(seed_genres[:5])

            return await self._request(
                "GET",
                "/recommendations",
                params=params,
            )
        return await safe_call(_do) or {"tracks": []}

    # ------------------------------------------------------------------
    # Required base class stubs
    # ------------------------------------------------------------------
    async def send_message(
        self,
        channel: str,
        content: str,
        **_: Any,
    ) -> dict[str, Any]:
        """Not applicable for Spotify - stub implementation."""
        return {"ok": False, "error": "Spotify does not support messaging"}

    async def list_channels(self) -> list[dict[str, Any]]:
        """List available playback devices as 'channels'."""
        return await self.get_available_devices()

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get user profile by ID."""
        async def _do() -> dict[str, Any]:
            return await self._request("GET", f"/users/{user_id}")
        return await safe_call(_do) or {"ok": False, "error": "user not found"}

    async def receive_messages(
        self,
        callback: ReceiveCallback,
        **_: Any,
    ) -> None:
        """Spotify uses webhooks/polling for real-time events."""
        logger.info("Spotify receive_messages() called - no active listener")
        return


class SpotifyPlayer:
    """High-level Spotify player interface."""

    def __init__(self, integration: SpotifyIntegration) -> None:
        self._integration = integration

    async def now_playing(self) -> str:
        """Get the currently playing track as 'Artist - Track Name'."""
        data = await self._integration.get_currently_playing()
        if not data.get("is_playing"):
            return "Nothing playing"

        item = data.get("item", {})
        if not item:
            return "Nothing playing"

        artists = item.get("artists", [])
        artist_name = artists[0].get("name", "Unknown") if artists else "Unknown"
        track_name = item.get("name", "Unknown Track")

        return f"{artist_name} - {track_name}"

    async def play_artist_top(self, artist_name: str) -> bool:
        """Search for an artist and play their top track."""
        result = await self._integration.search(artist_name, types=["artist"], limit=1)
        artists = result.get("artists", {}).get("items", [])
        if not artists:
            return False

        artist_id = artists[0].get("id")
        if not artist_id:
            return False

        top_tracks_result = await self._integration._request(
            "GET",
            f"/artists/{artist_id}/top-tracks",
            params={"country": "from_token"},
        )
        tracks = top_tracks_result.get("tracks", [])
        if not tracks:
            return False

        track_uri = tracks[0].get("uri")
        if not track_uri:
            return False

        return await self._integration.start_playback(uris=[track_uri])

    async def play_genre(self, genre: str) -> bool:
        """Play music from a specific genre."""
        genres = MOOD_GENRE_MAP.get(genre.lower(), [genre])
        result = await self._integration.get_recommendations(
            seed_genres=genres[:1],
            limit=10,
        )
        tracks = result.get("tracks", [])
        if not tracks:
            return False

        uris = [t.get("uri") for t in tracks if t.get("uri")]
        if not uris:
            return False

        return await self._integration.start_playback(uris=uris)

    async def play_liked_songs(self) -> bool:
        """Play the user's liked songs (saved tracks)."""
        async def _do() -> dict[str, Any]:
            return await self._integration._request(
                "GET",
                "/me/tracks",
                params={"limit": 50},
            )

        result = await self._integration.safe_call(_do)
        if not result:
            return False

        items = result.get("items", [])
        if not items:
            return False

        track_ids = [item.get("track", {}).get("uri") for item in items if item.get("track", {}).get("uri")]
        if not track_ids:
            return False

        return await self._integration.start_playback(uris=track_ids[:50])

    async def play_recommendations(
        self,
        seed: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get and play track recommendations."""
        if seed:
            search_result = await self._integration.search(seed, types=["track"], limit=1)
            tracks = search_result.get("tracks", {}).get("items", [])
            seed_tracks = [tracks[0].get("id")] if tracks and tracks[0].get("id") else None
        else:
            top_tracks = await self._integration.get_user_top_tracks(limit=5)
            seed_tracks = [t.get("id") for t in top_tracks.get("items", []) if t.get("id")]

        if not seed_tracks:
            return []

        result = await self._integration.get_recommendations(
            seed_tracks=seed_tracks,
            limit=10,
        )
        tracks = result.get("tracks", [])
        if tracks:
            uris = [t.get("uri") for t in tracks if t.get("uri")]
            if uris:
                await self._integration.start_playback(uris=uris)

        return tracks

    async def mood_play(self, mood: str) -> bool:
        """Play music based on mood (focus, energize, relax, party)."""
        return await self.play_genre(mood.lower())


class SpotifySearch:
    """High-level Spotify search interface."""

    def __init__(self, integration: SpotifyIntegration) -> None:
        self._integration = integration

    async def find_track(self, query: str) -> dict[str, Any]:
        """Search for tracks."""
        result = await self._integration.search(query, types=["track"], limit=10)
        return result.get("tracks", {}).get("items", [])

    async def find_artist(self, query: str) -> dict[str, Any]:
        """Search for artists."""
        result = await self._integration.search(query, types=["artist"], limit=10)
        return result.get("artists", {}).get("items", [])

    async def find_playlist(self, query: str) -> dict[str, Any]:
        """Search for playlists."""
        result = await self._integration.search(query, types=["playlist"], limit=10)
        return result.get("playlists", {}).get("items", [])

    async def find_album(self, query: str) -> dict[str, Any]:
        """Search for albums."""
        result = await self._integration.search(query, types=["album"], limit=10)
        return result.get("albums", {}).get("items", [])

    async def play_first_result(self, query: str) -> bool:
        """Search for tracks and play the first result."""
        tracks = await self.find_track(query)
        if not tracks:
            return False

        first_track = tracks[0]
        uri = first_track.get("uri")
        if not uri:
            return False

        return await self._integration.start_playback(uris=[uri])


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def _require_config(config: dict[str, Any], key: str) -> Any:
    """Return config[key] or raise SpotifyAuthError."""
    if key not in config or config[key] in (None, ""):
        raise SpotifyAuthError(f"Missing required config key: {key}")
    return config[key]


def _generate_code_challenge(verifier: str) -> str:
    """Generate PKCE code challenge from verifier."""
    import hashlib
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# Global tool functions
# ---------------------------------------------------------------------------
_integration: SpotifyIntegration | None = None


async def _get_integration() -> SpotifyIntegration:
    """Get or create the global Spotify integration instance."""
    global _integration
    if _integration is None:
        _integration = SpotifyIntegration({})
    return _integration


async def spotify_now_playing() -> dict[str, Any]:
    """Get the currently playing track."""
    integration = await _get_integration()
    data = await integration.get_currently_playing()

    if not data.get("is_playing"):
        return {"ok": True, "playing": False, "message": "Nothing is currently playing"}

    item = data.get("item", {})
    artists = item.get("artists", [])
    artist_name = artists[0].get("name", "Unknown") if artists else "Unknown"
    track_name = item.get("name", "Unknown Track")
    album_name = item.get("album", {}).get("name", "")
    progress_ms = data.get("progress_ms", 0)
    duration_ms = item.get("duration_ms", 0)

    return {
        "ok": True,
        "playing": True,
        "artist": artist_name,
        "track": track_name,
        "album": album_name,
        "progress_ms": progress_ms,
        "duration_ms": duration_ms,
        "formatted": f"{artist_name} - {track_name}",
    }


async def spotify_play(
    query: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Play a track, artist, or playlist by name or URI."""
    integration = await _get_integration()

    if context:
        if context.startswith("spotify:playlist:"):
            playlist_id = context.split(":")[-1]
            success = await integration.play_playlist(playlist_id)
        elif context.startswith("spotify:album:"):
            album_id = context.split(":")[-1]
            success = await integration.start_playback(
                context_uri=f"spotify:album:{album_id}"
            )
        elif context.startswith("spotify:artist:"):
            artist_id = context.split(":")[-1]
            success = await integration.start_playback(
                context_uri=f"spotify:artist:{artist_id}"
            )
        else:
            return {"ok": False, "error": "Invalid context URI format"}

        return {"ok": success, "action": "play", "context": context}

    if query:
        search = SpotifySearch(integration)
        success = await search.play_first_result(query)
        return {"ok": success, "action": "play", "query": query}

    success = await integration.start_playback()
    return {"ok": success, "action": "resume"}


async def spotify_pause() -> dict[str, Any]:
    """Pause playback."""
    integration = await _get_integration()
    success = await integration.pause_playback()
    return {"ok": success, "action": "pause"}


async def spotify_next() -> dict[str, Any]:
    """Skip to the next track."""
    integration = await _get_integration()
    success = await integration.next_track()
    return {"ok": success, "action": "next"}


async def spotify_previous() -> dict[str, Any]:
    """Skip to the previous track."""
    integration = await _get_integration()
    success = await integration.previous_track()
    return {"ok": success, "action": "previous"}


async def spotify_volume(level: int) -> dict[str, Any]:
    """Set playback volume (0-100)."""
    integration = await _get_integration()
    success = await integration.set_volume(level)
    return {"ok": success, "action": "volume", "level": level}


async def spotify_search(query: str, type: str = "track") -> dict[str, Any]:
    """Search for tracks, artists, albums, or playlists."""
    integration = await _get_integration()
    types = [type] if type in ["track", "artist", "album", "playlist"] else ["track"]
    result = await integration.search(query, types=types, limit=10)

    if type == "track":
        return {"ok": True, "type": "track", "results": result.get("tracks", {}).get("items", [])}
    elif type == "artist":
        return {"ok": True, "type": "artist", "results": result.get("artists", {}).get("items", [])}
    elif type == "album":
        return {"ok": True, "type": "album", "results": result.get("albums", {}).get("items", [])}
    elif type == "playlist":
        return {"ok": True, "type": "playlist", "results": result.get("playlists", {}).get("items", [])}

    return {"ok": True, "results": result}


async def spotify_mood(mood: str) -> dict[str, Any]:
    """Play music based on mood (focus, energize, relax, party)."""
    integration = await _get_integration()
    player = SpotifyPlayer(integration)
    success = await player.mood_play(mood)
    return {"ok": success, "action": "mood_play", "mood": mood}


_ = ReceiveCallback
