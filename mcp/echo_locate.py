import httpx
from typing import Optional, List, Dict, Any

class EchoLocate:
    def __init__(self, vector_service_urls: Dict[str, str]):
        """
        Initialize with a dictionary of vector service URLs.
        Example: {"library": "http://vector-service:8080", "fma": "http://fma-vector-service:8080"}
        If a simple string is passed to legacy VECTOR_SERVICE_URL env var, it will be mapped to "default".
        """
        self.vector_service_urls = vector_service_urls

    def _get_url(self, service_name: str) -> str:
        url = self.vector_service_urls.get(service_name)
        if not url:
            # Fallback to default if exists
            url = self.vector_service_urls.get("default")
        if not url:
             # Fallback to first available if strictly one? Or error.
             if len(self.vector_service_urls) > 0:
                 return list(self.vector_service_urls.values())[0]
             raise ValueError(f"Vector service '{service_name}' not configured.")
        return url

    async def _request(self, service_name: str, method: str, path: str, json_body: dict = None, params: dict = None):
        base_url = self._get_url(service_name)
        url = f"{base_url}{path}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, json=json_body, params=params, timeout=30.0)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                print(f"EchoLocate Error ({service_name} -> {path}): {e}")
                raise Exception(f"EchoLocate failed for {service_name}: {e}")

    async def sample_db(self, service_name: str = "default", limit: int = 20, offset: int = 0, random_sample: bool = True):
        return await self._request(service_name, "GET", "/tracks", params={"limit": limit, "offset": offset, "random": random_sample})

    async def find_similar_tracks(self, track_id: str, service_name: str = "default", limit: int = 5):
        # Use endpoint /tracks/{id}/similar
        return await self._request(service_name, "GET", f"/tracks/{track_id}/similar", params={"limit": limit})

    async def interpolate(self, track_id_1: str, track_id_2: str, service_name: str = "default", limit: int = 10, method: str = "greedy_walk", steer_track_id: Optional[str] = None):
        payload = {
            "track_id_1": track_id_1,
            "track_id_2": track_id_2,
            "limit": limit,
            "method": method
        }
        if steer_track_id:
            payload["steer_track_id"] = steer_track_id
            
        return await self._request(service_name, "POST", "/interpolate", json_body=payload)

    async def generate_playlist(self, track_id_1: str, track_id_2: str, service_name: str = "default", limit: int = 20):
        payload = {
            "track_id_1": track_id_1,
            "track_id_2": track_id_2,
            "limit": limit
        }
        return await self._request(service_name, "POST", "/interpolate/playlist", json_body=payload)
    
    async def get_available_services(self) -> List[str]:
        return list(self.vector_service_urls.keys())
