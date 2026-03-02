from playwright.sync_api import sync_playwright
import json

def check_page(page, url):
    assets = {}
    def on_response(response):
        u = response.url
        if ('/static/' in u and u.endswith('.js')) or any(x in u for x in ('admin.js', 'chartist', 'cdn.min.js')):
            assets[u] = response.status
    page.on('response', on_response)
    console_messages = []
    page_errors = []
    def on_console(msg):
        console_messages.append({'type': msg.type, 'text': msg.text})
    def on_page_error(err):
        page_errors.append(str(err))
    page.on('console', on_console)
    page.on('pageerror', on_page_error)
    page.goto(url, timeout=15000)
    # give client scripts time to initialize and render charts
    try:
        page.wait_for_selector('.ct-chart, [class*=ct-chart]', timeout=3000)
    except:
        page.wait_for_timeout(1000)
    btn = page.query_selector('button[type=submit]')
    charts = page.query_selector('.ct-chart') or page.query_selector('[class*=ct-chart]')
    return {
        'url': url,
        'status_assets': assets,
        'has_login_button': bool(btn),
        'has_chart_element': bool(charts),
        'html_snippet': page.content()[:2000],
        'console': console_messages,
        'page_errors': page_errors
    }

def main():
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        results['login'] = check_page(page, 'http://127.0.0.1:8080/jehat/login')
        # perform login using seeded admin credentials
        try:
            page.goto('http://127.0.0.1:8080/jehat/login')
            page.fill('input[name=username]', 'denez')
            page.fill('input[name=password]', 'sanane21')
            page.click('button[type=submit]')
            page.wait_for_load_state('networkidle', timeout=5000)
        except Exception as e:
            results['login_post'] = {'error': str(e)}

        try:
            results['dashboard'] = check_page(page, 'http://127.0.0.1:8080/jehat/dashboard')
        except Exception as e:
            results['dashboard'] = {'error': str(e)}
        browser.close()

    print(json.dumps(results, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
