#!/usr/bin/env python3
"""
CLAP Semantic Search Verification Script
=========================================
Test semantic search queries against the deployed vector service.

Usage:
    python verify_semantic.py "jazz saxophone"
    python verify_semantic.py "A recording of ethereal ambient synths with reverb"
    
    # With custom service URL (overrides auto-detection)
    VECTOR_URL=http://localhost:8001 python verify_semantic.py "heavy techno beats"
    
    # Force local
    python verify_semantic.py --local "jazz saxophone"
"""

import sys
import os
import subprocess
import requests


def get_cloud_run_url(service_name: str = "library-vector") -> str:
    """
    Get the Cloud Run service URL using gcloud CLI.
    """
    try:
        result = subprocess.run(
            ["gcloud", "run", "services", "describe", service_name, 
             "--format=value(status.url)", "--region=us-central1"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        print(f"⚠️  Could not fetch Cloud Run URL: {e}")
    return None


def get_vector_service_url(use_local: bool = False) -> str:
    """
    Determine the vector service URL.
    Priority: 1. VECTOR_URL env var, 2. --local flag, 3. Cloud Run lookup, 4. localhost fallback
    """
    # 1. Environment variable override
    if os.getenv("VECTOR_URL"):
        return os.getenv("VECTOR_URL")
    
    # 2. Local flag
    if use_local:
        return "http://localhost:8001"
    
    # 3. Try Cloud Run lookup
    cloud_url = get_cloud_run_url()
    if cloud_url:
        return cloud_url
    
    # 4. Fallback to localhost
    print("⚠️  No Cloud Run service found, falling back to localhost:8001")
    return "http://localhost:8001"


def semantic_search(query: str, service_url: str, limit: int = 10, enhance: bool = False):
    """
    Send a semantic search query to the vector service.
    """
    url = f"{service_url}/semantic-search"
    payload = {"query": query, "limit": limit, "enhance": enhance}
    
    print(f"🔍 Query: \"{query}\" {'(Enhanced)' if enhance else ''}")
    print(f"📡 Service: {url}")
    print("-" * 60)
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        # Updated to handle dict response with results list
        results = []
        if isinstance(response.json(), list):
            results = response.json()
        elif isinstance(response.json(), dict):
            data = response.json()
            results = data.get('results', [])
            if data.get('enhanced_query'):
               print(f"🤖 Enhanced: \"{data.get('enhanced_query')}\"\n")
        
        if not results:
            print("No results found.")
            return
        
        print(f"Found {len(results)} results:\n")
        for i, track in enumerate(results, 1):
            sim = track.get('similarity', 0)
            title = track.get('title', 'Unknown')
            artist = track.get('artist', 'Unknown')
            album = track.get('album', 'Unknown')
            track_id = track.get('id', '')
            
            # Color code similarity score
            if sim >= 0.3:
                score_indicator = "🟢"
            elif sim >= 0.2:
                score_indicator = "🟡"
            else:
                score_indicator = "🔴"
            
            print(f"{i:2}. {score_indicator} {sim:.4f} | {title}")
            print(f"              {artist} - {album}")
            print(f"              ID: {track_id}")
            print()
        
        # Summary
        avg_sim = sum(t.get('similarity', 0) for t in results) / len(results)
        top_sim = results[0].get('similarity', 0) if results else 0
        print("-" * 60)
        print(f"📊 Top Score: {top_sim:.4f} | Avg Score: {avg_sim:.4f}")
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Error: Could not connect to {url}")
        print("   Is the vector service running?")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        if response.status_code == 503:
            print("   CLAP model may not be loaded. Check service logs.")
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ Error: {e}")
        sys.exit(1)


def main():
    # Parse args
    args = sys.argv[1:]
    use_local = False
    enhance = False
    
    if "--local" in args:
        use_local = True
        args.remove("--local")
        
    if "--enhance" in args:
        enhance = True
        args.remove("--enhance")
    
    if not args:
        print(__doc__)
        print("\nExamples:")
        print('  python verify_semantic.py "alien singing"')
        print('  python verify_semantic.py "A recording of warm jazz piano in a smoky club"')
        print('  python verify_semantic.py --local "heavy distorted guitar with fast drums"')
        print('  python verify_semantic.py --enhance "scary monster sounds"')
        sys.exit(1)
    
    query = args[0]
    limit = int(args[1]) if len(args) > 1 else 10
    
    # Get service URL
    service_url = get_vector_service_url(use_local)
    
    semantic_search(query, service_url, limit, enhance=enhance)


if __name__ == "__main__":
    main()
