import os
import time
import json
import httpx
from jose import jwt
import base64

class AppleCrate:
    def __init__(self, team_id: str, key_id: str, private_key: str):
        self.team_id = team_id
        self.key_id = key_id
        self.private_key = private_key
        # Ensure private key has headers if missing (common PEM issue)
        if "-----BEGIN PRIVATE KEY-----" not in self.private_key:
            self.private_key = f"-----BEGIN PRIVATE KEY-----\n{self.private_key}\n-----END PRIVATE KEY-----"
            
        self.developer_token = None
        self.token_expiry = 0
        
    def get_developer_token(self) -> str:
        """
        Generates or returns a valid Developer Token (JWT).
        """
        now = time.time()
        if self.developer_token and now < self.token_expiry - 60:
            return self.developer_token

        headers = {
            "alg": "ES256",
            "kid": self.key_id
        }
        payload = {
            "iss": self.team_id,
            "iat": int(now),
            "exp": int(now + 15777000) # 6 months
        }
        
        try:
            token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)
            self.developer_token = token
            self.token_expiry = payload["exp"]
            return token
        except Exception as e:
            print(f"Error generating developer token: {e}")
            raise

    async def _request(self, method: str, path: str, user_token: str = None, json_body: dict = None, params: dict = None):
        """
        Internal request helper.
        """
        url = f"https://api.music.apple.com/v1/{path}"
        headers = {
            "Authorization": f"Bearer {self.get_developer_token()}",
            "Content-Type": "application/json"
        }
        if user_token:
            headers["Music-User-Token"] = user_token
            
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=headers, json=json_body, params=params)
            response.raise_for_status()
            return response.json()

    async def search(self, query: str, limit: int = 5, types: str = "songs"):
        """
        Search the Apple Music Catalog.
        """
        params = {
            "term": query,
            "limit": limit,
            "types": types
        }
        # Use US storefront by default or fetch? 'us' is usually safe for search if not specified, 
        # but better to use a storefront. Let's assume 'us' for anonymous.
        storefront = "us" 
        return await self._request("GET", f"catalog/{storefront}/search", params=params)

    async def get_resource(self, id: str, type: str, storefront: str = "us", user_token: str = None):
        """
        Get a specific resource.
        """
        # Type mapping cleanup if needed
        return await self._request("GET", f"catalog/{storefront}/{type}/{id}", user_token=user_token)

    async def get_songs(self, ids: list[str], storefront: str = "us"):
        """
        Get multiple songs by ID.
        """
        # Join IDs with comma
        ids_str = ",".join(ids)
        return await self._request("GET", f"catalog/{storefront}/songs", params={"ids": ids_str})

    async def create_playlist(self, name: str, description: str, track_ids: list[str], user_token: str):
        """
        Create a playlist and add tracks.
        """
        if not user_token:
            raise ValueError("User Token is required for playlist creation.")
            
        # 1. Create Playlist
        payload = {
            "attributes": {
                "name": name,
                "description": description
            }
        }
        # Add relationships directly if possible? 
        # API allows creating with tracks.
        
        tracks_data = []
        for tid in track_ids:
            t_type = "songs" # Default catalog song
            if tid.startswith("i."): # Library song ID pattern usually
                t_type = "library-songs"
            
            # Clean ID if prefixed
            clean_id = tid
            if ":" in tid:
                clean_id = tid.split(":", 1)[1]
                
            tracks_data.append({"id": clean_id, "type": t_type})
            
        if tracks_data:
             payload["relationships"] = {
                 "tracks": {
                     "data": tracks_data
                 }
             }

        # POST to /me/library/playlists
        return await self._request("POST", "me/library/playlists", user_token=user_token, json_body=payload)

    async def search_library(self, query: str, user_token: str, limit: int = 5, types: str = "library-songs", offset: int = 0):
        """
        Search the user's Apple Music Library.
        """
        if not user_token:
            raise ValueError("User Token is required for library search.")
            
        params = {
            "term": query,
            "limit": limit,
            "types": types,
            "offset": offset
        }
        return await self._request("GET", "me/library/search", user_token=user_token, params=params)
