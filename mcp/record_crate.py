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

    async def _request(self, method: str, url: str, params: Optional[Dict[str, Any]] = None, json_data: Optional[Dict[str, Any]] = None) -> Any:
        """
        Internal helper to perform requests with rate limiting (60 rpm).
        """
        # Simple rate limiter: wait 1.1s between requests to be safe
        await asyncio.sleep(1.1) 
        
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=self.headers, params=params, json=json_data)
            
            # If we still hit 429, backoff and retry once
            if response.status_code == 429:
                print("⚠️ Hit 429, backing off for 60s...")
                await asyncio.sleep(60)
                response = await client.request(method, url, headers=self.headers, params=params, json=json_data)
            
            # Allow 204 No Content (common for DELETE/PUT)
            if response.status_code == 204:
                return None
                
            response.raise_for_status()
            return response.json()

    async def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("GET", url, params=params)

    async def _put(self, url: str, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("PUT", url, json_data=json_data)

    async def _delete(self, url: str) -> None:
        await self._request("DELETE", url)

    async def _post(self, url: str, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self._request("POST", url, json_data=json_data)

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

    async def add_to_wantlist(self, username: str, release_id: str, notes: Optional[str] = None, rating: Optional[int] = None) -> Dict[str, Any]:
        """
        Add a release to user's wantlist.
        """
        url = f"{self.BASE_URL}/users/{username}/wants/{release_id}"
        data = {}
        if notes: data["notes"] = notes
        if rating: data["rating"] = rating
        return await self._put(url, json_data=data)

    async def remove_from_wantlist(self, username: str, release_id: str) -> None:
        """
        Remove a release from user's wantlist.
        """
        url = f"{self.BASE_URL}/users/{username}/wants/{release_id}"
        await self._delete(url)

    async def get_collection_folders(self, username: str) -> Dict[str, Any]:
        """Get all folders in user's collection."""
        url = f"{self.BASE_URL}/users/{username}/collection/folders"
        return await self._get(url)

    async def get_collection_releases(
        self,
        username: str,
        folder_id: int = 0,
        page: int = 1,
        per_page: int = 50,
        sort: Optional[str] = None,
        sort_order: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get releases in a collection folder. Folder 0 = All."""
        url = f"{self.BASE_URL}/users/{username}/collection/folders/{folder_id}/releases"
        params = {"page": page, "per_page": per_page}
        if sort:
            params["sort"] = sort
        if sort_order:
            params["sort_order"] = sort_order
        return await self._get(url, params=params)

    async def add_to_collection(
        self,
        username: str,
        folder_id: int,
        release_id: str
    ) -> Dict[str, Any]:
        """Add a release to a collection folder. Cannot add to folder 0."""
        url = f"{self.BASE_URL}/users/{username}/collection/folders/{folder_id}/releases/{release_id}"
        return await self._post(url)

    def get_marketplace_url(self, release_id: str) -> str:
        """
        Returns the simplified marketplace URL for a given release ID.
        Note: This is a constructed URL, not an API call.
        """
        # Example: https://www.discogs.com/sell/release/12345
        return f"https://www.discogs.com/sell/release/{release_id}?ev=rb"
