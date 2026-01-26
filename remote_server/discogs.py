import asyncio
import httpx
import urllib.parse
from typing import Optional, Dict, Any, List

class DiscogsClient:
    """
    A simple async client for the Discogs API (v2.0).
    """

    BASE_URL = "https://api.discogs.com"

    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Discogs token={self.token}",
            "User-Agent": "CloudCrate/1.0 +http://cloud-crate.example.com"
        }

    async def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Internal helper to perform GET requests.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()

    async def search(self, query: str, type: str = "master", format: Optional[str] = None, limit: int = 5) -> Dict[str, Any]:
        """
        Search for releases. Defaults to searching for 'master' releases.
        """
        url = f"{self.BASE_URL}/database/search"
        params = {
            "q": query,
            "type": type,
            "limit": limit
        }
        if format:
            params["format"] = format
            
        return await self._get(url, params=params)

    async def get_master_versions(self, master_id: str, page: int = 1, per_page: int = 30, format: Optional[str] = None) -> Dict[str, Any]:
        """
        Get all versions of a master release.
        """
        url = f"{self.BASE_URL}/masters/{master_id}/versions"
        params = {
            "page": page,
            "per_page": per_page
        }
        if format:
            params["format"] = format
            
        return await self._get(url, params=params)

    async def get_release(self, release_id: str) -> Dict[str, Any]:
        """
        Get details for a specific release.
        """
        url = f"{self.BASE_URL}/releases/{release_id}"
        return await self._get(url)

    async def get_releases(self, release_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Get details for multiple releases concurrently.
        """
        tasks = [self.get_release(rid) for rid in release_ids]
        return await asyncio.gather(*tasks, return_exceptions=True)

    def get_marketplace_url(self, release_id: str) -> str:
        """
        Returns the simplified marketplace URL for a given release ID.
        Note: This is a constructed URL, not an API call.
        """
        # Example: https://www.discogs.com/sell/release/12345
        return f"https://www.discogs.com/sell/release/{release_id}?ev=rb"
