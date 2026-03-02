#!/usr/bin/env python3
"""
Tokmanni site scraper - Login yapıp tüm sayfaları ve API verilerini çeker.
"""
import requests
import os
import json
import time
import sys

BASE = "https://tokmanni.palkintohakemus.fi"
OUT = "/root/cark1/site-capture"
USERNAME = "denez"
PASSWORD = "sanane21"

# Dizinleri oluştur
for d in ["pages", "api", "pages/languages_edit"]:
    os.makedirs(os.path.join(OUT, d), exist_ok=True)

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36'
})

# Login
print("=== Login ===")
resp = session.post(f"{BASE}/jehat/login", data={
    "username": USERNAME,
    "password": PASSWORD
}, allow_redirects=True)
print(f"  Status: {resp.status_code}, URL: {resp.url}")
print(f"  Title match: {'Yönetim Paneli - Giriş' not in resp.text}")

if "Yönetim Paneli - Giriş" in resp.text:
    print("  ERROR: Login failed!")
    sys.exit(1)

print(f"  Cookies: {dict(session.cookies)}")
print()

# Admin Sayfaları
PAGES = [
    "dashboard",
    "bank/list",
    "bank/add",
    "onlineUsers",
    "wheelSettings",
    "countrySettings",
    "languages/list",
    "languages/edit/fi",
    "languages/edit/se",
    "languages/edit/no",
    "languages/edit/dk",
    "languages/edit/es",
    "languages/edit/at",
    "languages/edit/au",
    "languages/edit/ie",
    "languages/edit/hk",
    "userManagement",
    "activityLogs",
    "bannedList",
    "adminSettings",
    "export",
    "truncate",
    "clear-session",
]

print("=== Fetching Admin Pages ===")
for page in PAGES:
    safe = page.replace("/", "_")
    try:
        r = session.get(f"{BASE}/jehat/{page}", allow_redirects=True)
        if "Yönetim Paneli - Giriş" in r.text:
            print(f"  /jehat/{page} -> REDIRECTED TO LOGIN (session expired?)")
            # Re-login
            session.post(f"{BASE}/jehat/login", data={"username": USERNAME, "password": PASSWORD}, allow_redirects=True)
            r = session.get(f"{BASE}/jehat/{page}", allow_redirects=True)
        
        with open(os.path.join(OUT, "pages", f"{safe}.html"), "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"  /jehat/{page} -> {len(r.text)} bytes")
    except Exception as e:
        print(f"  /jehat/{page} -> ERROR: {e}")

print()

# Login sayfası (auth olmadan)
print("=== Fetching Login Page ===")
r2 = requests.get(f"{BASE}/jehat")
with open(os.path.join(OUT, "pages", "login.html"), "w", encoding="utf-8") as f:
    f.write(r2.text)
print(f"  login -> {len(r2.text)} bytes")

# Front page
print("=== Fetching Front Page ===")
r3 = requests.get(f"{BASE}/")
with open(os.path.join(OUT, "pages", "index.html"), "w", encoding="utf-8") as f:
    f.write(r3.text)
print(f"  index -> {len(r3.text)} bytes")

print()

# API Endpoints - admin.js'den çıkarıldı
# Bunlar fetch() ile çağrılan endpoint'ler
API_ENDPOINTS = [
    # listRows - ana dashboard veri tablosu
    ("/jehat/listRows", "GET"),
    ("/jehat/lis", "GET"),
    ("/jehat/list", "GET"),
    # Banks
    ("/jehat/listBanks", "GET"),
    ("/jehat/list-banks", "GET"),
    ("/jehat/banks", "GET"),
    # Stats
    ("/jehat/stats", "GET"),
    ("/jehat/getStats", "GET"),
    # Logs
    ("/jehat/logs", "GET"),
    ("/jehat/getLogs", "GET"),
    ("/jehat/listLogs", "GET"),
    # Online users
    ("/jehat/onlineUsers/list", "GET"),
    ("/jehat/getOnlineUsers", "GET"),
    # Wheel settings
    ("/jehat/getWheelSettings", "GET"),
    ("/jehat/wheelSettings/get", "GET"),
    # Country settings
    ("/jehat/getCountrySettings", "GET"),
    ("/jehat/countrySettings/get", "GET"),
    # Languages
    ("/jehat/languages/list/data", "GET"),
    ("/jehat/getLanguages", "GET"),
    ("/jehat/listLanguages", "GET"),
    # Users
    ("/jehat/getUsers", "GET"),
    ("/jehat/listUsers", "GET"),
    # Admin settings
    ("/jehat/getSettings", "GET"),
    ("/jehat/settings", "GET"),
    # Activity logs
    ("/jehat/getActivityLogs", "GET"),
    ("/jehat/activityLogs/list", "GET"),
    # Banned
    ("/jehat/getBannedList", "GET"),
    ("/jehat/bannedList/data", "GET"),
    # Visitors/rows
    ("/jehat/visitors", "GET"),
    ("/jehat/getVisitors", "GET"),
    ("/jehat/rows", "GET"),
    ("/jehat/getRows", "GET"),
    ("/jehat/fetchRows", "GET"),
    # resetUserSession endpoint
    ("/jehat/resetUserSession", "GET"),
    ("/jehat/res", "GET"),
]

print("=== Probing API Endpoints ===")
api_results = {}
for endpoint, method in API_ENDPOINTS:
    try:
        if method == "GET":
            r = session.get(f"{BASE}{endpoint}", allow_redirects=False)
        else:
            r = session.post(f"{BASE}{endpoint}", allow_redirects=False)
        
        ct = r.headers.get('Content-Type', '')
        safe = endpoint.replace("/", "_").strip("_")
        
        # JSON yanıtı mı?
        is_json = 'json' in ct or r.text.strip().startswith('{') or r.text.strip().startswith('[')
        
        status_info = f"status={r.status_code}, type={ct[:40]}, size={len(r.text)}"
        
        if r.status_code == 200 and len(r.text) > 0:
            with open(os.path.join(OUT, "api", f"{safe}.json" if is_json else f"{safe}.html"), "w", encoding="utf-8") as f:
                f.write(r.text)
            
            if is_json:
                try:
                    data = json.loads(r.text)
                    api_results[endpoint] = {"status": r.status_code, "json": True, "preview": str(data)[:200]}
                    print(f"  {endpoint} -> JSON ✓ ({len(r.text)} bytes)")
                except:
                    api_results[endpoint] = {"status": r.status_code, "json": False, "size": len(r.text)}
                    print(f"  {endpoint} -> TEXT ({len(r.text)} bytes)")
            else:
                api_results[endpoint] = {"status": r.status_code, "json": False, "size": len(r.text)}
                print(f"  {endpoint} -> HTML/TEXT ({len(r.text)} bytes)")
        elif r.status_code == 302:
            print(f"  {endpoint} -> 302 Redirect to {r.headers.get('Location', '?')}")
        elif r.status_code == 404:
            print(f"  {endpoint} -> 404 Not Found")
        else:
            print(f"  {endpoint} -> {status_info}")
    except Exception as e:
        print(f"  {endpoint} -> ERROR: {e}")

# API sonuçlarını kaydet
with open(os.path.join(OUT, "api", "_results.json"), "w") as f:
    json.dump(api_results, f, indent=2, ensure_ascii=False)

print()
print("=== DONE ===")
print(f"Pages saved to: {OUT}/pages/")
print(f"API data saved to: {OUT}/api/")
