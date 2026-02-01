import asyncio
import time
import httpx
import urllib.parse
from typing import Optional, Dict, Any, List

class RecordCrate:
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
        Internal helper to perform GET requests with rate limiting (60 rpm).
        """
        # Simple rate limiter: wait 1.1s between requests to be safe (60/min = 1/s)
        # In a real heavy app we'd use a token bucket, but sleep is fine here.
        # We use a lock to ensure only one request fires per 1.1s if we want strict serial throttling,
        # OR we just sleep before every request.
        # Since we are using asyncio.gather for get_releases, we want them to effectively serialize or
        # spacing out.
        
        # NOTE: This sleep strategy slows down *batch* fetches significantly but avoids 429s.
        await asyncio.sleep(1.1) 
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params)
            
            # If we still hit 429, backoff and retry once
            if response.status_code == 429:
                print("⚠️ Hit 429, backing off for 60s...")
                await asyncio.sleep(60)
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

    async def get_identity(self) -> Dict[str, Any]:
        """
        Get authenticated user identity.
        """
        url = f"{self.BASE_URL}/oauth/identity"
        return await self._get(url)

    async def get_wantlist(self, username: str, page: int = 1, per_page: int = 50) -> Dict[str, Any]:
        """
        Get user's wantlist.
        """
        url = f"{self.BASE_URL}/users/{username}/wants"
        params = {
            "page": page,
            "per_page": per_page
        }
        return await self._get(url, params=params)

    def get_marketplace_url(self, release_id: str) -> str:
        """
        Returns the simplified marketplace URL for a given release ID.
        Note: This is a constructed URL, not an API call.
        """
        # Example: https://www.discogs.com/sell/release/12345
        return f"https://www.discogs.com/sell/release/{release_id}?ev=rb"
