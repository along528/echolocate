import httpx
from typing import Optional, List, Literal

import google.auth.transport.requests
import google.oauth2.id_token

class EchoLocate:
    """
    Client for the Cloud Crate Vector Service.

    The vector service contains tracks from two sources:
    - 'library': Your personal Apple Music library
    - 'fma': Free Music Archive tracks

    Use the 'source' parameter to filter which tracks to search/return.
    """

    def __init__(self, vector_service_url: str):
        """Initialize with the vector service URL."""
        self.base_url = vector_service_url.rstrip('/')

    def _get_id_token(self) -> Optional[str]:
        """Fetch a Google Cloud ID token with the vector service URL as audience.
        Returns None in local dev (where metadata server is unavailable)."""
        try:
            auth_req = google.auth.transport.requests.Request()
            token = google.oauth2.id_token.fetch_id_token(auth_req, self.base_url)
            return token
        except Exception as e:
            print(f"EchoLocate: Could not fetch ID token (local dev?): {e}")
            return None

    async def _request(self, method: str, path: str, json_body: dict = None, params: dict = None):
        url = f"{self.base_url}{path}"
        headers = {}
        token = self._get_id_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, json=json_body, params=params, headers=headers, timeout=30.0)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                print(f"EchoLocate Error ({path}): {e}")
                raise Exception(f"EchoLocate request failed: {e}")

    async def sample_db(
        self, 
        limit: int = 20, 
        offset: int = 0, 
        random_sample: bool = True,
        source: Literal["library", "fma", "all"] = "library"
    ):
        """
        Sample tracks from the vector database.
        
        Args:
            limit: Maximum number of tracks to return
            offset: Offset for pagination
            random_sample: If True, return random tracks; if False, return in order
            source: Filter tracks by source - 'library' (personal), 'fma' (Free Music Archive), or 'all'
        """
        return await self._request(
            "GET", "/tracks", 
            params={"limit": limit, "offset": offset, "random": random_sample, "source": source}
        )

    async def find_similar_tracks(
        self, 
        track_id: str, 
        limit: int = 5,
        source: Literal["library", "fma", "all"] = "library"
    ):
        """
        Find tracks similar to the given track using audio embeddings.
        
        Args:
            track_id: Vector ID of the reference track
            limit: Maximum number of similar tracks to return
            source: Filter results by source - 'library', 'fma', or 'all'
        """
        return await self._request(
            "GET", f"/tracks/{track_id}/similar", 
            params={"limit": limit, "source": source}
        )

    async def interpolate(
        self,
        track_id_1: str,
        track_id_2: str,
        limit: int = 10,
        method: str = "greedy_walk",
        steer_track_ids: Optional[List[str]] = None
    ):
        """
        Find tracks that sonically bridge between two tracks.

        Args:
            track_id_1: Vector ID of the starting track
            track_id_2: Vector ID of the ending track
            limit: Number of intermediate tracks to find
            method: Interpolation method - 'greedy_walk', 'slerp', or 'linear'
            steer_track_ids: Optional list of track IDs for multi-point steering
        """
        payload = {
            "track_id_1": track_id_1,
            "track_id_2": track_id_2,
            "limit": limit,
            "method": method
        }
        if steer_track_ids:
            payload["steer_track_ids"] = steer_track_ids

        return await self._request("POST", "/interpolate", json_body=payload)

    async def generate_playlist(
        self,
        track_id_1: str,
        track_id_2: str,
        limit: int = 20,
        steer_track_ids: Optional[List[str]] = None
    ):
        """
        Generate a full playlist path between two tracks.

        Args:
            track_id_1: Vector ID of the starting track
            track_id_2: Vector ID of the ending track
            limit: Total number of tracks in the playlist
            steer_track_ids: Optional list of track IDs for multi-point steering
        """
        payload = {
            "track_id_1": track_id_1,
            "track_id_2": track_id_2,
            "limit": limit
        }
        if steer_track_ids:
            payload["steer_track_ids"] = steer_track_ids
        return await self._request("POST", "/interpolate/playlist", json_body=payload)

    async def text_search(
        self, 
        query: str = None,
        artist: str = None, 
        album: str = None, 
        title: str = None,
        limit: int = 20,
        source: Literal["library", "fma", "all"] = "library"
    ):
        """
        Search tracks by text metadata (artist, album, title).
        
        Args:
            query: General search term
            artist: Filter by artist name
            album: Filter by album name
            title: Filter by track title
            limit: Maximum results to return
            source: Filter by source - 'library', 'fma', or 'all'
        """
        params = {"limit": limit, "source": source}
        if query:
            params["query"] = query
        if artist:
            params["artist"] = artist
        if album:
            params["album"] = album
        if title:
            params["title"] = title
        return await self._request("GET", "/search", params=params)

    async def semantic_search(
        self, 
        query: str, 
        limit: int = 10,
        source: Literal["library", "fma", "all"] = "library",
        enhance: bool = True
    ):
        """
        Search for tracks using natural language descriptions.
        
        Uses CLAP AI to match audio content to text descriptions like
        'jazz saxophone' or 'ambient rain sounds'.
        
        Args:
            query: Natural language description of desired sound
            limit: Maximum results to return
            source: Filter by source - 'library', 'fma', or 'all'
            enhance: Whether to use Gemini Agent to expand the query
        """
        return await self._request(
            "POST", 
            "/semantic-search", 
            json_body={"query": query, "limit": limit, "source": source, "enhance": enhance}
        )
