// Mock browser environment to capture fetch URLs from admin.js
const fetchCalls = [];
const alpineComponents = {};

// Mock fetch
global.fetch = function(url, options) {
    fetchCalls.push({ url, method: (options && options.method) || 'GET', options });
    return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, data: [], message: 'OK' }),
        text: () => Promise.resolve(''),
    });
};

// Mock XMLHttpRequest
global.XMLHttpRequest = class {
    constructor() { this._url = ''; this._method = ''; }
    open(method, url) { this._method = method; this._url = url; fetchCalls.push({ url, method, source: 'XHR' }); }
    send(body) {}
    setRequestHeader() {}
    addEventListener() {}
    set onreadystatechange(fn) {}
    get readyState() { return 4; }
    get status() { return 200; }
    get responseText() { return '{"success":true,"data":[]}'; }
};

// Mock DOM
global.window = global;
global.document = {
    querySelector: () => ({ 
        getAttribute: () => '', value: '', textContent: '',
        addEventListener: () => {},
        classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
        style: {},
        innerHTML: '',
        querySelectorAll: () => [],
        appendChild: () => {},
    }),
    querySelectorAll: () => [],
    getElementById: () => null,
    createElement: () => ({ 
        setAttribute() {}, style: {}, classList: { add() {}, remove() {} },
        appendChild() {}, addEventListener() {},
    }),
    body: { appendChild() {}, classList: { add() {}, remove() {} } },
    addEventListener: () => {},
    cookie: 'ci_session=test123',
    location: { href: '', pathname: '/jehat/dashboard', hostname: 'localhost' },
    head: { appendChild() {} },
    createTextNode: () => ({}),
    createDocumentFragment: () => ({ appendChild() {} }),
    readyState: 'complete',
};
global.location = global.document.location;
global.navigator = { userAgent: 'Mozilla/5.0', clipboard: { writeText: () => Promise.resolve() } };
global.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.sessionStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
global.alert = () => {};
global.confirm = () => true;
global.prompt = () => '';
global.console = { log() {}, error() {}, warn() {}, info() {}, debug() {} };
const realSetTimeout = setTimeout;
const realSetInterval = setInterval;
global.setTimeout = (fn, ms) => { return realSetTimeout(() => { try { fn(); } catch(e) {} }, ms || 0); };
global.setInterval = (fn, ms) => { return realSetInterval(() => { try { fn(); } catch(e) {} }, ms || 1000); };
global.clearTimeout = () => {};
global.clearInterval = () => {};
global.requestAnimationFrame = () => 1;
global.FormData = class {
    constructor() { this._data = {}; }
    append(k, v) { this._data[k] = v; }
    get(k) { return this._data[k]; }
    entries() { return Object.entries(this._data); }
};
global.Swal = { fire: () => Promise.resolve({ isConfirmed: true }) };
global.toastr = { success() {}, error() {}, warning() {}, info() {} };
global.Notyf = class { success() {} error() {} };
global.ClipboardJS = class { constructor() {} on() {} };

// Mock Alpine.js - capture data definitions
global.Alpine = {
    data: function(name, factory) {
        console.error(`[ALPINE_DATA] ${name}`);
        try {
            const instance = factory();
            alpineComponents[name] = instance;
            
            // Call init if it exists
            if (instance.init) {
                try { instance.init(); } catch(e) {}
            }
            
            // Call all fetch* methods
            for (const [key, val] of Object.entries(instance)) {
                if (typeof val === 'function' && key.startsWith('fetch')) {
                    console.error(`[CALLING] ${name}.${key}()`);
                    try { val.call(instance); } catch(e) {}
                }
            }
        } catch(e) {
            console.error(`[ALPINE_ERROR] ${name}: ${e.message}`);
        }
    },
    store: function(name, data) {
        console.error(`[ALPINE_STORE] ${name}`);
    },
    plugin: () => {},
    start: () => {},
};

global.JSONEditor = class { constructor() {} set() {} get() { return {}; } };

// Load and run admin.js
try {
    const fs = require('fs');
    const code = fs.readFileSync('/root/tokmanni.palkintohakemus.fi/static/js/admin.js', 'utf8');
    eval(code);
} catch(e) {
    console.error(`[EVAL_ERROR] ${e.message}`);
}

// Wait for promises to resolve
setTimeout(() => {
    console.log('\n=== ALL FETCH CALLS ===');
    fetchCalls.forEach((call, i) => {
        console.log(`${i+1}. ${call.method || 'GET'} ${call.url} ${call.source || ''}`);
    });
    
    console.log('\n=== ALPINE COMPONENTS ===');
    for (const [name, comp] of Object.entries(alpineComponents)) {
        const methods = Object.entries(comp)
            .filter(([k, v]) => typeof v === 'function')
            .map(([k]) => k);
        console.log(`${name}: methods=[${methods.join(', ')}]`);
    }
}, 500);

setTimeout(() => {
    console.log('\n=== FINAL FETCH CALLS ===');
    fetchCalls.forEach((call, i) => {
        console.log(`${i+1}. ${call.method || 'GET'} ${call.url}`);
    });
    process.exit(0);
}, 1000);
