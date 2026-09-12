# ⚡ Fast Browser MCP (v0.2.0)

Універсальний, надшвидкий MCP-сервер та CLI-інструмент для автоматизації браузера на базі **Chrome DevTools Protocol (CDP)**.

Розроблено спеціально для усунення головної проблеми AI-агентів — **затримок очікування між діями (round-trip latency)** та **надлишкового споживання токенів контексту**.

---

## 🌟 Ключові особливості

1. **🚀 Multi-Action Batch Execution (`browser_batch`)**:
   - Виконує цілий ланцюжок дій (`click`, `fill`, `press_key`, `scroll`, `select_option`, `hover`, `wait`, `eval`, `extract`, `snapshot`, `screenshot`, `reload`) за **один виклик**.
   - Ланцюжок із 4–5 дій виконується за **~0.6 секунди** (замість 20–30 секунд у звичайних MCP).

2. **🏷️ Розумний Token-Efficient Snapshot (`@ref` система)**:
   - Автоматично розпізнає елементи без звичайного тексту (іконки, SVG, фонові зображення CSS `background-image`, `aria-label`, `title`, `alt`):
     ```text
     @1 [td] "cls:nav-drawer__item nav-surface"
     @2 [td] "Назад"
     @3 [div] "bg:quest1.png"
     @4 [div] "bg:questA2.png"
     @5 [div] "bg:questA3.png"
     @6 [a] "Сбор Старейшин"
     ```
   - Займає **менше 100 токенів** замість важкого HTML на 1–2 МБ!
   - Клік, введення або скрол виконуються прямо за міткою: `click: "@6"`, `scroll: "@6"`.

3. **🛡️ Автоматична обробка JS-діалогів**:
   - Автоматично перехоплює та підтверджує діалоги `alert()`, `confirm()`, `prompt()`, запобігаючи «зависанню» вкладки.

4. **⌨️ Повна підтримка клавіатури та скролінгу**:
   - Натискання клавіш (`Enter`, `Escape`, `Tab`, `Backspace`, `ArrowDown`, `Space`).
   - Скролінг сторінки на N пікселів або плавний скрол до конкретного елемента.

5. **📑 Керування вкладками**:
   - Створення нової вкладки (`new_tab`), закриття (`close_tab`), оновлення (`reload`), перемикання (`select_tab`).

6. **🔍 Повноцінний реверс-інжиніринг та перехоплення трафіку**:
   - Автоматичне логування всіх **HTTP / XHR / Fetch** запитів (URL, метод, POST-параметри, статус).
   - Читання повного **тіла відповіді сервера** (`get_response_body`).
   - Перехоплення **WebSocket пакетів** (`sent` / `received`) у реальному часі (ідеально для бойових дій в MMO).
   - Вивантаження всіх **куків і токенів сесії** (`uid`, `hash`, `PHPSESSID` тощо).

7. **🔒 Робота з твоїм реальним браузером (порт 9222)**:
   - Підключається до твого активного Chrome (`--remote-debugging-port=9222`).
   - Зберігає всі куки, паролі та активні сесії. Жодних проблем із захистами (Cloudflare).

---

## 📦 Встановлення

Працює на стандартному Python 3.10+ (потрібні лише `websockets` та `requests`):
```bash
pip install websockets requests
```

---

## ⚙️ Підключення як MCP Server

Додай у свій `mcp_config.json` (Antigravity, Claude Desktop, Cursor тощо):

```json
{
  "mcpServers": {
    "fast-browser": {
      "command": "python3",
      "args": [
        "-m",
        "fast_browser.server"
      ],
      "env": {
        "PYTHONPATH": "/home/qumhab/Documents/Projects/fast-browser-mcp"
      }
    }
  }
}
```

### Доступні інструменти:
| Інструмент | Опис |
|---|---|
| `browser_list_tabs` | Список відкритих вкладок (id, title, url) |
| `browser_select_tab` | Перемикання на потрібну вкладку за назвою чи URL |
| `browser_new_tab` | Відкрити нову вкладку з URL |
| `browser_close_tab` | Закрити вкладку за ID (або активну) |
| `browser_reload` | Перезавантажити активну сторінку |
| `browser_snapshot` | Розумний компактний знімок сторінки з номерами `@1`, `@2`... |
| `browser_batch` | **Пакетне виконання дій за мілісекунди** |
| `browser_eval` | Виконання JavaScript у контексті сторінки |
| `browser_click` | Клік по `@ref` або CSS-селектору |
| `browser_fill` | Введення тексту в поле за `@ref` чи селектором |
| `browser_press_key` | Натискання клавіші (`Enter`, `Escape`, `Tab` тощо) |
| `browser_scroll` | Скролінг сторінки або скрол до конкретного `@ref` |
| `browser_navigate` | Перехід за адресою |
| `browser_console_logs` | **Логи консолі браузера (console.log, console.error, exceptions)** |
| `browser_get_storage` | **Вивантаження localStorage та sessionStorage** |
| `browser_export_traffic` | **Експорт усього перехопленого трафіку (HTTP + WebSockets) у JSON-файл** |
| `browser_set_viewport` | **Емуляція розміру екрану (мобільний / десктоп) та DPI** |
| `browser_upload_file` | **Нативне завантаження файлів у `<input type='file'>`** |
| `browser_network_requests` | **Список перехоплених HTTP/XHR запитів (POST/GET/статус)** |
| `browser_network_get_response` | **Тіло відповіді сервера (JSON/HTML) та деталі запиту** |
| `browser_websocket_messages` | **WebSocket пакети гри в реальному часі (sent/received)** |
| `browser_get_cookies` | **Отримання куків, токенів авторизації та сесій** |
| `browser_screenshot` | Збереження скріншоту у файл |

---

## 💻 Використання через CLI

```bash
cd /home/qumhab/Documents/Projects/fast-browser-mcp

# Список відкритих вкладок
python3 -m fast_browser.cli list-tabs

# Знімок сторінки зі смарт-мітками
python3 -m fast_browser.cli --tab mmobitva snapshot

# Натискання клавіші Enter
python3 -m fast_browser.cli --tab mmobitva press-key Enter

# Скрол сторінки вниз на 300px
python3 -m fast_browser.cli --tab mmobitva scroll --delta-y 300

# Пакетний ланцюжок дій (Snapshot -> Click -> Wait -> Snapshot)
python3 -m fast_browser.cli --tab mmobitva batch '[
  {"action": "snapshot"},
  {"action": "click", "ref": "@6"},
  {"action": "wait", "ms": 300},
  {"action": "snapshot"}
]'
```

---

## 📊 Бенчмарк швидкості

| Операція | Звичайний MCP через LLM | Fast Browser Batch |
|---|---|---|
| 1 дія (клік / eval) | ~3–5 сек | **10–25 мс** |
| Ланцюжок з 4 дій | ~20–30 сек | **0.6 сек** |
| Споживання токенів | ~10,000–50,000 токенів | **< 150 токенів** |
