
import urllib.request
import urllib.parse
import json
import sys
import time
import re

BASE_URL = "http://localhost:8080"
AUTH_SECRET = "test_auth_secret"
CLIENT_ID = "test_client_id"
REDIRECT_URI = "https://claude.ai/auth/callback"
STATE = "xyz123"

def run_test():
    print(f"Testing Auth Flow against {BASE_URL}...")
    
    # 1. Test Unauthenticated Access (Should Fail)
    print("\n[1] Testing Unauthenticated Access to /sse...")
    try:
        urllib.request.urlopen(f"{BASE_URL}/sse")
        print("❌ Failed: /sse should be 401")
        sys.exit(1)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("✅ Success: Got 401 Unauthorized")
        else:
            print(f"❌ Failed: Expected 401, got {e.code}")
            sys.exit(1)

    # 2. GET /authorize
    print("\n[2] Testing GET /authorize...")
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": STATE,
        "response_type": "code"
    }
    url = f"{BASE_URL}/authorize?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url) as response:
        html = response.read().decode('utf-8')
        if "password" in html and 'name="state" value="xyz123"' in html:
            print("✅ Success: Received Login Page with hidden state")
        else:
            print("❌ Failed: Login page missing password field or state")
            print(html)
            sys.exit(1)

    # 3. POST /authorize (Submit Password)
    print("\n[3] Testing POST /authorize...")
    data = urllib.parse.urlencode({
        "password": AUTH_SECRET,
        "redirect_uri": REDIRECT_URI,
        "state": STATE,
        "client_id": CLIENT_ID
    }).encode()
    
    req = urllib.request.Request(f"{BASE_URL}/authorize", data=data, method="POST")
    try:
        # We expect a redirect (303), urllib handles redirects automatically.
        # But we want to inspect the redirect URL to get the 'code'
        # So we disable auto-redirect by extending the opener (too complex), 
        # or just catch the result. 
        # Actually, urllib follows 303. The final URL will be the redirect_uri 
        # BUT redirect_uri is external (claude.ai), so it might fail or return 404/200.
        # Let's use a RedirectHandler to print the redirect.
        
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None # Stop redirect
        
        opener = urllib.request.build_opener(NoRedirect)
        response = opener.open(req)
    except urllib.error.HTTPError as e:
        if e.code == 303:
            location = e.headers.get("Location")
            print(f"✅ Success: Redirected to {location}")
            
            # Extract Code
            match = re.search(r'code=([^&]+)', location)
            if match:
                auth_code = match.group(1)
                print(f"   Auth Code: {auth_code}")
            else:
                print("❌ Failed: No code in redirect")
                sys.exit(1)
                
            # Verify State
            if f"state={STATE}" not in location:
                print("❌ Failed: State was not preserved in redirect")
                sys.exit(1)
        else:
            print(f"❌ Failed: Expected 303 Redirect, got {e.code}")
            sys.exit(1)

    # 4. POST /token (Exchange Code)
    print("\n[4] Testing POST /token...")
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID
    }).encode()
    
    req = urllib.request.Request(f"{BASE_URL}/token", data=data, method="POST")
    with urllib.request.urlopen(req) as response:
        body = json.loads(response.read().decode('utf-8'))
        access_token = body.get("access_token") 
        if access_token:
            print("✅ Success: Received Access Token")
            # print(f"   Token: {access_token}")
        else:
            print("❌ Failed: No access_token in response")
            print(body)
            sys.exit(1)

    # 5. Access Protected Resource
    print("\n[5] Testing Authorized Access to /sse...")
    req = urllib.request.Request(f"{BASE_URL}/sse")
    req.add_header("Authorization", f"Bearer {access_token}")
    
    # SSE keeps connection open, so we set a tiny timeout just to see if it connects
    try:
        urllib.request.urlopen(req, timeout=1)
        print("✅ Success: Connected to SSE (Timeout expected)")
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError) or "timed out" in str(e.reason):
             print("✅ Success: Connected to SSE (Timeout implies connection established)")
        else:
             print(f"❓ Info: Connection closed: {e}")
             # If it wasn't 401, it's a success for auth purposes
    except urllib.error.HTTPError as e:
        print(f"❌ Failed: Got HTTP {e.code}")
        sys.exit(1)

    print("\n🎉 All Auth Tests Passed!")

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
        sys.exit(1)
