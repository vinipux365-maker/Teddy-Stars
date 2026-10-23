import subprocess, sys, time, random, asyncio, logging, sqlite3, os, hmac, hashlib
import requests as req
from datetime import datetime, timedelta
from urllib.parse import parse_qsl

def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

try: import aiogram
except: install("aiogram==3.20.0")

try: import requests
except: install("requests")

try:
    from aiohttp import web
    import aiohttp
except Exception:
    install("aiohttp>=3.8.0")
    from aiohttp import web
    import aiohttp

# Telethon потрібен лише для автовидачі подарунків (розділ "🎁 Подарунки").
# Якщо пакет не встановлено — ця частина функціоналу просто вимикається,
# решта бота продовжує працювати як раніше.
try:
    from telethon import TelegramClient as GiftTelegramClient
    from telethon.tl.functions.payments import GetPaymentFormRequest, SendStarsFormRequest, GetStarGiftsRequest
    from telethon.tl.types import InputInvoiceStarGift, TextWithEntities, CodeSettings
    from telethon.tl.functions.auth import SendCodeRequest, SignInRequest, CheckPasswordRequest
    from telethon.tl.functions.account import GetPasswordRequest
    from telethon.password import compute_check as gift_compute_check
    from telethon import errors as telethon_errors
    GIFT_TELETHON_AVAILABLE = True
except ImportError:
    try:
        install("telethon")
        from telethon import TelegramClient as GiftTelegramClient
        from telethon.tl.functions.payments import GetPaymentFormRequest, SendStarsFormRequest, GetStarGiftsRequest
        from telethon.tl.types import InputInvoiceStarGift, TextWithEntities, CodeSettings
        from telethon.tl.functions.auth import SendCodeRequest, SignInRequest, CheckPasswordRequest
        from telethon.tl.functions.account import GetPasswordRequest
        from telethon.password import compute_check as gift_compute_check
        from telethon import errors as telethon_errors
        GIFT_TELETHON_AVAILABLE = True
    except Exception:
        GIFT_TELETHON_AVAILABLE = False

# Fragment (неофіційний API) — потрібен лише для автовиводу Stars/Premium з адмінки.
# Якщо пакет не встановлено чи не задані TON_SEED/FRAGMENT_COOKIES/FRAGMENT_API_KEY —
# автовивід просто вимикається, адмін підтверджує виплату вручну як і раніше.
try:
    from pyfragment import FragmentClient
    from pyfragment import exceptions as fragment_exceptions
    FRAGMENT_AVAILABLE = True
except ImportError:
    try:
        install("pyfragment")
        from pyfragment import FragmentClient
        from pyfragment import exceptions as fragment_exceptions
        FRAGMENT_AVAILABLE = True
    except Exception:
        FRAGMENT_AVAILABLE = False

# tonutils — прямі TON-перекази клієнтам (для автовиконання заявок "Купити TON").
# Використовує ту саму пару TON_SEED + FRAGMENT_API_KEY (tonapi/tonconsole ключ),
# без Fragment та без cookies — це звичайний переказ у мережі TON.
try:
    from tonutils.clients.http.tonapi import TonapiClient
    from tonutils.contracts.wallet.versions.v5 import WalletV5R1
    from ton_core import NetworkGlobalID
    TONUTILS_AVAILABLE = True
except ImportError:
    try:
        install("tonutils")
        from tonutils.clients.http.tonapi import TonapiClient
        from tonutils.contracts.wallet.versions.v5 import WalletV5R1
        from ton_core import NetworkGlobalID
        TONUTILS_AVAILABLE = True
    except Exception:
        TONUTILS_AVAILABLE = False

# ========================================================
# НАСТРОЙКИ
# ========================================================

BOT_TOKEN     = os.getenv("BOT_TOKEN", "8756492243:AAEau3fHTCBESTAicbY-L3B22E-q_Vr6jnM")
ADMIN_ID      = 6031180988
ADMIN_IDS     = [6031180988]
ADMIN_CHAT_ID = -1004313347719
REVIEWS_CHANNEL = "@teddyluxxRep"
BOT_NAME        = "Teddy Stars"
BOT_USERNAME    = os.getenv("BOT_USERNAME", "")  # якщо порожньо — береться через getMe при старті

# ---- Автовивід Stars/автовидача Premium/TON через Fragment (неофіційний API) ----
# ---- Автовивід Stars/автовидача Premium/TON через Fragment (неофіційний API) ----
TON_SEED          = os.getenv("TON_SEED", "")            # seed-фраза робочого TON-гаманця (24 слова)
FRAGMENT_COOKIES  = os.getenv("FRAGMENT_COOKIES", "")     # сесійні cookies з fragment.com (Header String)
FRAGMENT_API_KEY  = os.getenv("FRAGMENT_API_KEY", "")     # ключ tonapi з tonconsole.com
FRAGMENT_WALLET_VERSION = os.getenv("FRAGMENT_WALLET_VERSION", "V5R1")
AUTO_WITHDRAW_ENABLED = bool(TON_SEED and FRAGMENT_COOKIES and FRAGMENT_API_KEY)
AUTO_PREMIUM_SEND_ENABLED = bool(TON_SEED and FRAGMENT_COOKIES and FRAGMENT_API_KEY)  # автовидача Premium через Fragment
AUTO_TON_SEND_ENABLED = bool(TON_SEED and FRAGMENT_API_KEY)  # прямий переказ TON клієнту не потребує cookies

# ---- CryptoBot (Crypto Pay API) — автоматична оплата через @CryptoBot ----
CRYPTOBOT_API_TOKEN = os.getenv("CRYPTOBOT_API_TOKEN", "")
CRYPTOBOT_API_BASE = "https://pay.crypt.bot/api"
CRYPTOBOT_ENABLED = bool(CRYPTOBOT_API_TOKEN)


from aiogram import Bot, Dispatcher, F
from aiogram.types import (Message, CallbackQuery, ReplyKeyboardMarkup,
                           KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton,
                           BotCommand, WebAppInfo, MenuButtonWebApp, CopyTextButton,
                           LabeledPrice, PreCheckoutQuery)
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========================================================
# 🌐 Мультимова: поточна мова користувача доступна через ContextVar,
# щоб функція T() автоматично підбирала переклад без потреби
# передавати lang в кожен виклик по всьому коду.
# ========================================================
import contextvars
_current_lang: contextvars.ContextVar = contextvars.ContextVar("_current_lang", default="uk")

class LangMiddleware:
    """Перед обробкою будь-якого апдейта визначає мову користувача з БД
    і виставляє її в ContextVar на час обробки цього апдейта."""
    async def __call__(self, handler, event, data):
        uid = None
        user = getattr(event, "from_user", None)
        if user:
            uid = user.id
        token = _current_lang.set(get_lang(uid) if uid else "uk")
        try:
            return await handler(event, data)
        finally:
            _current_lang.reset(token)

dp.message.outer_middleware(LangMiddleware())

class MenuButtonResetMiddleware:
    """Якщо користувач натиснув кнопку головного меню, поки бот чекає на текстовий
    ввод (кількість зірок, username тощо) — скидаємо стан, щоб кнопка спрацювала,
    а не сприймалась як невалідне число."""
    async def __call__(self, handler, event, data):
        try:
            text = (getattr(event, "text", None) or "").strip()
            state = data.get("state")
            if text and state is not None and not text.startswith("/"):
                cur = await state.get_state()
                if cur and cur != "S:menu" and not cur.split(":")[-1].startswith("admin"):
                    for b in get_menu_buttons():
                        labels = set()
                        for col in ("text_uk", "text_ru", "text_en"):
                            t = (b.get(col) or "").strip()
                            if t:
                                labels.add(t)
                                labels.add(f"{b.get('emoji') or ''} {t}".strip())
                        if text in labels:
                            await state.set_state(S.menu)
                            break
        except Exception as e:
            logger.error(f"MenuButtonResetMiddleware: {e}")
        return await handler(event, data)

dp.message.outer_middleware(MenuButtonResetMiddleware())
dp.callback_query.outer_middleware(LangMiddleware())
dp.pre_checkout_query.outer_middleware(LangMiddleware())

# Антифлуд
user_last_msg = {}
FLOOD_TIMEOUT = 0.8  # секунд между сообщениями

# ========================================================
# БАЗА ДАННЫХ
# ========================================================

DB_PATH = os.getenv("DB_PATH", "/data/bot.db")
# Файл Telethon-сесії для автовидачі подарунків. Лежить поруч з базою даних
# на тому самому персистентному томі, щоб вхід в акаунт не злітав після рестарту.
GIFT_SESSION_NAME = os.getenv("GIFT_SESSION_NAME", os.path.join(os.path.dirname(DB_PATH) or ".", "gift_session"))
try:
    os.makedirs(os.path.dirname(GIFT_SESSION_NAME) or ".", exist_ok=True)
except Exception:
    pass

async def check_subscription(uid: int) -> bool:
    """Перевірка підписки на канал відгуків (обов'язкова підписка)"""
    if get_setting("sub_required") != "1":
        return True
    channels = [c.strip() for c in (get_setting("sub_channels") or REVIEWS_CHANNEL).split(",") if c.strip()]
    for ch in channels:
        try:
            member = await bot.get_chat_member(f'@{ch.lstrip("@")}', uid)
            if member.status in ('left', 'kicked', 'banned'):
                return False
        except:
            pass  # якщо канал недоступний — пропускаємо
    return True

def sub_required_kb():
    channels = [c.strip() for c in (get_setting("sub_channels") or REVIEWS_CHANNEL).split(",") if c.strip()]
    rows = []
    for ch in channels:
        clean_ch = ch.lstrip("@")
        rows.append(InlineKeyboardButton(text=f"📢 @{clean_ch}", url=f"https://t.me/{clean_ch}"))
    rows = [rows]
    rows.append([InlineKeyboardButton(text="✅ Я підписався", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def is_valid_ton_wallet(w: str) -> bool:
    """Validate wallet — min 10 chars, not only digits, no spaces"""
    import re
    w = w.strip()
    if not w: return False
    if len(w) < 10: return False
    if w.isdigit(): return False
    if ' ' in w: return False
    if not re.match(r'^[A-Za-z0-9_:+\-./]+$', w): return False
    return True

def init_db():
    conn = get_conn(); c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
        language TEXT DEFAULT 'uk', stars_bought INTEGER DEFAULT 0,
        ton_bought REAL DEFAULT 0, premium_bought INTEGER DEFAULT 0,
        total_spent REAL DEFAULT 0, stars_balance INTEGER DEFAULT 0,
        ref_by INTEGER DEFAULT 0, ref_count INTEGER DEFAULT 0,
        ref_earned INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0, ban_reason TEXT DEFAULT '',
        last_active TEXT DEFAULT (datetime('now')),
        registered_at TEXT DEFAULT (datetime('now')))""")

    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        order_type TEXT, amount REAL, price_uah REAL,
        recipient TEXT DEFAULT '', wallet TEXT DEFAULT '',
        bank TEXT DEFAULT '', status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT (datetime('now')), package_key TEXT DEFAULT NULL,
        gift_sent_count INTEGER DEFAULT 0, cryptobot_invoice_id TEXT DEFAULT NULL)""")
    # Міграція для БД, створених до появи прив'язки паку Stars до реального подарунка
    c.execute("PRAGMA table_info(orders)")
    _orders_cols = [r["name"] for r in c.fetchall()]
    if "package_key" not in _orders_cols:
        c.execute("ALTER TABLE orders ADD COLUMN package_key TEXT DEFAULT NULL")
    if "gift_sent_count" not in _orders_cols:
        c.execute("ALTER TABLE orders ADD COLUMN gift_sent_count INTEGER DEFAULT 0")
    if "cryptobot_invoice_id" not in _orders_cols:
        c.execute("ALTER TABLE orders ADD COLUMN cryptobot_invoice_id TEXT DEFAULT NULL")

    c.execute("""CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        message TEXT, file_id TEXT DEFAULT '', file_type TEXT DEFAULT '',
        status TEXT DEFAULT 'open', created_at TEXT DEFAULT (datetime('now')))""")

    c.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS menu_buttons (
        id INTEGER PRIMARY KEY AUTOINCREMENT, button_key TEXT UNIQUE,
        text_ru TEXT, text_uk TEXT DEFAULT '', emoji TEXT DEFAULT '',
        style TEXT DEFAULT 'default', custom_emoji_id TEXT DEFAULT '',
        position INTEGER, row_num INTEGER, text_en TEXT DEFAULT '')""")

    c.execute("""CREATE TABLE IF NOT EXISTS bot_texts (
        key TEXT PRIMARY KEY, value_ru TEXT, value_uk TEXT, value_en TEXT)""")

    # Міграції для БД, створених до появи англійської мови
    c.execute("PRAGMA table_info(menu_buttons)")
    if "text_en" not in [r["name"] for r in c.fetchall()]:
        c.execute("ALTER TABLE menu_buttons ADD COLUMN text_en TEXT DEFAULT ''")
    c.execute("PRAGMA table_info(bot_texts)")
    if "value_en" not in [r["name"] for r in c.fetchall()]:
        c.execute("ALTER TABLE bot_texts ADD COLUMN value_en TEXT")

    c.execute("""CREATE TABLE IF NOT EXISTS payment_methods (
        id INTEGER PRIMARY KEY AUTOINCREMENT, method_key TEXT UNIQUE,
        name_ru TEXT, name_uk TEXT, emoji TEXT,
        style TEXT DEFAULT 'default', details TEXT DEFAULT '',
        owner TEXT DEFAULT '', custom_emoji_id TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1, position INTEGER, instructions TEXT DEFAULT '')""")
    # Міграції для payment_methods — виконуються ПІСЛЯ створення таблиці,
    # інакше на щойно розгорнутій базі ALTER падав би з "no such table".
    c.execute("PRAGMA table_info(payment_methods)")
    pm_cols = [r["name"] for r in c.fetchall()]
    if "name_en" not in pm_cols:
        c.execute("ALTER TABLE payment_methods ADD COLUMN name_en TEXT DEFAULT ''")
    if "instructions" not in pm_cols:
        c.execute("ALTER TABLE payment_methods ADD COLUMN instructions TEXT DEFAULT ''")

    c.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        amount INTEGER, wallet TEXT, status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT (datetime('now')),
        auto_status TEXT DEFAULT '', tx_id TEXT DEFAULT '', error_message TEXT DEFAULT '')""")
    # Міграція для БД, створених до появи автовиводу через Fragment
    c.execute("PRAGMA table_info(withdrawals)")
    _wd_cols = [r["name"] for r in c.fetchall()]
    for col in ("auto_status", "tx_id", "error_message"):
        if col not in _wd_cols:
            c.execute(f"ALTER TABLE withdrawals ADD COLUMN {col} TEXT DEFAULT ''")

    c.execute("""CREATE TABLE IF NOT EXISTS request_log (
        user_id INTEGER, created_at TEXT)""")

    c.execute("""CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        comment TEXT DEFAULT '', photo_id TEXT DEFAULT '', rating INTEGER DEFAULT 0,
        order_type TEXT DEFAULT '', amount REAL DEFAULT 0,
        status TEXT DEFAULT 'pending', created_at TEXT DEFAULT (datetime('now')))""")

    # ---- ⭐ Паки Stars: каталог позицій (фіксовані + діапазони "своя сума") ----
    c.execute("""CREATE TABLE IF NOT EXISTS stars_packages (
        item_key TEXT PRIMARY KEY,
        kind TEXT DEFAULT 'fixed',
        amount INTEGER,
        range_min INTEGER,
        range_max INTEGER,
        emoji TEXT DEFAULT '⭐',
        custom_emoji_id TEXT DEFAULT '',
        label TEXT DEFAULT '',
        position INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        parent_key TEXT DEFAULT NULL,
        linked_gift_key TEXT DEFAULT NULL,
        linked_gift_qty INTEGER DEFAULT 1,
        description TEXT DEFAULT '',
        fixed_price REAL DEFAULT NULL)""")
    # Міграція для БД, створених до появи прив'язки паку до реального подарунка
    c.execute("PRAGMA table_info(stars_packages)")
    _sp_cols = [r["name"] for r in c.fetchall()]
    if "fixed_price" not in _sp_cols:
        c.execute("ALTER TABLE stars_packages ADD COLUMN fixed_price REAL DEFAULT NULL")
    if "description" not in _sp_cols:
        c.execute("ALTER TABLE stars_packages ADD COLUMN description TEXT DEFAULT ''")
    if "linked_gift_key" not in _sp_cols:
        c.execute("ALTER TABLE stars_packages ADD COLUMN linked_gift_key TEXT DEFAULT NULL")
    if "linked_gift_qty" not in _sp_cols:
        c.execute("ALTER TABLE stars_packages ADD COLUMN linked_gift_qty INTEGER DEFAULT 1")
    # Міграція для БД, створених до появи "групових" паків (parent_key)
    c.execute("PRAGMA table_info(stars_packages)")
    if "parent_key" not in [r["name"] for r in c.fetchall()]:
        c.execute("ALTER TABLE stars_packages ADD COLUMN parent_key TEXT DEFAULT NULL")

    c.execute("SELECT COUNT(*) as n FROM stars_packages")
    if c.fetchone()["n"] == 0:
        default_packages = [
            ("p4",  "fixed", 100,  None, None, "⭐", "", "", 4, 1, None),
            ("p5",  "fixed", 200,  None, None, "⭐", "", "", 5, 1, None),
            ("p6",  "fixed", 500,  None, None, "⭐", "", "", 6, 1, None),
            ("p7",  "fixed", 1000, None, None, "⭐", "", "", 7, 1, None),
            ("p8",  "group", None, None, None, "🎁", "", "Набір подарунків", 8, 1, None),
            ("p8a", "fixed", 13,   None, None, "🐻", "", "", 1, 1, "p8"),
            ("p8b", "fixed", 25,   None, None, "🌹", "", "", 2, 1, "p8"),
            ("p8c", "fixed", 50,   None, None, "🚀", "", "", 3, 1, "p8"),
            ("p9",  "range", None, 50,   None, "✏️", "", "Своя кількість 50+", 9, 1, None),
        ]
        for dp_ in default_packages:
            c.execute("""INSERT INTO stars_packages
                (item_key,kind,amount,range_min,range_max,emoji,custom_emoji_id,label,position,enabled,parent_key)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", dp_)
    else:
        # Міграція для БД, де "p8" вже існував як діапазон "13-50" зі старої версії —
        # перетворюємо на груповий пак із трьома дочірніми кнопками (як у подарунків).
        c.execute("SELECT * FROM stars_packages WHERE item_key='p8'")
        p8 = c.fetchone()
        if p8 and p8["kind"] == "range":
            c.execute("""UPDATE stars_packages SET kind='group', amount=NULL,
                range_min=NULL, range_max=NULL, label=? WHERE item_key='p8'""",
                ("Набір подарунків",))
            children = [
                ("p8a", "fixed", 13, "🐻", 1, "p8"),
                ("p8b", "fixed", 25, "🌹", 2, "p8"),
                ("p8c", "fixed", 50, "🚀", 3, "p8"),
            ]
            for key, kind, amt, emoji, pos, parent in children:
                c.execute("""INSERT OR IGNORE INTO stars_packages
                    (item_key,kind,amount,emoji,position,enabled,parent_key)
                    VALUES (?,?,?,?,?,1,?)""", (key, kind, amt, emoji, pos, parent))
        # Прибираємо дублі топ-рівневих 15/25/50 (p1/p2/p3) — тепер ці ж суми є
        # кнопками всередині "Набір подарунків", і мати їх ще й окремо зверху
        # тільки плутає. Видаляємо безумовно (адмін підтвердив), лише якщо
        # вони й досі є топ-рівневими позиціями (parent_key IS NULL).
        c.execute("DELETE FROM stars_packages WHERE item_key IN ('p1','p2','p3') AND parent_key IS NULL")

    # ---- 🎁 Подарунки: каталог позицій ----
    c.execute("""CREATE TABLE IF NOT EXISTS gift_items (
        item_key TEXT PRIMARY KEY,
        emoji TEXT DEFAULT '🎁',
        name TEXT DEFAULT '',
        price REAL DEFAULT 55.0,
        enabled INTEGER DEFAULT 1,
        quantity INTEGER,
        telegram_gift_id TEXT DEFAULT '',
        sticker_id TEXT DEFAULT '',
        position INTEGER DEFAULT 0,
        price_stars INTEGER)""")
    # Міграція для БД, створених до появи стовпця price_stars
    c.execute("PRAGMA table_info(gift_items)")
    if "price_stars" not in [r["name"] for r in c.fetchall()]:
        c.execute("ALTER TABLE gift_items ADD COLUMN price_stars INTEGER")

    # ---- 🎁 Подарунки: замовлення ----
    c.execute("""CREATE TABLE IF NOT EXISTS gift_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_uid TEXT UNIQUE,
        user_id INTEGER,
        item_key TEXT,
        gift_name TEXT DEFAULT '',
        gift_emoji TEXT DEFAULT '',
        gift_sticker TEXT DEFAULT '',
        price REAL DEFAULT 0,
        target_username TEXT DEFAULT '',
        comment TEXT DEFAULT '',
        payment_method TEXT DEFAULT '',
        status TEXT DEFAULT 'pending_payment',
        fulfill_error TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        cryptobot_invoice_id TEXT DEFAULT NULL)""")
    c.execute("PRAGMA table_info(gift_orders)")
    if "cryptobot_invoice_id" not in [r["name"] for r in c.fetchall()]:
        c.execute("ALTER TABLE gift_orders ADD COLUMN cryptobot_invoice_id TEXT DEFAULT NULL")

    defaults = {
        "stars_rate": "0.74", "ton_markup": "0", "crypto_markup": "0",
        "min_stars": "50", "min_ton": "0.25",
        "premium_3m": "280", "premium_6m": "520", "premium_12m": "950",
        "review_count": "0", "sell_stars_rate": "0.50", "min_sell_stars": "50",
        "sell_contact": "@teddyluxxRep",
        # Обов'язкова підписка
        "sub_required": "0", "sub_channels": "teddyluxxRep",
        # Антиспам
        "max_orders_per_hour": "5",
        # Вивід Stars
        "min_withdraw": "50",
        # Нарахування Stars вручну ліміт
        "max_give_stars": "100000",
        # Нагорода за відгук
        "review_reward_min": "1",
        "review_reward_max": "2",
        # Реферальна система
        "ref_enabled": "1", "ref_percent_purchase": "5",
        "btn_copyref_text": "📋 Скопіювати посилання", "btn_copyref_style": "default", "btn_copyref_emoji_id": "",
        # 🎁 Подарунки: Telethon-акаунт для автовидачі
        "gift_api_id": "0", "gift_api_hash": "",
        # ⭐ Оплата Telegram Stars напряму (Premium/Подарунки)
        "stars_pay_premium_enabled": "0", "stars_pay_gift_enabled": "0",
        "premium_3m_stars": "150", "premium_6m_stars": "280", "premium_12m_stars": "500",
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, v))

    # 🎁 Подарунки: дефолтний каталог (11 позицій, ціна 55 грн, преміум-стикери)
    default_gift_items = [
        ("1",  "🧸", "Ведмідь",   55.0, 1, None, "5935895822435615975", "5359736160224586485", 1),
        ("2",  "🧸", "Ведмідь",   55.0, 1, None, "6026193266406327981", "5447213743417105726", 2),
        ("3",  "🧸", "Ведмідь",   55.0, 1, None, "5956217000635139069", "5379850840691476775", 3),
        ("4",  "🎄", "Ялинка",    55.0, 1, None, "5922558454332916696", "5345935030143196497", 4),
        ("5",  "🧸", "Ведмідь",   55.0, 1, None, "5800655655995968830", "5226661632259691727", 5),
        ("6",  "🧸", "Ведмідь",   55.0, 1, None, "5893356958802511476", "5317000922096769303", 6),
        ("7",  "🧸", "Ведмідь",   55.0, 1, None, "5866352046986232958", "5289761157173775507", 7),
        ("8",  "🧸", "Ведмідь",   55.0, 1, None, "5969796561943660080", "5393309541620291208", 8),
        ("9",  "❤️", "Серце",     55.0, 1, None, "5801108895304779062", "5224628072619216265", 9),
        ("10", "🧸", "Ведмідь",   55.0, 1, None, "5974210632977745012", "5397971251878732060", 10),
        ("11", "🎁", "Подарунок", 55.0, 1, None, "6046178578163303744", "5470129614439362117", 11),
    ]
    for gi in default_gift_items:
        c.execute("""INSERT OR IGNORE INTO gift_items
            (item_key,emoji,name,price,enabled,quantity,telegram_gift_id,sticker_id,position)
            VALUES (?,?,?,?,?,?,?,?,?)""", gi)
    # Якщо позиції gift_items вже існували в БД (бот запускався раніше, до
    # появи преміум-стикерів у каталозі) — INSERT OR IGNORE їх не зачепить,
    # тож донатягуємо sticker_id для існуючих рядків, де його ще не задано
    # вручну через адмінку (щоб не затерти ручні правки).
    for gi in default_gift_items:
        item_key, sticker_id = gi[0], gi[7]
        c.execute("""UPDATE gift_items SET sticker_id=?
            WHERE item_key=? AND (sticker_id IS NULL OR sticker_id='')""",
            (sticker_id, item_key))

    # Примусово оновлюємо контакт для продажу Stars на новий (для баз, створених раніше)

    # Примусово оновлюємо канал обов'язкової підписки на новий (лише якщо він ще не був
    # кастомізований адміном і містить старе значення за замовчуванням)

    btns = [
        ("stars",      "Купити Stars",    "Купити Stars",    "⭐", "primary", 1, 1, "Buy Stars"),
        ("premium",    "Telegram Premium","Telegram Premium","💎", "primary", 2, 1, "Telegram Premium"),
        ("ton",        "Купити TON",      "Купити TON",      "💎", "primary", 3, 1, "Buy TON"),
        ("profile",    "Профіль",         "Профіль",         "👤", "success", 4, 2, "Profile"),
        ("reviews",    "Відгуки",         "Відгуки",         "💬", "default", 6, 2, "Reviews"),
        ("sell_stars", "Продати Stars",   "Продати Stars",   "💰", "success", 5, 2, "Sell Stars"),
        ("referral",   "Реферали",        "Реферали",        "👥", "default", 7, 3, "Referrals"),
        ("support",    "Підтримка",       "Підтримка",       "🆘", "default", 8, 3, "Support"),
        ("calculator", "Калькулятор",     "Калькулятор",     "🧮", "default", 9, 3, "Calculator"),
    ]
    for b in btns:
        c.execute("""INSERT OR IGNORE INTO menu_buttons
            (button_key,text_ru,text_uk,emoji,style,position,row_num,text_en)
            VALUES (?,?,?,?,?,?,?,?)""", b)
        if c.rowcount == 1:
            # Кнопка щойно створена вперше — дефолтні значення вже встановлені через INSERT.
            # Якщо ж кнопка вже існувала (rowcount=0) — НІЧОГО не чіпаємо, щоб не затерти
            # кастомізацію адміна (текст/стиль/преміум-емодзі), зроблену через "🎨 Кнопки меню".
            pass
        else:
            # Кнопка вже існувала: лише донатягуємо англійський переклад, якщо його ще нема.
            c.execute("""UPDATE menu_buttons SET text_en=COALESCE(NULLIF(text_en,''), ?)
                WHERE button_key=?""", (b[7], b[0]))

    # Одноразова міграція: меню 3 ряди по 3 кнопки
    c.execute("SELECT value FROM settings WHERE key='menu_layout_3x3'")
    if not c.fetchone():
        layout = [("stars",1,1),("premium",2,1),("ton",3,1),
                  ("profile",4,2),("sell_stars",5,2),("reviews",6,2),
                  ("referral",7,3),("support",8,3),("calculator",9,3)]
        for key,pos,row in layout:
            c.execute("UPDATE menu_buttons SET position=?, row_num=? WHERE button_key=?", (pos,row,key))
        c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('menu_layout_3x3','1')")

    # Видаляємо кнопки мови/топів/бонусу/ігор якщо залишились у БД зі старих версій
    c.execute("""DELETE FROM menu_buttons WHERE button_key IN
        ('changelang','daily_bonus','top_buyers','top_winners','games','language','gift')""")
    # Преміум-емодзі на кнопці "🎁 Подарунки" — задаємо лише якщо ще не задано
    # вручну через адмінку (щоб не перезаписати ручні налаштування).
    c.execute("""UPDATE menu_buttons SET custom_emoji_id=?
        WHERE button_key='gift' AND (custom_emoji_id IS NULL OR custom_emoji_id='')""",
        ("5379850840691476775",))

    methods = [
        ("ua",       "🇺🇦 Українська картка", "🇺🇦 Українська картка",    "🇺🇦", "primary", 1),
        ("monobank", "🏦 Monobank",          "🏦 Monobank",              "🏦", "primary", 2),
        ("privat24", "🟩 Privat24",          "🟩 Privat24",              "🟩", "success", 3),
        ("abank",    "🅰️ А-Банк",            "🅰️ А-Банк",               "🅰️", "primary", 4),
        ("paypal",   "🅿️ PayPal",            "🅿️ PayPal",               "🅿️", "primary", 5),
        ("intl",     "🌍 Міжнародна картка",  "🌍 Міжнародна картка",     "🌍", "primary", 6),
        ("crypto",   "🌏 Крипта (TON/USDT)", "🌏 Крипта (TON/USDT)",    "🌏", "primary", 7),
        ("cryptobot", "🤖 CryptoBot (авто)", "🤖 CryptoBot (авто)",    "🤖", "success", 8),
    ]
    for m in methods:
        c.execute("""INSERT OR IGNORE INTO payment_methods
            (method_key,name_ru,name_uk,emoji,style,position) VALUES (?,?,?,?,?,?)""", m)

    bot_texts = [
        ("welcome",
         "\U0001F44B \u0412\u0456\u0442\u0430\u0454\u043c\u043e \u0432 <b>Teddy Stars</b>!\n\n\u2b50 \u041a\u0443\u043f\u0443\u0439 Telegram Stars \u0432\u0438\u0433\u0456\u0434\u043d\u043e\n\U0001F48E TON, Premium \u0442\u0430 \u043f\u043e\u0434\u0430\u0440\u0443\u043d\u043a\u0438\n\U0001F512 \u0411\u0435\u0437\u043f\u0435\u0447\u043d\u043e \u0442\u0430 \u0448\u0432\u0438\u0434\u043a\u043e\n\n\u041e\u0431\u0435\u0440\u0456\u0442\u044c \u0440\u043e\u0437\u0434\u0456\u043b \u043d\u0438\u0436\u0447\u0435 \U0001F447",
         "\U0001F44B \u0412\u0438\u0442\u0430\u0435\u043c \u0432 <b>Teddy Stars</b>!\n\n\u2b50 \u041f\u043e\u043a\u0443\u043f\u0430\u0439 Telegram Stars \u0432\u044b\u0433\u043e\u0434\u043d\u043e\n\U0001F48E TON, Premium \u0438 \u043f\u043e\u0434\u0430\u0440\u043a\u0438\n\U0001F512 \u0411\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e \u0438 \u0431\u044b\u0441\u0442\u0440\u043e\n\n\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0440\u0430\u0437\u0434\u0435\u043b \u043d\u0438\u0436\u0435 \U0001F447",
         "\U0001F44B Welcome to <b>Teddy Stars</b>!\n\n\u2b50 Buy Telegram Stars at a great rate\n\U0001F48E TON, Premium and gifts\n\U0001F512 Safe and fast\n\nChoose a section below \U0001F447"),
        ("receipt_ok",
         "\u2705 <b>\u0417\u0430\u043c\u043e\u0432\u043b\u0435\u043d\u043d\u044f #{oid} \u043f\u0440\u0438\u0439\u043d\u044f\u0442\u043e!</b>\n\n\u23f3 \u041e\u0431\u0440\u043e\u0431\u043a\u0430 \u0437\u0430\u0439\u043c\u0435 \u043d\u0435 \u0431\u0456\u043b\u044c\u0448\u0435 15 \u0445\u0432\u0438\u043b\u0438\u043d.\n\n\u0414\u044f\u043a\u0443\u0454\u043c\u043e \u0449\u043e \u043e\u0431\u0440\u0430\u043b\u0438 Teddy Stars! \U0001F499",
         "\u2705 <b>\u0417\u0430\u044f\u0432\u043a\u0430 #{oid} \u043f\u0440\u0438\u043d\u044f\u0442\u0430!</b>\n\n\u23f3 \u041e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430 \u0437\u0430\u0439\u043c\u0451\u0442 \u043d\u0435 \u0431\u043e\u043b\u0435\u0435 15 \u043c\u0438\u043d\u0443\u0442.\n\n\u0421\u043f\u0430\u0441\u0438\u0431\u043e \u0447\u0442\u043e \u0432\u044b\u0431\u0440\u0430\u043b\u0438 Teddy Stars! \U0001F499",
         "\u2705 <b>Order #{oid} accepted!</b>\n\n\u23f3 Processing takes up to 15 minutes.\n\nThanks for choosing Teddy Stars! \U0001F499"),
        ("order_done",
         "\u2705 <b>\u0417\u0430\u043c\u043e\u0432\u043b\u0435\u043d\u043d\u044f \u0432\u0438\u043a\u043e\u043d\u0430\u043d\u043e!</b>\n\n\u0414\u044f\u043a\u0443\u0454\u043c\u043e \u0437\u0430 \u043f\u043e\u043a\u0443\u043f\u043a\u0443 \u0432 <b>Teddy Stars</b>! \U0001F4AB",
         "\u2705 <b>\u0417\u0430\u043a\u0430\u0437 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d!</b>\n\n\u0421\u043f\u0430\u0441\u0438\u0431\u043e \u0437\u0430 \u043f\u043e\u043a\u0443\u043f\u043a\u0443 \u0432 <b>Teddy Stars</b>! \U0001F4AB",
         "\u2705 <b>Order completed!</b>\n\nThanks for your purchase at <b>Teddy Stars</b>! \U0001F4AB"),
        ("support_reply",
         "\U0001F4AC <b>\u0412\u0456\u0434\u043f\u043e\u0432\u0456\u0434\u044c \u0432\u0456\u0434 \u043f\u0456\u0434\u0442\u0440\u0438\u043c\u043a\u0438 Teddy Stars</b>\n\n{text}",
         "\U0001F4AC <b>\u041e\u0442\u0432\u0435\u0442 \u043e\u0442 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0438 Teddy Stars</b>\n\n{text}",
         "\U0001F4AC <b>Reply from Teddy Stars support</b>\n\n{text}"),
        ("stars_choose_amount",
         "\u2b50 \u041e\u0431\u0435\u0440\u0456\u0442\u044c \u043a\u0456\u043b\u044c\u043a\u0456\u0441\u0442\u044c \u0437\u0456\u0440\u043e\u043a \u0434\u043b\u044f <b>{username}</b>",
         "\u2b50 \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e \u0437\u0432\u0451\u0437\u0434 \u0434\u043b\u044f <b>{username}</b>",
         "\u2b50 Choose the amount of Stars for <b>{username}</b>"),
        ("order_done_review",
         "\u2705 <b>\u0417\u0430\u043c\u043e\u0432\u043b\u0435\u043d\u043d\u044f \u0432\u0438\u043a\u043e\u043d\u0430\u043d\u043e!</b>\n\n"
         "{order_details}\n\n"
         "\U0001F499 <b>\u0414\u044f\u043a\u0443\u0454\u043c\u043e \u0437\u0430 \u043f\u043e\u043a\u0443\u043f\u043a\u0443!</b>\n\n"
         "\U0001F381 <b>\u0417\u0430\u043b\u0438\u0448\u0442\u0435 \u0432\u0456\u0434\u0433\u0443\u043a \u0456 \u043e\u0442\u0440\u0438\u043c\u0430\u0439\u0442\u0435 1-2 Stars \u043d\u0430 \u0431\u0430\u043b\u0430\u043d\u0441 \u0431\u0435\u0437\u043a\u043e\u0448\u0442\u043e\u0432\u043d\u043e!</b>\n\n"
         "\U0001F4F8 <b>\u0421\u043f\u043e\u0447\u0430\u0442\u043a\u0443 \u043f\u0440\u0438\u043a\u0440\u0456\u043f\u0456\u0442\u044c \u0444\u043e\u0442\u043e \u0430\u0431\u043e \u0441\u043a\u0440\u0456\u043d\u0448\u043e\u0442 \u043f\u043e\u043a\u0443\u043f\u043a\u0438.</b>\n"
         "<i>(\u0446\u0435 \u043e\u0431\u043e\u0432'\u044f\u0437\u043a\u043e\u0432\u043e \u2014 \u0431\u0435\u0437 \u0444\u043e\u0442\u043e \u0432\u0456\u0434\u0433\u0443\u043a \u043d\u0435 \u0431\u0443\u0434\u0435 \u043f\u0440\u0438\u0439\u043d\u044f\u0442\u043e)</i>\n\n"
         "<blockquote>\u0426\u0435 \u0434\u0443\u0436\u0435 \u0432\u0430\u0436\u043b\u0438\u0432\u043e \u0434\u043b\u044f \u043d\u0430\u0441 \U0001F642</blockquote>\n\n"
         "<i>\u041d\u0430\u0442\u0438\u0441\u043d\u0456\u0442\u044c \u00ab\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u0438\u00bb \u044f\u043a\u0449\u043e \u043d\u0435 \u0445\u043e\u0447\u0435\u0442\u0435 \u0437\u0430\u043b\u0438\u0448\u0430\u0442\u0438 \u0432\u0456\u0434\u0433\u0443\u043a.</i>",
         "\u2705 <b>\u0417\u0430\u043a\u0430\u0437 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d!</b>\n\n"
         "{order_details}\n\n"
         "\U0001F499 <b>\u0421\u043f\u0430\u0441\u0438\u0431\u043e \u0437\u0430 \u043f\u043e\u043a\u0443\u043f\u043a\u0443!</b>\n\n"
         "\U0001F381 <b>\u041e\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u043e\u0442\u0437\u044b\u0432 \u0438 \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u0435 1-2 Stars \u043d\u0430 \u0431\u0430\u043b\u0430\u043d\u0441 \u0431\u0435\u0441\u043f\u043b\u0430\u0442\u043d\u043e!</b>\n\n"
         "\U0001F4F8 <b>\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043f\u0440\u0438\u043a\u0440\u0435\u043f\u0438\u0442\u0435 \u0444\u043e\u0442\u043e \u0438\u043b\u0438 \u0441\u043a\u0440\u0438\u043d\u0448\u043e\u0442 \u043f\u043e\u043a\u0443\u043f\u043a\u0438.</b>\n"
         "<i>(\u044d\u0442\u043e \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u043e \u2014 \u0431\u0435\u0437 \u0444\u043e\u0442\u043e \u043e\u0442\u0437\u044b\u0432 \u043d\u0435 \u0431\u0443\u0434\u0435\u0442 \u043f\u0440\u0438\u043d\u044f\u0442)</i>\n\n"
         "<blockquote>\u042d\u0442\u043e \u043e\u0447\u0435\u043d\u044c \u0432\u0430\u0436\u043d\u043e \u0434\u043b\u044f \u043d\u0430\u0441 \U0001F642</blockquote>\n\n"
         "<i>\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u00ab\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c\u00bb \u0435\u0441\u043b\u0438 \u043d\u0435 \u0445\u043e\u0442\u0438\u0442\u0435 \u043e\u0441\u0442\u0430\u0432\u043b\u044f\u0442\u044c \u043e\u0442\u0437\u044b\u0432.</i>",
         "\u2705 <b>Order completed!</b>\n\n"
         "{order_details}\n\n"
         "\U0001F499 <b>Thanks for your purchase!</b>\n\n"
         "\U0001F381 <b>Leave a review and get 1-2 Stars added to your balance for free!</b>\n\n"
         "\U0001F4F8 <b>First attach a photo or screenshot of your purchase.</b>\n"
         "<i>(required \u2014 without a photo the review won't be accepted)</i>\n\n"
         "<blockquote>This really matters to us \U0001F642</blockquote>\n\n"
         "<i>Tap \u00abSkip\u00bb if you don't want to leave a review.</i>"),
        ("sell_stars_promo",
         "\U0001F4B0 <b>\u041f\u0440\u043e\u0434\u0430\u0436 Stars \u2014 \u0448\u0432\u0438\u0434\u043a\u043e \u0442\u0430 \u0432\u0438\u0433\u0456\u0434\u043d\u043e!</b>\n\n"
         "\U0001F4CA <b>\u041d\u0430\u0448 \u043a\u0443\u0440\u0441 \u0432\u0438\u043a\u0443\u043f\u0443:</b>\n"
         "<b>1\u2b50 = {rate} \u0433\u0440\u043d</b>\n"
         "<b>\u041c\u0456\u043d\u0456\u043c\u0443\u043c \u2014 {min} Stars</b>\n\n"
         "\U0001F525 <b>\u041f\u0440\u0438\u043a\u043b\u0430\u0434:</b>\n"
         "<b>1000\u2b50 = {example} \u0433\u0440\u043d \u043d\u0430 \u0442\u0432\u0456\u0439 \u0440\u0430\u0445\u0443\u043d\u043e\u043a!</b>\n\n"
         "\u26a1 <b>\u041e\u0431\u0440\u043e\u0431\u043a\u0430 \u0434\u043e 5 \u0445\u0432\u0438\u043b\u0438\u043d</b>\n\n"
         "\U0001F447 <b>\u041d\u0430\u043f\u0438\u0448\u0438 \u043d\u0430\u043c \u0456 \u043c\u0438 \u0432\u0441\u0435 \u043e\u0444\u043e\u0440\u043c\u0438\u043c\u043e:</b>",
         "\U0001F4B0 <b>\u041f\u0440\u043e\u0434\u0430\u0436\u0430 Stars \u2014 \u0431\u044b\u0441\u0442\u0440\u043e \u0438 \u0432\u044b\u0433\u043e\u0434\u043d\u043e!</b>\n\n"
         "\U0001F4CA <b>\u041d\u0430\u0448 \u043a\u0443\u0440\u0441 \u0432\u044b\u043a\u0443\u043f\u0430:</b>\n"
         "<b>1\u2b50 = {rate} \u0433\u0440\u043d</b>\n"
         "<b>\u041c\u0438\u043d\u0438\u043c\u0443\u043c \u2014 {min} Stars</b>\n\n"
         "\U0001F525 <b>\u041f\u0440\u0438\u043c\u0435\u0440:</b>\n"
         "<b>1000\u2b50 = {example} \u0433\u0440\u043d \u043d\u0430 \u0442\u0432\u043e\u0439 \u0441\u0447\u0451\u0442!</b>\n\n"
         "\u26a1 <b>\u041e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0430 \u0434\u043e 5 \u043c\u0438\u043d\u0443\u0442</b>\n\n"
         "\U0001F447 <b>\u041d\u0430\u043f\u0438\u0448\u0438 \u043d\u0430\u043c, \u0438 \u043c\u044b \u0432\u0441\u0451 \u043e\u0444\u043e\u0440\u043c\u0438\u043c:</b>",
         "\U0001F4B0 <b>Sell Stars \u2014 fast and profitable!</b>\n\n"
         "\U0001F4CA <b>Our buyback rate:</b>\n"
         "<b>1\u2b50 = {rate} UAH</b>\n"
         "<b>Minimum \u2014 {min} Stars</b>\n\n"
         "\U0001F525 <b>Example:</b>\n"
         "<b>1000\u2b50 = {example} UAH to your account!</b>\n\n"
         "\u26a1 <b>Processing up to 5 minutes</b>\n\n"
         "\U0001F447 <b>Message us and we'll set it all up:</b>"),
        ("withdraw_paid_review",
         "\u2705 <b>\u0412\u0438\u0432\u0456\u0434 #{wid} \u0432\u0438\u043f\u043b\u0430\u0447\u0435\u043d\u043e!</b>\n\n"
         "\u2b50 \u0421\u0443\u043c\u0430: <b>{amount} Stars</b>\n\n"
         "\U0001F381 <b>\u0417\u0430\u043b\u0438\u0448\u0442\u0435 \u0432\u0456\u0434\u0433\u0443\u043a \u0456 \u043e\u0442\u0440\u0438\u043c\u0430\u0439\u0442\u0435 1-2 Stars \u043d\u0430 \u0431\u0430\u043b\u0430\u043d\u0441 \u0431\u0435\u0437\u043a\u043e\u0448\u0442\u043e\u0432\u043d\u043e!</b>\n\n"
         "\U0001F4F8 <b>\u0421\u043f\u043e\u0447\u0430\u0442\u043a\u0443 \u043f\u0440\u0438\u043a\u0440\u0456\u043f\u0456\u0442\u044c \u0444\u043e\u0442\u043e \u0430\u0431\u043e \u0441\u043a\u0440\u0456\u043d\u0448\u043e\u0442 \u043f\u043e\u043a\u0443\u043f\u043a\u0438.</b>\n"
         "<i>(\u0446\u0435 \u043e\u0431\u043e\u0432'\u044f\u0437\u043a\u043e\u0432\u043e \u2014 \u0431\u0435\u0437 \u0444\u043e\u0442\u043e \u0432\u0456\u0434\u0433\u0443\u043a \u043d\u0435 \u0431\u0443\u0434\u0435 \u043f\u0440\u0438\u0439\u043d\u044f\u0442\u043e)</i>\n\n"
         "<blockquote>\u0426\u0435 \u0434\u0443\u0436\u0435 \u0432\u0430\u0436\u043b\u0438\u0432\u043e \u0434\u043b\u044f \u043d\u0430\u0441 \U0001F642</blockquote>\n\n"
         "<i>\u041d\u0430\u0442\u0438\u0441\u043d\u0456\u0442\u044c \u00ab\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u0438\u00bb \u044f\u043a\u0449\u043e \u043d\u0435 \u0445\u043e\u0447\u0435\u0442\u0435 \u0437\u0430\u043b\u0438\u0448\u0430\u0442\u0438 \u0432\u0456\u0434\u0433\u0443\u043a.</i>",
         "\u2705 <b>\u0412\u044b\u0432\u043e\u0434 #{wid} \u0432\u044b\u043f\u043b\u0430\u0447\u0435\u043d!</b>\n\n"
         "\u2b50 \u0421\u0443\u043c\u043c\u0430: <b>{amount} Stars</b>\n\n"
         "\U0001F381 <b>\u041e\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u043e\u0442\u0437\u044b\u0432 \u0438 \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u0435 1-2 Stars \u043d\u0430 \u0431\u0430\u043b\u0430\u043d\u0441 \u0431\u0435\u0441\u043f\u043b\u0430\u0442\u043d\u043e!</b>\n\n"
         "\U0001F4F8 <b>\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043f\u0440\u0438\u043a\u0440\u0435\u043f\u0438\u0442\u0435 \u0444\u043e\u0442\u043e \u0438\u043b\u0438 \u0441\u043a\u0440\u0438\u043d\u0448\u043e\u0442 \u043f\u043e\u043a\u0443\u043f\u043a\u0438.</b>\n"
         "<i>(\u044d\u0442\u043e \u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u043e \u2014 \u0431\u0435\u0437 \u0444\u043e\u0442\u043e \u043e\u0442\u0437\u044b\u0432 \u043d\u0435 \u0431\u0443\u0434\u0435\u0442 \u043f\u0440\u0438\u043d\u044f\u0442)</i>\n\n"
         "<blockquote>\u042d\u0442\u043e \u043e\u0447\u0435\u043d\u044c \u0432\u0430\u0436\u043d\u043e \u0434\u043b\u044f \u043d\u0430\u0441 \U0001F642</blockquote>\n\n"
         "<i>\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u00ab\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c\u00bb \u0435\u0441\u043b\u0438 \u043d\u0435 \u0445\u043e\u0442\u0438\u0442\u0435 \u043e\u0441\u0442\u0430\u0432\u043b\u044f\u0442\u044c \u043e\u0442\u0437\u044b\u0432.</i>",
         "\u2705 <b>Withdrawal #{wid} paid out!</b>\n\n"
         "\u2b50 Amount: <b>{amount} Stars</b>\n\n"
         "\U0001F381 <b>Leave a review and get 1-2 Stars added to your balance for free!</b>\n\n"
         "\U0001F4F8 <b>First attach a photo or screenshot of your purchase.</b>\n"
         "<i>(required \u2014 without a photo the review won't be accepted)</i>\n\n"
         "<blockquote>This really matters to us \U0001F642</blockquote>\n\n"
         "<i>Tap \u00abSkip\u00bb if you don't want to leave a review.</i>"),
    ]
    for bt in bot_texts:
        c.execute("INSERT OR IGNORE INTO bot_texts (key,value_ru,value_uk,value_en) VALUES (?,?,?,?)",
                  (bt[0], bt[1], bt[2], bt[3]))
        # Для баз, створених ще до появи англійської — донатягуємо value_en,
        # якщо він порожній (і не чіпаємо, якщо адмін вже щось туди вписав).
        c.execute("UPDATE bot_texts SET value_en=? WHERE key=? AND (value_en IS NULL OR value_en='')",
                  (bt[3], bt[0]))


    # Міграція: раніше посилання в тексті "referral_info" було в <code>...</code>,
    # через що воно не було клікабельним. Чіпаємо лише той старий варіант,
    # щоб не затерти текст, який адмін вже міг відредагувати вручну.
    c.execute("SELECT value_uk, value_ru FROM bot_texts WHERE key='referral_info'")
    row = c.fetchone()
    if row:
        old_uk, old_ru = row["value_uk"], row["value_ru"]
        if old_uk and "<code>{ref_link}</code>" in old_uk:
            new_uk = old_uk.replace("<code>{ref_link}</code>", "<a href=\"{ref_link}\">{ref_link}</a>")
            c.execute("UPDATE bot_texts SET value_uk=? WHERE key='referral_info'", (new_uk,))
        if old_ru and "<code>{ref_link}</code>" in old_ru:
            new_ru = old_ru.replace("<code>{ref_link}</code>", "<a href=\"{ref_link}\">{ref_link}</a>")
            c.execute("UPDATE bot_texts SET value_ru=? WHERE key='referral_info'", (new_ru,))

    for col in [("style","'default'"),("custom_emoji_id","''"),("text_uk","''"),("text_ru","''")]:
        try: c.execute(f"ALTER TABLE menu_buttons ADD COLUMN {col[0]} TEXT DEFAULT {col[1]}")
        except: pass

    try: c.execute("ALTER TABLE payment_methods ADD COLUMN owner TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE payment_methods ADD COLUMN custom_emoji_id TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE reviews ADD COLUMN order_type TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE reviews ADD COLUMN amount REAL DEFAULT 0")
    except: pass

    for col in [("stars_balance","0"),("ref_by","0"),("ref_count","0"),("ref_earned","0"),
                ("banned","0"),("ban_reason","''")]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col[0]} INTEGER DEFAULT {col[1]}")
        except: pass

    c.execute("UPDATE menu_buttons SET emoji='' WHERE custom_emoji_id != '' AND custom_emoji_id IS NOT NULL")
    conn.commit(); conn.close()

# ========================================================
# DB HELPERS
# ========================================================

def get_setting(key):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = c.fetchone(); conn.close()
    return row["value"] if row else None

def set_setting(key, value):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))
    conn.commit(); conn.close()

def safe_html(text: str) -> str:
    """Делает HTML безопасным для Telegram parse_mode=HTML:
    - убирает лишние/непарные закрывающие теги (когда </b> идёт без открывающего <b>)
    - убирает незакрытые открывающие теги, если для них нет соответствующего закрывающего
    - удаляет любые теги, не входящие в список разрешённых Telegram'ом
    """
    import re
    if not text:
        return text
    allowed = {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del',
               'code', 'pre', 'tg-spoiler', 'blockquote', 'a', 'span', 'tg-emoji'}

    def strip_unknown(match):
        tag_name = match.group(2).lower()
        return match.group(0) if tag_name in allowed else ''
    text = re.sub(r'<(/?)([a-zA-Z0-9-]+)[^>]*>', strip_unknown, text)

    token_re = re.compile(r'<(/?)([a-zA-Z0-9-]+)[^>]*>')
    stack = []
    out = []
    pos = 0
    for m in token_re.finditer(text):
        out.append(text[pos:m.start()])
        pos = m.end()
        is_close, tag = m.group(1), m.group(2).lower()
        if not is_close:
            stack.append(tag)
            out.append(m.group(0))
        else:
            if tag in stack:
                while stack and stack[-1] != tag:
                    out.append(f'</{stack.pop()}>')
                if stack:
                    stack.pop()
                    out.append(m.group(0))
    out.append(text[pos:])
    text = ''.join(out)

    while stack:
        text += f'</{stack.pop()}>'
    return text

def get_bot_text(key, lang="uk"):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM bot_texts WHERE key=?", (key,))
    row = c.fetchone(); conn.close()
    if not row: return ""
    col = {"ru": "value_ru", "en": "value_en", "uk": "value_uk"}.get(lang, "value_uk")
    val = row[col] if row[col] else ((row["value_uk"] if row["value_uk"] else row["value_ru"]) or "")
    return safe_html(val)

def set_bot_text(key, value_ru=None, value_uk=None, value_en=None):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO bot_texts (key,value_ru,value_uk,value_en) VALUES (?,?,?,?)", (key, "", "", ""))
    if value_ru:
        c.execute("UPDATE bot_texts SET value_ru=? WHERE key=?", (value_ru, key))
    if value_uk:
        c.execute("UPDATE bot_texts SET value_uk=? WHERE key=?", (value_uk, key))
    if value_en:
        c.execute("UPDATE bot_texts SET value_en=? WHERE key=?", (value_en, key))
    conn.commit(); conn.close()

def get_payment_methods():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM payment_methods WHERE enabled=1 ORDER BY position")
    rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]

def get_all_payment_methods():
    """Всі способи оплати, включно з вимкненими — для списку в адмінці (щоб можна було увімкнути назад)."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM payment_methods ORDER BY position")
    rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]

def update_payment_method(key, field, value):
    conn = get_conn(); c = conn.cursor()
    c.execute(f"UPDATE payment_methods SET {field}=? WHERE method_key=?", (value, key))
    conn.commit(); conn.close()

def get_stars_packages(enabled_only=True) -> list:
    """Топ-рівень паків (без дочірніх кнопок групи)."""
    conn = get_conn(); c = conn.cursor()
    if enabled_only:
        c.execute("SELECT * FROM stars_packages WHERE enabled=1 AND parent_key IS NULL ORDER BY position")
    else:
        c.execute("SELECT * FROM stars_packages WHERE parent_key IS NULL ORDER BY position")
    rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]

def get_stars_package_children(parent_key, enabled_only=True) -> list:
    conn = get_conn(); c = conn.cursor()
    if enabled_only:
        c.execute("SELECT * FROM stars_packages WHERE enabled=1 AND parent_key=? ORDER BY position", (str(parent_key),))
    else:
        c.execute("SELECT * FROM stars_packages WHERE parent_key=? ORDER BY position", (str(parent_key),))
    rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]

def get_stars_package(key) -> dict:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM stars_packages WHERE item_key=?", (str(key),))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def set_stars_package_field(key, field, value) -> None:
    conn = get_conn(); c = conn.cursor()
    c.execute(f"UPDATE stars_packages SET {field}=? WHERE item_key=?", (value, str(key)))
    conn.commit(); conn.close()

def add_stars_package(kind="fixed", amount=None, range_min=None, range_max=None,
                       emoji="⭐", custom_emoji_id="", label="", parent_key=None) -> str:
    conn = get_conn(); c = conn.cursor()
    scope = "parent_key=?" if parent_key else "parent_key IS NULL"
    params = (parent_key,) if parent_key else ()
    c.execute(f"SELECT COALESCE(MAX(position),0)+1 as p FROM stars_packages WHERE {scope}", params)
    pos = c.fetchone()["p"]
    # Унікальний ключ: беремо найбільший номер серед усіх item_key вигляду "p<число>"
    # (ігноруючи дочірні ключі на кшталт "p8a") і додаємо 1.
    c.execute("SELECT item_key FROM stars_packages")
    max_n = 0
    for r in c.fetchall():
        m = r["item_key"]
        if m.startswith("p") and m[1:].isdigit():
            max_n = max(max_n, int(m[1:]))
    key = f"p{max_n + 1}"
    c.execute("""INSERT INTO stars_packages
        (item_key,kind,amount,range_min,range_max,emoji,custom_emoji_id,label,position,enabled,parent_key)
        VALUES (?,?,?,?,?,?,?,?,?,1,?)""",
        (key, kind, amount, range_min, range_max, emoji, custom_emoji_id, label, pos, parent_key))
    conn.commit(); conn.close()
    return key

def delete_stars_package(key) -> None:
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM stars_packages WHERE item_key=? OR parent_key=?", (str(key), str(key)))
    conn.commit(); conn.close()

def get_gift_items() -> dict:
    """Повертає {item_key: {emoji, name, price, enabled, quantity, telegram_gift_id, sticker_id, position}}."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM gift_items ORDER BY position")
    rows = c.fetchall(); conn.close()
    return {r["item_key"]: dict(r) for r in rows}

def get_gift_item(key) -> dict:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM gift_items WHERE item_key=?", (str(key),))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def set_gift_field(key, field, value) -> None:
    conn = get_conn(); c = conn.cursor()
    c.execute(f"UPDATE gift_items SET {field}=? WHERE item_key=?", (value, str(key)))
    conn.commit(); conn.close()

def add_gift_item(emoji="🎁", name="", price=55.0) -> str:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(position),0)+1 as p FROM gift_items")
    pos = c.fetchone()["p"]
    c.execute("SELECT item_key FROM gift_items")
    max_n = 0
    for r in c.fetchall():
        if r["item_key"].isdigit():
            max_n = max(max_n, int(r["item_key"]))
    key = str(max_n + 1)
    c.execute("""INSERT INTO gift_items (item_key,emoji,name,price,enabled,position)
        VALUES (?,?,?,?,1,?)""", (key, emoji, name, price, pos))
    conn.commit(); conn.close()
    return key

def delete_gift_item(key) -> None:
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM gift_items WHERE item_key=?", (str(key),))
    conn.commit(); conn.close()

def decrement_gift_quantity(key) -> None:
    item = get_gift_item(key)
    if item and item.get("quantity") is not None:
        new_qty = max(0, int(item["quantity"]) - 1)
        set_gift_field(key, "quantity", new_qty)

def get_gift_api_creds() -> dict:
    """Telethon api_id/api_hash акаунта, з якого йде автовидача подарунків."""
    return {
        "api_id": int(get_setting("gift_api_id") or 0),
        "api_hash": get_setting("gift_api_hash") or ""
    }

def set_gift_api_creds(api_id: int, api_hash: str) -> None:
    set_setting("gift_api_id", api_id)
    set_setting("gift_api_hash", api_hash)

# ========================================================
# TELETHON: АВТОВИДАЧА ПОДАРУНКІВ
# ========================================================
# Один живий TelegramClient перевикористовується для всіх відправок —
# щоб не робити повне підключення (connect) на кожне замовлення.
# Бот вже працює на власному asyncio event loop (aiogram), тому окремий
# фоновий потік з власним loop тут не потрібен, на відміну від synchronous-бота.

_gift_client = None
_gift_client_lock = None

def _get_gift_client_lock() -> asyncio.Lock:
    global _gift_client_lock
    if _gift_client_lock is None:
        _gift_client_lock = asyncio.Lock()
    return _gift_client_lock

async def _get_connected_gift_client(api_id: int, api_hash: str):
    """Повертає вже підключений клієнт, перевикористовуючи попередній, якщо він живий."""
    global _gift_client
    async with _get_gift_client_lock():
        if _gift_client is None:
            _gift_client = GiftTelegramClient(GIFT_SESSION_NAME, api_id, api_hash)
        if not _gift_client.is_connected():
            await _gift_client.connect()
        return _gift_client

async def reset_gift_client() -> None:
    """Розриває поточне з'єднання (напр. перед інтерактивним логіном, щоб уникнути
    конфлікту доступу до файлу сесії)."""
    global _gift_client
    if _gift_client is not None:
        try:
            await _gift_client.disconnect()
        except Exception:
            pass
        _gift_client = None

async def gift_login_send_code(api_id: int, api_hash: str, phone: str) -> dict:
    """Крок 1 логіну: запитує код підтвердження.
    Повертає {"ok": True, "phone_code_hash": str} або {"ok": False, "error": str}."""
    if not GIFT_TELETHON_AVAILABLE:
        return {"ok": False, "error": "Пакет telethon не встановлено на сервері"}
    await reset_gift_client()
    client = GiftTelegramClient(GIFT_SESSION_NAME, api_id, api_hash)
    await client.connect()
    try:
        result = await client(SendCodeRequest(
            phone_number=phone,
            api_id=api_id,
            api_hash=api_hash,
            settings=CodeSettings(allow_flashcall=False, current_number=False, allow_app_hash=False)
        ))
        return {"ok": True, "phone_code_hash": result.phone_code_hash}
    except telethon_errors.FloodWaitError as e:
        return {"ok": False, "error": f"Забагато спроб, зачекайте {e.seconds} сек"}
    except telethon_errors.RPCError as e:
        return {"ok": False, "error": f"Telegram RPC помилка: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await client.disconnect()

async def gift_login_sign_in(api_id: int, api_hash: str, phone: str, phone_code_hash: str, code: str) -> dict:
    """Крок 2 логіну: вхід за кодом.
    Повертає {"ok": True} / {"ok": False, "need_password": True} / {"ok": False, "error": str}."""
    if not GIFT_TELETHON_AVAILABLE:
        return {"ok": False, "error": "Пакет telethon не встановлено на сервері"}
    client = GiftTelegramClient(GIFT_SESSION_NAME, api_id, api_hash)
    await client.connect()
    try:
        await client(SignInRequest(phone_number=phone, phone_code_hash=phone_code_hash, phone_code=code))
        return {"ok": True}
    except telethon_errors.SessionPasswordNeededError:
        return {"ok": False, "need_password": True}
    except telethon_errors.RPCError as e:
        return {"ok": False, "error": f"Telegram RPC помилка: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await client.disconnect()

async def gift_login_check_password(api_id: int, api_hash: str, password: str) -> dict:
    """Крок 3 логіну (за потреби): 2FA пароль."""
    if not GIFT_TELETHON_AVAILABLE:
        return {"ok": False, "error": "Пакет telethon не встановлено на сервері"}
    client = GiftTelegramClient(GIFT_SESSION_NAME, api_id, api_hash)
    await client.connect()
    try:
        pwd = await client(GetPasswordRequest())
        await client(CheckPasswordRequest(password=gift_compute_check(pwd, password)))
        return {"ok": True}
    except telethon_errors.RPCError as e:
        return {"ok": False, "error": f"Telegram RPC помилка: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await client.disconnect()

async def send_star_gift(gift_id: int, recipient: str, message_text: str = "", hide_name: bool = True) -> dict:
    """Надсилає подарунок через Telegram Gift API з попередньо авторизованого
    акаунта (сесія GIFT_SESSION_NAME). Перевикористовує вже підключений клієнт.
    hide_name=True приховує від отримувача, хто саме надіслав подарунок (анонімна відправка).
    Повертає {"ok": True, "recipient_id": int, "tx_id": str} або {"ok": False, "error": str}."""
    if not GIFT_TELETHON_AVAILABLE:
        return {"ok": False, "error": "Пакет telethon не встановлено на сервері"}
    creds = get_gift_api_creds()
    if not creds.get("api_id") or not creds.get("api_hash"):
        return {"ok": False, "error": "Telethon api_id/api_hash не налаштовані в адмін-панелі"}

    try:
        client = await _get_connected_gift_client(int(creds["api_id"]), creds["api_hash"])
    except Exception as e:
        return {"ok": False, "error": f"Не вдалося підключитись до Telethon: {e}"}

    if not await client.is_user_authorized():
        return {"ok": False, "error": "Telethon-сесія не авторизована. Увійдіть в акаунт через адмін-панель («📱 Увійти в акаунт»)."}

    target = (recipient or "").strip()
    try:
        if target.upper().startswith("ID:"):
            user = await client.get_entity(int(target[3:]))
        elif target.lstrip("@").isdigit():
            user = await client.get_entity(int(target.lstrip("@")))
        else:
            user = await client.get_entity(target.lstrip("@"))
    except Exception as e:
        return {"ok": False, "error": f"Отримувач '{recipient}' не знайдений: {e}"}

    msg = TextWithEntities(text=message_text, entities=[]) if message_text else None
    try:
        input_peer = await client.get_input_entity(user)
        invoice = InputInvoiceStarGift(peer=input_peer, gift_id=gift_id, message=msg, hide_name=hide_name)
        form = await client(GetPaymentFormRequest(invoice=invoice))
        await client(SendStarsFormRequest(form_id=form.form_id, invoice=invoice))
        return {"ok": True, "recipient_id": user.id, "tx_id": str(form.form_id)}
    except telethon_errors.FloodWaitError as e:
        return {"ok": False, "error": f"Зачекайте {e.seconds} сек і спробуйте знову"}
    except telethon_errors.RPCError as e:
        return {"ok": False, "error": f"Telegram RPC помилка: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def fetch_real_gift_catalog() -> dict:
    """Отримує СПРАВЖНІЙ каталог подарунків Telegram напряму через Telethon-акаунт
    (без жодних припущень) — реальні ID, ціну в Stars і емодзі кожного подарунка.
    Повертає {"ok": True, "gifts": [{"id":.., "stars":.., "emoji":..}, ...]} або {"ok": False, "error": str}."""
    if not GIFT_TELETHON_AVAILABLE:
        return {"ok": False, "error": "Пакет telethon не встановлено на сервері"}
    creds = get_gift_api_creds()
    if not creds.get("api_id") or not creds.get("api_hash"):
        return {"ok": False, "error": "Telethon api_id/api_hash не налаштовані в адмін-панелі"}
    try:
        client = await _get_connected_gift_client(int(creds["api_id"]), creds["api_hash"])
    except Exception as e:
        return {"ok": False, "error": f"Не вдалося підключитись до Telethon: {e}"}
    if not await client.is_user_authorized():
        return {"ok": False, "error": "Telethon-сесія не авторизована. Увійдіть в акаунт через адмін-панель («📱 Увійти в акаунт»)."}

    try:
        result = await client(GetStarGiftsRequest(hash=0))
    except telethon_errors.RPCError as e:
        return {"ok": False, "error": f"Telegram RPC помилка: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    gifts = []
    for g in getattr(result, "gifts", []):
        # У не-унікальних подарунків (StarGift) поле .id — це і є той самий gift_id,
        # який використовується для відправки (InputInvoiceStarGift.gift_id).
        gid = getattr(g, "id", None)
        stars = getattr(g, "stars", None)
        if gid is None or stars is None:
            continue
        emoji = "🎁"
        sticker = getattr(g, "sticker", None)
        for attr in getattr(sticker, "attributes", []) or []:
            alt = getattr(attr, "alt", None)
            if alt:
                emoji = alt
                break
        limited = bool(getattr(g, "limited_per_user", False) or getattr(g, "availability_total", None))
        gifts.append({"id": gid, "stars": stars, "emoji": emoji, "limited": limited})
    gifts.sort(key=lambda x: x["stars"])
    return {"ok": True, "gifts": gifts}

async def auto_fulfill_gift_order(order_uid: str) -> dict:
    """Автоматична видача подарунка через Telegram Gift API (Telethon).
    Оновлює статус замовлення у БД відповідно до результату."""
    order = get_gift_order(order_uid)
    if not order:
        return {"ok": False, "error": "Замовлення не знайдено"}
    item = get_gift_item(order["item_key"]) or {}
    gift_tg_id = item.get("telegram_gift_id")
    if not gift_tg_id:
        err = f"Для позиції «{order.get('gift_name')}» не вказано Telegram Gift ID"
        update_gift_order(order_uid, fulfill_error=err)
        return {"ok": False, "error": err}

    result = await send_star_gift(int(gift_tg_id), order["target_username"], order.get("comment") or "", hide_name=True)
    if result.get("ok"):
        update_gift_order(order_uid, status="completed", fulfill_error="")
    else:
        update_gift_order(order_uid, fulfill_error=result.get("error", "Невідома помилка"))
    return result

def create_gift_order(order_uid: str, user_id: int, item: dict, target_username: str) -> None:
    conn = get_conn(); c = conn.cursor()
    c.execute("""INSERT INTO gift_orders
        (order_uid,user_id,item_key,gift_name,gift_emoji,gift_sticker,price,target_username,status)
        VALUES (?,?,?,?,?,?,?,?,'pending_payment')""",
        (order_uid, user_id, item["item_key"], item["name"], item["emoji"],
         item.get("sticker_id",""), item["price"], target_username))
    conn.commit(); conn.close()

def get_gift_order(order_uid: str) -> dict:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM gift_orders WHERE order_uid=?", (order_uid,))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def update_gift_order(order_uid: str, **kwargs) -> None:
    if not kwargs: return
    conn = get_conn(); c = conn.cursor()
    for key, val in kwargs.items():
        c.execute(f"UPDATE gift_orders SET {key}=? WHERE order_uid=?", (val, order_uid))
    conn.commit(); conn.close()

def register_user(uid, username, full_name, ref_by=0):
    """Реєструє користувача. Повертає True якщо це новий користувач."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    exists = c.fetchone()
    if not exists:
        c.execute("""INSERT INTO users (user_id,username,full_name,language,ref_by)
                     VALUES (?,?,?,?,?)""", (uid, username or "Без ніка", full_name, "uk", ref_by))
        conn.commit()
        conn.close()
        return True  # новий користувач
    conn.close()
    return False  # вже був

def get_user(uid):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def update_user(uid, **kwargs):
    conn = get_conn(); c = conn.cursor()
    for key, val in kwargs.items():
        c.execute(f"UPDATE users SET {key}=? WHERE user_id=?", (val, uid))
    conn.commit(); conn.close()

def update_user_active(uid, username=None, full_name=None):
    conn = get_conn(); c = conn.cursor()
    if username:
        c.execute("UPDATE users SET last_active=datetime('now'), username=?, full_name=? WHERE user_id=?",
                  (username, full_name or "", uid))
    else:
        c.execute("UPDATE users SET last_active=datetime('now') WHERE user_id=?", (uid,))
    conn.commit(); conn.close()

def add_stars_balance(uid, amount):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET stars_balance=stars_balance+? WHERE user_id=?", (amount, uid))
    conn.commit(); conn.close()


def get_lang(uid):
    return "uk"

def set_lang(uid, lang):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET language=? WHERE user_id=?", (lang, uid))
    conn.commit(); conn.close()

def is_banned(uid):
    u = get_user(uid)
    return u and u.get("banned", 0) == 1

def create_order(uid, otype, amount, price, recipient="", wallet="", bank="", package_key=None):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO orders (user_id,order_type,amount,price_uah,recipient,wallet,bank,package_key) VALUES (?,?,?,?,?,?,?,?)",
              (uid, otype, amount, price, recipient, wallet, bank, package_key))
    oid = c.lastrowid; conn.commit(); conn.close()
    return oid

def set_order_cryptobot_invoice(oid, invoice_id):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE orders SET cryptobot_invoice_id=? WHERE id=?", (invoice_id, oid))
    conn.commit(); conn.close()

def get_order(oid):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id=?", (oid,))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def update_order_status(oid, status):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
    conn.commit(); conn.close()

def update_user_stats(uid, otype, amount, price):
    conn = get_conn(); c = conn.cursor()
    if otype == "stars":
        c.execute("UPDATE users SET stars_bought=stars_bought+? WHERE user_id=?", (int(amount), uid))
    elif otype == "ton":
        c.execute("UPDATE users SET ton_bought=ton_bought+? WHERE user_id=?", (amount, uid))
    elif otype == "premium":
        c.execute("UPDATE users SET premium_bought=premium_bought+? WHERE user_id=?", (int(amount), uid))
    c.execute("UPDATE users SET total_spent=total_spent+? WHERE user_id=?", (price, uid))
    conn.commit(); conn.close()

def pay_referral_commission(buyer_uid, price_uah, order_type, amount):
    """Нараховує % від покупки тому, хто запросив покупця.
    Повертає (ref_uid, commission) або (None, 0), якщо нарахування не відбулось."""
    if get_setting("ref_enabled") != "1":
        logger.info(f"[REF] complete: SKIPPED — ref_enabled != '1'")
        return None, 0
    buyer = get_user(buyer_uid)
    if not buyer:
        logger.info(f"[REF] complete: SKIPPED — buyer {buyer_uid} не знайдено в БД")
        return None, 0
    ref_by = buyer.get("ref_by") or 0
    if not ref_by:
        logger.info(f"[REF] complete: SKIPPED — buyer {buyer_uid} не має ref_by (ref_by=0)")
        return None, 0
    ref_percent = int(get_setting("ref_percent_purchase") or 5)
    commission = round(float(price_uah) * ref_percent / 100)
    if commission <= 0:
        logger.info(f"[REF] complete: SKIPPED — commission <= 0 (price_uah={price_uah}, percent={ref_percent})")
        return None, 0
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET stars_balance=stars_balance+?, ref_earned=ref_earned+? WHERE user_id=?",
              (commission, commission, ref_by))
    conn.commit(); conn.close()
    logger.info(f"[REF] complete: OK — ref_by={ref_by} отримав {commission} Stars за покупку buyer={buyer_uid}")
    return ref_by, commission

def create_ticket(uid, msg, file_id="", file_type=""):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO support_tickets (user_id,message,file_id,file_type) VALUES (?,?,?,?)",
              (uid, msg, file_id, file_type))
    tid = c.lastrowid; conn.commit(); conn.close()
    return tid

def get_ticket(tid):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM support_tickets WHERE id=?", (tid,))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def get_all_users():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE banned=0")
    rows = c.fetchall(); conn.close()
    return [r["user_id"] for r in rows]

def get_stats():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT COUNT(*) as t FROM users"); total = c.fetchone()["t"]
    week_ago = (datetime.now()-timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("SELECT COUNT(*) as t FROM users WHERE last_active>=?", (week_ago,)); active = c.fetchone()["t"]
    c.execute("SELECT COALESCE(SUM(total_spent),0) as t FROM users"); sales = c.fetchone()["t"]
    c.execute("SELECT COUNT(*) as t FROM users WHERE banned=1"); banned = c.fetchone()["t"]
    c.execute("SELECT COUNT(*) as t FROM orders WHERE status='pending'"); pending = c.fetchone()["t"]
    conn.close()
    return total, active, round(sales, 2), banned, pending

def get_menu_buttons():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM menu_buttons ORDER BY position")
    rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]

def update_btn_text(key, text_ru, emoji, custom_emoji_id="", text_uk=""):
    conn = get_conn(); c = conn.cursor()
    if custom_emoji_id: emoji = ""
    c.execute("UPDATE menu_buttons SET text_ru=?,text_uk=?,emoji=?,custom_emoji_id=? WHERE button_key=?",
              (text_ru, text_uk, emoji, custom_emoji_id, key))
    conn.commit(); conn.close()

def update_btn_style(key, style):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE menu_buttons SET style=? WHERE button_key=?", (style, key))
    conn.commit(); conn.close()

def update_btn_order(order_list):
    conn = get_conn(); c = conn.cursor()
    for pos, key in enumerate(order_list, 1):
        c.execute("UPDATE menu_buttons SET position=? WHERE button_key=?", (pos, key))
    conn.commit(); conn.close()

def check_request_limit(uid):
    conn = get_conn(); c = conn.cursor()
    hour_ago = (datetime.now()-timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("SELECT COUNT(*) as t FROM request_log WHERE user_id=? AND created_at>=?", (uid, hour_ago))
    count = c.fetchone()["t"]
    max_orders = int(get_setting("max_orders_per_hour") or 5)
    conn.close()
    return count < max_orders

def log_request(uid):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO request_log (user_id,created_at) VALUES (?,datetime('now'))", (uid,))
    conn.commit(); conn.close()

def create_withdrawal(uid, amount, wallet):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO withdrawals (user_id,amount,wallet) VALUES (?,?,?)", (uid, amount, wallet))
    wid = c.lastrowid; conn.commit(); conn.close()
    return wid

def get_withdrawal(wid):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM withdrawals WHERE id=?", (wid,))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def mark_withdrawal_result(wid, status, auto_status, tx_id="", error_message=""):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE withdrawals SET status=?, auto_status=?, tx_id=?, error_message=? WHERE id=?",
              (status, auto_status, tx_id, error_message, wid))
    conn.commit(); conn.close()

# ========================================================
# АВТОВИВІД STARS / АВТОВИДАЧА PREMIUM / АВТОВІДПРАВКА TON — ЧЕРЕЗ FRAGMENT
# ========================================================

def _parse_fragment_cookies(raw: str) -> dict:
    """FRAGMENT_COOKIES зберігається у форматі Header String
    (stel_ssid=...; stel_dt=...; stel_token=...; stel_ton_token=...) —
    перетворюємо на dict, який очікує pyfragment."""
    cookies = {}
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        cookies[k.strip()] = v.strip()
    return cookies

async def fragment_send_stars(username: str, amount: int) -> dict:
    """Купує та надсилає Stars на username через Fragment.
    Повертає {"ok": True, "tx_id": ...} або {"ok": False, "error": ...}.
    Ніколи не кидає виняток назовні — весь фейл ловиться тут."""
    if not FRAGMENT_AVAILABLE:
        return {"ok": False, "error": "Пакет pyfragment не встановлено на сервері."}
    if not AUTO_WITHDRAW_ENABLED:
        return {"ok": False, "error": "Автовивід не налаштовано (немає TON_SEED / FRAGMENT_COOKIES / FRAGMENT_API_KEY)."}

    uname = username.lstrip("@").strip()
    try:
        cookies = _parse_fragment_cookies(FRAGMENT_COOKIES)
        async with FragmentClient(
            seed=TON_SEED,
            api_key=FRAGMENT_API_KEY,
            cookies=cookies,
            wallet_version=FRAGMENT_WALLET_VERSION,
        ) as client:
            result = await client.purchase_stars(uname, int(amount))
            return {"ok": True, "tx_id": getattr(result, "transaction_id", "")}
    except Exception as e:
        # Ловимо всі fragment_exceptions.* та будь-які інші помилки (мережа, парсинг тощо)
        logger.error(f"[fragment_send_stars] {uname} x{amount}: {e}")
        return {"ok": False, "error": str(e)}

async def fragment_send_premium(username: str, months: int) -> dict:
    """Купує та надсилає Telegram Premium на username через Fragment.
    Підтримуються 3, 6 або 12 місяців. Повертає {"ok": True, "tx_id": ...}
    або {"ok": False, "error": ...}; винятки назовні не кидає."""
    if not FRAGMENT_AVAILABLE:
        return {"ok": False, "error": "Пакет pyfragment не встановлено на сервері."}
    if not AUTO_PREMIUM_SEND_ENABLED:
        return {"ok": False, "error": "Автовидача Premium не налаштована (потрібні TON_SEED / FRAGMENT_COOKIES / FRAGMENT_API_KEY)."}

    uname = (username or "").strip()
    if not uname:
        return {"ok": False, "error": "Не вказано Telegram username одержувача."}
    if not uname.startswith("@") and not uname.startswith("https://t.me/"):
        uname = "@" + uname

    try:
        months = int(months)
    except Exception:
        return {"ok": False, "error": "Некоректний термін Premium."}
    if months not in (3, 6, 12):
        return {"ok": False, "error": "Fragment підтримує Premium лише на 3, 6 або 12 місяців."}

    try:
        cookies = _parse_fragment_cookies(FRAGMENT_COOKIES)
        async with FragmentClient(
            seed=TON_SEED,
            api_key=FRAGMENT_API_KEY,
            cookies=cookies,
            wallet_version=FRAGMENT_WALLET_VERSION,
        ) as client:
            result = await client.purchase_premium(uname, months=months)
            return {
                "ok": True,
                "tx_id": getattr(result, "transaction_id", ""),
                "username": getattr(result, "username", uname),
            }
    except Exception as e:
        logger.error(f"[fragment_send_premium] {uname} x{months}m: {e}")
        return {"ok": False, "error": str(e)}

async def auto_send_ton(destination_address: str, amount_ton: float) -> dict:
    """Пряма відправка TON з робочого гаманця (TON_SEED) на адресу клієнта.
    Використовується для замовлень типу 'ton' (купівля TON за гривні).
    Повертає {"ok": True} або {"ok": False, "error": ...}. Винятків не кидає."""
    if not TONUTILS_AVAILABLE:
        return {"ok": False, "error": "Пакет tonutils не встановлено на сервері."}
    if not AUTO_TON_SEND_ENABLED:
        return {"ok": False, "error": "Автовідправка TON не налаштована (немає TON_SEED / FRAGMENT_API_KEY)."}
    try:
        async with TonapiClient(network=NetworkGlobalID.MAINNET, api_key=FRAGMENT_API_KEY) as client:
            wallet, _pub, _priv, _mnemonic = WalletV5R1.from_mnemonic(client, TON_SEED)
            nano_amount = int(round(float(amount_ton) * 1_000_000_000))
            await wallet.transfer(destination=destination_address.strip(), amount=nano_amount)
        return {"ok": True}
    except Exception as e:
        logger.error(f"[auto_send_ton] {destination_address} x{amount_ton}: {e}")
        return {"ok": False, "error": str(e)}

async def cryptobot_create_invoice(asset: str, amount: float, description: str = "") -> dict:
    """Створює рахунок в @CryptoBot через Crypto Pay API.
    asset: "TON" або "USDT". Повертає {"ok": True, "invoice_id": ..., "pay_url": ...}
    або {"ok": False, "error": ...}. Винятків не кидає."""
    if not CRYPTOBOT_ENABLED:
        return {"ok": False, "error": "CryptoBot не налаштовано (немає CRYPTOBOT_API_TOKEN)"}
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN}
    payload = {
        "asset": asset,
        "amount": str(amount),
        "description": description[:1000] if description else "",
        "allow_comments": False,
        "allow_anonymous": False,
        "expires_in": 3600,  # рахунок дійсний 1 годину
    }
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{CRYPTOBOT_API_BASE}/createInvoice", json=payload, headers=headers) as resp:
                data = await resp.json()
        if not data.get("ok"):
            return {"ok": False, "error": data.get("error", {}).get("name", "Невідома помилка CryptoBot")}
        result = data["result"]
        pay_url = result.get("bot_invoice_url") or result.get("pay_url") or result.get("mini_app_invoice_url")
        return {"ok": True, "invoice_id": str(result["invoice_id"]), "pay_url": pay_url}
    except Exception as e:
        logger.error(f"[cryptobot_create_invoice] {asset} {amount}: {e}")
        return {"ok": False, "error": str(e)}

async def cryptobot_check_invoice(invoice_id: str) -> dict:
    """Перевіряє статус рахунку. Повертає {"ok": True, "status": "paid"/"active"/"expired"}
    або {"ok": False, "error": ...}."""
    if not CRYPTOBOT_ENABLED:
        return {"ok": False, "error": "CryptoBot не налаштовано"}
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{CRYPTOBOT_API_BASE}/getInvoices",
                                    params={"invoice_ids": invoice_id}, headers=headers) as resp:
                data = await resp.json()
        if not data.get("ok"):
            return {"ok": False, "error": data.get("error", {}).get("name", "Невідома помилка CryptoBot")}
        items = data["result"]["items"]
        if not items:
            return {"ok": False, "error": "Рахунок не знайдено"}
        return {"ok": True, "status": items[0]["status"]}
    except Exception as e:
        logger.error(f"[cryptobot_check_invoice] {invoice_id}: {e}")
        return {"ok": False, "error": str(e)}

async def cryptobot_confirm_paid_order(oid: int) -> bool:
    """Викликається після підтвердження оплати через CryptoBot (автоперевірка або ручна).
    Для Stars (включно з паком, прив'язаним до подарунка) — одразу finalize_order,
    все інше вже автоматизовано всередині неї.
    Для Premium і TON — НЕ фіналізує замовлення і НЕ намагається видати автоматично: просто
    підтверджує адміну, що оплата пройшла вірно, і чекає ручної видачі + підтвердження
    кнопкою (адмін сам видає Premium/TON і тисне «Підтвердити»)."""
    order = get_order(oid)
    if not order:
        return False
    if order["order_type"] not in ("premium", "ton"):
        return await finalize_order(oid)

    item_label = "Premium" if order["order_type"] == "premium" else "TON"
    action_label = "Видайте Premium вручну на Fragment" if order["order_type"] == "premium" else f"Відправте {order['amount']} TON на гаманець <code>{order['wallet']}</code>"
    try:
        await bot.send_message(ADMIN_CHAT_ID,
            f"✅ <b>ОПЛАЧЕНО ВІРНО</b> (замовлення #{oid} — {item_label}, через CryptoBot)\n\n"
            f"{action_label} і підтвердіть:",
            reply_markup=order_kb(oid, order["order_type"]), parse_mode="HTML")
    except Exception:
        pass
    return False

async def cryptobot_poll_and_finalize(oid: int, invoice_id: str, chat_id: int) -> None:
    """Фонова задача: перевіряє рахунок кожні 8 секунд до 30 хвилин.
    Щойно бачить статус "paid" — сама завершує замовлення (без участі адміна),
    окрім Premium без налаштованої автовидачі — там просто передає адміну на підтвердження."""
    max_checks = 225  # 225 * 8с ≈ 30 хвилин
    for _ in range(max_checks):
        await asyncio.sleep(8)
        order = get_order(oid)
        if not order or order.get("status") == "completed":
            return  # вже підтверджено вручну паралельно — нема сенсу продовжувати
        result = await cryptobot_check_invoice(invoice_id)
        if result.get("ok") and result.get("status") == "paid":
            await cryptobot_confirm_paid_order(oid)
            return
        if result.get("ok") and result.get("status") == "expired":
            try:
                await bot.send_message(chat_id, "⌛ <b>Час на оплату через CryptoBot вичерпано.</b> Оформіть замовлення заново.", parse_mode="HTML")
            except Exception:
                pass
            return
    # Час очікування (30 хв) вичерпано без оплати — тихо завершуємо фонову задачу,
    # замовлення лишається "pending", адмін може підтвердити вручну пізніше за потреби.

async def cryptobot_confirm_paid_gift_order(order_uid: str) -> bool:
    """Викликається після підтвердження оплати подарунка (🎁 Каталог подарунків) через
    CryptoBot. На відміну від Premium — тут ПОВНІСТЮ автоматично: списує залишок,
    намагається одразу видати подарунок (Telethon) і повідомляє покупця й адміна."""
    order = get_gift_order(order_uid)
    if not order or order.get("status") in ("completed", "approved"):
        return False
    update_gift_order(order_uid, status="approved", payment_method="cryptobot")
    decrement_gift_quantity(order["item_key"])
    try:
        await bot.send_message(order["user_id"],
            f"✅ <b>Оплату отримано!</b>\n\n🎁 Ваш подарунок для {order['target_username']} буде надіслано найближчим часом.",
            parse_mode="HTML")
    except Exception:
        pass
    try:
        await bot.send_message(ADMIN_CHAT_ID,
            f"🤖 <b>Оплату CryptoBot підтверджено — {order_uid}</b>\n🎁 {order['gift_emoji']} {order['gift_name']} → {order['target_username']}\n⏳ Виконую автовидачу...",
            parse_mode="HTML")
    except Exception:
        pass
    result = await auto_fulfill_gift_order(order_uid)
    if result.get("ok"):
        try:
            await bot.send_message(ADMIN_CHAT_ID, f"🎁✅ Подарунок за замовленням {order_uid} успішно надіслано автоматично!", parse_mode="HTML")
        except Exception:
            pass
        try:
            await bot.send_message(order["user_id"],
                f"🎉 <b>Подарунок надіслано!</b>\n\n🎁 Ваш подарунок для {order['target_username']} успішно доставлено.", parse_mode="HTML")
        except Exception:
            pass
        asyncio.create_task(request_gift_review(order))
    else:
        try:
            await bot.send_message(ADMIN_CHAT_ID,
                f"⚠️ <b>Автовидача не вдалась для {order_uid}</b>\n<i>{result.get('error','')[:300]}</i>\n\nНадішліть подарунок вручну.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔁 Спробувати ще раз", callback_data=f"giftretry_{order_uid}")]]),
                parse_mode="HTML")
        except Exception:
            pass
    return True

async def cryptobot_gift_poll_and_finalize(order_uid: str, invoice_id: str, chat_id: int) -> None:
    """Фонова задача для замовлень подарунків (🎁 Каталог подарунків), оплачених через
    CryptoBot — аналог cryptobot_poll_and_finalize, але для gift_orders."""
    max_checks = 225  # 225 * 8с ≈ 30 хвилин
    for _ in range(max_checks):
        await asyncio.sleep(8)
        order = get_gift_order(order_uid)
        if not order or order.get("status") in ("completed", "approved", "rejected"):
            return
        result = await cryptobot_check_invoice(invoice_id)
        if result.get("ok") and result.get("status") == "paid":
            await cryptobot_confirm_paid_gift_order(order_uid)
            return
        if result.get("ok") and result.get("status") == "expired":
            try:
                await bot.send_message(chat_id, "⌛ <b>Час на оплату через CryptoBot вичерпано.</b> Оформіть замовлення заново.", parse_mode="HTML")
            except Exception:
                pass
            return
    # Час очікування вичерпано без оплати — замовлення лишається "pending_payment".

def get_total_withdrawn(uid):
    """Сума всіх успішно виплачених виводів Stars користувача."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(amount),0) as t FROM withdrawals WHERE user_id=? AND status='paid'", (uid,))
    total = c.fetchone()["t"]; conn.close()
    return total or 0

def get_total_ton_bought(uid):
    """Сума всіх завершених покупок TON користувача."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(amount),0) as t FROM orders WHERE user_id=? AND order_type='ton' AND status='completed'", (uid,))
    total = c.fetchone()["t"]; conn.close()
    return total or 0

def get_pending_orders():
    conn = get_conn(); c = conn.cursor()
    c.execute("""SELECT o.*, u.username, u.full_name FROM orders o
                 JOIN users u ON o.user_id=u.user_id
                 WHERE o.status='pending' ORDER BY o.created_at DESC LIMIT 20""")
    rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]

def get_banned_users():
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT user_id,username,full_name,ban_reason FROM users WHERE banned=1")
    rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]

def create_review(uid, comment, photo_id="", rating=0, order_type="", amount=0):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO reviews (user_id,comment,photo_id,rating,order_type,amount) VALUES (?,?,?,?,?,?)",
              (uid, comment, photo_id, rating, order_type, amount))
    rid = c.lastrowid; conn.commit(); conn.close()
    return rid

def get_review(rid):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM reviews WHERE id=?", (rid,))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def update_review_status(rid, status):
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE reviews SET status=? WHERE id=?", (status, rid))
    conn.commit(); conn.close()

# ========================================================
# ОТПРАВКА МЕНЮ
# ========================================================

def _btn_text(b: dict, lang: str) -> str:
    """Обирає підпис кнопки для потрібної мови з fallback на uk/ru."""
    col = {"en": "text_en", "ru": "text_ru", "uk": "text_uk"}.get(lang, "text_uk")
    text = (b.get(col) or "").strip()
    if not text: text = (b.get("text_uk") or "").strip()
    if not text: text = (b.get("text_ru") or "").strip()
    return text

def get_main_kb_json(lang="uk"):
    btns = get_menu_buttons()
    rows = {}
    for b in btns:
        r = b["row_num"]
        if r not in rows: rows[r] = []
        ceid  = b.get("custom_emoji_id") or ""
        style = b.get("style") or "default"
        text = _btn_text(b, lang)
        label = text if ceid else f"{b['emoji']} {text}".strip()
        btn = {"text": label}
        if style != "default": btn["style"] = style
        if ceid: btn["icon_custom_emoji_id"] = ceid
        rows[r].append(btn)
    keyboard = [rows[k] for k in sorted(rows.keys()) if rows[k]]
    return {"keyboard": keyboard, "resize_keyboard": True}

def get_main_kb_markup(lang="uk"):
    btns = get_menu_buttons()
    rows = {}
    for b in btns:
        r = b["row_num"]
        if r not in rows: rows[r] = []
        text = _btn_text(b, lang)
        emoji = b.get("emoji") or ""
        label = f"{emoji} {text}".strip()
        rows[r].append(KeyboardButton(text=label))
    keyboard = [rows[k] for k in sorted(rows.keys()) if rows[k]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

async def send_menu(chat_id: int, text: str, lang: str = None):
    if lang is None:
        lang = get_lang(chat_id)
    try:
        kb = get_main_kb_json(lang)
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = req.post(url, json={"chat_id": chat_id, "text": text,
                             "parse_mode": "HTML", "reply_markup": kb}, timeout=10)
        if not resp.ok:
            raise Exception(resp.text[:100])
    except Exception as e:
        logger.error(f"send_menu raw error: {e}")
        try:
            kb = get_main_kb_markup(lang)
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
        except Exception as e2:
            logger.error(f"send_menu fallback error: {e2}")

# ========================================================
# ПОДАРУНКИ
# ========================================================

# ========================================================
# 🎁 ПОДАРУНКИ — клавіатури
# ========================================================

def gifts_keyboard() -> InlineKeyboardMarkup:
    """Клавіатура 3×3 з подарунками (лише увімкнені та в наявності)."""
    items = get_gift_items()
    rows = []
    row = []
    for key, item in sorted(items.items(), key=lambda kv: int(kv[0])):
        if not item.get("enabled", 1):
            continue
        if item.get("quantity") is not None and item["quantity"] <= 0:
            continue
        ceid = GIFT_BUTTON_STICKERS.get(key) or item.get("sticker_id") or ""
        label = f"{item['emoji']} {fmt_price(item['price'])} грн" if not ceid else f"{fmt_price(item['price'])} грн"
        kwargs = {"text": label, "callback_data": f"giftitem_{key}"}
        if ceid:
            kwargs["icon_custom_emoji_id"] = ceid
        try:
            row.append(InlineKeyboardButton(**kwargs))
        except TypeError:
            kwargs.pop("icon_custom_emoji_id", None)
            kwargs["text"] = f"{item['emoji']} {fmt_price(item['price'])} грн"
            row.append(InlineKeyboardButton(**kwargs))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    if not rows:
        rows.append([InlineKeyboardButton(text="😢 Немає подарунків", callback_data="show_gifts")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def gift_detail_keyboard(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купити", callback_data=f"buygift_{key}")],
        [InlineKeyboardButton(text="🔙 До подарунків", callback_data="show_gifts")]
    ])

def gift_recipient_keyboard(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Другу", callback_data=f"gift_for_friend_{key}"),
         InlineKeyboardButton(text="👤 Собі", callback_data=f"gift_for_self_{key}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"giftitem_{key}")]
    ])

def stars_pkg_recipient_kb(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Другу", callback_data=f"pkgfriend_{key}"),
         InlineKeyboardButton(text="👤 Собі", callback_data=f"pkgself_{key}")]
    ])

def gift_comment_keyboard(order_uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ Без коментаря", callback_data=f"giftcomment_skip_{order_uid}")
    ]])

# ========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ========================================================

def get_ton_rate():
    """Курс TON для розділу 'Купити TON' — використовує ton_markup"""
    try:
        r = req.get("https://api.coingecko.com/api/v3/simple/price?ids=the-open-network,tether&vs_currencies=uah", timeout=5)
        data = r.json()
        ton_uah = data["the-open-network"]["uah"]
        markup = 1 + float(get_setting("ton_markup") or 0) / 100
        return round(ton_uah * markup, 2)
    except:
        return round(100.0 * (1 + float(get_setting("ton_markup") or 0) / 100), 2)

def get_usdt_rate():
    """Курс USDT (без накрутки) — використовується тільки як базовий курс для крипто-розрахунків"""
    try:
        r = req.get("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=uah", timeout=5)
        return round(r.json()["tether"]["uah"], 2)
    except:
        return 42.0

def get_crypto_ton_rate(markup_key="crypto_markup"):
    """Курс TON для оплати криптою — markup_key дозволяє використовувати окрему накрутку
    (наприклад "cryptobot_markup" для CryptoBot, незалежно від звичайної "Криптовалюта").
    Накрутка ЗНИЖУЄ курс (грн за 1 TON), через що клієнту доводиться слати БІЛЬШЕ TON
    за ту саму суму в грн — тобто накрутка робить ціну для клієнта вищою, як і має бути."""
    try:
        r = req.get("https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=uah", timeout=5)
        ton_uah = r.json()["the-open-network"]["uah"]
        markup = 1 + float(get_setting(markup_key) or 0) / 100
        return round(ton_uah / markup, 2)
    except:
        return round(100.0 / (1 + float(get_setting(markup_key) or 0) / 100), 2)

def get_crypto_usdt_rate(markup_key="crypto_markup"):
    """Курс USDT для оплати криптою — markup_key дозволяє окрему накрутку (див. get_crypto_ton_rate)."""
    base = get_usdt_rate()
    markup = 1 + float(get_setting(markup_key) or 0) / 100
    return round(base / markup, 2)

def is_cancel(t): return t in ["❌ Скасувати"]
def is_back(t): return t in ["🔙 Назад"]
def is_skip(t): return t in ["😢 Пропустити"]

def check_flood(uid):
    now = time.time()
    last = user_last_msg.get(uid, 0)
    user_last_msg[uid] = now
    return (now - last) < FLOOD_TIMEOUT

def tg_emoji(custom_emoji_id: str, fallback: str = "🔹") -> str:
    """Обгортає fallback-емодзі в <tg-emoji>, якщо переданий premium custom_emoji_id."""
    if custom_emoji_id:
        return f'<tg-emoji emoji-id="{custom_emoji_id}">{fallback}</tg-emoji>'
    return fallback

# Преміум-стикери на кнопках каталогу подарунків, захардкоджені прямо в код
# (щоб не залежати від значення sticker_id в БД). Ключ — item_key позиції.
GIFT_BUTTON_STICKERS = {
    "1":  "5359736160224586485",
    "2":  "5447213743417105726",
    "3":  "5379850840691476775",
    "4":  "5345935030143196497",
    "5":  "5226661632259691727",
    "6":  "5317000922096769303",
    "7":  "5289761157173775507",
    "8":  "5393309541620291208",
    "9":  "5224628072619216265",
    "10": "5397971251878732060",
    "11": "5470129614439362117",
}

# ========================================================
# ТЕКСТИ (тільки українською)
# ========================================================

FALLBACK_TEXTS = {
  "uk": {
    "main_menu": "🏠 <b>Головне меню</b>\n\nВиберіть розділ:",
    "enter_friend": "Введіть <b>@username</b> акаунту, якому потрібно відправити зірки.\n\nНаприклад: <code>@username</code>\n\n<blockquote>Переконайтесь, що вказали правильний нік!</blockquote>",
    "enter_stars": "⭐ <b>Скільки Stars хочете купити?</b>\n\n📌 <b>Мінімум: {min} Stars</b>",
    "choose_bank": "💰 <b>До оплати: {price} грн</b>\n📦 <b>{amount}</b>\n\n🏦 <b>Оберіть спосіб оплати:</b>",
    "ton_enter": "💵 Курс TON: <b>{rate} грн</b>\n\n💰 Введіть кількість TON:\n\n📌 Мінімум: <b>{min} TON</b>",
    "ton_wallet": "💼 Введіть ваш <b>TON/USDT гаманець</b>:",
    "ton_summary": "💵 До оплати: <b>{price} грн</b>\n💰 Отримаєте: <b>{amount} TON</b>\n👛 Гаманець: <code>{wallet}</code>\n\n🏦 Оберіть спосіб оплати:",
    "prem_months": "💎 <b>Telegram Premium</b>\n\n• 3 місяці — <b>{m3} грн</b>\n• 6 місяців — <b>{m6} грн</b>\n• 12 місяців — <b>{m12} грн</b>",
    "sell_wallet": "💼 Введіть вашу <b>картку або гаманець</b>:",
    "sell_summary": "💰 Ви отримаєте: <b>{price} грн</b>\n⭐ Продаєте: <b>{amount} Stars</b>\n💳 Реквізити: <code>{wallet}</code>\n\n✅ Підтвердити?",
    "sell_ok": "🎉 <b>Заявку на продаж прийнято!</b>\n\nОчікуйте переказу протягом <b>15 хвилин</b>.",
    "pay_confirmed": "✅ <b>Оплату підтверджено!</b>\n\n🚀 Stars скоро будуть доставлені!",
    "order_rejected": "❌ <b>Заявку відхилено.</b>\n\n📝 Причина: {reason}",
    "calc_stars": "⭐ <b>{amount} Stars</b> = <b>{price} грн</b>",
    "support_enter": "📝 <b>Опишіть проблему.</b>\n\n<b>Можна прикріпити фото або відео:</b>",
    "support_sent": "✅ <b>Заявку відправлено!</b>\n\n<b>Очікуйте відповіді від підтримки.</b>",
    "review_ask": "⭐ Напишіть відгук про наш сервіс!\n\nМожна прикріпити фото 📸\nВаша думка дуже важлива 🙏",
    "review_thanks": "✅ <b>Дякуємо за відгук!</b>\n\nВін буде перевірений та опублікований.",
    "review_skipped": "Добре! Будемо раді бачити вас знову 😊",
    "err_num": "❌ Введіть коректне число.",
    "err_min_stars": "❌ Мінімум: <b>{min} Stars</b>",
    "err_min_ton": "❌ Мінімум: <b>{min} TON</b>",
    "err_min_sell": "❌ Мінімум для продажу: <b>{min} Stars</b>",
    "banned": "🚫 Вас заблоковано.\n\nПричина: {reason}",
    "flood": "⚡ Не так швидко! Зачекайте трохи.",
    "spam_limit": "⚠️ Забагато заявок. Спробуйте через годину.",
    "withdraw_enter_username": "💳 Введіть @username отримувача:\n\n<blockquote>Можна вказати свій акаунт або акаунт друга — Stars будуть надіслані саме на цей username</blockquote>",
    "sell_confirm_yes": "✅ Підтвердити продаж?",
    "referral_info": "👥 <b>Реферальна програма</b>\n\n🔗 Ваше посилання:\n<a href=\"{ref_link}\">{ref_link}</a>\n\n💰 <b>Ви будете отримувати {percent}% від кожної покупки запрошеного друга!</b>\n\n👤 Запрошено: <b>{ref_count}</b>",
    "choose_language": "🌐 <b>Оберіть мову / Choose language / Выберите язык:</b>",
    "language_set": "✅ Мову змінено на українську 🇺🇦",
  },
  "ru": {
    "main_menu": "🏠 <b>Главное меню</b>\n\nВыберите раздел:",
    "enter_friend": "Введите <b>@username</b> аккаунта, которому нужно отправить звёзды.\n\nНапример: <code>@username</code>\n\n<blockquote>Убедитесь, что указали правильный ник!</blockquote>",
    "enter_stars": "⭐ <b>Сколько Stars хотите купить?</b>\n\n📌 <b>Минимум: {min} Stars</b>",
    "choose_bank": "💰 <b>К оплате: {price} грн</b>\n📦 <b>{amount}</b>\n\n🏦 <b>Выберите способ оплаты:</b>",
    "ton_enter": "💵 Курс TON: <b>{rate} грн</b>\n\n💰 Введите количество TON:\n\n📌 Минимум: <b>{min} TON</b>",
    "ton_wallet": "💼 Введите ваш <b>TON/USDT кошелёк</b>:",
    "ton_summary": "💵 К оплате: <b>{price} грн</b>\n💰 Получите: <b>{amount} TON</b>\n👛 Кошелёк: <code>{wallet}</code>\n\n🏦 Выберите способ оплаты:",
    "prem_months": "💎 <b>Telegram Premium</b>\n\n• 3 месяца — <b>{m3} грн</b>\n• 6 месяцев — <b>{m6} грн</b>\n• 12 месяцев — <b>{m12} грн</b>",
    "sell_wallet": "💼 Введите вашу <b>карту или кошелёк</b>:",
    "sell_summary": "💰 Вы получите: <b>{price} грн</b>\n⭐ Продаёте: <b>{amount} Stars</b>\n💳 Реквизиты: <code>{wallet}</code>\n\n✅ Подтвердить?",
    "sell_ok": "🎉 <b>Заявка на продажу принята!</b>\n\nОжидайте перевод в течение <b>15 минут</b>.",
    "pay_confirmed": "✅ <b>Оплата подтверждена!</b>\n\n🚀 Stars скоро будут доставлены!",
    "order_rejected": "❌ <b>Заявка отклонена.</b>\n\n📝 Причина: {reason}",
    "calc_stars": "⭐ <b>{amount} Stars</b> = <b>{price} грн</b>",
    "support_enter": "📝 <b>Опишите проблему.</b>\n\n<b>Можно прикрепить фото или видео:</b>",
    "support_sent": "✅ <b>Заявка отправлена!</b>\n\n<b>Ожидайте ответа от поддержки.</b>",
    "review_ask": "⭐ Напишите отзыв о нашем сервисе!\n\nМожно прикрепить фото 📸\nВаше мнение очень важно 🙏",
    "review_thanks": "✅ <b>Спасибо за отзыв!</b>\n\nОн будет проверен и опубликован.",
    "review_skipped": "Хорошо! Будем рады видеть вас снова 😊",
    "err_num": "❌ Введите корректное число.",
    "err_min_stars": "❌ Минимум: <b>{min} Stars</b>",
    "err_min_ton": "❌ Минимум: <b>{min} TON</b>",
    "err_min_sell": "❌ Минимум для продажи: <b>{min} Stars</b>",
    "banned": "🚫 Вы заблокированы.\n\nПричина: {reason}",
    "flood": "⚡ Не так быстро! Подождите немного.",
    "spam_limit": "⚠️ Слишком много заявок. Попробуйте через час.",
    "withdraw_enter_username": "💳 Введите @username получателя:\n\n<blockquote>Можно указать свой аккаунт или аккаунт друга — Stars будут отправлены именно на этот username</blockquote>",
    "sell_confirm_yes": "✅ Подтвердить продажу?",
    "referral_info": "👥 <b>Реферальная программа</b>\n\n🔗 Ваша ссылка:\n<a href=\"{ref_link}\">{ref_link}</a>\n\n💰 <b>Вы будете получать {percent}% от каждой покупки приглашённого друга!</b>\n\n👤 Приглашено: <b>{ref_count}</b>",
    "choose_language": "🌐 <b>Оберіть мову / Choose language / Выберите язык:</b>",
    "language_set": "✅ Язык изменён на русский 🇷🇺",
  },
  "en": {
    "main_menu": "🏠 <b>Main menu</b>\n\nChoose a section:",
    "enter_friend": "Enter the <b>@username</b> of the account to send Stars to.\n\nExample: <code>@username</code>\n\n<blockquote>Make sure the username is correct!</blockquote>",
    "enter_stars": "⭐ <b>How many Stars would you like to buy?</b>\n\n📌 <b>Minimum: {min} Stars</b>",
    "choose_bank": "💰 <b>To pay: {price} UAH</b>\n📦 <b>{amount}</b>\n\n🏦 <b>Choose a payment method:</b>",
    "ton_enter": "💵 TON rate: <b>{rate} UAH</b>\n\n💰 Enter the amount of TON:\n\n📌 Minimum: <b>{min} TON</b>",
    "ton_wallet": "💼 Enter your <b>TON/USDT wallet</b>:",
    "ton_summary": "💵 To pay: <b>{price} UAH</b>\n💰 You'll receive: <b>{amount} TON</b>\n👛 Wallet: <code>{wallet}</code>\n\n🏦 Choose a payment method:",
    "prem_months": "💎 <b>Telegram Premium</b>\n\n• 3 months — <b>{m3} UAH</b>\n• 6 months — <b>{m6} UAH</b>\n• 12 months — <b>{m12} UAH</b>",
    "sell_wallet": "💼 Enter your <b>card or wallet</b>:",
    "sell_summary": "💰 You'll receive: <b>{price} UAH</b>\n⭐ Selling: <b>{amount} Stars</b>\n💳 Details: <code>{wallet}</code>\n\n✅ Confirm?",
    "sell_ok": "🎉 <b>Sell request accepted!</b>\n\nExpect the transfer within <b>15 minutes</b>.",
    "pay_confirmed": "✅ <b>Payment confirmed!</b>\n\n🚀 Stars will be delivered soon!",
    "order_rejected": "❌ <b>Order rejected.</b>\n\n📝 Reason: {reason}",
    "calc_stars": "⭐ <b>{amount} Stars</b> = <b>{price} UAH</b>",
    "support_enter": "📝 <b>Describe your issue.</b>\n\n<b>You can attach a photo or video:</b>",
    "support_sent": "✅ <b>Request sent!</b>\n\n<b>Please wait for a support reply.</b>",
    "review_ask": "⭐ Leave a review about our service!\n\nYou can attach a photo 📸\nYour opinion matters a lot 🙏",
    "review_thanks": "✅ <b>Thanks for the review!</b>\n\nIt will be checked and published.",
    "review_skipped": "Okay! We'll be glad to see you again 😊",
    "err_num": "❌ Enter a valid number.",
    "err_min_stars": "❌ Minimum: <b>{min} Stars</b>",
    "err_min_ton": "❌ Minimum: <b>{min} TON</b>",
    "err_min_sell": "❌ Minimum to sell: <b>{min} Stars</b>",
    "banned": "🚫 You are banned.\n\nReason: {reason}",
    "flood": "⚡ Not so fast! Please wait a bit.",
    "spam_limit": "⚠️ Too many requests. Try again in an hour.",
    "withdraw_enter_username": "💳 Enter recipient's @username:\n\n<blockquote>You can enter your own account or a friend's — Stars will be sent to exactly this username</blockquote>",
    "sell_confirm_yes": "✅ Confirm the sale?",
    "referral_info": "👥 <b>Referral program</b>\n\n🔗 Your link:\n<a href=\"{ref_link}\">{ref_link}</a>\n\n💰 <b>You'll earn {percent}% from every purchase made by an invited friend!</b>\n\n👤 Invited: <b>{ref_count}</b>",
    "choose_language": "🌐 <b>Оберіть мову / Choose language / Выберите язык:</b>",
    "language_set": "✅ Language set to English 🇬🇧",
  },
}

def T(key, **kw):
    lang = _current_lang.get()
    text = get_bot_text(key, lang)
    if not text:
        text = FALLBACK_TEXTS.get(lang, FALLBACK_TEXTS["uk"]).get(key) or FALLBACK_TEXTS["uk"].get(key, "")
    return text.format(**kw) if kw else text

def build_channel_review(num, name, comment, rating, date_str, order_type="", amount=0, total_amount=0):
    stars_line = "⭐" * rating if rating else ""

    if order_type == "stars":
        purchase_block = (
            f"🌟 Виведено зараз: {fmt_price(amount)} ⭐\n"
            f"📊 Всього виведено: {fmt_price(total_amount)} ⭐\n\n"
        )
    elif order_type == "ton":
        purchase_block = (
            f"💎 Придбав зараз: {fmt_price(amount)} TON\n"
            f"📊 Всього придбав: {fmt_price(total_amount)} TON\n\n"
        )
    elif order_type == "premium":
        months_int = int(amount) if amount else 0
        purchase_block = f"🚀 Придбав: {months_int} міс. Premium\n\n"
    elif order_type == "gift":
        purchase_block = f"🎁 Придбав подарунок за {fmt_price(total_amount)} грн\n\n"
    else:
        purchase_block = ""

    return (
        f"<b>💬 Відгук #{num}</b>\n\n"
        f"<b>👤 {name}</b>\n"
        f"<b>{stars_line}</b>\n\n"
        f"<b>Декілька слів про нас:</b>\n"
        f"<b>{comment}</b>\n\n"
        f"<b>{purchase_block}</b>"
        f"<b>📅 {date_str}</b>\n\n"
        f"<b><i>Дякуємо за довіру до {BOT_NAME} 🙂</i></b>"
    )

def fmt_price(value):
    """Форматує суму грошей: ціле число без '.0' (37 замість 37.0), з копійками — як є (37.5)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")

def fmt_price_bold(value):
    """Залишено для сумісності — тепер просто повертає fmt_price без додаткового <b>,
    бо шаблон choose_bank вже сам оборачує {price} в <b>...</b>."""
    return fmt_price(value)

def stars_amount_label(amount):
    """Формує текст 'N зірок ⭐' для повідомлень — якщо адмін задав преміум-емодзі для пакетів Stars,
    використовує саме його (через <tg-emoji>), інакше звичайну зірку.
    Без власного <b>, бо шаблони (choose_bank тощо) вже самі оборачують {amount} в <b>."""
    ceid = get_setting("btn_pkg_emoji_id") or ""
    if ceid:
        return f'{amount} зірок <tg-emoji emoji-id="{ceid}">⭐</tg-emoji>'
    return f"{amount} зірок ⭐"

def pay_text(method_key, lang, price, order_type="stars"):
    methods = {m["method_key"]: m for m in get_payment_methods()}
    m = methods.get(method_key)
    if not m:
        return f"💰 До сплати: <b>{price} грн</b>"

    owner = m.get("owner") or ""
    owner_line = f"\n👤 <b>Отримувач:</b> {owner}" if owner else ""

    # Якщо адмін задав власний повний текст оплати — використовуємо його замість
    # стандартного шаблону. Доступні плейсхолдери: {name} {details} {owner} {price}
    custom = (m.get("instructions") or "").strip()
    if custom:
        try:
            rendered = custom.format(name=m["name_uk"], details=m.get("details") or "",
                                      owner=owner, price=price)
        except Exception:
            rendered = custom
        # Захист від зламаного/незакритого HTML в тексті адміна — без цього
        # Telegram міг би взагалі відмовитись відправляти повідомлення.
        return safe_html(rendered)

    if method_key == "crypto":
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            price_f = 0.0
        usdt_rate = get_crypto_usdt_rate()
        usdt_amount = round(price_f / usdt_rate, 2) if usdt_rate else 0
        crypto_lines = f"💲 <b>До сплати: {usdt_amount} USDT</b>\n"
        # Купуючи TON за крипту — платити TON за TON виглядає нелогічно (та ще й з накруткою),
        # тому для замовлень типу "ton" пропонуємо оплату лише в USDT, без варіанту в TON.
        if order_type != "ton":
            ton_rate = get_crypto_ton_rate()
            ton_amount = round(price_f / ton_rate, 2) if ton_rate else 0
            crypto_lines += f"💎 <b>або {ton_amount} TON</b>\n"
        return (
            f"🏦 <b>{m['name_uk']}</b>\n\n"
            f"💳 <code>{m['details']}</code>{owner_line}\n\n"
            f"{crypto_lines}"
            f"\n💰 <i>(≈ {price} грн)</i>\n\n"
            f"📸 Після оплати надішліть скріншот"
        )

    return (
        f"🏦 <b>{m['name_uk']}</b>\n\n"
        f"💳 <code>{m['details']}</code>{owner_line}\n\n"
        f"💰 <b>До сплати: {price} грн</b>\n\n"
        f"📸 Після оплати надішліть скріншот"
    )

def get_bank_key(text):
    methods = {m["name_uk"]: m["method_key"] for m in get_payment_methods()}
    return methods.get(text.strip(), "")

# ========================================================
# КЛАВІАТУРИ
# ========================================================

def start_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚀 Почати")]], resize_keyboard=True)

def cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Скасувати")]], resize_keyboard=True)

def back_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Назад")]], resize_keyboard=True)

def review_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="😢 Пропустити")]], resize_keyboard=True)

def stars_packages_kb(rate=0.74):
    """Клавіатура паків Stars — повністю з БД (fixed-позиції одразу ведуть до оплати,
    range-позиції відкривають ввід своєї суми в заданих межах,
    group-позиції відкривають підменю з дочірніми кнопками, як у подарунків)."""
    packages = get_stars_packages(enabled_only=True)
    pkg_style = get_setting("btn_pkg_style") or "primary"
    custom_style = get_setting("btn_pkg_custom_style") or "danger"
    rows = []
    for p in packages:
        ceid = p.get("custom_emoji_id") or ""
        if p["kind"] == "fixed":
            price = p["fixed_price"] if p.get("fixed_price") is not None else round((p["amount"] or 0) * rate, 0)
            label = p.get("label") or f"{p['amount']} — {int(price)} грн"
            cb_data = f"pkg_{p['item_key']}"
            style = pkg_style
        elif p["kind"] == "group":
            label = p.get("label") or "🎁 Набір"
            cb_data = f"pkggroup_{p['item_key']}"
            style = pkg_style
        else:
            label = p.get("label") or (
                f"Своя сума {p['range_min']}-{p['range_max']}" if p.get("range_max")
                else f"Своя кількість {p['range_min']}+")
            cb_data = f"pkg_{p['item_key']}"
            style = custom_style
        kwargs = {"text": label, "callback_data": cb_data}
        if style != "default":
            kwargs["style"] = style
        if ceid:
            kwargs["icon_custom_emoji_id"] = ceid
        try:
            rows.append([InlineKeyboardButton(**kwargs)])
        except TypeError:
            kwargs.pop("icon_custom_emoji_id", None)
            kwargs.pop("style", None)
            rows.append([InlineKeyboardButton(**kwargs)])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="stars_pkg_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def stars_group_kb(parent_key: str, rate=0.74) -> InlineKeyboardMarkup:
    """Підменю групового паку — кнопки 3 в ряд у стилі подарунків. Якщо адмін задав свій
    підпис (через "✏️ Підпис") — використовується він. Інакше: якщо задано преміум-емодзі —
    показуємо лише кількість Stars без ціни (іконка вже "каже" що це за товар); без емодзі —
    стандартний "{amount} — {price} грн"."""
    children = get_stars_package_children(parent_key, enabled_only=True)
    rows, row = [], []
    for ch in children:
        ceid = ch.get("custom_emoji_id") or ""
        price = ch["fixed_price"] if ch.get("fixed_price") is not None else round((ch["amount"] or 0) * rate, 0)
        if ch.get("label"):
            label = ch["label"]
        elif ceid:
            label = f"{ch['amount']} Stars"
        else:
            label = f"{ch['amount']} — {int(price)} грн"
        kwargs = {"text": label, "callback_data": f"pkg_{ch['item_key']}"}
        if ceid:
            kwargs["icon_custom_emoji_id"] = ceid
        try:
            row.append(InlineKeyboardButton(**kwargs))
        except TypeError:
            kwargs.pop("icon_custom_emoji_id", None)
            row.append(InlineKeyboardButton(**kwargs))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    if not rows:
        rows.append([InlineKeyboardButton(text="😢 Порожньо", callback_data="stars_pkg_group_back")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="stars_pkg_group_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def _method_button(m, callback_data):
    """Будує кнопку способу оплати, з підтримкою premium-емодзі (icon_custom_emoji_id).
    Якщо преміум-емодзі задано — прибираємо старий emoji-префікс з назви (він там завжди
    першим "словом"), щоб не показувались одразу дві іконки."""
    name = m["name_uk"]
    style = m.get("style") or "default"
    ceid = m.get("custom_emoji_id") or ""
    if ceid and " " in name:
        first_word, rest = name.split(" ", 1)
        # Прибираємо перше "слово", лише якщо це схоже на emoji-префікс (коротке, без літер/цифр)
        if len(first_word) <= 4 and not any(ch.isalnum() for ch in first_word):
            name = rest.strip()
    kwargs = {"text": name, "callback_data": callback_data}
    if style != "default":
        kwargs["style"] = style
    if ceid:
        kwargs["icon_custom_emoji_id"] = ceid
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("icon_custom_emoji_id", None)
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)

def bank_kb(stars_button: InlineKeyboardButton = None, back_button: InlineKeyboardButton = None):
    methods = get_payment_methods()
    rows = []
    row = []
    for m in methods:
        if m["method_key"] in ("monobank","privat24","abank"):
            continue
        btn = _method_button(m, f"bank_{m['method_key']}")
        row.append(btn)
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    if stars_button is not None:
        rows.append([stars_button])
    if back_button is not None:
        rows.append([back_button])
    try:
        rows.append([InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data="bank_cancel", style="danger")])
    except TypeError:
        rows.append([InlineKeyboardButton(text="❌ Скасувати замовлення", callback_data="bank_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def gift_price_stars(item: dict) -> int:
    """Ціна подарунка у Stars: власне значення price_stars, або авто-розрахунок з ціни в грн."""
    if item.get("price_stars"):
        return int(item["price_stars"])
    rate = float(get_setting("stars_rate") or 0.74)
    return max(1, round(float(item.get("price", 0)) / rate))

def premium_price_stars(months: int) -> int:
    key = {3: "premium_3m_stars", 6: "premium_6m_stars", 12: "premium_12m_stars"}.get(months)
    val = get_setting(key) if key else None
    if val:
        try: return int(val)
        except Exception: pass
    rate = float(get_setting("stars_rate") or 0.74)
    price_uah = float(get_setting({3:"premium_3m",6:"premium_6m",12:"premium_12m"}.get(months,"premium_3m")) or 0)
    return max(1, round(price_uah / rate))

def _premium_stars_button(months) -> InlineKeyboardButton:
    """Кнопка «Оплатити Stars» для Premium, якщо ввімкнено в адмінці. Інакше None."""
    if get_setting("stars_pay_premium_enabled") != "1":
        return None
    try:
        months_int = int(months)
    except Exception:
        return None
    stars = premium_price_stars(months_int)
    return InlineKeyboardButton(text=f"⭐ Оплатити {stars} Stars", callback_data=f"paystars_prem_{months_int}")

def _gift_stars_button(item: dict) -> InlineKeyboardButton:
    """Кнопка «Оплатити Stars» для подарунка, якщо ввімкнено в адмінці. Інакше None."""
    if get_setting("stars_pay_gift_enabled") != "1":
        return None
    stars = gift_price_stars(item)
    return InlineKeyboardButton(text=f"⭐ Оплатити {stars} Stars", callback_data="paystars_gift")

def ua_submenu_kb():
    """Підменю для української картки — Monobank, Privat24, А-Банк"""
    methods = get_payment_methods()
    ua_methods = [m for m in methods if m["method_key"] in ("monobank","privat24","abank")]
    rows = []
    row = []
    for m in ua_methods:
        btn = _method_button(m, f"bank_{m['method_key']}")
        row.append(btn)
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    try:
        rows.append([
            InlineKeyboardButton(text="🔙 Назад",      callback_data="bank_ua_back"),
            InlineKeyboardButton(text="❌ Скасувати",   callback_data="bank_cancel", style="danger")
        ])
    except TypeError:
        rows.append([
            InlineKeyboardButton(text="🔙 Назад",      callback_data="bank_ua_back"),
            InlineKeyboardButton(text="❌ Скасувати",   callback_data="bank_cancel")
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def cryptobot_currency_kb(cur_prefix="cryptobot_cur_", back_cb="bank_ua_back"):
    """Вибір валюти для оплати через CryptoBot — з підтримкою свого тексту кнопок,
    преміум-емодзі та кольору (все налаштовується в адмінці). cur_prefix дозволяє
    використовувати цю ж клавіатуру для різних систем замовлень (Stars/Premium/TON
    через звичайні orders, і окремо — подарунки через gift_orders)."""
    style = get_setting("cryptobot_currency_style") or "default"
    ton_ceid = get_setting("cryptobot_ton_emoji") or ""
    usdt_ceid = get_setting("cryptobot_usdt_emoji") or ""
    ton_custom_text = get_setting("cryptobot_ton_btn_text")
    usdt_custom_text = get_setting("cryptobot_usdt_btn_text")
    # Якщо адмін не задав свій текст — беремо стандартний, але без emoji-префікса,
    # якщо вже стоїть преміум-емодзі (щоб не показувались одразу дві іконки).
    ton_text = ton_custom_text or ("TON" if ton_ceid else "💎 TON")
    usdt_text = usdt_custom_text or ("USDT" if usdt_ceid else "💵 USDT")

    def _build(text, ceid, cb_data):
        kwargs = {"text": text, "callback_data": cb_data}
        if style != "default":
            kwargs["style"] = style
        if ceid:
            kwargs["icon_custom_emoji_id"] = ceid
        try:
            return InlineKeyboardButton(**kwargs)
        except TypeError:
            kwargs.pop("icon_custom_emoji_id", None)
            kwargs.pop("style", None)
            return InlineKeyboardButton(**kwargs)

    rows = [
        [_build(ton_text, ton_ceid, f"{cur_prefix}TON"), _build(usdt_text, usdt_ceid, f"{cur_prefix}USDT")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=back_cb)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def cryptobot_pay_kb(pay_url: str, oid, check_prefix="cryptobot_check_"):
    pay_ceid = get_setting("cryptobot_pay_btn_emoji") or ""
    check_ceid = get_setting("cryptobot_check_btn_emoji") or ""
    pay_custom_text = get_setting("cryptobot_pay_btn_text")
    check_custom_text = get_setting("cryptobot_check_btn_text")
    pay_text = pay_custom_text or ("Оплатити" if pay_ceid else "🤖 Оплатити")
    check_text = check_custom_text or ("Перевірити оплату" if check_ceid else "🔄 Перевірити оплату")
    pay_kwargs = {"text": pay_text, "url": pay_url}
    if pay_ceid: pay_kwargs["icon_custom_emoji_id"] = pay_ceid
    check_kwargs = {"text": check_text, "callback_data": f"{check_prefix}{oid}"}
    if check_ceid: check_kwargs["icon_custom_emoji_id"] = check_ceid
    try:
        pay_btn = InlineKeyboardButton(**pay_kwargs)
    except TypeError:
        pay_kwargs.pop("icon_custom_emoji_id", None)
        pay_btn = InlineKeyboardButton(**pay_kwargs)
    try:
        check_btn = InlineKeyboardButton(**check_kwargs)
    except TypeError:
        check_kwargs.pop("icon_custom_emoji_id", None)
        check_btn = InlineKeyboardButton(**check_kwargs)
    try:
        return InlineKeyboardMarkup(inline_keyboard=[
            [pay_btn], [check_btn],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="bank_cryptobot")],
        ])
    except TypeError:
        return InlineKeyboardMarkup(inline_keyboard=[
            [pay_btn], [check_btn],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="bank_cryptobot")],
        ])

def months_kb():
    months = [(3, "premium_3m"), (6, "premium_6m"), (12, "premium_12m")]
    month_style = get_setting("btn_month_style") or "primary"
    rows = []
    row = []
    for m, key in months:
        price = get_setting(key) or "0"
        label = f"💎 {m} міс — {fmt_price(price)} грн"
        try:
            btn = InlineKeyboardButton(text=label, callback_data=f"prem_month_{m}", style=month_style)
        except TypeError:
            btn = InlineKeyboardButton(text=label, callback_data=f"prem_month_{m}")
        row.append(btn)
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    try:
        rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="prem_month_back")])
    except TypeError:
        rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="prem_month_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def confirm_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="✅ Підтвердити")],
        [KeyboardButton(text="❌ Скасувати")]
    ], resize_keyboard=True)

def order_kb(oid, order_type="stars"):
    labels = {
        "stars":   "⭐ Зарахувати зірки",
        "ton":     "💎 Підтвердити TON",
        "premium": "💎 Підтвердити Premium",
        "gift":    "🎁 Видано подарунок",
        "sell":    "💸 Виплачено",
    }
    label = labels.get(order_type, "✅ Виконати замовлення")
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=f"complete_{oid}"),
        InlineKeyboardButton(text="❌ Відхилити", callback_data=f"reject_{oid}")
    ]])

def support_kb(tid):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✉️ Відповісти", callback_data=f"reply_{tid}")
    ]])

def review_admin_kb(num):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Опублікувати", callback_data=f"pub_review_{num}"),
        InlineKeyboardButton(text="❌ Відхилити",    callback_data=f"rej_review_{num}")
    ]])

def buy_stars_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⭐ Придбати Stars", url=f"https://t.me/{BOT_USERNAME}")
    ]])

def withdraw_kb(wid):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Виплатити", callback_data=f"pay_withdraw_{wid}"),
        InlineKeyboardButton(text="❌ Відхилити", callback_data=f"rej_withdraw_{wid}")
    ]])

# ========================================================
# АДМІН-КЛАВІАТУРИ
# ========================================================

def admin_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика"),     KeyboardButton(text="📢 Розсилка")],
        [KeyboardButton(text="💰 Курси і ціни"),   KeyboardButton(text="⚙️ Мінімуми")],
        [KeyboardButton(text="🎨 Кнопки меню"),    KeyboardButton(text="📝 Тексти бота")],
        [KeyboardButton(text="💳 Способи оплати"), KeyboardButton(text="👤 Знайти юзера")],
        [KeyboardButton(text="📋 Активні замовлення"), KeyboardButton(text="🚫 Забанені")],
        [KeyboardButton(text="👥 Реферали"),        KeyboardButton(text="🔔 Обов. підписка")],
        [KeyboardButton(text="📸 Фото для розділів"), KeyboardButton(text="📊 Статистика продаж")],
        [KeyboardButton(text="🎁 Каталог подарунків")],
        [KeyboardButton(text="⭐ Паки Stars")],
        [KeyboardButton(text="🚪 Вийти з адмінки")]
    ], resize_keyboard=True)

def admin_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Назад в меню", callback_data="adm_back")
    ]])

def admin_gifts_kb():
    items = get_gift_items()
    rows = []
    for key, item in sorted(items.items(), key=lambda kv: (kv[1].get("position") or 0, kv[0])):
        status = "✅" if item.get("enabled") else "🚫"
        qty = "∞" if item.get("quantity") is None else str(item["quantity"])
        rows.append([InlineKeyboardButton(
            text=f"{status} {item['emoji']} {item['name']} · {item['price']:.0f} грн · {qty} шт.",
            callback_data=f"adm_gift_item_{key}")])
    creds = get_gift_api_creds()
    tg_status = "✅ увійшли" if creds.get("api_id") else "❌ не налаштовано"
    rows.append([InlineKeyboardButton(text="➕ Додати подарунок", callback_data="adm_gift_add")])
    rows.append([InlineKeyboardButton(text="🔑 Telethon-акаунт (автовидача)", callback_data="adm_gift_api_creds")])
    rows.append([InlineKeyboardButton(text=f"📱 Увійти в акаунт ({tg_status})", callback_data="adm_gift_login_start")])
    rows.append([InlineKeyboardButton(text="📜 Каталог подарунків Telegram", callback_data="adm_gift_real_catalog")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_gift_item_kb(key: str):
    item = get_gift_item(key) or {}
    toggle_label = "🚫 Вимкнути" if item.get("enabled") else "✅ Увімкнути"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Назва", callback_data=f"adm_gedit_name_{key}"),
         InlineKeyboardButton(text="✏️ Емодзі", callback_data=f"adm_gedit_emoji_{key}")],
        [InlineKeyboardButton(text="💰 Ціна (грн)", callback_data=f"adm_gedit_price_{key}"),
         InlineKeyboardButton(text="⭐ Ціна (Stars)", callback_data=f"adm_gedit_pricestars_{key}")],
        [InlineKeyboardButton(text="🔢 Кількість", callback_data=f"adm_gedit_qty_{key}")],
        [InlineKeyboardButton(text="🆔 Telegram Gift ID", callback_data=f"adm_gedit_tgid_{key}")],
        [InlineKeyboardButton(text="🖼 Прем-емодзі", callback_data=f"adm_gedit_sticker_{key}")],
        [InlineKeyboardButton(text="⬆️ Вище", callback_data=f"adm_gpos_{key}_up"),
         InlineKeyboardButton(text="⬇️ Нижче", callback_data=f"adm_gpos_{key}_down")],
        [InlineKeyboardButton(text=toggle_label, callback_data=f"adm_gtoggle_{key}"),
         InlineKeyboardButton(text="🗑 Видалити", callback_data=f"adm_gdel_{key}")],
        [InlineKeyboardButton(text="🔙 До каталогу", callback_data="adm_gifts")]
    ])

def admin_star_packages_kb():
    packages = get_stars_packages(enabled_only=False)
    rows = []
    for p in sorted(packages, key=lambda x: (x.get("position") or 0, x["item_key"])):
        status = "✅" if p.get("enabled") else "🚫"
        if p["kind"] == "fixed":
            desc = f"{p['emoji']} {p['amount']} Stars"
        elif p["kind"] == "group":
            n = len(get_stars_package_children(p["item_key"], enabled_only=False))
            desc = f"{p['emoji']} {p.get('label') or 'Набір'} ({n} кнопок)"
        else:
            desc = f"{p['emoji']} {p['range_min']}-{p['range_max']}" if p.get("range_max") else f"{p['emoji']} {p['range_min']}+"
        rows.append([InlineKeyboardButton(text=f"{status} {desc}", callback_data=f"adm_spitem_{p['item_key']}")])
    rows.append([InlineKeyboardButton(text="➕ Додати пак", callback_data="adm_spadd")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_star_package_kb(key: str):
    p = get_stars_package(key) or {}
    toggle_label = "🚫 Вимкнути" if p.get("enabled") else "✅ Увімкнути"
    rows = [[InlineKeyboardButton(text="✏️ Емодзі", callback_data=f"adm_spedit_emoji_{key}"),
             InlineKeyboardButton(text="✏️ Підпис", callback_data=f"adm_spedit_label_{key}")]]
    if p.get("kind") == "fixed":
        price_label = f"💰 Ціна: {p['fixed_price']:.0f} грн (вручну)" if p.get("fixed_price") is not None else "💰 Ціна (грн, вручну)"
        rows.append([InlineKeyboardButton(text="⭐ Кількість Stars", callback_data=f"adm_spedit_amount_{key}"),
                     InlineKeyboardButton(text=price_label, callback_data=f"adm_spedit_price_{key}")])
        rows.append([InlineKeyboardButton(text="🖼 Прем-емодзі", callback_data=f"adm_spedit_sticker_{key}")])
        link_label = "🎁 Прив'язаний подарунок ✅" if p.get("linked_gift_key") else "🎁 Прив'язати подарунок"
        rows.append([InlineKeyboardButton(text=link_label, callback_data=f"adm_splink_{key}")])
        if p.get("linked_gift_key"):
            qty = int(p.get("linked_gift_qty") or 1)
            rows.append([InlineKeyboardButton(text=f"🔢 Кількість подарунків: {qty}", callback_data=f"adm_spgiftqty_{key}")])
    elif p.get("kind") == "range":
        rows.append([InlineKeyboardButton(text="🔽 Мін.", callback_data=f"adm_spedit_min_{key}"),
                     InlineKeyboardButton(text="🔼 Макс. (- = без ліміту)", callback_data=f"adm_spedit_max_{key}")])
        rows.append([InlineKeyboardButton(text="🖼 Прем-емодзі", callback_data=f"adm_spedit_sticker_{key}")])
    else:  # group
        rows.append([InlineKeyboardButton(text="🧩 Кнопки набору", callback_data=f"adm_spchildren_{key}")])
        rows.append([InlineKeyboardButton(text="🖼 Прем-емодзі", callback_data=f"adm_spedit_sticker_{key}")])
        rows.append([InlineKeyboardButton(text="📝 Текст при відкритті", callback_data=f"adm_spedit_description_{key}")])
    rows.append([InlineKeyboardButton(text="⬆️ Вище", callback_data=f"adm_sppos_{key}_up"),
                 InlineKeyboardButton(text="⬇️ Нижче", callback_data=f"adm_sppos_{key}_down")])
    rows.append([InlineKeyboardButton(text=toggle_label, callback_data=f"adm_sptoggle_{key}"),
                 InlineKeyboardButton(text="🗑 Видалити", callback_data=f"adm_spdel_{key}")])
    rows.append([InlineKeyboardButton(text="🔙 До паків", callback_data="adm_star_packages")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_sp_link_gift_kb(key: str):
    items = get_gift_items()
    p = get_stars_package(key) or {}
    rows = []
    for gk, item in sorted(items.items(), key=lambda kv: int(kv[0])):
        mark = "✅ " if p.get("linked_gift_key") == gk else ""
        rows.append([InlineKeyboardButton(
            text=f"{mark}{item['emoji']} {item['name']} ({item['price']:.0f} грн)",
            callback_data=f"adm_spdolink_{key}_{gk}")])
    if p.get("linked_gift_key"):
        rows.append([InlineKeyboardButton(text="➖ Відв'язати", callback_data=f"adm_spunlink_{key}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"adm_spitem_{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_sp_children_kb(parent_key: str):
    children = get_stars_package_children(parent_key, enabled_only=False)
    rows = []
    for ch in sorted(children, key=lambda x: (x.get("position") or 0, x["item_key"])):
        status = "✅" if ch.get("enabled") else "🚫"
        rows.append([InlineKeyboardButton(
            text=f"{status} {ch.get('emoji') or '⭐'} {ch['amount']} Stars",
            callback_data=f"adm_spitem_{ch['item_key']}")])
    rows.append([InlineKeyboardButton(text="➕ Додати кнопку", callback_data=f"adm_spaddchild_{parent_key}")])
    rows.append([InlineKeyboardButton(text="🔙 До паку", callback_data=f"adm_spitem_{parent_key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_sp_add_kind_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Фіксований (напр. 15 Stars)", callback_data="adm_spaddkind_fixed")],
        [InlineKeyboardButton(text="✏️ Діапазон (своя сума)", callback_data="adm_spaddkind_range")],
        [InlineKeyboardButton(text="🧩 Набір кнопок (як подарунки)", callback_data="adm_spaddkind_group")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_star_packages")]
    ])

def admin_refs_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 % від покупки",     callback_data="adm_ref_percent")],
        [InlineKeyboardButton(text="✅ Вкл/Викл реферали", callback_data="adm_ref_toggle")],
        [InlineKeyboardButton(text="📋 Кнопка «Скопіювати»", callback_data="adm_copyref_menu")],
        [InlineKeyboardButton(text="🔙 Назад",              callback_data="adm_back")]
    ])

def admin_copyref_kb():
    cur_style = get_setting("btn_copyref_style") or "default"
    cur_ceid = get_setting("btn_copyref_emoji_id") or ""
    styles = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Текст кнопки", callback_data="adm_copyref_text")],
        [InlineKeyboardButton(text=f"🎨 Колір: {styles.get(cur_style,cur_style)}", callback_data="adm_copyref_style")],
        [InlineKeyboardButton(text=f"💎 Premium Emoji: {'встановлено ✅' if cur_ceid else 'не встановлено ❌'}",
                               callback_data="adm_copyref_emoji")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_refs")]
    ])

def admin_prices_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Курс Stars",        callback_data="adm_stars_rate"),
         InlineKeyboardButton(text="💵 Наценка TON",       callback_data="adm_ton_markup")],
        [InlineKeyboardButton(text="💲 Наценка крипти",    callback_data="adm_crypto_markup"),
         InlineKeyboardButton(text="🤖 Наценка CryptoBot", callback_data="adm_cryptobot_markup")],
        [InlineKeyboardButton(text="💎 Ціни Premium",      callback_data="adm_premium_prices")],
        [InlineKeyboardButton(text="💰 Курс викупу Stars", callback_data="adm_sell_rate")],
        [InlineKeyboardButton(text="📉 Мін. нагорода відгук", callback_data="adm_review_reward_min"),
         InlineKeyboardButton(text="📈 Макс. нагорода відгук", callback_data="adm_review_reward_max")],
        [InlineKeyboardButton(text="⭐ Оплата Telegram Stars", callback_data="adm_stars_pay")],
        [InlineKeyboardButton(text="🔙 Назад",             callback_data="adm_back")]
    ])

def admin_stars_pay_kb():
    prem_status = "✅ Увімкнено" if get_setting("stars_pay_premium_enabled") == "1" else "🚫 Вимкнено"
    gift_status = "✅ Увімкнено" if get_setting("stars_pay_gift_enabled") == "1" else "🚫 Вимкнено"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💎 Premium: {prem_status}", callback_data="adm_stars_pay_toggle_premium")],
        [InlineKeyboardButton(text=f"🎁 Подарунки: {gift_status}", callback_data="adm_stars_pay_toggle_gift")],
        [InlineKeyboardButton(text="💎 Ціни Premium в Stars", callback_data="adm_premium_stars_prices")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_prices")]
    ])

def admin_prem_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 3 місяці",   callback_data="adm_prem_3m"),
         InlineKeyboardButton(text="💎 6 місяців",  callback_data="adm_prem_6m")],
        [InlineKeyboardButton(text="💎 12 місяців", callback_data="adm_prem_12m")],
        [InlineKeyboardButton(text="🔙 Назад",       callback_data="adm_back")]
    ])

def admin_prem_stars_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⭐ 3 міс. — {get_setting('premium_3m_stars')} Stars", callback_data="adm_prem_stars_3m")],
        [InlineKeyboardButton(text=f"⭐ 6 міс. — {get_setting('premium_6m_stars')} Stars", callback_data="adm_prem_stars_6m")],
        [InlineKeyboardButton(text=f"⭐ 12 міс. — {get_setting('premium_12m_stars')} Stars", callback_data="adm_prem_stars_12m")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_stars_pay")]
    ])

def admin_minimums_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Мін. Stars",       callback_data="adm_min_stars"),
         InlineKeyboardButton(text="💵 Мін. TON",         callback_data="adm_min_ton")],
        [InlineKeyboardButton(text="💰 Мін. продаж",      callback_data="adm_min_sell"),
         InlineKeyboardButton(text="💸 Мін. вивід Stars",  callback_data="adm_min_withdraw")],
        [InlineKeyboardButton(text="🚫 Ліміт заявок/год", callback_data="adm_req_limit")],
        [InlineKeyboardButton(text="🔙 Назад",            callback_data="adm_back")]
    ])

def admin_cards_kb():
    methods = get_payment_methods()
    rows = []
    for m in methods:
        prefix = f"{m['emoji']} " if m['emoji'] else ""
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{m['name_uk']} — {m['details'] or 'не вказано'}",
            callback_data=f"adm_card_{m['method_key']}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_texts_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👋 Привітання",          callback_data="adm_text_welcome")],
        [InlineKeyboardButton(text="🏠 Головне меню",        callback_data="adm_text_main_menu")],
        [InlineKeyboardButton(text="👤 Профіль",             callback_data="adm_text_profile")],
        [InlineKeyboardButton(text="🎉 Заявка прийнята",     callback_data="adm_text_receipt_ok")],
        [InlineKeyboardButton(text="✅ Замовлення виконано", callback_data="adm_text_order_done")],
        [InlineKeyboardButton(text="⭐ Stars: Кіл-сть",       callback_data="adm_text_enter_stars")],
        [InlineKeyboardButton(text="⭐ Stars: Вибір пакету",  callback_data="adm_text_stars_choose_amount")],
        [InlineKeyboardButton(text="⭐ Stars: Друг username", callback_data="adm_text_enter_friend")],
        [InlineKeyboardButton(text="⭐ Stars: Спосіб оплати", callback_data="adm_text_choose_bank")],
        [InlineKeyboardButton(text="💵 TON: Ввід кіл-сті",   callback_data="adm_text_ton_enter")],
        [InlineKeyboardButton(text="💵 TON: Кошелёк",        callback_data="adm_text_ton_wallet")],
        [InlineKeyboardButton(text="💵 TON: Підсумок",       callback_data="adm_text_ton_summary")],
        [InlineKeyboardButton(text="💎 Premium: Ціни",       callback_data="adm_text_prem_months")],
        [InlineKeyboardButton(text="💸 Вивід: Реквізити",    callback_data="adm_text_sell_wallet")],
        [InlineKeyboardButton(text="💸 Вивід: Підсумок",     callback_data="adm_text_sell_summary")],
        [InlineKeyboardButton(text="💸 Вивід: Прийнято",     callback_data="adm_text_sell_ok")],
        [InlineKeyboardButton(text="💸 Вивід: Виплачено+відгук", callback_data="adm_text_withdraw_paid_review")],
        [InlineKeyboardButton(text="🚀 Premium/Подарунок: Виконано+відгук", callback_data="adm_text_order_done_review")],
        [InlineKeyboardButton(text="💰 Продати Stars (екран)", callback_data="adm_text_sell_stars_promo")],
        [InlineKeyboardButton(text="💬 Відповідь підтримки",  callback_data="adm_text_support_reply")],
        [InlineKeyboardButton(text="💳 Вивід: ввід username", callback_data="adm_text_withdraw_enter_username")],
        [InlineKeyboardButton(text="✅ Підтримка: відправлено", callback_data="adm_text_support_sent")],
        [InlineKeyboardButton(text="👥 Реферали: інфо",       callback_data="adm_text_referral_info")],
        [InlineKeyboardButton(text="🧮 Калькулятор: результат", callback_data="adm_text_calc_stars")],
        [InlineKeyboardButton(text="💬 Підтримка: ввід питання", callback_data="adm_text_support_enter")],
        [InlineKeyboardButton(text="✅ Оплату підтверджено",  callback_data="adm_text_pay_confirmed")],
        [InlineKeyboardButton(text="❌ Заявку відхилено",     callback_data="adm_text_order_rejected")],
        [InlineKeyboardButton(text="💬 Прохання про відгук",  callback_data="adm_text_review_ask")],
        [InlineKeyboardButton(text="🙏 Дякуємо за відгук",    callback_data="adm_text_review_thanks")],
        [InlineKeyboardButton(text="⏭ Відгук пропущено",     callback_data="adm_text_review_skipped")],
        [InlineKeyboardButton(text="💸 Вивід: підтвердження", callback_data="adm_text_sell_confirm_yes")],
        [InlineKeyboardButton(text="🚫 Ви забанені",          callback_data="adm_text_banned")],
        [InlineKeyboardButton(text="⏱ Занадто швидко (флуд)", callback_data="adm_text_flood")],
        [InlineKeyboardButton(text="🚦 Ліміт заявок",         callback_data="adm_text_spam_limit")],
        [InlineKeyboardButton(text="🔙 Назад",                callback_data="adm_back")]
    ])

def admin_methods_kb():
    methods = get_all_payment_methods()
    rows = []
    for m in methods:
        # name_uk вже завжди починається зі свого emoji за конвенцією ("🅿️ PayPal" тощо) —
        # окремий префікс з поля emoji тут не додаємо, інакше емодзі дублюється.
        status = "✅ " if m.get("enabled") else "🚫 "
        rows.append([InlineKeyboardButton(
            text=f"{status}{m['name_uk']} | {m['style']}",
            callback_data=f"adm_method_{m['method_key']}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_method_style_kb(mk):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT enabled FROM payment_methods WHERE method_key=?", (mk,))
    row = c.fetchone(); conn.close()
    is_enabled = bool(row and row["enabled"])
    toggle_label = "🚫 Вимкнути (тимчасово сховати)" if is_enabled else "✅ Увімкнути"
    rows = [
        [InlineKeyboardButton(text=toggle_label, callback_data=f"adm_mtoggle_{mk}")],
        [InlineKeyboardButton(text="✏️ Змінити назву",     callback_data=f"adm_medit_name_{mk}")],
        [InlineKeyboardButton(text="💳 Змінити реквізити", callback_data=f"adm_medit_details_{mk}")],
        [InlineKeyboardButton(text="👤 Власник картки",    callback_data=f"adm_medit_owner_{mk}")],
        [InlineKeyboardButton(text="📝 Весь текст оплати", callback_data=f"adm_medit_instructions_{mk}")],
        [InlineKeyboardButton(text="🖼 Прем-емодзі кнопки", callback_data=f"adm_medit_emoji_{mk}")],
    ]
    if mk == "cryptobot":
        rows.append([InlineKeyboardButton(text="📝 Текст вибору валюти", callback_data=f"adm_medit_cctext_{mk}")])
        rows.append([InlineKeyboardButton(text="🖼 Емодзі TON", callback_data=f"adm_medit_ctonbtn_{mk}"),
                     InlineKeyboardButton(text="🖼 Емодзі USDT", callback_data=f"adm_medit_cusdtbtn_{mk}")])
        rows.append([InlineKeyboardButton(text="✏️ Текст TON", callback_data=f"adm_medit_ctontext_{mk}"),
                     InlineKeyboardButton(text="✏️ Текст USDT", callback_data=f"adm_medit_cusdttext_{mk}")])
        rows.append([InlineKeyboardButton(text="🟢 Валюта Success", callback_data=f"adm_mcstl_{mk}_success"),
                     InlineKeyboardButton(text="🔵 Валюта Primary", callback_data=f"adm_mcstl_{mk}_primary")])
        rows.append([InlineKeyboardButton(text="🔴 Валюта Danger", callback_data=f"adm_mcstl_{mk}_danger"),
                     InlineKeyboardButton(text="⬜ Валюта Default", callback_data=f"adm_mcstl_{mk}_default")])
        rows.append([InlineKeyboardButton(text="📝 Текст після вибору валюти", callback_data=f"adm_medit_ctext_{mk}")])
        rows.append([InlineKeyboardButton(text="🖼 Емодзі «Оплатити»", callback_data=f"adm_medit_cpaybtn_{mk}"),
                     InlineKeyboardButton(text="🖼 Емодзі «Перевірити»", callback_data=f"adm_medit_ccheckbtn_{mk}")])
        rows.append([InlineKeyboardButton(text="✏️ Текст «Оплатити»", callback_data=f"adm_medit_cpaytext_{mk}"),
                     InlineKeyboardButton(text="✏️ Текст «Перевірити»", callback_data=f"adm_medit_cchecktext_{mk}")])
    rows += [
        [InlineKeyboardButton(text="⬆️ Вище", callback_data=f"adm_mpos_{mk}_up"),
         InlineKeyboardButton(text="⬇️ Нижче", callback_data=f"adm_mpos_{mk}_down")],
        [InlineKeyboardButton(text="🟢 Success", callback_data=f"adm_mstl_{mk}_success"),
         InlineKeyboardButton(text="🔵 Primary", callback_data=f"adm_mstl_{mk}_primary")],
        [InlineKeyboardButton(text="🔴 Danger",  callback_data=f"adm_mstl_{mk}_danger"),
         InlineKeyboardButton(text="⬜ Default", callback_data=f"adm_mstl_{mk}_default")],
        [InlineKeyboardButton(text="🔙 Назад",   callback_data="adm_methods")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_menu_btns_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Назви кнопок", callback_data="admbtn_text")],
        [InlineKeyboardButton(text="💅 Стиль кнопок",  callback_data="admbtn_style"),
         InlineKeyboardButton(text="🔢 Порядок",        callback_data="admbtn_order")],
        [InlineKeyboardButton(text="🎨 Пакети Stars",  callback_data="adm_btn_pkg_style"),
         InlineKeyboardButton(text="🎨 Своя кіл-сть",   callback_data="adm_btn_pkg_custom_style")],
        [InlineKeyboardButton(text="💎 Емодзі пакетів Stars", callback_data="adm_btn_pkg_emoji")],
        [InlineKeyboardButton(text="🎨 Місяці Premium", callback_data="adm_btn_month_style")],
        [InlineKeyboardButton(text="🔙 Назад",          callback_data="adm_back")]
    ])

def admin_select_btn_kb():
    btns = get_menu_buttons()
    rows = [[InlineKeyboardButton(
        text=f"{b['emoji']} {b['text_uk']}",
        callback_data=f"admbtnsel_{b['button_key']}")] for b in btns]
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admbtn_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_style_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Success", callback_data="admbtnstl_success"),
         InlineKeyboardButton(text="🔵 Primary", callback_data="admbtnstl_primary")],
        [InlineKeyboardButton(text="🔴 Danger",  callback_data="admbtnstl_danger"),
         InlineKeyboardButton(text="⬜ Default", callback_data="admbtnstl_default")],
        [InlineKeyboardButton(text="🔙 Назад",   callback_data="admbtn_back")]
    ])

def user_profile_admin_kb(uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Нарахувати Stars", callback_data=f"adm_give_stars_{uid}"),
         InlineKeyboardButton(text="💰 Списати Stars",    callback_data=f"adm_take_stars_{uid}")],
        [InlineKeyboardButton(text="🚫 Забанити",         callback_data=f"adm_ban_{uid}"),
         InlineKeyboardButton(text="✅ Розбанити",        callback_data=f"adm_unban_{uid}")],
        [InlineKeyboardButton(text="💬 Написати",         callback_data=f"adm_msg_{uid}")],
        [InlineKeyboardButton(text="🔙 Назад",            callback_data="adm_back")]
    ])

def back_cancel_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔙 Назад")], [KeyboardButton(text="❌ Скасувати")]
    ], resize_keyboard=True)

# ========================================================
# STATES
# ========================================================

class S(StatesGroup):
    menu = State()
    stars_amount = State(); stars_amount_custom = State(); stars_pkg_recipient = State()
    stars_bank = State(); stars_receipt = State()
    ton_amount = State(); ton_wallet_s = State(); ton_bank = State(); ton_receipt = State()
    gift_recipient = State(); gift_comment = State(); gift_bank = State(); gift_receipt = State()
    admin_gift_edit = State(); admin_gift_api_creds = State()
    admin_gift_add_emoji = State(); admin_gift_add_price = State()
    admin_sp_edit = State(); admin_sp_add = State()
    gift_login_phone = State(); gift_login_code = State(); gift_login_password = State()
    prem_user = State(); prem_months = State(); prem_bank = State(); prem_receipt = State()
    sell_amount = State(); sell_wallet_s = State(); sell_confirm = State()
    withdraw_amount = State(); withdraw_wallet = State()
    calc_stars = State()
    support = State(); admin = State(); admin_broadcast = State()
    admin_stars_rate = State(); admin_ton_markup = State(); admin_sell_rate = State()
    admin_card_edit = State()
    admin_min_stars = State(); admin_min_ton = State(); admin_min_sell = State()
    admin_gift_edit_price = State()
    admin_min_withdraw = State(); admin_req_limit = State()
    admin_prem_price = State()
    admin_edit_text = State(); admin_photo_upload = State(); admin_btn_order = State()
    admin_text_edit = State()
    admin_find_user = State()
    admin_give_stars = State(); admin_take_stars = State(); admin_gset = State(); withdraw_reject_reason = State()
    admin_ban = State(); admin_msg_user = State()
    waiting_review = State(); review_photo = State(); review_text = State()
    admin_review_reward_min = State(); admin_review_reward_max = State()
    admin_pkg_emoji = State()
    admin_copyref_text = State()
    admin_copyref_emoji = State()
    admin_review_reject_reason = State()
    admin_reject = State(); admin_reply = State()

# ========================================================
# ОТПРАВКА В АДМІН ЧАТ
# ========================================================

async def send_to_admin(message, oid, text, order_type="stars"):
    sent = False
    kb = order_kb(oid, order_type)
    try:
        if message.photo:
            await bot.send_photo(ADMIN_CHAT_ID, photo=message.photo[-1].file_id,
                                 caption=text, reply_markup=kb, parse_mode="HTML")
        elif message.document:
            await bot.send_document(ADMIN_CHAT_ID, document=message.document.file_id,
                                    caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await bot.send_message(ADMIN_CHAT_ID, text+"\n\n⚠️ Квитанція не прикріплена!",
                                   reply_markup=kb, parse_mode="HTML")
        sent = True
    except Exception as e:
        logger.error(f"❌ Помилка групи: {e}")
    if not sent:
        try:
            fb = f"⚠️ <b>НЕ ВДАЛОСЯ В ГРУПУ!</b>\n\n{text}"
            if message.photo:
                await bot.send_photo(ADMIN_IDS[0], photo=message.photo[-1].file_id, caption=fb, reply_markup=kb, parse_mode="HTML")
            else:
                await bot.send_message(ADMIN_IDS[0], fb+"\n\n⚠️ Квитанція не прикріплена!", reply_markup=kb, parse_mode="HTML")
        except Exception as e2:
            logger.error(f"❌ Резерв: {e2}")

# ========================================================
# МІДЛВАР АНТИФЛУД + БАН
# ========================================================

async def check_user(msg_or_cb, state):
    uid = msg_or_cb.from_user.id
    if uid in ADMIN_IDS: return True
    u = get_user(uid)
    if u and u.get("banned"):
        reason = u.get("ban_reason","")
        text = T("banned",reason=reason)
        if hasattr(msg_or_cb, 'answer'):
            await msg_or_cb.answer(text)
        return False
    if hasattr(msg_or_cb, 'text') and check_flood(uid):
        txt = getattr(msg_or_cb, 'text', '') or ''
        safe_btns = ['/start', '🔙 Назад', '❌ Скасувати']
        if any(s in txt for s in safe_btns):
            pass
        else:
            await msg_or_cb.answer(T("flood"))
            return False
    return True

# ========================================================
# ХЕНДЛЕРИ — СТАРТ І МЕНЮ
# ========================================================

async def process_referral_and_welcome(uid, username, first_name, deep, state: FSMContext):
    """Реєстрація + реферальна логіка + привітальне меню.
    Винесено окремо, щоб однаково відпрацьовувало і з /start, і після
    підтвердження обов'язкової підписки (де deep-link інакше губився)."""
    if deep == 'support':
        register_user(uid, username, first_name)
        update_user_active(uid)
        await bot.send_message(uid,
            f'🎧 <b>Підтримка {BOT_NAME}</b>\n\n'
            f'<b>Привіт, {first_name}!</b>\n\n'
            f'✍️ <b>Напишіть ваше питання або проблему — ми відповімо якомога швидше:</b>',
            reply_markup=cancel_kb())
        await state.set_state(S.support)
        return

    # Реферальна система
    ref_by = 0
    if deep:
        try:
            ref_by = int(deep)
            if ref_by == uid: ref_by = 0
        except:
            if deep.startswith('ref'):
                try:
                    ref_by = int(deep[3:])
                    if ref_by == uid: ref_by = 0
                except: pass

    logger.info(f"[REF] /start from uid={uid} raw_deep={deep!r} parsed_ref_by={ref_by}")

    is_new = register_user(uid, username, first_name, ref_by)
    logger.info(f"[REF] uid={uid} is_new={is_new} ref_enabled={get_setting('ref_enabled')!r}")

    # Дозволяємо прив'язку реферера і для вже існуючого (але "порожнього") юзера:
    # якщо він ще нікого не купував і в нього ще немає реферера — це не накрутка,
    # а типовий випадок "писав боту раніше, але реально прийшов лише зараз".
    existing_user = None if is_new else get_user(uid)
    can_attach_ref = bool(
        ref_by and get_setting("ref_enabled") == "1" and (
            is_new or (existing_user and not (existing_user.get("ref_by") or 0)
                       and not (existing_user.get("total_spent") or 0))
        )
    )
    if ref_by and not can_attach_ref:
        if not is_new and existing_user and (existing_user.get("ref_by") or 0):
            logger.info(f"[REF] SKIPPED: uid={uid} вже має свого реферера")
        elif not is_new and existing_user and (existing_user.get("total_spent") or 0):
            logger.info(f"[REF] SKIPPED: uid={uid} вже робив покупки раніше — реферал не зараховано")
        elif get_setting("ref_enabled") != "1":
            logger.info(f"[REF] SKIPPED: реферали вимкнені в налаштуваннях (ref_enabled != '1')")

    if can_attach_ref:
        conn = get_conn(); c = conn.cursor()
        c.execute("UPDATE users SET ref_by=?, ref_count=ref_count WHERE user_id=? AND ref_by=0", (ref_by, uid))
        c.execute("UPDATE users SET ref_count=ref_count+1 WHERE user_id=?", (ref_by,))
        conn.commit(); conn.close()
        logger.info(f"[REF] OK: ref_by={ref_by} отримав +1 до ref_count (запрошений uid={uid})")
        ref_percent = int(get_setting("ref_percent_purchase") or 5)
        referer = get_user(ref_by)
        if referer:
            try:
                await bot.send_message(ref_by,
                    f"🎉 <b>За вашим реферальним посиланням зареєструвався новий користувач!</b>\n"
                    f"💰 <b>Ви будете отримувати {ref_percent}% від кожної його покупки!</b>")
            except: pass

    welcome = get_bot_text("welcome") or f"👋 <b>Привіт, {first_name}!</b>"
    welcome = welcome.replace("{name}", first_name or "")
    await send_menu(uid, welcome)


@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    update_user_active(uid, username=msg.from_user.username, full_name=msg.from_user.first_name)

    args = msg.text.split() if msg.text else []
    deep = args[1] if len(args) > 1 else ''

    if not await check_subscription(uid):
        # Зберігаємо deep-link ДО показу гейту підписки — інакше після натискання
        # "✅ Перевірити підписку" (окремий callback) реферальний параметр губиться.
        await state.update_data(pending_deep=deep)
        channels = [c.strip() for c in (get_setting("sub_channels") or REVIEWS_CHANNEL).split(",") if c.strip()]
        ch_text = "\n".join([f"🔗 @{ch.lstrip('@')}" for ch in channels])
        channel_buttons = [
            [InlineKeyboardButton(text=f"📢 Перейти на @{ch.lstrip('@')}", url=f"https://t.me/{ch.lstrip('@')}")]
            for ch in channels
        ]
        channel_buttons.append([InlineKeyboardButton(text="✅ Перевірити підписку", callback_data="check_sub")])
        await msg.answer(
            f"📢 <b>Обов'язкова підписка</b>\n\n"
            f"Щоб користуватись ботом, підпишіться на канали:\n\n"
            f"{ch_text}\n\n"
            f"Після підписки натисніть кнопку нижче:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=channel_buttons),
            parse_mode="HTML"
        )
        return

    await state.set_state(S.menu)
    await process_referral_and_welcome(uid, msg.from_user.username, msg.from_user.first_name, deep, state)

@dp.message(Command("menu"))
async def cmd_menu(msg: Message, state: FSMContext):
    if not await check_user(msg, state): return
    await state.set_state(S.menu)
    await send_menu(msg.from_user.id, T("main_menu"))

@dp.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    await state.set_state(S.admin)
    await msg.answer("🛠 <b>Панель адміністратора</b>", reply_markup=admin_main_kb(), parse_mode="HTML")

@dp.message(Command("profile"))
async def cmd_profile(msg: Message, state: FSMContext):
    if not await check_user(msg, state): return
    await show_profile(msg.from_user.id, msg, state)

def get_user_status(total_spent):
    if total_spent >= 500:
        return "💎 VIP Клієнт"
    elif total_spent >= 200:
        return "⭐ Досвідчений"
    else:
        return "👤 Новачок"

async def show_profile(uid, msg_or_cb, state=None):
    u = get_user(uid)
    if not u:
        from_user = getattr(msg_or_cb, 'from_user', None)
        username = getattr(from_user, 'username', None) if from_user else None
        full_name = getattr(from_user, 'full_name', None) if from_user else None
        register_user(uid, username, full_name)
        u = get_user(uid)
        if not u:
            try:
                await bot.send_message(uid, "⚠️ Сталася помилка завантаження профілю. Спробуйте /start")
            except: pass
            return

    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref{uid}"
    status = get_user_status(float(u.get("total_spent", 0)))
    registered = str(u.get("registered_at",""))[:10]
    username = u.get("username") or "—"
    balance = u.get("stars_balance", 0)
    total_spent = round(float(u.get("total_spent", 0)), 2)
    stars_bought = u.get("stars_bought", 0)
    ton_bought = u.get("ton_bought", 0)
    prem_bought = u.get("premium_bought", 0)
    ref_count = u.get("ref_count", 0)

    # Текст профілю — завжди фіксований український варіант (не береться з БД)
    text = (
        f"👤 <b>Ваш профіль</b>\n\n"
        f"🆔 <b>ID:</b> <code>{u['user_id']}</code>\n"
        f"👤 <b>Username:</b> @{username}\n\n"
        f"⭐ <b>Баланс: {balance} Stars</b>\n"
        f"📊 Статус: <b>{status}</b>\n\n"
        f"⭐ Куплено Stars: <b>{stars_bought}</b>\n"
        f"💎 Куплено TON: <b>{ton_bought}</b>\n"
        f"🚀 Premium: <b>{prem_bought} міс.</b>\n"
        f"💰 Витрачено: <b>{total_spent} грн</b>\n\n"
        f"👥 Запрошено друзів: <b>{ref_count}</b>\n\n"
        f"📅 Дата реєстрації: <b>{registered}</b>"
    )

    try:
        profile_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вивести Stars", callback_data="profile_withdraw", style="danger"),
             InlineKeyboardButton(text="👥 Запросити друга", callback_data="profile_invite", style="primary")],
        ])
    except TypeError:
        profile_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вивести Stars", callback_data="profile_withdraw"),
             InlineKeyboardButton(text="👥 Запросити друга", callback_data="profile_invite")],
        ])

    photo_id = get_setting("photo_profile")

    if hasattr(msg_or_cb, 'answer'):
        if photo_id:
            await msg_or_cb.answer_photo(photo=photo_id, caption=text, reply_markup=profile_kb, parse_mode='HTML')
        else:
            await msg_or_cb.answer(text, reply_markup=profile_kb, parse_mode='HTML')
    else:
        if photo_id:
            await msg_or_cb.message.answer_photo(photo=photo_id, caption=text, reply_markup=profile_kb, parse_mode='HTML')
        else:
            await msg_or_cb.message.answer(text, reply_markup=profile_kb, parse_mode='HTML')
    if state:
        await state.set_state(S.menu)

def build_copyref_button(ref_link: str) -> InlineKeyboardButton:
    text = get_setting("btn_copyref_text") or "📋 Скопіювати посилання"
    style = get_setting("btn_copyref_style") or "default"
    ceid = get_setting("btn_copyref_emoji_id") or ""
    kwargs = {"copy_text": CopyTextButton(text=ref_link)}
    if style and style != "default":
        kwargs["style"] = style
    if ceid:
        kwargs["icon_custom_emoji_id"] = ceid
    try:
        return InlineKeyboardButton(text=text, **kwargs)
    except TypeError:
        return InlineKeyboardButton(text=text, copy_text=CopyTextButton(text=ref_link))

@dp.callback_query(F.data == "profile_invite")
async def profile_invite_cb(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref{uid}"
    ref_percent = get_setting("ref_percent_purchase") or "5"
    u = get_user(uid) or {}
    ref_count = u.get("ref_count", 0)
    text = T("referral_info", ref_link=ref_link, percent=ref_percent, ref_count=ref_count)
    try:
        share_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📤 Поділитись посиланням",
                url=f"https://t.me/share/url?url={ref_link}&text={'Приєднуйся до ' + BOT_NAME + '!'}"
            )],
            [build_copyref_button(ref_link)]
        ])
    except TypeError:
        share_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поділитись посиланням",
                                   url=f"https://t.me/share/url?url={ref_link}&text={'Приєднуйся до ' + BOT_NAME + '!'}")]
        ])
    await cb.message.answer(text, reply_markup=share_kb, parse_mode="HTML")

@dp.callback_query(F.data == "profile_withdraw")
async def profile_withdraw_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    u = get_user(cb.from_user.id)
    balance = u.get("stars_balance", 0) if u else 0
    min_withdraw = int(get_setting("min_withdraw") or 50)
    if balance < min_withdraw:
        await cb.message.answer(
            f"❌ <b>Недостатньо коштів для виводу.</b>\n\n"
            f"💰 Ваш баланс: <b>{balance} Stars</b>\n"
            f"📌 Мінімум для виводу: <b>{min_withdraw} Stars</b>",
            parse_mode="HTML")
        return
    await cb.message.answer(
        f"💸 <b>Вивід Stars</b>\n\n"
        f"💰 Ваш баланс: <b>{balance} Stars</b>\n\n"
        f"⭐ Скільки Stars хочете вивести?",
        reply_markup=cancel_kb(), parse_mode="HTML")
    await state.set_state(S.withdraw_amount)

@dp.message(S.withdraw_amount)
async def withdraw_amount(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    try:
        amount = int(msg.text.strip())
    except:
        await msg.answer(T("err_num")); return
    u = get_user(msg.from_user.id)
    balance = u.get("stars_balance", 0) if u else 0
    min_withdraw = int(get_setting("min_withdraw") or 50)
    if amount < min_withdraw:
        await msg.answer(f"❌ Мінімум для виводу: <b>{min_withdraw} Stars</b>", parse_mode="HTML"); return
    if amount > balance:
        await msg.answer(f"❌ Недостатньо коштів. Ваш баланс: <b>{balance} Stars</b>", parse_mode="HTML"); return
    await state.update_data(withdraw_amount=amount)
    await msg.answer(T("withdraw_enter_username"), reply_markup=cancel_kb())
    await state.set_state(S.withdraw_wallet)

@dp.message(S.withdraw_wallet)
async def withdraw_wallet(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    username = msg.text.strip()
    if not username.startswith("@") or len(username) < 4:
        await msg.answer("❌ <b>Невірний формат.</b>\n\nВведіть @username коректно:", parse_mode="HTML")
        return
    data = await state.get_data()
    amount = data.get("withdraw_amount")
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE users SET stars_balance=stars_balance-? WHERE user_id=?", (amount, msg.from_user.id))
    conn.commit(); conn.close()
    wid = create_withdrawal(msg.from_user.id, amount, username)
    admin_text = (f"💸 <b>Заявка на вивід #{wid}</b>\n\n"
                  f"👤 {msg.from_user.username and f'@{msg.from_user.username}' or msg.from_user.id}\n"
                  f"⭐ Сума: <b>{amount} Stars</b>\n"
                  f"👤 Отримувач: <code>{username}</code>")
    try:
        await bot.send_message(ADMIN_CHAT_ID, admin_text, reply_markup=withdraw_kb(wid), parse_mode="HTML")
    except:
        try: await bot.send_message(ADMIN_ID, admin_text, reply_markup=withdraw_kb(wid), parse_mode="HTML")
        except: pass
    await msg.answer(
        f"✅ <b>Заявку на вивід прийнято!</b>\n\n"
        f"⭐ Сума: <b>{amount} Stars</b>\n"
        f"👤 Отримувач: <code>{username}</code>\n\n"
        f"⏳ Обробка протягом 15 хвилин.",
        parse_mode="HTML")
    await state.set_state(S.menu)
    await send_menu(msg.from_user.id, T("main_menu"))

async def _notify_user_withdraw_paid(w: dict, wid: int) -> None:
    """Єдине повідомлення покупцю: підтвердження виплати + запит відгуку."""
    uid = w["user_id"]
    text = (get_bot_text("withdraw_paid_review") or
            "✅ <b>Вивід #{wid} виплачено!</b>\n\n⭐ Сума: <b>{amount} Stars</b>\n\n"
            "🎁 <b>Залиште відгук і отримайте 1-2 Stars на баланс безкоштовно!</b>\n\n"
            "📸 <b>Спочатку прикріпіть фото або скріншот покупки.</b>\n"
            "<i>(це обов'язково — без фото відгук не буде прийнято)</i>\n\n"
            "<blockquote>Це дуже важливо для нас 🙂</blockquote>\n\n"
            "<i>Натисніть «Пропустити» якщо не хочете залишати відгук.</i>"
           ).replace("{wid}", str(wid)).replace("{amount}", str(w["amount"]))
    try:
        user_state = FSMContext(storage=storage,
            key=StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid))
        await user_state.update_data(review_order_type="stars", review_amount=w["amount"])
        await user_state.set_state(S.waiting_review)
        await bot.send_message(uid, text, reply_markup=review_kb(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"review request error (withdraw): {e}")

@dp.callback_query(F.data.startswith("pay_withdraw_"))
async def pay_withdraw(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    wid = int(cb.data.split("_")[-1])
    w = get_withdrawal(wid)
    if not w:
        await cb.message.answer("❌ Заявку не знайдено"); return
    if w.get("status") == "paid":
        await cb.message.answer("ℹ️ Цю заявку вже виплачено."); return

    if not AUTO_WITHDRAW_ENABLED:
        # Автовивід не налаштовано — стара поведінка: адмін платить вручну, бот просто фіксує.
        mark_withdrawal_result(wid, "paid", "manual")
        await _notify_user_withdraw_paid(w, wid)
        try:
            await cb.message.edit_text(cb.message.text + "\n\n✅ <b>ВИПЛАЧЕНО (вручну)</b>", parse_mode="HTML")
        except: pass
        return

    # Одразу показуємо, що почали — автовивід (очікування задачі) може займати до кількох хвилин,
    # без цього виглядає ніби кнопка нічого не зробила.
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except: pass
    processing_msg = None
    try:
        processing_msg = await cb.message.answer("⏳ <b>Виконую автовивід...</b>\n\nЦе може зайняти до кількох хвилин, зачекайте.", parse_mode="HTML")
    except: pass

    # Спроба автовиводу через apifragment.online
    result = await fragment_send_stars(w["wallet"], w["amount"])
    if result["ok"]:
        mark_withdrawal_result(wid, "paid", "auto", tx_id=result.get("tx_id", ""))
        await _notify_user_withdraw_paid(w, wid)
        tx_note = f"\n🧾 Task ID: <code>{result['tx_id']}</code>" if result.get("tx_id") else ""
        try:
            await cb.message.edit_text(cb.message.text + f"\n\n✅ <b>ВИПЛАЧЕНО (авто)</b>{tx_note}", parse_mode="HTML")
        except: pass
        if processing_msg:
            try: await processing_msg.delete()
            except: pass
    else:
        mark_withdrawal_result(wid, "pending", "failed", error_message=result.get("error", ""))
        fail_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔁 Спробувати ще раз", callback_data=f"pay_withdraw_{wid}"),
            InlineKeyboardButton(text="✍️ Підтвердити вручну", callback_data=f"manual_withdraw_{wid}")
        ]])
        fail_text = f"❌ <b>АВТОВИВІД НЕ ВДАВСЯ</b>\n<i>{result.get('error','')[:500]}</i>"
        if processing_msg:
            try:
                await processing_msg.edit_text(fail_text, reply_markup=fail_kb, parse_mode="HTML")
            except:
                await cb.message.answer(fail_text, reply_markup=fail_kb, parse_mode="HTML")
        else:
            await cb.message.answer(fail_text, reply_markup=fail_kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("manual_withdraw_"))
async def manual_withdraw(cb: CallbackQuery, state: FSMContext):
    """Фолбек: адмін сам оплатив на Fragment вручну і підтверджує це в боті."""
    await cb.answer()
    wid = int(cb.data.split("_")[-1])
    w = get_withdrawal(wid)
    if not w:
        await cb.message.answer("❌ Заявку не знайдено"); return
    if w.get("status") == "paid":
        await cb.message.answer("ℹ️ Цю заявку вже виплачено."); return
    mark_withdrawal_result(wid, "paid", "manual")
    await _notify_user_withdraw_paid(w, wid)
    try:
        await cb.message.edit_text(cb.message.text + "\n\n✅ <b>ВИПЛАЧЕНО (вручну)</b>", parse_mode="HTML")
    except: pass

@dp.callback_query(F.data.startswith("rej_withdraw_"))
async def rej_withdraw(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    wid = int(cb.data.split("_")[-1])
    await state.update_data(reject_withdraw_id=wid)
    await cb.message.answer("📝 Вкажіть причину відхилення:", reply_markup=cancel_kb())
    await state.set_state(S.withdraw_reject_reason)

@dp.message(S.withdraw_reject_reason)
async def withdraw_reject_reason_handler(msg: Message, state: FSMContext):
    data = await state.get_data()
    wid = data.get("reject_withdraw_id")
    w = get_withdrawal(wid)
    if w:
        conn = get_conn(); c = conn.cursor()
        c.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (wid,))
        c.execute("UPDATE users SET stars_balance=stars_balance+? WHERE user_id=?", (w["amount"], w["user_id"]))
        conn.commit(); conn.close()
        try:
            await bot.send_message(w["user_id"],
                f"❌ <b>Вивід #{wid} відхилено.</b>\n\n📝 Причина: {msg.text}\n\n💰 Кошти повернуто на баланс.",
                parse_mode="HTML")
        except: pass
    await msg.answer("✅ Заявку відхилено, кошти повернуто користувачу.", reply_markup=admin_main_kb())
    await state.set_state(S.admin)

@dp.message(StateFilter(S.menu, None), ~F.text.startswith("/"), ~StateFilter(S.admin_photo_upload))
async def menu_handler(msg: Message, state: FSMContext):
    if not await check_user(msg, state): return
    update_user_active(msg.from_user.id)
    btns = get_menu_buttons()

    def matches(key):
        for b in btns:
            if b["button_key"] == key:
                if (b.get("text_uk","") in (msg.text or "") or b.get("text_ru","") in (msg.text or "")
                        or b.get("text_en","") in (msg.text or "")):
                    return True
        return False

    need_sub_keys = ["stars","ton","premium","sell_stars","profile","support","calculator","gift"]
    if any(matches(k) for k in need_sub_keys):
        if not await check_subscription(msg.from_user.id):
            await msg.answer(
                "📢 <b>Потрібна підписка на канали:</b>\n\n"
                "Щоб продовжити, будь ласка, підпишіться на наші канали:",
                reply_markup=sub_required_kb(),
                parse_mode="HTML")
            return

    if matches("stars"):
        rate = float(get_setting("stars_rate") or 0.74)
        username = f"@{msg.from_user.username or msg.from_user.id}"
        await state.update_data(recipient=username)
        txt = T("stars_choose_amount", username=username)
        await msg.answer(txt, reply_markup=stars_packages_kb(rate), parse_mode="HTML")
        await state.set_state(S.stars_amount)

    elif matches("ton"):
        rate = get_ton_rate()
        await state.update_data(ton_rate=rate)
        try:
            ton_nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Скасувати", callback_data="ton_cancel", style="danger")
            ]])
        except TypeError:
            ton_nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Скасувати", callback_data="ton_cancel")
            ]])
        await msg.answer(T("ton_enter",rate=rate,min=get_setting("min_ton")), reply_markup=ton_nav_kb, parse_mode="HTML")
        await state.set_state(S.ton_amount)

    elif matches("premium"):
        txt = "👤 <b>Введіть @username для кого купуємо Premium:</b>"
        try:
            prem_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Скасувати", callback_data="prem_cancel", style="danger")
            ]])
        except TypeError:
            prem_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Скасувати", callback_data="prem_cancel")
            ]])
        await msg.answer(txt, reply_markup=prem_kb, parse_mode="HTML")
        await state.set_state(S.prem_user)

    elif matches("gift"):
        await show_gifts_menu(msg.from_user.id)

    elif matches("sell_stars"):
        rate = float(get_setting("sell_stars_rate") or 0.50)
        min_s = int(get_setting("min_sell_stars") or 50)
        example = round(1000 * rate, 0)
        db_text = get_bot_text("sell_stars_promo")
        if db_text:
            txt = (db_text
                   .replace("{rate}", str(rate))
                   .replace("{min}", str(min_s))
                   .replace("{example}", str(int(example))))
        else:
            txt = (
                f"💰 <b>Продаж Stars — швидко та вигідно!</b>\n\n"
                f"📊 <b>Наш курс викупу:</b>\n"
                f"<b>1⭐ = {rate} грн</b>\n"
                f"<b>Мінімум — {min_s} Stars</b>\n\n"
                f"🔥 <b>Приклад:</b>\n"
                f"<b>1000⭐ = {int(example)} грн на твій рахунок!</b>\n\n"
                f"⚡ <b>Обробка до 5 хвилин</b>\n\n"
                f"👇 <b>Напиши нам і ми все оформимо:</b>"
            )
        sell_contact = get_setting("sell_contact") or "@teddyluxxRep"
        try:
            sell_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"👤 {sell_contact}", url=f"https://t.me/{sell_contact.lstrip('@')}", style="primary")
            ]])
        except TypeError:
            sell_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"👤 {sell_contact}", url=f"https://t.me/{sell_contact.lstrip('@')}")
            ]])
        await msg.answer(txt, reply_markup=sell_kb, parse_mode="HTML")

    elif matches("calculator"):
        await msg.answer("🧮 <b>Введіть кількість Stars для розрахунку:</b>", reply_markup=cancel_kb(), parse_mode="HTML")
        await state.set_state(S.calc_stars)

    elif matches("reviews"):
        clean_channel = REVIEWS_CHANNEL.lstrip('@')
        try:
            reviews_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Подивитись відгуки 🤩",
                                     url=f"https://t.me/{clean_channel}", style="primary")
            ]])
        except TypeError:
            reviews_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Подивитись відгуки 🤩",
                                     url=f"https://t.me/{clean_channel}")
            ]])
        await msg.answer(
            f"💬 <b>Відгуки наших клієнтів</b>\n\n"
            f"Переглянути реальні відгуки можна в нашому каналі 👇",
            reply_markup=reviews_kb, parse_mode="HTML")

    elif matches("referral"):
        uid = msg.from_user.id
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref{uid}"
        ref_percent = get_setting("ref_percent_purchase") or "5"
        u = get_user(uid) or {}
        ref_count = u.get("ref_count", 0)
        text = T("referral_info", ref_link=ref_link, percent=ref_percent, ref_count=ref_count)
        try:
            share_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📤 Поділитись посиланням",
                    url=f"https://t.me/share/url?url={ref_link}&text={'Приєднуйся до ' + BOT_NAME + '!'}")],
                [build_copyref_button(ref_link)]
            ])
        except TypeError:
            share_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📤 Поділитись посиланням",
                                      url=f"https://t.me/share/url?url={ref_link}&text={'Приєднуйся до ' + BOT_NAME + '!'}")
            ]])
        await msg.answer(text, reply_markup=share_kb, parse_mode="HTML")

    elif matches("support"):
        await msg.answer(T("support_enter"), reply_markup=cancel_kb())
        await state.set_state(S.support)

    elif matches("profile"):
        await show_profile(msg.from_user.id, msg, state)

# ========================================================
# ПОКУПКА STARS
# ========================================================

@dp.callback_query(F.data.in_({"prem_cancel", "gift_cancel", "ton_cancel"}))
async def purchase_cancel_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(S.menu)
    try: await cb.message.delete()
    except: pass
    await send_menu(cb.from_user.id, T("main_menu"))

@dp.callback_query(F.data.startswith("pkg_"), S.stars_amount)
async def stars_pkg_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    key = cb.data.replace("pkg_", "", 1)
    pkg = get_stars_package(key)
    if not pkg or not pkg.get("enabled", 1):
        await cb.answer("❌ Цей пак недоступний", show_alert=True); return
    if pkg["kind"] == "range":
        await state.update_data(pkg_range_min=pkg.get("range_min"), pkg_range_max=pkg.get("range_max"))
        min_v = pkg.get("range_min") or int(get_setting("min_stars") or 50)
        max_v = pkg.get("range_max")
        hint = f"від {min_v} до {max_v}" if max_v else f"від {min_v}"
        txt = f"⭐ <b>Введіть кількість Stars ({hint}):</b>"
        try: await cb.message.edit_text(txt, reply_markup=None, parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=cancel_kb())
        await state.set_state(S.stars_amount_custom)
        return
    amount = pkg["amount"]
    price = pkg["fixed_price"] if pkg.get("fixed_price") is not None else round(amount * float(get_setting("stars_rate") or 0.74), 2)
    await state.update_data(stars_amount=amount, stars_price=price, pkg_parent_key=pkg.get("parent_key"), pkg_key=pkg["item_key"])

    linked_gift = get_linked_gift_for_package(pkg["item_key"])
    if linked_gift:
        # Цей пак насправді видає справжній подарунок — питаємо кому його надіслати.
        txt = "<b>👤 Кому надіслати подарунок?</b>"
        kb = stars_pkg_recipient_kb(pkg["item_key"])
        try: await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=kb, parse_mode="HTML")
        return

    back_btn = None
    if pkg.get("parent_key"):
        try:
            back_btn = InlineKeyboardButton(text="🔙 Назад", callback_data=f"pkgback_{pkg['parent_key']}", style="default")
        except TypeError:
            back_btn = InlineKeyboardButton(text="🔙 Назад", callback_data=f"pkgback_{pkg['parent_key']}")
    kb = bank_kb(back_button=back_btn)
    try: await cb.message.edit_text(T("choose_bank",price=fmt_price_bold(price),amount=stars_amount_label(amount)), reply_markup=kb, parse_mode="HTML")
    except: await cb.message.answer(T("choose_bank",price=fmt_price_bold(price),amount=stars_amount_label(amount)), reply_markup=kb)
    await state.set_state(S.stars_bank)

async def _proceed_to_stars_pkg_bank(target, state: FSMContext, edit: bool):
    """Спільна логіка показу вибору способу оплати після того, як визначено отримувача
    (використовується і для «Собі», і після вводу @username друга)."""
    data = await state.get_data()
    amount = data.get("stars_amount")
    price = data.get("stars_price")
    pkg_key = data.get("pkg_key")
    pkg = get_stars_package(pkg_key) if pkg_key else None
    back_btn = None
    if pkg and pkg.get("parent_key"):
        try:
            back_btn = InlineKeyboardButton(text="🔙 Назад", callback_data=f"pkgback_{pkg['parent_key']}", style="default")
        except TypeError:
            back_btn = InlineKeyboardButton(text="🔙 Назад", callback_data=f"pkgback_{pkg['parent_key']}")
    kb = bank_kb(back_button=back_btn)
    txt = T("choose_bank",price=fmt_price_bold(price),amount=stars_amount_label(amount))
    if edit:
        try: await target.edit_text(txt, reply_markup=kb, parse_mode="HTML")
        except: await target.answer(txt, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(txt, reply_markup=kb, parse_mode="HTML")
    await state.set_state(S.stars_bank)

@dp.callback_query(F.data.startswith("pkgself_"))
async def stars_pkg_self_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    username = f"@{cb.from_user.username or cb.from_user.id}"
    await state.update_data(recipient=username)
    await _proceed_to_stars_pkg_bank(cb.message, state, edit=True)

@dp.callback_query(F.data.startswith("pkgfriend_"))
async def stars_pkg_friend_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    key = cb.data.replace("pkgfriend_", "", 1)
    await state.update_data(pkg_key=key)
    txt = "<b>👤 Введіть @username друга, якому надіслати подарунок.</b>\n\nНаприклад: <code>@username</code>"
    try:
        cancel_inline_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Скасувати", callback_data="stars_pkg_recipient_cancel", style="danger")
        ]])
    except TypeError:
        cancel_inline_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Скасувати", callback_data="stars_pkg_recipient_cancel")
        ]])
    try: await cb.message.edit_text(txt, reply_markup=cancel_inline_kb, parse_mode="HTML")
    except: await cb.message.answer(txt, reply_markup=cancel_inline_kb, parse_mode="HTML")
    await state.set_state(S.stars_pkg_recipient)

@dp.callback_query(F.data == "stars_pkg_recipient_cancel")
async def stars_pkg_recipient_cancel_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(S.menu)
    try: await cb.message.delete()
    except: pass
    await send_menu(cb.from_user.id, T("main_menu"))

@dp.message(S.stars_pkg_recipient)
async def stars_pkg_recipient_input(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    username = (msg.text or "").strip()
    if not username.startswith("@") or len(username) < 3:
        await msg.answer("❌ <b>Введіть коректний @username.</b>", parse_mode="HTML")
        return
    await state.update_data(recipient=username)
    await _proceed_to_stars_pkg_bank(msg, state, edit=False)

@dp.callback_query(F.data.startswith("pkgback_"))
async def stars_pkg_group_back_from_bank_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    parent_key = cb.data.replace("pkgback_", "", 1)
    rate = float(get_setting("stars_rate") or 0.74)
    pkg = get_stars_package(parent_key)
    custom_description = pkg.get("description") if pkg else None
    if custom_description:
        txt = custom_description
    else:
        header = f"<b>{(pkg.get('label') if pkg else None) or '🎁 Набір'}</b>"
        txt = f"{header}\n\nОберіть подарунок:"
    kb = stars_group_kb(parent_key, rate)
    try: await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
    except: await cb.message.answer(txt, reply_markup=kb, parse_mode="HTML")
    await state.set_state(S.stars_amount)

@dp.callback_query(F.data == "stars_pkg_back", S.stars_amount)
async def stars_pkg_back_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(S.menu)
    try: await cb.message.delete()
    except: pass
    await send_menu(cb.from_user.id, T("main_menu"))

@dp.callback_query(F.data.startswith("pkggroup_"), S.stars_amount)
async def stars_pkg_group_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    key = cb.data.replace("pkggroup_", "", 1)
    pkg = get_stars_package(key)
    if not pkg or not pkg.get("enabled", 1):
        await cb.answer("❌ Цей набір недоступний", show_alert=True); return
    rate = float(get_setting("stars_rate") or 0.74)
    custom_description = pkg.get("description")
    if custom_description:
        txt = custom_description
    else:
        header = f"<b>{pkg.get('label') or '🎁 Набір'}</b>"
        txt = f"{header}\n\nОберіть подарунок:"
    kb = stars_group_kb(key, rate)
    try: await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
    except: await cb.message.answer(txt, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "stars_pkg_group_back", S.stars_amount)
async def stars_pkg_group_back_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    rate = float(get_setting("stars_rate") or 0.74)
    txt = T("stars_choose_amount", username=(await state.get_data()).get("recipient", ""))
    kb = stars_packages_kb(rate)
    try: await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
    except: await cb.message.answer(txt, reply_markup=kb, parse_mode="HTML")

@dp.message(S.stars_amount_custom)
async def stars_amount_custom(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    try: amount = int(msg.text.strip())
    except: await msg.answer(T("err_num")); return
    data = await state.get_data()
    min_s = data.get("pkg_range_min") or int(get_setting("min_stars") or 50)
    max_s = data.get("pkg_range_max")
    if amount < min_s: await msg.answer(T("err_min_stars",min=min_s)); return
    if max_s and amount > max_s:
        await msg.answer(f"❌ Максимум: <b>{max_s} Stars</b>", parse_mode="HTML"); return
    price = round(amount * float(get_setting("stars_rate") or 0.74), 2)
    await state.update_data(stars_amount=amount, stars_price=price, pkg_key=None)
    await msg.answer(T("choose_bank",price=fmt_price_bold(price),amount=stars_amount_label(amount)), reply_markup=bank_kb())
    await state.set_state(S.stars_bank)

@dp.message(S.stars_amount)
async def stars_amount(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    try: amount = int(msg.text.strip())
    except: await msg.answer(T("err_num")); return
    min_s = int(get_setting("min_stars") or 50)
    if amount < min_s: await msg.answer(T("err_min_stars",min=min_s)); return
    price = round(amount * float(get_setting("stars_rate") or 0.74), 2)
    await state.update_data(stars_amount=amount, stars_price=price, pkg_key=None)
    await msg.answer(T("choose_bank",price=fmt_price_bold(price),amount=stars_amount_label(amount)), reply_markup=bank_kb())
    await state.set_state(S.stars_bank)

@dp.callback_query(F.data.startswith("bank_"), S.stars_bank)
async def stars_bank(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    if cb.data == "bank_cancel":
        await state.set_state(S.menu)
        try: await cb.message.delete()
        except: pass
        await send_menu(cb.from_user.id, T("main_menu"))
        return
    if cb.data == "bank_ua":
        data = await state.get_data()
        txt = T("choose_bank",price=fmt_price_bold(data.get("stars_price","")),amount=stars_amount_label(data.get('stars_amount','')))
        try: await cb.message.edit_text(txt, reply_markup=ua_submenu_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=ua_submenu_kb(), parse_mode="HTML")
        return
    if cb.data == "bank_ua_back":
        data = await state.get_data()
        txt = T("choose_bank",price=fmt_price_bold(data.get("stars_price","")),amount=stars_amount_label(data.get('stars_amount','')))
        try: await cb.message.edit_text(txt, reply_markup=bank_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=bank_kb(), parse_mode="HTML")
        return
    if cb.data == "bank_cryptobot":
        txt = safe_html(get_setting("cryptobot_currency_text") or "🤖 <b>Оберіть валюту для оплати через CryptoBot:</b>")
        try: await cb.message.edit_text(txt, reply_markup=cryptobot_currency_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=cryptobot_currency_kb(), parse_mode="HTML")
        return
    bank_key = cb.data.replace("bank_","")
    data = await state.get_data()
    await state.update_data(bank=bank_key)
    try:
        receipt_nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 Назад", callback_data="receipt_back_stars"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="receipt_cancel", style="danger")
        ]])
    except TypeError:
        receipt_nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 Назад", callback_data="receipt_back_stars"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="receipt_cancel")
        ]])
    payment_text = pay_text(bank_key, "uk", data.get("stars_price"), order_type="stars")
    if not payment_text:
        await cb.answer("❌ Спосіб оплати не знайдено", show_alert=True)
        return
    try:
        await cb.message.edit_text(payment_text, reply_markup=receipt_nav_kb, parse_mode="HTML")
    except:
        await cb.message.answer(payment_text, reply_markup=receipt_nav_kb, parse_mode="HTML")
    await state.set_state(S.stars_receipt)

@dp.callback_query(F.data.startswith("cryptobot_cur_"))
async def cryptobot_currency_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    asset = cb.data.replace("cryptobot_cur_", "", 1)  # "TON" або "USDT"
    data = await state.get_data()

    if data.get("stars_amount") and data.get("stars_price"):
        order_type = "stars"
        amount = data.get("stars_amount")
        price = data.get("stars_price")
        recipient = data.get("recipient", "")
        wallet = ""
        package_key = data.get("pkg_key")
        item_label = f"{amount} Stars"
    elif data.get("prem_months") and data.get("prem_price") and data.get("prem_username"):
        order_type = "premium"
        amount = data.get("prem_months")
        price = data.get("prem_price")
        recipient = data.get("prem_username")
        wallet = ""
        package_key = None
        item_label = f"Premium на {amount} міс."
    elif data.get("ton_amount") and data.get("ton_price") and data.get("ton_wallet"):
        order_type = "ton"
        amount = data.get("ton_amount")
        price = data.get("ton_price")
        recipient = ""
        wallet = data.get("ton_wallet")
        package_key = None
        item_label = f"{amount} TON"
    else:
        await cb.message.answer("❌ <b>Сесія застаріла.</b> Почніть замовлення заново.", parse_mode="HTML")
        await state.set_state(S.menu); await send_menu(cb.from_user.id, T("main_menu")); return

    wait_msg = None
    try:
        await cb.message.edit_text("⏳ Створюю рахунок в CryptoBot...")
        wait_msg = cb.message
    except Exception:
        try:
            wait_msg = await cb.message.answer("⏳ Створюю рахунок в CryptoBot...")
        except Exception:
            pass

    rate = get_crypto_ton_rate("cryptobot_markup") if asset == "TON" else get_crypto_usdt_rate("cryptobot_markup")
    decimals = 2 if asset == "USDT" else 4
    crypto_amount = round(float(price) / rate, decimals) if rate else 0
    if crypto_amount <= 0:
        if wait_msg:
            try: await wait_msg.edit_text("❌ Не вдалося отримати курс. Спробуйте інший спосіб оплати.")
            except: pass
        return

    register_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    oid = create_order(cb.from_user.id, order_type, amount, price,
                        recipient, wallet, "cryptobot", package_key)

    result = await cryptobot_create_invoice(asset, crypto_amount, description=f"Teddy Stars #{oid}: {item_label}")
    if not result.get("ok"):
        fail_text = f"❌ <b>Не вдалося створити рахунок CryptoBot.</b>\n<i>{result.get('error','')[:300]}</i>"
        if wait_msg:
            try: await wait_msg.edit_text(fail_text, parse_mode="HTML")
            except: await cb.message.answer(fail_text, parse_mode="HTML")
        else:
            await cb.message.answer(fail_text, parse_mode="HTML")
        return

    set_order_cryptobot_invoice(oid, result["invoice_id"])
    try:
        uname = f"@{cb.from_user.username}" if cb.from_user.username else f"ID:{cb.from_user.id}"
        await bot.send_message(ADMIN_CHAT_ID,
            f"🤖 <b>Замовлення #{oid} — {item_label} через CryptoBot</b>\n\n👤 {uname}\n"
            f"💰 {price} грн ({crypto_amount} {asset})\n"
            f"⏳ Очікує оплату — підтвердиться автоматично.", parse_mode="HTML")
    except Exception:
        pass

    custom_pay_text = get_setting("cryptobot_pay_text")
    if custom_pay_text:
        pay_text_msg = safe_html(custom_pay_text.replace("{amount}", str(crypto_amount))
                                  .replace("{asset}", asset).replace("{price}", str(price)))
    else:
        pay_text_msg = (f"🤖 <b>Оплата через CryptoBot</b>\n\n"
                         f"💰 До сплати: <b>{crypto_amount} {asset}</b>\n"
                         f"({price} грн)\n\n"
                         f"Натисніть «Оплатити» — після оплати замовлення підтвердиться автоматично, "
                         f"нічого додатково надсилати не потрібно.")
    if wait_msg:
        try:
            await wait_msg.edit_text(pay_text_msg, reply_markup=cryptobot_pay_kb(result["pay_url"], oid), parse_mode="HTML")
        except:
            await cb.message.answer(pay_text_msg, reply_markup=cryptobot_pay_kb(result["pay_url"], oid), parse_mode="HTML")
    else:
        await cb.message.answer(pay_text_msg, reply_markup=cryptobot_pay_kb(result["pay_url"], oid), parse_mode="HTML")

    asyncio.create_task(cryptobot_poll_and_finalize(oid, result["invoice_id"], cb.from_user.id))

@dp.callback_query(F.data.startswith("cryptobot_gcur_"), S.gift_bank)
async def cryptobot_gift_currency_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    asset = cb.data.replace("cryptobot_gcur_", "", 1)  # "TON" або "USDT"
    data = await state.get_data()
    order_uid = data.get("gift_order_uid")
    order = get_gift_order(order_uid) if order_uid else None
    if not order:
        await cb.message.answer("❌ <b>Сесія застаріла.</b> Почніть замовлення заново.", parse_mode="HTML")
        await state.set_state(S.menu); await send_menu(cb.from_user.id, T("main_menu")); return

    wait_msg = None
    try:
        await cb.message.edit_text("⏳ Створюю рахунок в CryptoBot...")
        wait_msg = cb.message
    except Exception:
        try:
            wait_msg = await cb.message.answer("⏳ Створюю рахунок в CryptoBot...")
        except Exception:
            pass

    price = order["price"]
    rate = get_crypto_ton_rate("cryptobot_markup") if asset == "TON" else get_crypto_usdt_rate("cryptobot_markup")
    decimals = 2 if asset == "USDT" else 4
    crypto_amount = round(float(price) / rate, decimals) if rate else 0
    if crypto_amount <= 0:
        if wait_msg:
            try: await wait_msg.edit_text("❌ Не вдалося отримати курс. Спробуйте інший спосіб оплати.")
            except: pass
        return

    result = await cryptobot_create_invoice(asset, crypto_amount, description=f"Teddy Stars {order_uid}: {order['gift_emoji']} {order['gift_name']}")
    if not result.get("ok"):
        fail_text = f"❌ <b>Не вдалося створити рахунок CryptoBot.</b>\n<i>{result.get('error','')[:300]}</i>"
        if wait_msg:
            try: await wait_msg.edit_text(fail_text, parse_mode="HTML")
            except: await cb.message.answer(fail_text, parse_mode="HTML")
        else:
            await cb.message.answer(fail_text, parse_mode="HTML")
        return

    update_gift_order(order_uid, cryptobot_invoice_id=result["invoice_id"], payment_method="cryptobot")
    try:
        uname = f"@{cb.from_user.username}" if cb.from_user.username else f"ID:{cb.from_user.id}"
        await bot.send_message(ADMIN_CHAT_ID,
            f"🤖 <b>Замовлення {order_uid} — {order['gift_emoji']} {order['gift_name']} через CryptoBot</b>\n\n👤 {uname}\n"
            f"💰 {price} грн ({crypto_amount} {asset})\n"
            f"⏳ Очікує оплату — видасться автоматично.", parse_mode="HTML")
    except Exception:
        pass

    custom_pay_text = get_setting("cryptobot_pay_text")
    if custom_pay_text:
        pay_text_msg = safe_html(custom_pay_text.replace("{amount}", str(crypto_amount))
                                  .replace("{asset}", asset).replace("{price}", str(price)))
    else:
        pay_text_msg = (f"🤖 <b>Оплата через CryptoBot</b>\n\n"
                         f"💰 До сплати: <b>{crypto_amount} {asset}</b>\n"
                         f"({price} грн)\n\n"
                         f"Натисніть «Оплатити» — після оплати подарунок надійде автоматично, "
                         f"нічого додатково надсилати не потрібно.")
    pay_kb = cryptobot_pay_kb(result["pay_url"], order_uid, check_prefix="cryptobot_gcheck_")
    if wait_msg:
        try:
            await wait_msg.edit_text(pay_text_msg, reply_markup=pay_kb, parse_mode="HTML")
        except:
            await cb.message.answer(pay_text_msg, reply_markup=pay_kb, parse_mode="HTML")
    else:
        await cb.message.answer(pay_text_msg, reply_markup=pay_kb, parse_mode="HTML")

    asyncio.create_task(cryptobot_gift_poll_and_finalize(order_uid, result["invoice_id"], cb.from_user.id))

@dp.callback_query(F.data.startswith("cryptobot_gcheck_"))
async def cryptobot_gift_check_cb(cb: CallbackQuery):
    order_uid = cb.data.replace("cryptobot_gcheck_", "", 1)
    order = get_gift_order(order_uid)
    if not order:
        await cb.answer("❌ Замовлення не знайдено", show_alert=True); return
    if order.get("status") in ("completed", "approved"):
        await cb.answer("✅ Вже підтверджено!", show_alert=True); return
    invoice_id = order.get("cryptobot_invoice_id")
    if not invoice_id:
        await cb.answer("❌ Рахунок не знайдено", show_alert=True); return
    result = await cryptobot_check_invoice(invoice_id)
    if result.get("ok") and result.get("status") == "paid":
        await cryptobot_confirm_paid_gift_order(order_uid)
        await cb.answer("✅ Оплату підтверджено! Подарунок обробляється.", show_alert=True)
        try: await cb.message.edit_reply_markup(reply_markup=None)
        except: pass
    else:
        await cb.answer("⏳ Оплата ще не надійшла. Спробуйте через хвилину.", show_alert=True)

@dp.callback_query(F.data.startswith("cryptobot_check_"))
async def cryptobot_check_cb(cb: CallbackQuery):
    oid = int(cb.data.replace("cryptobot_check_", "", 1))
    order = get_order(oid)
    if not order:
        await cb.answer("❌ Замовлення не знайдено", show_alert=True); return
    if order.get("status") == "completed":
        await cb.answer("✅ Вже підтверджено!", show_alert=True); return
    invoice_id = order.get("cryptobot_invoice_id")
    if not invoice_id:
        await cb.answer("❌ Рахунок не знайдено", show_alert=True); return
    result = await cryptobot_check_invoice(invoice_id)
    if result.get("ok") and result.get("status") == "paid":
        ok = await cryptobot_confirm_paid_order(oid)
        if ok:
            await cb.answer("✅ Оплату підтверджено!", show_alert=True)
            try: await cb.message.edit_reply_markup(reply_markup=None)
            except: pass
        else:
            await cb.answer("✅ Оплату отримано! Дивіться повідомлення адміну для завершення.", show_alert=True)
    else:
        await cb.answer("⏳ Оплата ще не надійшла. Спробуйте через хвилину.", show_alert=True)

@dp.callback_query(F.data.in_({"receipt_cancel", "receipt_back_stars", "receipt_back_ton", "receipt_back_prem"}))
async def receipt_nav_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    if cb.data == "receipt_cancel":
        await state.set_state(S.menu)
        try: await cb.message.delete()
        except: pass
        await send_menu(cb.from_user.id, T("main_menu"))
        return
    data = await state.get_data()
    if cb.data == "receipt_back_stars":
        price = data.get("stars_price","")
        amount = stars_amount_label(data.get('stars_amount',''))
        txt = T("choose_bank",price=fmt_price_bold(price),amount=amount)
        try: await cb.message.edit_text(txt, reply_markup=bank_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=bank_kb(), parse_mode="HTML")
        await state.set_state(S.stars_bank)
    elif cb.data == "receipt_back_ton":
        price = data.get("ton_price","")
        amount = f"<b>{data.get('ton_amount','')}</b> TON"
        txt = T("choose_bank",price=fmt_price_bold(price),amount=amount)
        try: await cb.message.edit_text(txt, reply_markup=bank_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=bank_kb(), parse_mode="HTML")
        await state.set_state(S.ton_bank)
    elif cb.data == "receipt_back_prem":
        price = data.get("prem_price","")
        amount = f"<b>{data.get('prem_months','')}</b> міс. Premium"
        txt = T("choose_bank",price=fmt_price_bold(price),amount=amount)
        kb = bank_kb(_premium_stars_button(data.get('prem_months')))
        try: await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=kb, parse_mode="HTML")
        await state.set_state(S.prem_bank)

@dp.message(S.stars_receipt)
async def stars_receipt(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    if not msg.photo and not msg.document:
        await msg.answer("📸 <b>Будь ласка, надішліть фото квитанції!</b>\n\nБот приймає фото або документ.", parse_mode="HTML")
        return
    if not check_request_limit(msg.from_user.id):
        await msg.answer(T("spam_limit")); return

    try:
        log_request(msg.from_user.id)
        register_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
        data = await state.get_data()
        stars_amount = data.get("stars_amount")
        stars_price = data.get("stars_price")
        if not stars_amount or not stars_price:
            await state.clear()
            await msg.answer("❌ <b>Сесія застаріла.</b>\n\nБудь ласка, почніть замовлення заново через меню.", parse_mode="HTML")
            await state.set_state(S.menu)
            await send_menu(msg.from_user.id, T("main_menu"))
            return
        oid = create_order(msg.from_user.id,"stars",stars_amount,stars_price,
                           data.get("recipient",""),"",data.get("bank","ua"),data.get("pkg_key"))
        u = get_user(msg.from_user.id)
        total_spent = u["total_spent"] if u else 0
        uname = f"@{msg.from_user.username}" if msg.from_user.username else f"ID:{msg.from_user.id}"
        methods = {m["method_key"]: m["name_uk"] for m in get_payment_methods()}
        import html as _html_esc
        recipient_safe = _html_esc.escape(data.get("recipient","") or "")
        linked_gift = get_linked_gift_for_package(data.get("pkg_key"))
        gift_line = f"\n🎁 <b>Замість Stars буде надіслано: {linked_gift['emoji']} {linked_gift['name']}</b>" if linked_gift else ""
        admin_text = (f"🆕 <b>Замовлення #{oid} — Stars</b>\n\n👤 {uname}\n🆔 <code>{msg.from_user.id}</code>\n"
                      f"⭐ <b>{stars_amount} Stars</b>\n💰 <b>{stars_price} грн</b>{gift_line}\n"
                      f"👥 {recipient_safe}\n🏦 {methods.get(data.get('bank',''),'')}\n"
                      f"💸 Всього: <b>{total_spent} грн</b>")
        await send_to_admin(msg, oid, admin_text, "stars")

        await msg.answer(
            (get_bot_text("receipt_ok") or
             "✅ <b>Замовлення #{oid} прийнято!</b>\n\n⏳ Обробка займе не більше 15 хвилин.\n\nДякуємо що обрали " + BOT_NAME + "! 💙"
            ).replace("{oid}", str(oid)),
            parse_mode="HTML")
        await state.set_state(S.menu)
        await send_menu(msg.from_user.id, T("main_menu"))
    except Exception as e:
        logger.error(f"[STARS RECEIPT ERROR] {msg.from_user.id}: {e}")
        await msg.answer(f"❌ Помилка обробки: {str(e)[:100]}", parse_mode="HTML")

# ========================================================
# ПОКУПКА TON
# ========================================================

@dp.message(S.ton_amount)
async def ton_amount(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    try: ton = float(msg.text.strip().replace(",","."))
    except: await msg.answer(T("err_num")); return
    min_ton = float(get_setting("min_ton") or 0.25)
    if ton < min_ton: await msg.answer(T("err_min_ton",min=min_ton)); return
    data = await state.get_data(); rate = data.get("ton_rate", get_ton_rate())
    await state.update_data(ton_amount=ton, ton_price=round(ton*rate,2))
    await msg.answer(T("ton_wallet"), reply_markup=cancel_kb())
    await state.set_state(S.ton_wallet_s)

@dp.message(S.ton_wallet_s)
async def ton_wallet_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    wallet = msg.text.strip()
    if not is_valid_ton_wallet(wallet):
        await msg.answer("❌ <b>Невірний формат гаманця.</b>\n\nВведіть коректну адресу (мінімум 10 символів, без пробілів).", parse_mode="HTML")
        return
    await state.update_data(ton_wallet=wallet)
    data = await state.get_data()
    await msg.answer(T("ton_summary",price=fmt_price(data["ton_price"]),amount=data["ton_amount"],wallet=data["ton_wallet"]),
                     reply_markup=bank_kb(), parse_mode="HTML")
    await state.set_state(S.ton_bank)

@dp.callback_query(F.data.startswith("bank_"), S.ton_bank)
async def ton_bank_handler(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    if cb.data == "bank_cancel":
        await state.set_state(S.menu)
        try: await cb.message.delete()
        except: pass
        await send_menu(cb.from_user.id, T("main_menu"))
        return
    data = await state.get_data()
    if cb.data == "bank_ua":
        txt = T("choose_bank",price=fmt_price_bold(data.get("ton_price","")),amount=f"{data.get('ton_amount','')} TON")
        try: await cb.message.edit_text(txt, reply_markup=ua_submenu_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=ua_submenu_kb(), parse_mode="HTML")
        return
    if cb.data == "bank_ua_back":
        txt = T("choose_bank",price=fmt_price_bold(data.get("ton_price","")),amount=f"{data.get('ton_amount','')} TON")
        try: await cb.message.edit_text(txt, reply_markup=bank_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=bank_kb(), parse_mode="HTML")
        return
    if cb.data == "bank_cryptobot":
        txt = safe_html(get_setting("cryptobot_currency_text") or "🤖 <b>Оберіть валюту для оплати через CryptoBot:</b>")
        try: await cb.message.edit_text(txt, reply_markup=cryptobot_currency_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=cryptobot_currency_kb(), parse_mode="HTML")
        return
    bank_key = cb.data.replace("bank_","")
    await state.update_data(bank=bank_key)
    try:
        receipt_nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 Назад", callback_data="receipt_back_ton"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="receipt_cancel", style="danger")
        ]])
    except TypeError:
        receipt_nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 Назад", callback_data="receipt_back_ton"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="receipt_cancel")
        ]])
    payment_text = pay_text(bank_key, "uk", data.get("ton_price"), order_type="ton")
    if not payment_text:
        await cb.answer("❌ Спосіб оплати не знайдено", show_alert=True)
        return
    try:
        await cb.message.edit_text(payment_text, reply_markup=receipt_nav_kb, parse_mode="HTML")
    except:
        await cb.message.answer(payment_text, reply_markup=receipt_nav_kb, parse_mode="HTML")
    await state.set_state(S.ton_receipt)

@dp.message(S.ton_receipt)
async def ton_receipt(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    if not msg.photo and not msg.document:
        await msg.answer("📸 <b>Будь ласка, надішліть фото квитанції!</b>\n\nБот приймає фото або документ.", parse_mode="HTML")
        return
    if not check_request_limit(msg.from_user.id):
        await msg.answer(T("spam_limit")); return
    try:
        log_request(msg.from_user.id)
        register_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
        data = await state.get_data()
        ton_amount = data.get("ton_amount")
        ton_price = data.get("ton_price")
        ton_wallet = data.get("ton_wallet")
        if not ton_amount or not ton_price or not ton_wallet:
            await state.clear()
            await msg.answer("❌ <b>Сесія застаріла.</b>\n\nБудь ласка, почніть замовлення заново через меню.", parse_mode="HTML")
            await state.set_state(S.menu)
            await send_menu(msg.from_user.id, T("main_menu"))
            return
        import html as _html_esc
        uname = f"@{msg.from_user.username}" if msg.from_user.username else f"ID:{msg.from_user.id}"
        oid = create_order(msg.from_user.id,"ton",ton_amount,ton_price,
                           "",ton_wallet,data.get("bank","ua"))
        u = get_user(msg.from_user.id)
        total_spent = u["total_spent"] if u else 0
        methods = {m["method_key"]: m["name_uk"] for m in get_payment_methods()}
        ton_wallet_safe = _html_esc.escape(ton_wallet or "")
        admin_text = (f"🆕 <b>Замовлення #{oid} — TON</b>\n\n👤 {uname}\n🆔 <code>{msg.from_user.id}</code>\n"
                      f"💵 <b>{ton_amount} TON</b>\n💰 <b>{ton_price} грн</b>\n"
                      f"👛 <code>{ton_wallet_safe}</code>\n🏦 {methods.get(data.get('bank',''),'')}\n"
                      f"💸 Всього: <b>{total_spent} грн</b>")
        await send_to_admin(msg, oid, admin_text, "ton")
    except Exception as e:
        logger.error(f"[TON RECEIPT ERROR] {msg.from_user.id}: {e}")
        await msg.answer(f"❌ Помилка обробки: {str(e)[:100]}", parse_mode="HTML")
        return

    await msg.answer(
        (get_bot_text("receipt_ok") or
         "✅ <b>Замовлення #{oid} прийнято!</b>\n\n⏳ Обробка займе не більше 15 хвилин.\n\nДякуємо що обрали " + BOT_NAME + "! 💙"
        ).replace("{oid}", str(oid)),
        parse_mode="HTML"
    )
    await state.set_state(S.menu)
    await send_menu(msg.from_user.id, T("main_menu"))

# ========================================================
# ПОКУПКА PREMIUM
# ========================================================

@dp.message(S.prem_user)
async def prem_user(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    uname = msg.text.strip()
    uname = uname if uname.startswith("@") else "@"+uname
    await state.update_data(prem_username=uname)
    m3,m6,m12 = get_setting("premium_3m"),get_setting("premium_6m"),get_setting("premium_12m")
    await msg.answer(T("prem_months",m3=fmt_price(m3),m6=fmt_price(m6),m12=fmt_price(m12)), reply_markup=months_kb())
    await state.set_state(S.prem_months)

@dp.callback_query(F.data.startswith("prem_month_"))
async def prem_month_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    if cb.data == "prem_month_back":
        await state.set_state(S.menu)
        try: await cb.message.delete()
        except: pass
        await send_menu(cb.from_user.id, T("main_menu"))
        return
    try:
        months = int(cb.data.replace("prem_month_",""))
    except:
        return
    kmap = {3: "premium_3m", 6: "premium_6m", 12: "premium_12m"}
    key = kmap.get(months)
    if not key:
        return
    price = float(get_setting(key) or 100)
    await state.update_data(prem_months=months, prem_price=price)
    await state.set_state(S.prem_bank)
    txt = T("choose_bank",price=fmt_price_bold(price),amount=f"{months} міс. Premium")
    kb = bank_kb(_premium_stars_button(months))
    try: await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
    except: await cb.message.answer(txt, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("bank_"), S.prem_bank)
async def prem_bank_handler(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    if cb.data == "bank_cancel":
        await state.set_state(S.menu)
        try: await cb.message.delete()
        except: pass
        await send_menu(cb.from_user.id, T("main_menu"))
        return
    if cb.data == "bank_ua":
        data = await state.get_data()
        txt = T("choose_bank",price=fmt_price_bold(data.get("prem_price","")),amount=f"{data.get('prem_months','')} міс. Premium")
        try: await cb.message.edit_text(txt, reply_markup=ua_submenu_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=ua_submenu_kb(), parse_mode="HTML")
        return
    if cb.data == "bank_ua_back":
        data = await state.get_data()
        txt = T("choose_bank",price=fmt_price_bold(data.get("prem_price","")),amount=f"{data.get('prem_months','')} міс. Premium")
        try: await cb.message.edit_text(txt, reply_markup=bank_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=bank_kb(), parse_mode="HTML")
        return
    if cb.data == "bank_cryptobot":
        txt = safe_html(get_setting("cryptobot_currency_text") or "🤖 <b>Оберіть валюту для оплати через CryptoBot:</b>")
        try: await cb.message.edit_text(txt, reply_markup=cryptobot_currency_kb(), parse_mode="HTML")
        except: await cb.message.answer(txt, reply_markup=cryptobot_currency_kb(), parse_mode="HTML")
        return
    bank_key = cb.data.replace("bank_","")
    data = await state.get_data()
    await state.update_data(bank=bank_key)
    try:
        receipt_nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 Назад", callback_data="receipt_back_prem"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="receipt_cancel", style="danger")
        ]])
    except TypeError:
        receipt_nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 Назад", callback_data="receipt_back_prem"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="receipt_cancel")
        ]])
    payment_text = pay_text(bank_key, "uk", data.get("prem_price"), order_type="premium")
    if not payment_text:
        await cb.answer("❌ Спосіб оплати не знайдено", show_alert=True)
        return
    try:
        await cb.message.edit_text(payment_text, reply_markup=receipt_nav_kb, parse_mode="HTML")
    except:
        await cb.message.answer(payment_text, reply_markup=receipt_nav_kb, parse_mode="HTML")
    await state.set_state(S.prem_receipt)

@dp.message(S.prem_receipt)
async def prem_receipt(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    if not msg.photo and not msg.document:
        await msg.answer("📸 <b>Будь ласка, надішліть фото квитанції!</b>\n\nБот приймає фото або документ.", parse_mode="HTML")
        return
    if not check_request_limit(msg.from_user.id):
        await msg.answer(T("spam_limit")); return
    try:
        log_request(msg.from_user.id)
        register_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
        data = await state.get_data()
        prem_months = data.get("prem_months")
        prem_price = data.get("prem_price")
        prem_username = data.get("prem_username")
        if not prem_months or not prem_price or not prem_username:
            await state.clear()
            await msg.answer("❌ <b>Сесія застаріла.</b>\n\nБудь ласка, почніть замовлення заново через меню.", parse_mode="HTML")
            await state.set_state(S.menu)
            await send_menu(msg.from_user.id, T("main_menu"))
            return
        oid = create_order(msg.from_user.id,"premium",prem_months,prem_price,
                           prem_username,"",data.get("bank","ua"))
        u = get_user(msg.from_user.id)
        total_spent = u["total_spent"] if u else 0
        uname = f"@{msg.from_user.username}" if msg.from_user.username else f"ID:{msg.from_user.id}"
        methods = {m["method_key"]: m["name_uk"] for m in get_payment_methods()}
        import html as _html_esc
        prem_username_safe = _html_esc.escape(prem_username or "")
        admin_text = (f"🆕 <b>Замовлення #{oid} — Premium</b>\n\n👤 {uname}\n🆔 <code>{msg.from_user.id}</code>\n"
                      f"💎 <b>{prem_months} міс.</b>\n👥 {prem_username_safe}\n"
                      f"💰 <b>{prem_price} грн</b>\n🏦 {methods.get(data.get('bank',''),'')}\n"
                      f"💸 Всього: <b>{total_spent} грн</b>")
        await send_to_admin(msg, oid, admin_text, "premium")
    except Exception as e:
        logger.error(f"[PREMIUM RECEIPT ERROR] {msg.from_user.id}: {e}")
        await msg.answer(f"❌ Помилка обробки: {str(e)[:100]}", parse_mode="HTML")
        return

    await msg.answer(
        (get_bot_text("receipt_ok") or
         "✅ <b>Замовлення #{oid} прийнято!</b>\n\n⏳ Обробка займе не більше 15 хвилин.\n\nДякуємо що обрали " + BOT_NAME + "! 💙"
        ).replace("{oid}", str(oid)),
        parse_mode="HTML"
    )
    await state.set_state(S.menu)
    await send_menu(msg.from_user.id, T("main_menu"))

# ========================================================
# 🎁 ПОДАРУНКИ — навігація каталогом
# ========================================================

async def show_gifts_menu(chat_id: int, edit_message: Message = None) -> None:
    text = "🎁 <b>Подарунки</b>\n\nОберіть подарунок зі списку нижче:"
    kb = gifts_keyboard()
    if edit_message:
        try:
            await edit_message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

async def show_gift_detail(chat_id: int, key: str, edit_message: Message = None) -> None:
    item = get_gift_item(key)
    if not item or not item.get("enabled", 1):
        await bot.send_message(chat_id, "<b>❌ Цей подарунок вже недоступний</b>", parse_mode="HTML")
        return
    sticker = tg_emoji(item.get("sticker_id"), item.get("emoji", "🎁"))
    text = (
        f"<b>{sticker}</b>\n\n"
        f"<b>💰 Вартість: {fmt_price(item['price'])} грн</b>\n\n"
        f"<b>🕵️ Подарунок надсилається анонімно — отримувач не побачить, хто саме його купив.</b>"
    )
    kb = gift_detail_keyboard(key)
    if edit_message:
        try:
            await edit_message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "show_gifts")
async def gifts_back_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await show_gifts_menu(cb.from_user.id, edit_message=cb.message)

@dp.callback_query(F.data.startswith("giftitem_"))
async def gift_item_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    key = cb.data.split("_", 1)[1]
    await show_gift_detail(cb.from_user.id, key, edit_message=cb.message)

# ---- 🎁 Подарунки: оформлення замовлення ----

def gift_order_admin_kb(order_uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Оплату отримано", callback_data=f"giftpay_{order_uid}"),
        InlineKeyboardButton(text="❌ Відхилити", callback_data=f"giftrejstart_{order_uid}")
    ]])

async def ask_gift_comment(chat_id: int, order_uid: str, state: FSMContext, edit_message: Message = None) -> None:
    text = (
        f"<b>💬 Бажаєте додати особистий коментар до подарунка?</b>\n\n"
        f"Напишіть текст повідомлення, яке отримувач побачить разом із подарунком, "
        f"або натисніть «⏭ Без коментаря».\n\n"
        f"🕵️ Подарунок буде надіслано анонімно — отримувач не побачить, хто саме його купив."
    )
    kb = gift_comment_keyboard(order_uid)
    if edit_message:
        try:
            await edit_message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
    else:
        await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
    await state.update_data(gift_order_uid=order_uid)
    await state.set_state(S.gift_comment)

async def finalize_gift_order(chat_id: int, order_uid: str, state: FSMContext, edit_message: Message = None) -> None:
    """Показує підсумок замовлення (з коментарем, якщо є) і пропонує спосіб оплати."""
    order = get_gift_order(order_uid)
    if not order:
        return
    comment = order.get("comment") or ""
    comment_line = f"💬 Коментар: {comment}\n" if comment else ""
    sticker = tg_emoji(order.get("gift_sticker"), order.get("gift_emoji", "🎁"))
    text = (
        f"<b>🎁 Замовлення створено!</b>\n\n"
        f"<b>👤 Отримувач:</b> {order['target_username']}\n"
        f"<b>Подарунок:</b> {sticker}\n"
        f"{comment_line}"
        f"<b>🕵️ Відправлення:</b> анонімне\n"
        f"<b>💰 Вартість:</b> {fmt_price(order['price'])} грн\n\n"
        f"<b>💳 Оберіть спосіб оплати:</b>"
    )
    await state.update_data(gift_order_uid=order_uid)
    await state.set_state(S.gift_bank)
    item = get_gift_item(order["item_key"]) or {}
    kb = bank_kb(_gift_stars_button(item))
    if edit_message:
        try:
            await edit_message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")

def _gen_gift_order_uid() -> str:
    import uuid
    return "G" + uuid.uuid4().hex[:10].upper()

@dp.callback_query(F.data.startswith("buygift_"))
async def gift_buy_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    key = cb.data.split("_", 1)[1]
    item = get_gift_item(key)
    if not item or not item.get("enabled", 1):
        await cb.answer("❌ Цей подарунок вже недоступний", show_alert=True)
        return
    if item.get("quantity") is not None and item["quantity"] <= 0:
        await cb.answer("❌ Цього подарунка вже немає в наявності", show_alert=True)
        return
    text = "<b>👤 Кому надіслати подарунок?</b>"
    try:
        await cb.message.edit_text(text, reply_markup=gift_recipient_keyboard(key), parse_mode="HTML")
    except Exception:
        await cb.message.answer(text, reply_markup=gift_recipient_keyboard(key), parse_mode="HTML")

@dp.callback_query(F.data.startswith("gift_for_self_"))
async def gift_for_self_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    key = cb.data.split("_", 3)[3]
    item = get_gift_item(key)
    if not item or not item.get("enabled", 1):
        await cb.answer("❌ Цей подарунок вже недоступний", show_alert=True)
        return
    username = f"@{cb.from_user.username}" if cb.from_user.username else f"ID:{cb.from_user.id}"
    order_uid = _gen_gift_order_uid()
    create_gift_order(order_uid, cb.from_user.id, item, username)
    await ask_gift_comment(cb.from_user.id, order_uid, state, edit_message=cb.message)

@dp.callback_query(F.data.startswith("gift_for_friend_"))
async def gift_for_friend_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    key = cb.data.split("_", 3)[3]
    item = get_gift_item(key)
    if not item or not item.get("enabled", 1):
        await cb.answer("❌ Цей подарунок вже недоступний", show_alert=True)
        return
    await state.update_data(gift_key=key)
    await state.set_state(S.gift_recipient)
    text = (
        "<b>👤 Введіть @username друга, якому надіслати подарунок.</b>\n\n"
        "Наприклад: <code>@username</code>"
    )
    try:
        cancel_inline_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Скасувати", callback_data="gift_recipient_cancel", style="danger")
        ]])
    except TypeError:
        cancel_inline_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Скасувати", callback_data="gift_recipient_cancel")
        ]])
    try:
        await cb.message.edit_text(text, reply_markup=cancel_inline_kb, parse_mode="HTML")
    except Exception:
        await cb.message.answer(text, reply_markup=cancel_inline_kb, parse_mode="HTML")

@dp.callback_query(F.data == "gift_recipient_cancel")
async def gift_recipient_cancel_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(S.menu)
    try: await cb.message.delete()
    except Exception: pass
    await send_menu(cb.from_user.id, T("main_menu"))

@dp.message(S.gift_recipient)
async def gift_recipient_input(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    username = (msg.text or "").strip()
    if not username.startswith("@") or len(username) < 3:
        await msg.answer("❌ <b>Введіть коректний @username.</b>", parse_mode="HTML")
        return
    data = await state.get_data()
    key = data.get("gift_key")
    item = get_gift_item(key) if key else None
    if not item or not item.get("enabled", 1):
        await state.set_state(S.menu)
        await msg.answer("❌ <b>Цей подарунок вже недоступний</b>", parse_mode="HTML")
        await send_menu(msg.from_user.id, T("main_menu"))
        return
    order_uid = _gen_gift_order_uid()
    create_gift_order(order_uid, msg.from_user.id, item, username)
    await ask_gift_comment(msg.from_user.id, order_uid, state)

@dp.callback_query(F.data.startswith("giftcomment_skip_"))
async def gift_comment_skip_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    order_uid = cb.data.split("_", 2)[2]
    await finalize_gift_order(cb.from_user.id, order_uid, state, edit_message=cb.message)

@dp.message(S.gift_comment)
async def gift_comment_input(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    if msg.content_type != "text":
        await msg.answer(
            "⚠️ <b>Коментар до подарунка можна ввести лише текстом.</b>\n"
            "Напишіть текст коментаря або натисніть «⏭ Без коментаря».", parse_mode="HTML")
        return
    data = await state.get_data()
    order_uid = data.get("gift_order_uid")
    if not order_uid:
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    text = (msg.text or "").strip()
    if text:
        update_gift_order(order_uid, comment=text[:200])
    await finalize_gift_order(msg.from_user.id, order_uid, state)

@dp.callback_query(F.data.startswith("bank_"), S.gift_bank)
async def gift_bank_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    order_uid = data.get("gift_order_uid")
    order = get_gift_order(order_uid) if order_uid else None
    if not order:
        await state.set_state(S.menu)
        try: await cb.message.delete()
        except Exception: pass
        await send_menu(cb.from_user.id, T("main_menu"))
        return
    if cb.data == "bank_cancel":
        await state.set_state(S.menu)
        try: await cb.message.delete()
        except Exception: pass
        await send_menu(cb.from_user.id, T("main_menu"))
        return
    if cb.data == "bank_ua":
        try: await cb.message.edit_reply_markup(reply_markup=ua_submenu_kb())
        except Exception: pass
        return
    if cb.data == "bank_ua_back":
        try: await cb.message.edit_reply_markup(reply_markup=bank_kb())
        except Exception: pass
        return
    if cb.data == "bank_cryptobot":
        txt = safe_html(get_setting("cryptobot_currency_text") or "🤖 <b>Оберіть валюту для оплати через CryptoBot:</b>")
        kb = cryptobot_currency_kb(cur_prefix="cryptobot_gcur_", back_cb="bank_ua_back")
        try: await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
        except Exception: await cb.message.answer(txt, reply_markup=kb, parse_mode="HTML")
        return
    bank_key = cb.data.replace("bank_", "")
    payment_text = pay_text(bank_key, "uk", fmt_price(order["price"]), order_type="gift")
    if not payment_text:
        await cb.answer("❌ Спосіб оплати не знайдено", show_alert=True)
        return
    update_gift_order(order_uid, payment_method=bank_key)
    try:
        receipt_nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Скасувати", callback_data="gift_receipt_cancel", style="danger")
        ]])
    except TypeError:
        receipt_nav_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Скасувати", callback_data="gift_receipt_cancel")
        ]])
    try:
        await cb.message.edit_text(payment_text, reply_markup=receipt_nav_kb, parse_mode="HTML")
    except Exception:
        await cb.message.answer(payment_text, reply_markup=receipt_nav_kb, parse_mode="HTML")
    await state.set_state(S.gift_receipt)

@dp.callback_query(F.data == "gift_receipt_cancel")
async def gift_receipt_cancel_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(S.menu)
    try: await cb.message.delete()
    except Exception: pass
    await send_menu(cb.from_user.id, T("main_menu"))

@dp.message(S.gift_receipt)
async def gift_receipt(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    if not msg.photo and not msg.document:
        await msg.answer("📸 <b>Будь ласка, надішліть фото квитанції!</b>\n\nБот приймає фото або документ.", parse_mode="HTML")
        return
    if not check_request_limit(msg.from_user.id):
        await msg.answer(T("spam_limit")); return

    try:
        log_request(msg.from_user.id)
        register_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
        data = await state.get_data()
        order_uid = data.get("gift_order_uid")
        order = get_gift_order(order_uid) if order_uid else None
        if not order:
            await state.clear()
            await msg.answer("❌ <b>Сесія застаріла.</b>\n\nБудь ласка, почніть замовлення заново через меню.", parse_mode="HTML")
            await state.set_state(S.menu)
            await send_menu(msg.from_user.id, T("main_menu"))
            return
        update_gift_order(order_uid, status="pending_review")
        uname = f"@{msg.from_user.username}" if msg.from_user.username else f"ID:{msg.from_user.id}"
        methods = {m["method_key"]: m["name_uk"] for m in get_payment_methods()}
        import html as _html_esc
        recipient_safe = _html_esc.escape(order.get("target_username","") or "")
        comment_safe = _html_esc.escape(order.get("comment","") or "")
        comment_line = f"\n💬 {comment_safe}" if comment_safe else ""
        admin_text = (
            f"🎁 <b>Замовлення {order_uid} — Подарунок</b>\n\n"
            f"👤 Покупець: {uname}\n🆔 <code>{msg.from_user.id}</code>\n"
            f"🎁 {order['gift_emoji']} {order['gift_name']} — <b>{fmt_price(order['price'])} грн</b>\n"
            f"👥 Отримувач: {recipient_safe}{comment_line}\n"
            f"🏦 {methods.get(order.get('payment_method',''),'')}"
        )
        kb = gift_order_admin_kb(order_uid)
        sent = False
        try:
            if msg.photo:
                await bot.send_photo(ADMIN_CHAT_ID, photo=msg.photo[-1].file_id, caption=admin_text, reply_markup=kb, parse_mode="HTML")
            elif msg.document:
                await bot.send_document(ADMIN_CHAT_ID, document=msg.document.file_id, caption=admin_text, reply_markup=kb, parse_mode="HTML")
            sent = True
        except Exception as e:
            logger.error(f"❌ Помилка групи (gift): {e}")
        if not sent:
            try:
                await bot.send_message(ADMIN_IDS[0], admin_text + "\n\n⚠️ Квитанція не прикріплена!", reply_markup=kb, parse_mode="HTML")
            except Exception as e2:
                logger.error(f"❌ Резерв (gift): {e2}")

        await msg.answer(
            f"✅ <b>Замовлення {order_uid} прийнято!</b>\n\n⏳ Обробка займе не більше 15 хвилин.\n\nДякуємо що обрали {BOT_NAME}! 💙",
            parse_mode="HTML")
        await state.set_state(S.menu)
        await send_menu(msg.from_user.id, T("main_menu"))
    except Exception as e:
        logger.error(f"[GIFT RECEIPT ERROR] {msg.from_user.id}: {e}")
        await msg.answer(f"❌ Помилка обробки: {str(e)[:100]}", parse_mode="HTML")

# ---- 🎁 Подарунки: підтвердження/відхилення адміном ----

def gift_retry_kb(order_uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔁 Повторити видачу", callback_data=f"giftretry_{order_uid}")
    ]])

async def request_gift_review(order: dict) -> None:
    """Просить покупця залишити відгук одразу після підтвердження оплати подарунка —
    так само, як це вже робиться для TON/Premium (не чекаючи фактичної доставки)."""
    uid = order["user_id"]
    text = (get_bot_text("order_done_review") or
        "✅ <b>Замовлення виконано!</b>\n\n{order_details}\n\n💙 <b>Дякуємо за покупку!</b>\n\n"
        "🎁 <b>Залиште відгук і отримайте 1-2 Stars на баланс безкоштовно!</b>\n\n"
        "📸 <b>Спочатку прикріпіть фото або скріншот покупки.</b>\n"
        "<i>(це обов'язково — без фото відгук не буде прийнято)</i>\n\n"
        "<blockquote>Це дуже важливо для нас 🙂</blockquote>\n\n"
        "<i>Натисніть «Пропустити» якщо не хочете залишати відгук.</i>"
    ).replace("{order_details}", f"🎁 <b>Подарунок буде відправлено акаунту {order['target_username']} найближчим часом!</b>")
    try:
        user_state = FSMContext(storage=storage,
            key=StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid))
        await user_state.update_data(review_order_type="gift", review_amount=order.get("price", 0))
        await user_state.set_state(S.waiting_review)
    except Exception as e:
        logger.error(f"gift review request error: {e}")
    try:
        await bot.send_message(uid, text, reply_markup=review_kb(), parse_mode="HTML")
    except Exception:
        pass

async def _try_auto_fulfill_gift(cb_message, order_uid: str) -> None:
    """Намагається автоматично надіслати подарунок і повідомляє адміна/покупця про результат."""
    order = get_gift_order(order_uid)
    if not order:
        return
    if not GIFT_TELETHON_AVAILABLE:
        await bot.send_message(
            cb_message.chat.id,
            f"⚠️ Замовлення {order_uid}: автовидача недоступна (пакет telethon не встановлено). "
            f"Надішліть подарунок вручну.", parse_mode="HTML")
        return
    result = await auto_fulfill_gift_order(order_uid)
    if result.get("ok"):
        await bot.send_message(
            cb_message.chat.id,
            f"🎁✅ Подарунок за замовленням {order_uid} успішно надіслано автоматично!",
            parse_mode="HTML")
        try:
            await bot.send_message(
                order["user_id"],
                f"🎉 <b>Подарунок надіслано!</b>\n\n🎁 Ваш подарунок для {order['target_username']} успішно доставлено.",
                parse_mode="HTML")
        except Exception:
            pass
    else:
        await bot.send_message(
            cb_message.chat.id,
            f"⚠️ <b>Автовидача не вдалась для замовлення {order_uid}</b>\n\n"
            f"Причина: {result.get('error', 'невідома помилка')}\n\n"
            f"Надішліть подарунок вручну або натисніть «🔁 Повторити видачу».",
            reply_markup=gift_retry_kb(order_uid), parse_mode="HTML")

@dp.callback_query(F.data.startswith("giftpay_"))
async def gift_admin_pay_cb(cb: CallbackQuery):
    order_uid = cb.data.split("_", 1)[1]
    order = get_gift_order(order_uid)
    if not order:
        await cb.answer("Замовлення не знайдено", show_alert=True); return
    update_gift_order(order_uid, status="approved")
    decrement_gift_quantity(order["item_key"])
    try:
        await bot.send_message(
            order["user_id"],
            f"✅ <b>Оплату отримано!</b>\n\n🎁 Ваш подарунок для {order['target_username']} буде надіслано найближчим часом.",
            parse_mode="HTML")
    except Exception:
        pass
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.answer("✅ Оплата підтверджена")
    asyncio.create_task(_try_auto_fulfill_gift(cb.message, order_uid))
    asyncio.create_task(request_gift_review(order))

@dp.callback_query(F.data.startswith("giftretry_"))
async def gift_admin_retry_cb(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer(); return
    order_uid = cb.data.split("_", 1)[1]
    await cb.answer("⏳ Повторюю спробу...")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _try_auto_fulfill_gift(cb.message, order_uid)

@dp.callback_query(F.data.startswith("giftrejstart_"))
async def gift_admin_reject_start_cb(cb: CallbackQuery):
    order_uid = cb.data.split("_", 1)[1]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Невірна квитанція",  callback_data=f"giftrej_{order_uid}_Невірна квитанція")],
        [InlineKeyboardButton(text="⏳ Технічні роботи",     callback_data=f"giftrej_{order_uid}_Технічні роботи")],
        [InlineKeyboardButton(text="💸 Оплата не надійшла",  callback_data=f"giftrej_{order_uid}_Оплата не надійшла")],
    ])
    await cb.message.answer(f"❌ <b>Вкажіть причину відхилення замовлення {order_uid}:</b>", reply_markup=kb, parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data.startswith("giftrej_"))
async def gift_admin_reject_cb(cb: CallbackQuery):
    parts = cb.data.split("_", 2)  # giftrej, order_uid, reason
    order_uid = parts[1]
    reason = parts[2]
    order = get_gift_order(order_uid)
    if order:
        update_gift_order(order_uid, status="rejected")
        try:
            await bot.send_message(order["user_id"], T("order_rejected", reason=reason), parse_mode="HTML")
        except Exception:
            pass
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.answer("❌ Замовлення відхилено")

# ========================================================
# ПРОДАЖ STARS
# ========================================================

@dp.message(S.sell_amount)
async def sell_amount(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    try: amount = int(msg.text.strip())
    except: await msg.answer(T("err_num")); return
    min_s = int(get_setting("min_sell_stars") or 50)
    if amount < min_s: await msg.answer(T("err_min_sell",min=min_s)); return
    price = round(amount * float(get_setting("sell_stars_rate") or 0.30), 2)
    await state.update_data(sell_amount=amount, sell_price=price)
    await msg.answer(T("sell_wallet"), reply_markup=cancel_kb())
    await state.set_state(S.sell_wallet_s)

@dp.message(S.sell_wallet_s)
async def sell_wallet(msg: Message, state: FSMContext):
    if is_cancel(msg.text) or is_back(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    await state.update_data(sell_wallet=msg.text.strip())
    data = await state.get_data()
    await msg.answer(T("sell_summary",price=fmt_price(data["sell_price"]),
                       amount=data["sell_amount"],wallet=data["sell_wallet"]),
                     reply_markup=confirm_kb())
    await state.set_state(S.sell_confirm)

@dp.message(S.sell_confirm)
async def sell_confirm(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    if msg.text != "✅ Підтвердити": return
    data = await state.get_data()
    oid = create_order(msg.from_user.id,"sell_stars",data["sell_amount"],data["sell_price"],
                       "","",data["sell_wallet"])
    uname = f"@{msg.from_user.username}" if msg.from_user.username else f"ID:{msg.from_user.id}"
    admin_text = (f"💰 <b>Заявка #{oid} — ПРОДАЖ Stars</b>\n\n👤 {uname}\n🆔 <code>{msg.from_user.id}</code>\n"
                  f"⭐ <b>{data['sell_amount']} Stars</b>\n💰 Виплата: <b>{data['sell_price']} грн</b>\n"
                  f"💳 <code>{data['sell_wallet']}</code>")
    try: await bot.send_message(ADMIN_CHAT_ID, admin_text, reply_markup=order_kb(oid, "sell"))
    except: await bot.send_message(ADMIN_IDS[0], admin_text, reply_markup=order_kb(oid, "sell"))
    await state.set_state(S.menu)
    await send_menu(msg.from_user.id, T("sell_ok"))

# ========================================================
# КАЛЬКУЛЯТОР
# ========================================================

@dp.message(S.calc_stars)
async def calc_stars_h(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    try: amount = int(msg.text.strip())
    except: await msg.answer(T("err_num")); return
    price = round(amount * float(get_setting("stars_rate") or 0.74), 2)
    await msg.answer(T("calc_stars",amount=amount,price=price), reply_markup=cancel_kb())

# ========================================================
# ПІДТРИМКА
# ========================================================

@dp.message(S.support)
async def support(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.menu); await send_menu(msg.from_user.id, T("main_menu")); return
    file_id = file_type = ""
    text = msg.text or msg.caption or "Без тексту"
    if msg.photo: file_id,file_type = msg.photo[-1].file_id,"photo"
    elif msg.video: file_id,file_type = msg.video.file_id,"video"
    elif msg.document: file_id,file_type = msg.document.file_id,"document"
    tid = create_ticket(msg.from_user.id, text, file_id, file_type)
    uname = f"@{msg.from_user.username}" if msg.from_user.username else "Без ніка"
    admin_text = (f"🆘 <b>Звернення #{tid}</b>\n\n👤 {uname}\n🆔 <code>{msg.from_user.id}</code>\n"
                  f"📅 {msg.date.strftime('%d.%m.%Y %H:%M')}\n\n📝 <blockquote>{text}</blockquote>")
    try:
        if file_type == "photo": await bot.send_photo(ADMIN_CHAT_ID, photo=file_id, caption=admin_text, reply_markup=support_kb(tid))
        elif file_type == "video": await bot.send_video(ADMIN_CHAT_ID, video=file_id, caption=admin_text, reply_markup=support_kb(tid))
        elif file_type == "document": await bot.send_document(ADMIN_CHAT_ID, document=file_id, caption=admin_text, reply_markup=support_kb(tid))
        else: await bot.send_message(ADMIN_CHAT_ID, admin_text, reply_markup=support_kb(tid))
    except:
        try: await bot.send_message(ADMIN_IDS[0], admin_text, reply_markup=support_kb(tid))
        except: pass
    await state.set_state(S.menu)
    await send_menu(msg.from_user.id, T("support_sent"))

# ========================================================
# ЗАМОВЛЕННЯ
# ========================================================

@dp.callback_query(F.data.startswith("complete_"))
async def complete_order(cb: CallbackQuery):
    oid = int(cb.data.split("_")[1])
    order = get_order(oid)
    if not order:
        await cb.answer("Замовлення не знайдено"); return
    if order.get("status") == "completed":
        await cb.answer("Вже виконано"); return

    # Автовідправка TON — тільки для замовлень типу "ton", якщо налаштовано.
    # При невдачі замовлення НЕ позначається виконаним, показуємо помилку + кнопки повтору/ручного підтвердження.
    if order["order_type"] == "ton" and AUTO_TON_SEND_ENABLED:
        result = await auto_send_ton(order["wallet"], float(order["amount"]))
        if not result["ok"]:
            fail_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔁 Спробувати ще раз", callback_data=f"complete_{oid}"),
                InlineKeyboardButton(text="✍️ Підтвердити вручну", callback_data=f"manual_order_{oid}")
            ]])
            await cb.answer()
            try:
                await cb.message.edit_text(
                    (cb.message.text or cb.message.caption or "") +
                    f"\n\n❌ <b>АВТОВІДПРАВКА TON НЕ ВДАЛАСЬ</b>\n<i>{result.get('error','')[:500]}</i>",
                    reply_markup=fail_kb, parse_mode="HTML")
            except:
                await cb.message.answer(f"❌ Автовідправка TON не вдалась: {result.get('error','')[:500]}", reply_markup=fail_kb)
            return

    # Автовидача Telegram Premium через той самий гаманець.
    # Запускається лише після підтвердження замовлення адміністратором.
    if order["order_type"] == "premium" and AUTO_PREMIUM_SEND_ENABLED:
        await cb.answer()
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except: pass
        processing_msg = None
        try:
            processing_msg = await cb.message.answer("⏳ <b>Виконую автовидачу Premium...</b>\n\nЦе може зайняти до кількох хвилин, зачекайте.", parse_mode="HTML")
        except: pass
        result = await fragment_send_premium(order.get("recipient", ""), int(order["amount"]))
        if not result["ok"]:
            fail_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔁 Спробувати ще раз", callback_data=f"complete_{oid}"),
                InlineKeyboardButton(text="✍️ Підтвердити вручну", callback_data=f"manual_order_{oid}")
            ]])
            fail_text = f"❌ <b>АВТОВИДАЧА PREMIUM НЕ ВДАЛАСЬ</b>\n<i>{result.get('error','')[:500]}</i>"
            if processing_msg:
                try:
                    await processing_msg.edit_text(fail_text, reply_markup=fail_kb, parse_mode="HTML")
                except:
                    await cb.message.answer(fail_text, reply_markup=fail_kb, parse_mode="HTML")
            else:
                await cb.message.answer(fail_text, reply_markup=fail_kb, parse_mode="HTML")
            return
        tx_id = result.get("tx_id", "")
        tx_note = f"\nTask ID: <code>{tx_id}</code>" if tx_id else ""
        try:
            await cb.message.edit_text(
                (cb.message.text or cb.message.caption or "") +
                f"\n\n✅ <b>PREMIUM ВИДАНО АВТОМАТИЧНО</b>{tx_note}",
                parse_mode="HTML")
        except Exception:
            pass
        if processing_msg:
            try: await processing_msg.delete()
            except: pass

    ok = await finalize_order(oid)
    if not ok:
        await cb.answer("Замовлення не знайдено"); return
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except: pass
    await cb.answer()

@dp.callback_query(F.data.startswith("manual_order_"))
async def manual_order(cb: CallbackQuery):
    """Фолбек: адмін сам виконав TON/Premium вручну (наприклад, на Fragment)
    і підтверджує це в боті — без повторної спроби автовидачі."""
    oid = int(cb.data.split("_")[-1])
    order = get_order(oid)
    if not order:
        await cb.answer("Замовлення не знайдено"); return
    if order.get("status") == "completed":
        await cb.answer("Вже виконано"); return
    ok = await finalize_order(oid)
    if not ok:
        await cb.answer("Замовлення не знайдено"); return
    try:
        await cb.message.edit_text((cb.message.text or cb.message.caption or "") + "\n\n✅ <b>ВИКОНАНО (вручну)</b>", parse_mode="HTML")
    except: pass
    await cb.answer()

def get_linked_gift_for_package(package_key):
    """Повертає товар з каталогу подарунків (gift_items), прив'язаний до цього паку Stars,
    або None, якщо прив'язки немає."""
    if not package_key:
        return None
    pkg = get_stars_package(package_key)
    if not pkg or not pkg.get("linked_gift_key"):
        return None
    return get_gift_item(pkg["linked_gift_key"])

def get_order_gift_sent_count(oid: int) -> int:
    order = get_order(oid)
    return int(order.get("gift_sent_count") or 0) if order else 0

def set_order_gift_sent_count(oid: int, count: int) -> None:
    conn = get_conn(); c = conn.cursor()
    c.execute("UPDATE orders SET gift_sent_count=? WHERE id=?", (count, oid))
    conn.commit(); conn.close()

async def _send_linked_stars_gift(oid: int) -> dict:
    """Надсилає реальний(і) Telegram-подарунок(и) для замовлення на пак Stars, прив'язаний
    до товару з каталогу подарунків. Якщо у паку вказано кількість > 1 — надсилає їх по черзі
    (з невеликою паузою). Якщо частина замовлення вже була успішно надіслана раніше (повторна
    спроба) — досилає лише решту. Сповіщає покупця й адмін-групу про результат."""
    order = get_order(oid)
    if not order:
        return {"ok": False, "error": "Замовлення не знайдено"}
    gift_item = get_linked_gift_for_package(order.get("package_key"))
    if not gift_item:
        return {"ok": False, "error": "Немає прив'язаного подарунка"}
    gift_tg_id = gift_item.get("telegram_gift_id")
    pkg = get_stars_package(order.get("package_key")) or {}
    total_qty = max(1, int(pkg.get("linked_gift_qty") or 1))
    already_sent = get_order_gift_sent_count(oid)
    remaining = total_qty - already_sent

    if remaining <= 0:
        result = {"ok": True, "sent": already_sent, "total": total_qty}
    elif not gift_tg_id:
        result = {"ok": False, "error": f"Для «{gift_item.get('name') or gift_item.get('emoji')}» не вказано Telegram Gift ID"}
    elif not GIFT_TELETHON_AVAILABLE:
        result = {"ok": False, "error": "Пакет telethon не встановлено на сервері"}
    else:
        sent_now = 0
        last_error = None
        for _ in range(remaining):
            r = await send_star_gift(int(gift_tg_id), order["recipient"], "", hide_name=True)
            if r.get("ok"):
                sent_now += 1
                set_order_gift_sent_count(oid, already_sent + sent_now)
                if sent_now < remaining:
                    await asyncio.sleep(1.5)  # невелика пауза між відправками, щоб не зловити flood-ліміт
            else:
                last_error = r.get("error", "невідома помилка")
                break
        total_sent = already_sent + sent_now
        if total_sent >= total_qty:
            result = {"ok": True, "sent": total_sent, "total": total_qty}
        else:
            result = {"ok": False, "error": last_error or "невідома помилка",
                       "sent": total_sent, "total": total_qty}

    if result.get("ok"):
        qty_line = f" ({total_qty} шт.)" if total_qty > 1 else ""
        try:
            await bot.send_message(
                order["user_id"],
                f"🎉 <b>Подарунок надіслано!</b>\n\n🎁 Ваш подарунок для {order['recipient']} успішно доставлено{qty_line}.",
                parse_mode="HTML")
        except Exception:
            pass
        try:
            await bot.send_message(ADMIN_CHAT_ID, f"🎁✅ Подарунок за замовленням #{oid} успішно надіслано автоматично{qty_line}!", parse_mode="HTML")
        except Exception:
            pass
    else:
        progress_line = f"\n📦 Надіслано: {result.get('sent', 0)}/{result.get('total', 1)}" if result.get("total", 1) > 1 else ""
        try:
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"⚠️ <b>Автовидача не вдалась для замовлення #{oid}</b>\n\n"
                f"Причина: {result.get('error', 'невідома помилка')}{progress_line}\n\n"
                f"Надішліть подарунок вручну або натисніть «🔁 Повторити видачу» (довидасть лише решту).",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔁 Повторити видачу", callback_data=f"ordergiftretry_{oid}")
                ]]), parse_mode="HTML")
        except Exception:
            pass
    return result

@dp.callback_query(F.data.startswith("ordergiftretry_"))
async def order_gift_retry_cb(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer(); return
    oid = int(cb.data.replace("ordergiftretry_", "", 1))
    await cb.answer("⏳ Повторюю спробу...")
    try: await cb.message.edit_reply_markup(reply_markup=None)
    except Exception: pass
    await _send_linked_stars_gift(oid)

async def finalize_order(oid: int) -> bool:
    """Позначає замовлення виконаним, нараховує бонуси/реферальну комісію і
    сповіщає покупця. Використовується і адмін-кнопкою «Виконано», і автоматично
    після оплати Telegram Stars. Повертає False, якщо замовлення не знайдено."""
    order = get_order(oid)
    if not order: return False
    update_order_status(oid, "completed")
    update_user_stats(order["user_id"], order["order_type"], order["amount"], order["price_uah"])
    linked_gift = None
    if order["order_type"] == "stars":
        linked_gift = get_linked_gift_for_package(order.get("package_key"))
        if not linked_gift:
            add_stars_balance(order["user_id"], int(order["amount"]))
            logger.info(f"Stars credited: {order['amount']} to user {order['user_id']}")
        else:
            logger.info(f"Order #{oid}: pack linked to gift '{linked_gift.get('name')}' — sending real gift instead of Stars")

    # Реферальна комісія — нараховується через єдину функцію (узгоджена з ref_by)
    ref_by, commission = pay_referral_commission(order["user_id"], order["price_uah"], order["order_type"], order["amount"])
    if ref_by and commission > 0:
        try:
            item_text = (f"{fmt_price(order['amount'])} ⭐" if order["order_type"] == "stars"
                         else f"{fmt_price(order['amount'])} TON" if order["order_type"] == "ton"
                         else "🎁 Подарунок" if order["order_type"] == "gift"
                         else f"Telegram Premium на {fmt_price(order['amount'])} міс.")
            comm_text = (
                f"🎉 <b>Твій друг щось придбав!</b>\n\n"
                f"📦 <b>Покупка:</b> {item_text}\n\n"
                f"⭐ <b>Твоя винагорода: {commission} Stars</b>"
            )
            await bot.send_message(ref_by, comm_text, parse_mode="HTML")
        except: pass

    order_type = order["order_type"]

    if order_type == "stars" and linked_gift:
        order_details = f"🎁 <b>Подарунок буде відправлено акаунту {order['recipient']} найближчим часом!</b>"
        order_done_text = (get_bot_text("order_done_review") or
            "✅ <b>Замовлення виконано!</b>\n\n{order_details}\n\n💙 <b>Дякуємо за покупку!</b>\n\n"
            "🎁 <b>Залиште відгук і отримайте 1-2 Stars на баланс безкоштовно!</b>\n\n"
            "📸 <b>Спочатку прикріпіть фото або скріншот покупки.</b>\n"
            "<i>(це обов'язково — без фото відгук не буде прийнято)</i>\n\n"
            "<blockquote>Це дуже важливо для нас 🙂</blockquote>\n\n"
            "<i>Натисніть «Пропустити» якщо не хочете залишати відгук.</i>"
        ).replace("{order_details}", order_details)
    elif order_type == "stars":
        order_done_text = (
            f"✅ <b>Замовлення виконано!</b>\n\n"
            f"⭐ <b>{int(order['amount'])} Stars зараховано на ваш баланс!</b>\n\n"
            f"💙 <b>Дякуємо що обрали {BOT_NAME}!</b>"
            f"\n\n<blockquote>💡 Зірки вже на вашому балансі в боті!\nЩоб вивести — натисніть Профіль → Вивести Stars 👤</blockquote>"
        )
    elif order_type == "ton":
        order_details = (
            f"💎 <b>{order['amount']} TON відправлено на гаманець:</b>\n"
            f"<code>{order['wallet']}</code>"
        )
        order_done_text = (get_bot_text("order_done_review") or
            "✅ <b>Замовлення виконано!</b>\n\n{order_details}\n\n💙 <b>Дякуємо за покупку!</b>\n\n"
            "🎁 <b>Залиште відгук і отримайте 1-2 Stars на баланс безкоштовно!</b>\n\n"
            "📸 <b>Спочатку прикріпіть фото або скріншот покупки.</b>\n"
            "<i>(це обов'язково — без фото відгук не буде прийнято)</i>\n\n"
            "<blockquote>Це дуже важливо для нас 🙂</blockquote>\n\n"
            "<i>Натисніть «Пропустити» якщо не хочете залишати відгук.</i>"
        ).replace("{order_details}", order_details)
    elif order_type == "gift":
        order_details = f"🎁 <b>Подарунок буде відправлено акаунту {order['recipient']} найближчим часом!</b>"
        order_done_text = (get_bot_text("order_done_review") or
            "✅ <b>Замовлення виконано!</b>\n\n{order_details}\n\n💙 <b>Дякуємо за покупку!</b>\n\n"
            "🎁 <b>Залиште відгук і отримайте 1-2 Stars на баланс безкоштовно!</b>\n\n"
            "📸 <b>Спочатку прикріпіть фото або скріншот покупки.</b>\n"
            "<i>(це обов'язково — без фото відгук не буде прийнято)</i>\n\n"
            "<blockquote>Це дуже важливо для нас 🙂</blockquote>\n\n"
            "<i>Натисніть «Пропустити» якщо не хочете залишати відгук.</i>"
        ).replace("{order_details}", order_details)
    elif order_type == "premium":
        months_int = int(order['amount'])
        if months_int == 3: months_str = "3 місяці"
        elif months_int == 6: months_str = "6 місяців"
        else: months_str = f"{months_int} місяців"
        order_details = f"🚀 <b>Telegram Premium на {months_str} передано акаунту {order['recipient']}!</b>"
        order_done_text = (get_bot_text("order_done_review") or
            "✅ <b>Замовлення виконано!</b>\n\n{order_details}\n\n💙 <b>Дякуємо за покупку!</b>\n\n"
            "🎁 <b>Залиште відгук і отримайте 1-2 Stars на баланс безкоштовно!</b>\n\n"
            "📸 <b>Спочатку прикріпіть фото або скріншот покупки.</b>\n"
            "<i>(це обов'язково — без фото відгук не буде прийнято)</i>\n\n"
            "<blockquote>Це дуже важливо для нас 🙂</blockquote>\n\n"
            "<i>Натисніть «Пропустити» якщо не хочете залишати відгук.</i>"
        ).replace("{order_details}", order_details)
    elif order_type == "sell_stars":
        order_done_text = (
            f"✅ <b>Виплату здійснено!</b>\n\n"
            f"💰 <b>{order['price_uah']} грн відправлено на ваші реквізити!</b>\n\n"
            f"💙 <b>Дякуємо що обрали {BOT_NAME}!</b>"
        )
    else:
        order_done_text = f"✅ <b>Замовлення виконано!</b>\n\n💙 <b>Дякуємо що обрали {BOT_NAME}!</b>"

    # Для TON/Premium/подарунка через пак Stars відправляємо єдине повідомлення одразу
    # з клавіатурою "Пропустити", та готуємо state для прийому відгуку — щоб усе було
    # за один крок, як і для виводу Stars.
    if order_type in ("ton", "gift", "premium") or (order_type == "stars" and linked_gift):
        uid = order["user_id"]
        try:
            user_state = FSMContext(storage=storage,
                key=StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid))
            await user_state.update_data(review_order_type=order_type, review_amount=order["amount"])
            await user_state.set_state(S.waiting_review)
        except Exception as e:
            logger.error(f"review request error: {e}")
        try:
            await bot.send_message(order["user_id"], order_done_text, reply_markup=review_kb(), parse_mode="HTML")
        except: pass
    else:
        try:
            await bot.send_message(order["user_id"], order_done_text, parse_mode="HTML")
        except: pass

    if order_type == "stars" and not linked_gift:
        uid = order["user_id"]
        user_state = FSMContext(storage=storage,
            key=StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid))
        await user_state.set_data({})
        await user_state.set_state(S.menu)

    if order_type == "stars" and linked_gift:
        asyncio.create_task(_send_linked_stars_gift(oid))

    return True

# ========================================================
# ⭐ ОПЛАТА TELEGRAM STARS (Premium / Подарунки)
# ========================================================

@dp.callback_query(F.data.startswith("paystars_prem_"))
async def paystars_prem_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    if get_setting("stars_pay_premium_enabled") != "1":
        await cb.answer("⭐ Оплата Stars тимчасово недоступна", show_alert=True); return
    try:
        months = int(cb.data.replace("paystars_prem_", ""))
    except Exception:
        return
    data = await state.get_data()
    price_uah = data.get("prem_price") or float(get_setting({3:"premium_3m",6:"premium_6m",12:"premium_12m"}.get(months,"premium_3m")) or 0)
    recipient = data.get("recipient") or (f"@{cb.from_user.username}" if cb.from_user.username else f"ID:{cb.from_user.id}")
    oid = create_order(cb.from_user.id, "premium", months, price_uah, recipient, "", "stars_xtr")
    stars = premium_price_stars(months)
    try:
        await bot.send_invoice(
            chat_id=cb.from_user.id,
            title=f"Telegram Premium — {months} міс.",
            description=f"Купівля Telegram Premium на {months} місяців для {recipient}",
            payload=f"premstars_{oid}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"Premium {months} міс.", amount=stars)]
        )
    except Exception as e:
        logger.error(f"send_invoice premium error: {e}")
        await cb.message.answer(f"❌ Не вдалося створити рахунок: {e}")

@dp.callback_query(F.data == "paystars_gift")
async def paystars_gift_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    if get_setting("stars_pay_gift_enabled") != "1":
        await cb.answer("⭐ Оплата Stars тимчасово недоступна", show_alert=True); return
    data = await state.get_data()
    order_uid = data.get("gift_order_uid")
    order = get_gift_order(order_uid) if order_uid else None
    if not order:
        await cb.answer("❌ Замовлення застаріло, почніть заново", show_alert=True); return
    item = get_gift_item(order["item_key"]) or {}
    stars = gift_price_stars(item)
    update_gift_order(order_uid, payment_method="stars_xtr")
    try:
        await bot.send_invoice(
            chat_id=cb.from_user.id,
            title=f"{order['gift_emoji']} {order['gift_name']}",
            description=f"Подарунок для {order['target_username']}",
            payload=f"giftstars_{order_uid}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=order["gift_name"], amount=stars)]
        )
    except Exception as e:
        logger.error(f"send_invoice gift error: {e}")
        await cb.message.answer(f"❌ Не вдалося створити рахунок: {e}")

@dp.pre_checkout_query()
async def stars_pre_checkout(pcq: PreCheckoutQuery):
    payload = pcq.invoice_payload or ""
    if payload.startswith("premstars_"):
        try:
            oid = int(payload.replace("premstars_", ""))
            order = get_order(oid)
            if not order or order.get("status") == "completed":
                await pcq.answer(ok=False, error_message="Це замовлення вже недійсне")
                return
        except Exception:
            await pcq.answer(ok=False, error_message="Помилка замовлення"); return
    elif payload.startswith("giftstars_"):
        order_uid = payload.replace("giftstars_", "")
        order = get_gift_order(order_uid)
        if not order or order.get("status") in ("completed", "approved", "rejected"):
            await pcq.answer(ok=False, error_message="Це замовлення вже недійсне")
            return
    await pcq.answer(ok=True)

@dp.message(F.successful_payment)
async def stars_successful_payment(msg: Message, state: FSMContext):
    payload = msg.successful_payment.invoice_payload or ""
    if payload.startswith("premstars_"):
        oid = int(payload.replace("premstars_", ""))
        order = get_order(oid)
        if not order:
            return
        try:
            await msg.answer(
                "✅ <b>Оплату Stars отримано!</b>\n\n⏳ Заявку передано адміністратору — Premium буде активовано найближчим часом.",
                parse_mode="HTML")
        except Exception:
            pass
        try:
            uname = f"@{msg.from_user.username}" if msg.from_user.username else f"ID:{msg.from_user.id}"
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"⭐ <b>Замовлення #{oid} — Premium (оплачено Stars)</b>\n\n"
                f"👤 {uname} 🆔 <code>{msg.from_user.id}</code>\n"
                f"🚀 Premium на {order['amount']} міс. для {order['recipient']}\n\n"
                f"✅ Оплата вже підтверджена Telegram — натисніть кнопку нижче, щоб активувати Premium і завершити замовлення.",
                reply_markup=order_kb(oid, "premium"), parse_mode="HTML")
        except Exception as e:
            logger.error(f"admin notify premstars error: {e}")
    elif payload.startswith("giftstars_"):
        order_uid = payload.replace("giftstars_", "")
        order = get_gift_order(order_uid)
        if not order:
            return
        update_gift_order(order_uid, status="approved")
        decrement_gift_quantity(order["item_key"])
        try:
            await bot.send_message(
                msg.from_user.id,
                f"✅ <b>Оплату отримано!</b>\n\n🎁 Ваш подарунок для {order['target_username']} буде надіслано найближчим часом.",
                parse_mode="HTML")
        except Exception:
            pass
        try:
            uname = f"@{msg.from_user.username}" if msg.from_user.username else f"ID:{msg.from_user.id}"
            notice = await bot.send_message(
                ADMIN_CHAT_ID,
                f"⭐ <b>Оплачено Telegram Stars — подарунок {order_uid}</b>\n\n"
                f"👤 {uname} 🆔 <code>{msg.from_user.id}</code>\n"
                f"🎁 {order['gift_emoji']} {order['gift_name']} → {order['target_username']}",
                parse_mode="HTML")
        except Exception:
            notice = None
        if notice is not None:
            asyncio.create_task(_try_auto_fulfill_gift(notice, order_uid))
        asyncio.create_task(request_gift_review(order))
    await state.set_state(S.menu)
    await send_menu(msg.from_user.id, T("main_menu"))

@dp.callback_query(F.data.startswith("reject_"))
async def reject_start(cb: CallbackQuery, state: FSMContext):
    oid = int(cb.data.split("_")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Невірна квитанція",   callback_data=f"rej_ord_{oid}_Невірна квитанція")],
        [InlineKeyboardButton(text="⏳ Технічні роботи",     callback_data=f"rej_ord_{oid}_Технічні роботи")],
        [InlineKeyboardButton(text="🚫 Порушення правил",    callback_data=f"rej_ord_{oid}_Порушення правил")],
        [InlineKeyboardButton(text="💸 Оплата не надійшла",  callback_data=f"rej_ord_{oid}_Оплата не надійшла")],
    ])
    await cb.message.answer(f"❌ <b>Вкажіть причину відхилення замовлення #{oid}:</b>", reply_markup=kb, parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data.startswith("rej_ord_"))
async def reject_with_reason(cb: CallbackQuery):
    parts = cb.data.split("_", 3)  # rej, ord, oid, reason_text
    oid = int(parts[2])
    reason = parts[3]
    order = get_order(oid)
    if order:
        update_order_status(oid, "rejected")
        try:
            await bot.send_message(order["user_id"], T("order_rejected", reason=reason), parse_mode="HTML")
        except: pass
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except: pass
    await cb.message.answer(f"❌ <b>Замовлення #{oid} відхилено.</b>\n📝 Причина: {reason}", parse_mode="HTML")
    await cb.answer()

@dp.message(S.admin_reject)
async def reject_reason(msg: Message, state: FSMContext):
    data = await state.get_data(); order = get_order(data.get("reject_oid"))
    if order:
        update_order_status(data["reject_oid"], "rejected")
        try:
            await bot.send_message(order["user_id"], T("order_rejected",reason=msg.text), parse_mode="HTML")
        except: pass
    await msg.answer("❌ <b>Відхилено</b>", parse_mode="HTML")
    await state.set_state(S.admin)

# ========================================================
# ВІДГУКИ (через таблицю reviews — без set_setting-хаків)
# ========================================================

def review_admin_kb_full(rid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опублікувати", callback_data=f"pub_review_{rid}"),
         InlineKeyboardButton(text="❌ Відхилити",    callback_data=f"rej_review_{rid}")]
    ])

@dp.callback_query(F.data == "review_skip")
async def review_skip_cb(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except: pass
    user_state = FSMContext(storage=storage,
        key=StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid))
    await user_state.set_data({})
    await user_state.set_state(S.menu)
    await send_menu(uid, T("review_skipped"))

@dp.message(S.waiting_review)
async def review_receive(msg: Message, state: FSMContext):
    uid = msg.from_user.id
    if is_skip(msg.text if hasattr(msg, 'text') else None):
        await state.set_state(S.menu)
        await send_menu(uid, T("review_skipped"))
        return
    if not msg.photo:
        # Фото обов'язкове — без нього відгук не приймаємо, навіть якщо є текст.
        await msg.answer(
            "📸 <b>Будь ласка, спочатку прикріпіть фото або скріншот покупки.</b>\n\n"
            "<i>Без фото відгук не приймається.</i>\n\n"
            "<blockquote>Це дуже важливо для нас 🙂</blockquote>\n\n"
            "Натисніть «Пропустити» якщо не хочете залишати відгук.",
            parse_mode="HTML")
        return
    photo_file_id = msg.photo[-1].file_id
    caption = (msg.caption or "").strip()
    await state.update_data(review_photo_id=photo_file_id)
    if caption:
        await state.update_data(review_comment=caption)
        await _finish_review(msg, state, 5)
    else:
        await state.set_state(S.review_text)
        await msg.answer("✍️ <b>Тепер напишіть кілька слів про наш сервіс</b>", parse_mode="HTML")

@dp.message(S.review_text)
async def review_text_handler(msg: Message, state: FSMContext):
    if is_skip(msg.text if hasattr(msg, 'text') else None):
        await state.set_state(S.menu)
        await send_menu(msg.from_user.id, T("review_skipped"))
        return
    comment = (msg.text or "").strip()
    if not comment:
        await msg.answer("✍️ Напишіть текст відгуку:")
        return
    await state.update_data(review_comment=comment)
    await _finish_review(msg, state, 5)

async def _finish_review(msg_or_cb, state: FSMContext, rating: int):
    uid = msg_or_cb.from_user.id
    data = await state.get_data()
    comment = data.get("review_comment", "")
    photo_id = data.get("review_photo_id", "")
    review_order_type = data.get("review_order_type", "")
    review_amount = data.get("review_amount", 0)
    rid = create_review(uid, comment, photo_id, rating, review_order_type, review_amount)

    u = get_user(uid)
    uname = f"@{msg_or_cb.from_user.username}" if msg_or_cb.from_user.username else f"ID:{uid}"
    admin_text = (
        f"⭐ <b>Новий відгук #{rid}</b>\n\n"
        f"👤 {uname}\n🆔 <code>{uid}</code>\n"
        f"{'⭐'*rating if rating else ''}\n\n"
        f"💬 {comment or '(без тексту)'}\n"
        f"{'🖼 З фото' if photo_id else ''}\n\n"
        f"Натисніть ✅ щоб опублікувати і видати нагороду, або ❌ відхилити."
    )
    try:
        if photo_id:
            await bot.send_photo(ADMIN_CHAT_ID, photo=photo_id, caption=admin_text,
                                 reply_markup=review_admin_kb_full(rid), parse_mode="HTML")
        else:
            await bot.send_message(ADMIN_CHAT_ID, admin_text,
                                   reply_markup=review_admin_kb_full(rid), parse_mode="HTML")
    except:
        try:
            if photo_id:
                await bot.send_photo(ADMIN_IDS[0], photo=photo_id, caption=admin_text,
                                     reply_markup=review_admin_kb_full(rid), parse_mode="HTML")
            else:
                await bot.send_message(ADMIN_IDS[0], admin_text,
                                       reply_markup=review_admin_kb_full(rid), parse_mode="HTML")
        except: pass

    await state.set_state(S.menu)
    text = (
        "⏳ <b>Дякуємо!</b>\n\n"
        "Ваш відгук на перевірці. Бонус надійде на баланс автоматично 🎁"
    )
    if isinstance(msg_or_cb, CallbackQuery):
        await msg_or_cb.message.answer(text, parse_mode="HTML")
    else:
        await msg_or_cb.answer(text, parse_mode="HTML")
    await send_menu(uid, T("main_menu"))

@dp.callback_query(F.data.startswith("pub_review_"))
async def publish_review(cb: CallbackQuery):
    rid = int(cb.data.replace("pub_review_",""))
    review = get_review(rid)
    if not review:
        await cb.answer("Відгук не знайдено"); return
    update_review_status(rid, "published")

    user = get_user(review["user_id"])
    client_name = (user.get("full_name") if user else None) or f"ID:{review['user_id']}"
    review_order_type = review.get("order_type") or ""
    review_amount = review.get("amount") or 0

    if review_order_type == "stars":
        total_amount = get_total_withdrawn(review["user_id"])
    elif review_order_type == "ton":
        total_amount = get_total_ton_bought(review["user_id"])
    else:
        total_amount = 0

    channel_text = build_channel_review(rid, client_name, review["comment"], review["rating"],
                                        str(review["created_at"])[:10],
                                        order_type=review_order_type, amount=review_amount,
                                        total_amount=total_amount)
    try:
        if review["photo_id"]:
            await bot.send_photo(REVIEWS_CHANNEL, photo=review["photo_id"], caption=channel_text,
                                 reply_markup=buy_stars_kb(), parse_mode="HTML")
        else:
            await bot.send_message(REVIEWS_CHANNEL, channel_text, reply_markup=buy_stars_kb(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"publish review error: {e}")

    reward_min = int(get_setting("review_reward_min") or 1)
    reward_max = int(get_setting("review_reward_max") or 2)
    reward = random.randint(reward_min, reward_max)
    add_stars_balance(review["user_id"], reward)
    try:
        await bot.send_message(review["user_id"],
            f"🎉 <b>Ваш відгук опубліковано!</b>\n\n⭐ <b>Нагорода: {reward} Stars</b> вже на вашому балансі!",
            parse_mode="HTML")
    except: pass

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except: pass
    await cb.answer("Опубліковано!")

@dp.callback_query(F.data.startswith("rej_review_"))
async def reject_review(cb: CallbackQuery):
    rid = int(cb.data.replace("rej_review_",""))
    review = get_review(rid)
    if review:
        update_review_status(rid, "rejected")
        try:
            await bot.send_message(review["user_id"],
                "❌ <b>Ваш відгук не пройшов перевірку.</b>\n\nСпробуйте залишити інший відгук.",
                parse_mode="HTML")
        except: pass
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except: pass
    await cb.answer("Відхилено")

@dp.callback_query(F.data.startswith("reply_"))
async def reply_start(cb: CallbackQuery, state: FSMContext):
    tid = int(cb.data.replace("reply_",""))
    await state.update_data(reply_tid=tid)
    await cb.message.answer(f"✍️ Введіть відповідь на звернення #{tid}:", reply_markup=cancel_kb())
    await state.set_state(S.admin_reply)
    await cb.answer()

@dp.message(S.admin_reply)
async def reply_send(msg: Message, state: FSMContext):
    data = await state.get_data()
    tid = data.get("reply_tid")
    ticket = get_ticket(tid)
    if ticket:
        try:
            reply_text = (get_bot_text("support_reply") or "💬 <b>Відповідь від підтримки</b>\n\n{text}").replace("{text}", msg.text)
            await bot.send_message(ticket["user_id"], reply_text, parse_mode="HTML")
            await msg.answer("✅ Відповідь надіслано", reply_markup=admin_main_kb())
        except Exception as e:
            await msg.answer(f"❌ Помилка надсилання: {e}", reply_markup=admin_main_kb())
    await state.set_state(S.admin)

@dp.callback_query(F.data == 'check_sub')
async def cb_check_sub(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id
    if await check_subscription(uid):
        await cb.answer("✅ Підписка підтверджена!")
        try: await cb.message.delete()
        except: pass
        await state.set_state(S.menu)
        data = await state.get_data()
        deep = data.get("pending_deep", "")
        await process_referral_and_welcome(uid, cb.from_user.username, cb.from_user.first_name, deep, state)
    else:
        await cb.answer("❌ Ви ще не підписані на всі канали!", show_alert=True)

# ========================================================
# АДМІН-МЕНЮ (диспетчер reply-кнопок)
# ========================================================

def admin_orders_kb():
    orders = get_pending_orders()
    if not orders:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]])
    rows = []
    type_emoji = {"stars":"⭐","ton":"💵","premium":"💎","gift":"🎁","sell_stars":"💰"}
    for o in orders:
        uname = f"@{o['username']}" if o.get('username') else f"ID:{o['user_id']}"
        rows.append([InlineKeyboardButton(
            text=f"{type_emoji.get(o['order_type'],'📦')} #{o['id']} — {uname} — {o['amount']}",
            callback_data=f"admorder_{o['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data.startswith("admorder_"))
async def admin_order_detail(cb: CallbackQuery):
    oid = int(cb.data.replace("admorder_",""))
    order = get_order(oid)
    if not order:
        await cb.answer("Замовлення не знайдено"); return
    type_names = {"stars":"⭐ Stars","ton":"💵 TON","premium":"💎 Premium","gift":"🎁 Подарунок","sell_stars":"💰 Продаж Stars"}
    text = (
        f"📦 <b>Замовлення #{oid}</b>\n\n"
        f"Тип: <b>{type_names.get(order['order_type'], order['order_type'])}</b>\n"
        f"👤 User ID: <code>{order['user_id']}</code>\n"
        f"📊 Кількість: <b>{order['amount']}</b>\n"
        f"💰 Сума: <b>{order['price_uah']} грн</b>\n"
        f"📅 {order['created_at']}\n"
        f"📌 Статус: <b>{order['status']}</b>"
    )
    await cb.message.answer(text, reply_markup=order_kb(oid, order['order_type']), parse_mode="HTML")
    await cb.answer()

@dp.message(S.admin, ~F.text.startswith("/"))
async def admin_menu_handler(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    txt = msg.text or ""

    async def show_inline(text, kb):
        await msg.answer(text, reply_markup=kb, parse_mode="HTML")

    if "Статистика продаж" in txt:
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT COUNT(*) as t FROM users"); total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) as t FROM users WHERE date(registered_at)=date('now')"); today_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) as t FROM orders WHERE status='completed'"); orders = c.fetchone()[0]
        c.execute("SELECT COALESCE(SUM(price_uah),0) as t FROM orders WHERE status='completed'"); revenue = c.fetchone()[0]
        conn.close()
        await msg.answer(
            f"📊 <b>Статистика продаж</b>\n\n"
            f"👥 Всього юзерів: <b>{total}</b>\n"
            f"🆕 Сьогодні: <b>{today_users}</b>\n"
            f"✅ Виконано замовлень: <b>{orders}</b>\n"
            f"💰 Виручка: <b>{round(revenue,2)} грн</b>",
            reply_markup=admin_main_kb(), parse_mode="HTML")
    elif "Статистика" in txt:
        total, active, sales, banned, pending = get_stats()
        await msg.answer(
            f"📊 <b>Статистика</b>\n\n"
            f"👥 Всього юзерів: <b>{total}</b>\n"
            f"🟢 Активні (7 днів): <b>{active}</b>\n"
            f"💰 Загальний обіг: <b>{sales} грн</b>\n"
            f"🚫 Забанено: <b>{banned}</b>\n"
            f"⏳ В очікуванні: <b>{pending}</b>",
            reply_markup=admin_main_kb(), parse_mode="HTML")
    elif "Курси і ціни" in txt:
        await show_inline("💰 <b>Курси і ціни</b>", admin_prices_kb())
    elif "Мінімуми" in txt:
        await show_inline("⚙️ <b>Мінімуми і нагороди</b>", admin_minimums_kb())
    elif "Кнопки меню" in txt:
        await show_inline("🎨 <b>Кнопки меню</b>", admin_menu_btns_kb())
    elif "Тексти бота" in txt:
        await show_inline("📝 <b>Редагування текстів</b>", admin_texts_kb())
    elif "Способи оплати" in txt:
        await show_inline("💳 <b>Способи оплати</b>", admin_methods_kb())
    elif "Знайти юзера" in txt:
        await msg.answer("👤 Введіть ID або @username:", reply_markup=admin_main_kb())
        await state.set_state(S.admin_find_user)
    elif "Активні замовлення" in txt:
        await show_inline("📋 <b>Активні замовлення</b>", admin_orders_kb())
    elif "Забанені" in txt:
        banned = get_banned_users()
        if not banned:
            await msg.answer("✅ Забанених немає", reply_markup=admin_main_kb())
        else:
            txt2 = "🚫 <b>Забанені:</b>\n\n"
            for u in banned:
                txt2 += f"👤 @{u['username']} | ID: {u['user_id']}\n"
            await msg.answer(txt2, reply_markup=admin_main_kb(), parse_mode="HTML")
    elif "Каталог подарунків" in txt:
        await msg.answer("🎁 <b>Подарунки — редагування каталогу</b>\n\nОберіть позицію:", reply_markup=admin_gifts_kb(), parse_mode="HTML")
    elif "Паки Stars" in txt:
        await msg.answer("⭐ <b>Паки Stars — редагування каталогу</b>\n\nОберіть позицію:", reply_markup=admin_star_packages_kb(), parse_mode="HTML")
    elif "Реферали" in txt:
        ref_enabled = get_setting("ref_enabled") == "1"
        ref_percent = get_setting("ref_percent_purchase") or "5"
        status = "✅ Включена" if ref_enabled else "❌ Вимкнена"
        await msg.answer(
            f"👥 <b>Реферальна система</b>\n\nСтатус: <b>{status}</b>\n💰 Відсоток: <b>{ref_percent}%</b>",
            reply_markup=admin_refs_kb(), parse_mode="HTML")
    elif "Розсилка" in txt:
        await msg.answer(
            "📢 <b>Введіть текст розсилки</b>\n\n"
            "Можна форматувати як завгодно: <b>жирний</b>, <i>курсив</i>, преміум-емодзі "
            "(просто вставте потрібне форматування прямо в повідомленні через звичайну "
            "клавіатуру Telegram) — все збережеться під час відправки.\n\n"
            "Також можна прикріпити фото/відео з підписом.",
            reply_markup=admin_main_kb(), parse_mode="HTML")
        await state.set_state(S.admin_broadcast)
    elif "Обов. підписка" in txt:
        channels = [c.strip() for c in (get_setting("sub_channels") or REVIEWS_CHANNEL).split(",") if c.strip()]
        enabled = get_setting("sub_required") == "1"
        status = "✅ Включена" if enabled else "❌ Вимкнена"
        ch_list = "\n".join([f"• @{c}" for c in channels]) or "(немає)"
        rows = [[InlineKeyboardButton(text="✅ Включити" if not enabled else "❌ Вимкнути", callback_data="adm_sub_toggle")]]
        rows += [[InlineKeyboardButton(text=f"🗑 Видалити @{c}", callback_data=f"adm_sub_del_{c}")] for c in channels]
        rows += [[InlineKeyboardButton(text="➕ Додати канал", callback_data="adm_sub_channel")]]
        rows += [[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]]
        await msg.answer(
            f"🔔 <b>Обов'язкова підписка</b>\n\nСтатус: <b>{status}</b>\n\n<b>Канали:</b>\n{ch_list}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    elif "Фото для розділів" in txt:
        sections = ["stars", "premium", "ton", "gift", "profile", "support"]
        section_names = {
            "stars": "⭐ Купити Stars",
            "premium": "💎 Telegram Premium",
            "ton": "💵 Купити TON",
            "gift": "🎁 Подарунки",
            "profile": "👤 Профіль",
            "support": "📞 Підтримка",
        }
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=section_names[s], callback_data=f"adm_photo_{s}")]
            for s in sections
        ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]])
        await msg.answer("📸 <b>Оберіть розділ для завантаження фото:</b>", reply_markup=kb, parse_mode="HTML")
    elif "Вийти" in txt:
        await state.set_state(S.menu)
        await send_menu(msg.from_user.id, "👋 Вийшли з адмінки")

# ========================================================
# АДМІН-КОЛБЕКИ (adm_*)
# ========================================================

@dp.callback_query(F.data.startswith("adm_"))
async def admin_callback(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer(); return
    await state.set_state(S.admin)
    action = cb.data.replace("adm_","",1)
    await cb.answer()

    async def edit(text, kb=None):
        try: await cb.message.edit_text(text, reply_markup=kb or admin_back_kb(), parse_mode="HTML")
        except: await cb.message.answer(text, reply_markup=kb or admin_back_kb(), parse_mode="HTML")

    if action == "stats":
        total, active, sales, banned, pending = get_stats()
        conn = get_conn(); c = conn.cursor()
        method_lines = ""
        for m in get_payment_methods():
            c.execute("SELECT COUNT(*) as t FROM orders WHERE bank=? AND status!='rejected'", (m["method_key"],))
            count = c.fetchone()["t"]
            method_lines += f"\n  {m['name_uk']}: <b>{count}</b>"
        conn.close()
        text = (f"📊 <b>Статистика</b>\n\n"
                f"👥 Користувачів: <b>{total}</b>\n"
                f"🟢 Активних (7 днів): <b>{active}</b>\n"
                f"🚫 Забанено: <b>{banned}</b>\n"
                f"💰 Продажі: <b>{sales} грн</b>\n"
                f"📋 Активних замовлень: <b>{pending}</b>\n\n"
                f"💳 <b>Замовлень по методах:</b>{method_lines}")
        await edit(text)

    elif action == "broadcast":
        await cb.message.answer("📢 Надішліть повідомлення для розсилки:", reply_markup=cancel_kb())
        await state.set_state(S.admin_broadcast)

    elif action == "cards":
        await edit("💳 <b>Реквізити</b>\n\nОберіть спосіб оплати:", admin_cards_kb())

    elif action.startswith("card_"):
        mk = action.replace("card_","",1)
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT * FROM payment_methods WHERE method_key=?", (mk,))
        m = dict(c.fetchone()); conn.close()
        await state.update_data(card_key=mk)
        await cb.message.answer(
            f"<b>{m['name_uk']}</b>\n\n"
            f"Поточні реквізити: <code>{m['details'] or 'не вказано'}</code>\n\n"
            f"Введіть нові реквізити:", reply_markup=cancel_kb())
        await state.set_state(S.admin_card_edit)

    elif action == "prices":
        await edit(
            f"💰 <b>Курси і ціни</b>\n\n"
            f"⭐ Stars: <b>{get_setting('stars_rate')} грн</b>\n"
            f"💵 TON наценка: <b>{get_setting('ton_markup')}%</b>\n"
            f"💲 Крипто наценка: <b>{get_setting('crypto_markup')}%</b>\n"
            f"💰 Викуп Stars: <b>{get_setting('sell_stars_rate')} грн</b>\n"
            f"⭐ Нагорода за відгук: <b>{get_setting('review_reward_min')}–{get_setting('review_reward_max')} Stars</b>",
            admin_prices_kb())

    elif action == "stars_rate":
        await cb.message.answer(f"Поточний: <b>{get_setting('stars_rate')} грн</b>\nВведіть новий:", reply_markup=cancel_kb(), parse_mode="HTML")
        await state.update_data(gset_key="stars_rate")
        await state.set_state(S.admin_gset)
    elif action == "ton_markup":
        await cb.message.answer(f"Поточна: <b>{get_setting('ton_markup')}%</b>\nВведіть нову (наценка тільки для розділу 'Купити TON'):", reply_markup=cancel_kb(), parse_mode="HTML")
        await state.update_data(gset_key="ton_markup")
        await state.set_state(S.admin_gset)
    elif action == "crypto_markup":
        await cb.message.answer(f"Поточна: <b>{get_setting('crypto_markup')}%</b>\nВведіть нову (наценка для оплати криптою — USDT і TON):", reply_markup=cancel_kb(), parse_mode="HTML")
        await state.update_data(gset_key="crypto_markup")
        await state.set_state(S.admin_gset)
    elif action == "cryptobot_markup":
        await cb.message.answer(f"Поточна: <b>{get_setting('cryptobot_markup') or 0}%</b>\nВведіть нову (наценка тільки для CryptoBot (авто), окремо від звичайної крипти):", reply_markup=cancel_kb(), parse_mode="HTML")
        await state.update_data(gset_key="cryptobot_markup")
        await state.set_state(S.admin_gset)
    elif action == "sell_rate":
        await cb.message.answer(f"Поточний: <b>{get_setting('sell_stars_rate')} грн</b>\nВведіть новий:", reply_markup=cancel_kb(), parse_mode="HTML")
        await state.update_data(gset_key="sell_stars_rate")
        await state.set_state(S.admin_gset)
    elif action == "premium_prices":
        await edit(f"💎 3 міс: <b>{get_setting('premium_3m')} грн</b>\n6 міс: <b>{get_setting('premium_6m')} грн</b>\n12 міс: <b>{get_setting('premium_12m')} грн</b>", admin_prem_kb())
    elif action in ["prem_3m","prem_6m","prem_12m"]:
        kmap = {"prem_3m":"premium_3m","prem_6m":"premium_6m","prem_12m":"premium_12m"}
        await state.update_data(prem_key=kmap[action])
        await cb.message.answer("Введіть нову ціну в грн:", reply_markup=cancel_kb())
        await state.set_state(S.admin_prem_price)

    elif action == "stars_pay":
        await edit("⭐ <b>Оплата Telegram Stars</b>\n\nУвімкніть можливість оплатити Stars напряму (без чеків, миттєво) для Premium і Подарунків:", admin_stars_pay_kb())
    elif action == "stars_pay_toggle_premium":
        cur = get_setting("stars_pay_premium_enabled") == "1"
        set_setting("stars_pay_premium_enabled", "0" if cur else "1")
        await edit("⭐ <b>Оплата Telegram Stars</b>\n\nУвімкніть можливість оплатити Stars напряму (без чеків, миттєво) для Premium і Подарунків:", admin_stars_pay_kb())
    elif action == "stars_pay_toggle_gift":
        cur = get_setting("stars_pay_gift_enabled") == "1"
        set_setting("stars_pay_gift_enabled", "0" if cur else "1")
        await edit("⭐ <b>Оплата Telegram Stars</b>\n\nУвімкніть можливість оплатити Stars напряму (без чеків, миттєво) для Premium і Подарунків:", admin_stars_pay_kb())
    elif action == "premium_stars_prices":
        await edit("💎 <b>Ціни Premium в Stars</b>\n\nОберіть тариф для редагування:", admin_prem_stars_kb())
    elif action in ["prem_stars_3m","prem_stars_6m","prem_stars_12m"]:
        kmap = {"prem_stars_3m":"premium_3m_stars","prem_stars_6m":"premium_6m_stars","prem_stars_12m":"premium_12m_stars"}
        await state.update_data(gset_key=kmap[action])
        await cb.message.answer("Введіть нову ціну в Stars (ціле число):", reply_markup=cancel_kb())
        await state.set_state(S.admin_gset)

    elif action == "minimums":
        await edit(
            f"⚙️ <b>Мінімуми</b>\n\n"
            f"⭐ Stars: <b>{get_setting('min_stars')}</b>\n"
            f"💵 TON: <b>{get_setting('min_ton')}</b>\n"
            f"💰 Продаж: <b>{get_setting('min_sell_stars')}</b>\n"
            f"💸 Вивід Stars: <b>{get_setting('min_withdraw')}</b>\n"
            f"🚫 Ліміт заявок/год: <b>{get_setting('max_orders_per_hour')}</b>",
            admin_minimums_kb())
    elif action == "min_stars":
        await cb.message.answer(f"Поточний: <b>{get_setting('min_stars')}</b>\nВведіть:", reply_markup=cancel_kb())
        await state.update_data(gset_key="min_stars")
        await state.set_state(S.admin_gset)
    elif action == "min_ton":
        await cb.message.answer(f"Поточний: <b>{get_setting('min_ton')}</b>\nВведіть:", reply_markup=cancel_kb())
        await state.update_data(gset_key="min_ton")
        await state.set_state(S.admin_gset)
    elif action == "min_sell":
        await cb.message.answer(f"Поточний: <b>{get_setting('min_sell_stars')}</b>\nВведіть:", reply_markup=cancel_kb())
        await state.update_data(gset_key="min_sell_stars")
        await state.set_state(S.admin_gset)
    elif action == "min_withdraw":
        await cb.message.answer(f"Поточний: <b>{get_setting('min_withdraw')}</b>\nВведіть:", reply_markup=cancel_kb())
        await state.update_data(gset_key="min_withdraw")
        await state.set_state(S.admin_gset)
    elif action == "req_limit":
        await cb.message.answer(f"Поточний: <b>{get_setting('max_orders_per_hour')}</b> заявок/год\nВведіть:", reply_markup=cancel_kb())
        await state.update_data(gset_key="max_orders_per_hour")
        await state.set_state(S.admin_gset)

    elif action == "btns":
        await edit("🎨 <b>Налаштування кнопок меню</b>", admin_menu_btns_kb())

    elif action == "texts":
        await edit("📝 <b>Редагування текстів</b>", admin_texts_kb())

    elif action.startswith("text_"):
        import re as _re
        text_key = action.replace("text_","",1)
        cur = get_bot_text(text_key)
        cur_escaped = _re.sub(r'<', '&lt;', cur[:300])
        placeholders_hint = {
            "sell_stars_promo": "\n📌 Доступні змінні: <code>{rate}</code> (курс), <code>{min}</code> (мін. Stars), <code>{example}</code> (приклад у грн)\n",
            "receipt_ok": "\n📌 Доступна змінна: <code>{oid}</code> (номер замовлення)\n",
            "support_reply": "\n📌 Доступна змінна: <code>{text}</code> (текст відповіді)\n",
            "referral_info": "\n📌 Доступні змінні: <code>{ref_link}</code>, <code>{percent}</code>, <code>{ref_count}</code>\n",
            "withdraw_paid_review": "\n📌 Доступні змінні: <code>{wid}</code> (номер виводу), <code>{amount}</code> (сума Stars)\n",
            "stars_choose_amount": "\n📌 Доступна змінна: <code>{username}</code> (отримувач)\n",
            "order_done_review": "\n📌 Доступна змінна: <code>{order_details}</code> (деталі замовлення — подарунок або Premium на скільки місяців)\n",
        }.get(text_key, "")
        await state.update_data(text_key=text_key)
        await cb.message.answer(
            f"📝 <b>Редагування: {text_key}</b>\n\n"
            f"<b>Поточний текст:</b>\n<blockquote>{cur_escaped}</blockquote>\n\n"
            f"✏️ Надішліть новий текст українською.\n"
            f"{placeholders_hint}\n"
            f"Теги: <code>&lt;b&gt;жирний&lt;/b&gt;</code>, <code>&lt;i&gt;курсив&lt;/i&gt;</code>\n"
            f"💎 Премиум емодзі — вставте з клавіатури",
            reply_markup=cancel_kb(), parse_mode='HTML')
        await state.set_state(S.admin_text_edit)

    elif action == "methods":
        await edit("💳 <b>Способи оплати</b>", admin_methods_kb())

    elif action.startswith("method_"):
        mk = action.replace("method_","",1)
        await state.update_data(method_key=mk)
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT * FROM payment_methods WHERE method_key=?", (mk,))
        m = dict(c.fetchone()); conn.close()
        m_prefix = ""
        status = "✅ Увімкнено" if m.get("enabled") else "🚫 Вимкнено"
        await edit(f"{m_prefix}<b>{m['name_uk']}</b>\nСтиль: <b>{m['style']}</b>\nСтатус: <b>{status}</b>\n\nОберіть дію:", admin_method_style_kb(mk))

    elif action.startswith("mtoggle_"):
        mk = action.replace("mtoggle_","",1)
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT enabled FROM payment_methods WHERE method_key=?", (mk,))
        row = c.fetchone()
        new_val = 0 if (row and row["enabled"]) else 1
        c.execute("UPDATE payment_methods SET enabled=? WHERE method_key=?", (new_val, mk))
        conn.commit(); conn.close()
        await cb.answer("✅ Увімкнено" if new_val else "🚫 Вимкнено (тимчасово сховано)")
        try: await cb.message.edit_text("💳 <b>Способи оплати</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
        except: pass

    elif action.startswith("mpos_"):
        parts = action.replace("mpos_","",1).rsplit("_",1)
        mk, direction = parts[0], parts[1]
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT position FROM payment_methods WHERE method_key=?", (mk,))
        row = c.fetchone()
        if row:
            pos = row[0]
            new_pos = pos - 1 if direction == "up" else pos + 1
            c.execute("UPDATE payment_methods SET position=? WHERE position=? AND method_key!=?", (pos, new_pos, mk))
            c.execute("UPDATE payment_methods SET position=? WHERE method_key=?", (new_pos, mk))
            conn.commit()
        conn.close()
        await cb.answer("✅ Порядок оновлено")
        try: await cb.message.edit_text("💳 <b>Способи оплати</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
        except: pass

    elif action.startswith("mstl_"):
        parts = action.replace("mstl_","",1).rsplit("_",1)
        mk, style = parts[0], parts[1]
        update_payment_method(mk, "style", style)
        names = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
        await cb.answer(f"✅ {names.get(style,style)}")
        try: await cb.message.edit_text("💳 <b>Способи оплати</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
        except: pass

    elif action.startswith("mcstl_"):
        parts = action.replace("mcstl_","",1).rsplit("_",1)
        mk, style = parts[0], parts[1]
        set_setting("cryptobot_currency_style", style)
        names = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
        await cb.answer(f"✅ {names.get(style,style)}")
        try: await cb.message.edit_text("💳 <b>Способи оплати</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
        except: pass

    elif action.startswith("medit_name_"):
        mk = action.replace("medit_name_","",1)
        await state.update_data(medit_key=mk, medit_field="name")
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT * FROM payment_methods WHERE method_key=?", (mk,))
        m = dict(c.fetchone()); conn.close()
        await cb.message.answer(
            f"✏️ <b>Змінити назву: {m['name_uk']}</b>\n\n"
            f"Надішліть нову назву українською.\n"
            f"💎 Можна вставити преміум емодзі з клавіатури:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_details_"):
        mk = action.replace("medit_details_","",1)
        await state.update_data(medit_key=mk, medit_field="details")
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT * FROM payment_methods WHERE method_key=?", (mk,))
        m = dict(c.fetchone()); conn.close()
        cur_details = m.get("details") or "не вказано"
        await cb.message.answer(
            f"💳 <b>Змінити реквізити: {m['name_uk']}</b>\n\n"
            f"Поточні: <code>{cur_details}</code>\n\n"
            f"Відправте нові реквізити:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_owner_"):
        mk = action.replace("medit_owner_","",1)
        await state.update_data(medit_key=mk, medit_field="owner")
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT * FROM payment_methods WHERE method_key=?", (mk,))
        m = dict(c.fetchone()); conn.close()
        cur_owner = m.get("owner") or "не вказано"
        await cb.message.answer(
            f"👤 <b>Власник картки: {m['name_uk']}</b>\n\n"
            f"Поточний: <code>{cur_owner}</code>\n\n"
            f"Введіть ім'я власника (наприклад: <code>Іван П.</code>)\n"
            f"Або надішліть <code>-</code> щоб прибрати:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_emoji_"):
        mk = action.replace("medit_emoji_","",1)
        await state.update_data(medit_key=mk, medit_field="emoji")
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT * FROM payment_methods WHERE method_key=?", (mk,))
        m = dict(c.fetchone()); conn.close()
        cur_ceid = m.get("custom_emoji_id") or "не вказано"
        await cb.message.answer(
            f"🖼 <b>Прем-емодзі кнопки: {m['name_uk']}</b>\n\n"
            f"Поточний ID: <code>{cur_ceid}</code>\n\n"
            f"Надішліть повідомленням саме той преміум-емодзі, який хочете поставити на кнопку "
            f"(просто вставте його зі списку емодзі в Telegram).\n\n"
            f"Або надішліть <code>-</code> щоб прибрати й повернути звичайний emoji-префікс:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_ctext_"):
        mk = action.replace("medit_ctext_","",1)
        await state.update_data(medit_key=mk, medit_field="ctext")
        cur = get_setting("cryptobot_pay_text") or "(використовується стандартний текст)"
        await cb.message.answer(
            f"📝 <b>Текст після вибору валюти (крок оплати)</b>\n\n"
            f"Поточний:\n<code>{cur}</code>\n\n"
            f"Доступні змінні: <code>{{amount}}</code> (сума крипти), <code>{{asset}}</code> (TON/USDT), "
            f"<code>{{price}}</code> (сума в грн).\n\n"
            f"Надішліть новий текст, або <code>-</code> щоб повернути стандартний:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_cctext_"):
        mk = action.replace("medit_cctext_","",1)
        await state.update_data(medit_key=mk, medit_field="cctext")
        cur = get_setting("cryptobot_currency_text") or "(використовується стандартний текст)"
        await cb.message.answer(
            f"📝 <b>Текст екрана вибору валюти (TON/USDT)</b>\n\n"
            f"Поточний:\n<code>{cur}</code>\n\n"
            f"Надішліть новий текст, або <code>-</code> щоб повернути стандартний:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_ctonbtn_"):
        mk = action.replace("medit_ctonbtn_","",1)
        await state.update_data(medit_key=mk, medit_field="ctonbtn")
        cur = get_setting("cryptobot_ton_emoji") or "не вказано"
        await cb.message.answer(
            f"🖼 <b>Прем-емодзі для кнопки «TON»</b>\n\n"
            f"Поточний ID: <code>{cur}</code>\n\n"
            f"Надішліть сам преміум-емодзі повідомленням, або «-» щоб прибрати:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_cusdtbtn_"):
        mk = action.replace("medit_cusdtbtn_","",1)
        await state.update_data(medit_key=mk, medit_field="cusdtbtn")
        cur = get_setting("cryptobot_usdt_emoji") or "не вказано"
        await cb.message.answer(
            f"🖼 <b>Прем-емодзі для кнопки «USDT»</b>\n\n"
            f"Поточний ID: <code>{cur}</code>\n\n"
            f"Надішліть сам преміум-емодзі повідомленням, або «-» щоб прибрати:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_ctontext_"):
        mk = action.replace("medit_ctontext_","",1)
        await state.update_data(medit_key=mk, medit_field="ctontext")
        cur = get_setting("cryptobot_ton_btn_text") or "💎 TON"
        await cb.message.answer(
            f"✏️ <b>Текст кнопки TON</b>\n\nПоточний: <code>{cur}</code>\n\nНадішліть новий, або «-» для стандартного:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_cusdttext_"):
        mk = action.replace("medit_cusdttext_","",1)
        await state.update_data(medit_key=mk, medit_field="cusdttext")
        cur = get_setting("cryptobot_usdt_btn_text") or "💵 USDT"
        await cb.message.answer(
            f"✏️ <b>Текст кнопки USDT</b>\n\nПоточний: <code>{cur}</code>\n\nНадішліть новий, або «-» для стандартного:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_cpaybtn_"):
        mk = action.replace("medit_cpaybtn_","",1)
        await state.update_data(medit_key=mk, medit_field="cpaybtn")
        cur = get_setting("cryptobot_pay_btn_emoji") or "не вказано"
        await cb.message.answer(
            f"🖼 <b>Прем-емодзі для кнопки «Оплатити»</b>\n\n"
            f"Поточний ID: <code>{cur}</code>\n\n"
            f"Надішліть сам преміум-емодзі повідомленням, або «-» щоб прибрати:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_ccheckbtn_"):
        mk = action.replace("medit_ccheckbtn_","",1)
        await state.update_data(medit_key=mk, medit_field="ccheckbtn")
        cur = get_setting("cryptobot_check_btn_emoji") or "не вказано"
        await cb.message.answer(
            f"🖼 <b>Прем-емодзі для кнопки «Перевірити оплату»</b>\n\n"
            f"Поточний ID: <code>{cur}</code>\n\n"
            f"Надішліть сам преміум-емодзі повідомленням, або «-» щоб прибрати:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_cpaytext_"):
        mk = action.replace("medit_cpaytext_","",1)
        await state.update_data(medit_key=mk, medit_field="cpaytext")
        cur = get_setting("cryptobot_pay_btn_text") or "🤖 Оплатити"
        await cb.message.answer(
            f"✏️ <b>Текст кнопки «Оплатити»</b>\n\nПоточний: <code>{cur}</code>\n\nНадішліть новий, або «-» для стандартного:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_cchecktext_"):
        mk = action.replace("medit_cchecktext_","",1)
        await state.update_data(medit_key=mk, medit_field="cchecktext")
        cur = get_setting("cryptobot_check_btn_text") or "🔄 Перевірити оплату"
        await cb.message.answer(
            f"✏️ <b>Текст кнопки «Перевірити оплату»</b>\n\nПоточний: <code>{cur}</code>\n\nНадішліть новий, або «-» для стандартного:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action.startswith("medit_instructions_"):
        mk = action.replace("medit_instructions_","",1)
        await state.update_data(medit_key=mk, medit_field="instructions")
        conn = get_conn(); c = conn.cursor()
        c.execute("SELECT * FROM payment_methods WHERE method_key=?", (mk,))
        m = dict(c.fetchone()); conn.close()
        cur = m.get("instructions") or ""
        cur_display = f"<code>{cur}</code>" if cur else "не задано (використовується стандартний шаблон)"
        await cb.message.answer(
            f"📝 <b>Весь текст оплати: {m['name_uk']}</b>\n\n"
            f"Поточний: {cur_display}\n\n"
            f"Надішліть новий текст повністю (підтримує HTML: &lt;b&gt;, &lt;code&gt; тощо).\n\n"
            f"Можна вставляти плейсхолдери, які підставляться автоматично:\n"
            f"<code>{{name}}</code> — назва способу оплати\n"
            f"<code>{{details}}</code> — реквізити\n"
            f"<code>{{owner}}</code> — власник картки\n"
            f"<code>{{price}}</code> — сума до сплати\n\n"
            f"Або надішліть <code>-</code> щоб повернути стандартний шаблон:",
            parse_mode="HTML")
        await state.set_state(S.admin_card_edit)

    elif action in ("btn_pkg_style", "btn_pkg_custom_style"):
        styles = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
        skey = "btn_pkg_style" if action == "btn_pkg_style" else "btn_pkg_custom_style"
        label = "Пакети Stars" if action == "btn_pkg_style" else "Своя кількість"
        cur = get_setting(skey) or "primary"
        pfx = "set_pkg" if action == "btn_pkg_style" else "set_pkg_custom"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔵 Primary", callback_data=f"adm_{pfx}_primary"),
             InlineKeyboardButton(text="🟢 Success", callback_data=f"adm_{pfx}_success")],
            [InlineKeyboardButton(text="🔴 Danger",  callback_data=f"adm_{pfx}_danger"),
             InlineKeyboardButton(text="⬜ Default", callback_data=f"adm_{pfx}_default")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_btns")]
        ])
        await cb.message.answer(f"🎨 Колір кнопки <b>{label}</b>\nПоточний: <b>{styles.get(cur,cur)}</b>", reply_markup=kb, parse_mode="HTML")
    elif action.startswith("set_pkg_custom_"):
        style = action.replace("set_pkg_custom_","")
        set_setting("btn_pkg_custom_style", style)
        names = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
        await cb.answer(f"✅ {names.get(style,style)}")
    elif action.startswith("set_pkg_"):
        style = action.replace("set_pkg_","")
        set_setting("btn_pkg_style", style)
        names = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
        await cb.answer(f"✅ {names.get(style,style)}")

    elif action == "btn_pkg_emoji":
        cur_ceid = get_setting("btn_pkg_emoji_id") or ""
        status = "встановлено ✅" if cur_ceid else "не встановлено ❌"
        await cb.message.answer(
            f"💎 <b>Емодзі для кнопок пакетів Stars</b>\n\n"
            f"Поточний стан: <b>{status}</b>\n\n"
            f"Надішліть повідомлення з преміум-емодзі (просто вставте його з клавіатури) — "
            f"бот візьме його і буде показувати на кнопках 50/100/200/500/1000 замість звичайної зірки.\n\n"
            f"Надішліть <code>-</code> щоб прибрати емодзі.",
            reply_markup=cancel_kb(), parse_mode="HTML")
        await state.set_state(S.admin_pkg_emoji)

    elif action == "btn_month_style":
        styles = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
        cur = get_setting("btn_month_style") or "primary"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔵 Primary", callback_data="adm_set_month_primary"),
             InlineKeyboardButton(text="🟢 Success", callback_data="adm_set_month_success")],
            [InlineKeyboardButton(text="🔴 Danger",  callback_data="adm_set_month_danger"),
             InlineKeyboardButton(text="⬜ Default", callback_data="adm_set_month_default")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_btns")]
        ])
        await cb.message.answer(f"🎨 Колір кнопки <b>Місяці Premium</b>\nПоточний: <b>{styles.get(cur,cur)}</b>", reply_markup=kb, parse_mode="HTML")
    elif action.startswith("set_month_"):
        style = action.replace("set_month_","")
        set_setting("btn_month_style", style)
        names = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
        await cb.answer(f"✅ {names.get(style,style)}")

    elif action == "ref_percent":
        await cb.message.answer(f"Поточний відсоток: <b>{get_setting('ref_percent_purchase')}%</b>\nВведіть новий:", reply_markup=cancel_kb(), parse_mode="HTML")
        await state.update_data(admin_action="set_ref_percent")
        await state.set_state(S.admin_gset)
    elif action == "ref_toggle":
        cur = get_setting("ref_enabled")
        new = "0" if cur == "1" else "1"
        set_setting("ref_enabled", new)
        await cb.message.answer(f"{'✅ Реферали включені' if new=='1' else '❌ Реферали вимкнені'}")

    elif action == "refs":
        ref_enabled = get_setting("ref_enabled") == "1"
        ref_percent = get_setting("ref_percent_purchase") or "5"
        status = "✅ Включена" if ref_enabled else "❌ Вимкнена"
        await edit(f"👥 <b>Реферальна система</b>\n\nСтатус: <b>{status}</b>\n💰 Відсоток: <b>{ref_percent}%</b>",
                   admin_refs_kb())

    elif action == "copyref_menu":
        await edit("📋 <b>Кнопка «Скопіювати посилання»</b>\n\nНалаштування вигляду кнопки в розділі «Реферали».",
                   admin_copyref_kb())

    elif action == "copyref_text":
        cur_text = get_setting("btn_copyref_text") or "📋 Скопіювати посилання"
        await cb.message.answer(
            f"✏️ <b>Текст кнопки копіювання</b>\n\nПоточний: <code>{cur_text}</code>\n\nНадішліть новий текст:",
            reply_markup=cancel_kb(), parse_mode="HTML")
        await state.set_state(S.admin_copyref_text)

    elif action == "copyref_style":
        cur = get_setting("btn_copyref_style") or "default"
        styles = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔵 Primary", callback_data="adm_set_copyref_primary"),
             InlineKeyboardButton(text="🟢 Success", callback_data="adm_set_copyref_success")],
            [InlineKeyboardButton(text="🔴 Danger",  callback_data="adm_set_copyref_danger"),
             InlineKeyboardButton(text="⬜ Default", callback_data="adm_set_copyref_default")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_copyref_menu")]
        ])
        await cb.message.answer(f"🎨 Колір кнопки <b>Скопіювати посилання</b>\nПоточний: <b>{styles.get(cur,cur)}</b>",
                                 reply_markup=kb, parse_mode="HTML")
    elif action.startswith("set_copyref_"):
        style = action.replace("set_copyref_","")
        set_setting("btn_copyref_style", style)
        names = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
        await cb.answer(f"✅ {names.get(style,style)}")

    elif action == "copyref_emoji":
        cur_ceid = get_setting("btn_copyref_emoji_id") or ""
        status = "встановлено ✅" if cur_ceid else "не встановлено ❌"
        await cb.message.answer(
            f"💎 <b>Premium Emoji для кнопки «Скопіювати посилання»</b>\n\n"
            f"Поточний стан: <b>{status}</b>\n\n"
            f"Надішліть повідомлення з преміум-емодзі (просто вставте його з клавіатури).\n\n"
            f"Надішліть <code>-</code> щоб прибрати емодзі.",
            reply_markup=cancel_kb(), parse_mode="HTML")
        await state.set_state(S.admin_copyref_emoji)

    elif action == "review_reward_min":
        reward_min = int(get_setting("review_reward_min") or 1)
        await cb.message.answer(f"Поточний мінімум: <b>{reward_min} ⭐</b>\nВведіть новий мінімум:", reply_markup=cancel_kb(), parse_mode="HTML")
        await state.set_state(S.admin_review_reward_min)
    elif action == "review_reward_max":
        reward_max = int(get_setting("review_reward_max") or 2)
        await cb.message.answer(f"Поточний максимум: <b>{reward_max} ⭐</b>\nВведіть новий максимум:", reply_markup=cancel_kb(), parse_mode="HTML")
        await state.set_state(S.admin_review_reward_max)

    elif action == "sub_toggle":
        current = get_setting("sub_required") == "1"
        set_setting("sub_required", "0" if current else "1")
        enabled = not current
        await cb.answer("✅ Включена" if enabled else "❌ Вимкнена")
        channels = [c.strip() for c in (get_setting("sub_channels") or REVIEWS_CHANNEL).split(",") if c.strip()]
        status_txt = "✅ Включена" if enabled else "❌ Вимкнена"
        ch_list = "\n".join([f"• @{c}" for c in channels])
        rows = [[InlineKeyboardButton(text="✅ Включити" if not enabled else "❌ Вимкнути", callback_data="adm_sub_toggle")]]
        rows += [[InlineKeyboardButton(text=f"🗑 Видалити @{c}", callback_data=f"adm_sub_del_{c}")] for c in channels]
        rows += [[InlineKeyboardButton(text="➕ Додати канал", callback_data="adm_sub_channel")]]
        rows += [[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]]
        try: await cb.message.edit_text(
            f"🔔 <b>Обов'язкова підписка</b>\n\nСтатус: <b>{status_txt}</b>\n\n<b>Канали:</b>\n{ch_list}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
        except: pass

    elif action.startswith("sub_del_"):
        ch = action.replace("sub_del_","",1)
        channels = [c.strip() for c in (get_setting("sub_channels") or REVIEWS_CHANNEL).split(",") if c.strip()]
        channels = [c for c in channels if c != ch]
        set_setting("sub_channels", ",".join(channels) if channels else REVIEWS_CHANNEL)
        await cb.answer(f"✅ @{ch} видалено")
        enabled = get_setting("sub_required") == "1"
        status_txt = "✅ Включена" if enabled else "❌ Вимкнена"
        ch_list = "\n".join([f"• @{c}" for c in channels]) if channels else "немає каналів"
        rows = [[InlineKeyboardButton(text="✅ Включити" if not enabled else "❌ Вимкнути", callback_data="adm_sub_toggle")]]
        rows += [[InlineKeyboardButton(text=f"🗑 Видалити @{c}", callback_data=f"adm_sub_del_{c}")] for c in channels]
        rows += [[InlineKeyboardButton(text="➕ Додати канал", callback_data="adm_sub_channel")]]
        rows += [[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]]
        try: await cb.message.edit_text(
            f"🔔 <b>Обов'язкова підписка</b>\n\nСтатус: <b>{status_txt}</b>\n\n<b>Канали:</b>\n{ch_list}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
        except: pass

    elif action == "sub_channel":
        await cb.message.answer("📢 <b>Введіть username каналу (без @):</b>", parse_mode="HTML")
        await state.update_data(admin_action="set_sub_channel")
        await state.set_state(S.admin_gset)

    elif action.startswith("photo_"):
        section = action.replace("photo_","",1)
        await cb.message.answer("📸 Надішліть фото для розділу:")
        await state.update_data(photo_section=section)
        await state.set_state(S.admin_photo_upload)

    elif action == "gifts":
        await edit("🎁 <b>Подарунки — редагування каталогу</b>\n\nОберіть позицію:", admin_gifts_kb())

    elif action == "gift_add":
        await cb.message.answer(
            "🎁 <b>Новий подарунок</b>\n\n"
            "Надішліть емодзі для нового подарунка (звичайний або преміум):",
            reply_markup=cancel_kb())
        await state.set_state(S.admin_gift_add_emoji)

    elif action.startswith("gdel_"):
        key = action.replace("gdel_", "", 1)
        delete_gift_item(key)
        await cb.answer("🗑 Видалено")
        await edit("🎁 <b>Подарунки — редагування каталогу</b>\n\nОберіть позицію:", admin_gifts_kb())

    elif action.startswith("gift_item_"):
        key = action.replace("gift_item_", "", 1)
        item = get_gift_item(key)
        if not item:
            await cb.message.answer("❌ Позицію не знайдено"); return
        status = "✅ Увімкнено" if item.get("enabled") else "🚫 Вимкнено"
        qty = "без обмежень" if item.get("quantity") is None else str(item["quantity"])
        stars_display = f"{item['price_stars']} Stars" if item.get("price_stars") else f"~{gift_price_stars(item)} Stars (авто)"
        text = (
            f"{item['emoji']} <b>{item['name']}</b>\n\n"
            f"💰 Ціна: <b>{item['price']:.0f} грн</b>\n"
            f"⭐ Ціна в Stars: <b>{stars_display}</b>\n"
            f"🔢 Кількість: <b>{qty}</b>\n"
            f"🆔 Telegram Gift ID: <code>{item.get('telegram_gift_id') or '—'}</code>\n"
            f"🖼 Прем-стикер: <code>{item.get('sticker_id') or '—'}</code>\n"
            f"Статус: <b>{status}</b>"
        )
        await edit(text, admin_gift_item_kb(key))

    elif action.startswith("gedit_"):
        rest = action.replace("gedit_", "", 1)
        field, key = rest.split("_", 1)
        item = get_gift_item(key)
        if not item:
            await cb.message.answer("❌ Позицію не знайдено"); return
        field_names = {"name": "назву", "emoji": "емодзі", "price": "ціну (грн, число)",
                       "pricestars": "ціну в Stars (ціле число, або «-» для авто-розрахунку)",
                       "qty": "кількість (число, або «-» для необмеженої)", "tgid": "Telegram Gift ID (число)",
                       "sticker": "прем-емодзі (надішліть сам емодзі повідомленням)"}
        await state.update_data(gift_key=key, gift_field=field)
        await cb.message.answer(
            f"✏️ Введіть нове значення для «{field_names.get(field, field)}»:",
            reply_markup=cancel_kb())
        await state.set_state(S.admin_gift_edit)

    elif action.startswith("gtoggle_"):
        key = action.replace("gtoggle_", "", 1)
        item = get_gift_item(key)
        if item:
            set_gift_field(key, "enabled", 0 if item.get("enabled") else 1)
        await cb.answer("✅ Статус змінено")
        await edit("🎁 <b>Подарунки — редагування каталогу</b>\n\nОберіть позицію:", admin_gifts_kb())

    elif action.startswith("gpos_"):
        parts = action.replace("gpos_", "", 1).rsplit("_", 1)
        key, direction = parts[0], parts[1]
        item = get_gift_item(key)
        if item:
            pos = item.get("position") or 0
            new_pos = pos - 1 if direction == "up" else pos + 1
            conn = get_conn(); c = conn.cursor()
            c.execute("UPDATE gift_items SET position=? WHERE position=? AND item_key!=?", (pos, new_pos, key))
            c.execute("UPDATE gift_items SET position=? WHERE item_key=?", (new_pos, key))
            conn.commit(); conn.close()
        await cb.answer("✅ Порядок оновлено")
        await edit("🎁 <b>Подарунки — редагування каталогу</b>\n\nОберіть позицію:", admin_gifts_kb())

    elif action == "gift_api_creds":
        creds = get_gift_api_creds()
        current_id = creds.get("api_id") or "не вказано"
        await cb.message.answer(
            f"🔑 <b>Telethon-акаунт для автовидачі подарунків</b>\n\n"
            f"Поточний api_id: <code>{current_id}</code>\n\n"
            f"Отримайте api_id та api_hash на my.telegram.org (розділ «API development tools») "
            f"і надішліть їх через пробіл:\n"
            f"Приклад: <code>123456 abcdef0123456789abcdef0123456789</code>",
            reply_markup=cancel_kb(), parse_mode="HTML")
        await state.set_state(S.admin_gift_api_creds)

    elif action == "gift_login_start":
        creds = get_gift_api_creds()
        if not creds.get("api_id") or not creds.get("api_hash"):
            await cb.message.answer("⚠️ Спочатку вкажіть api_id/api_hash кнопкою «🔑 Telethon-акаунт (автовидача)»")
            return
        if not GIFT_TELETHON_AVAILABLE:
            await cb.message.answer("❌ Пакет telethon не встановлено на сервері")
            return
        await reset_gift_client()
        await cb.message.answer(
            "📱 <b>Вхід в акаунт для видачі подарунків</b>\n\n"
            "Введіть номер телефону акаунта у форматі +380XXXXXXXXX\n\n"
            "⚠️ Це має бути акаунт зі Stars-балансом, з якого фактично будуть "
            "надсилатись подарунки. Код підтвердження прийде саме в цей Telegram-акаунт.",
            reply_markup=cancel_kb(), parse_mode="HTML")
        await state.set_state(S.gift_login_phone)

    elif action == "gift_real_catalog":
        wait_msg = await cb.message.answer("⏳ Отримую справжній каталог подарунків з Telegram...")
        result = await fetch_real_gift_catalog()
        try: await wait_msg.delete()
        except Exception: pass
        if not result.get("ok"):
            await cb.message.answer(f"❌ {result.get('error', 'Не вдалося отримати каталог')}")
            return
        gifts = result.get("gifts", [])
        if not gifts:
            await cb.message.answer("😢 Каталог порожній")
            return
        lines = ["📜 <b>Справжній каталог подарунків Telegram</b>\n"]
        for g in gifts:
            lim = " 🔒лімітований" if g.get("limited") else ""
            lines.append(f"{g['emoji']} <b>{g['stars']} Stars</b> — ID: <code>{g['id']}</code>{lim}")
        # Розбиваємо на частини по ~35 рядків, щоб не перевищити ліміт довжини повідомлення Telegram
        chunk = [lines[0]]
        for line in lines[1:]:
            chunk.append(line)
            if len(chunk) >= 36:
                await cb.message.answer("\n".join(chunk), parse_mode="HTML")
                chunk = []
        if chunk:
            await cb.message.answer("\n".join(chunk), parse_mode="HTML")

    elif action == "star_packages":
        await edit("⭐ <b>Паки Stars — редагування каталогу</b>\n\nОберіть позицію:", admin_star_packages_kb())

    elif action.startswith("spitem_"):
        key = action.replace("spitem_", "", 1)
        p = get_stars_package(key)
        if not p:
            await cb.message.answer("❌ Позицію не знайдено"); return
        status = "✅ Увімкнено" if p.get("enabled") else "🚫 Вимкнено"
        ceid_display = p.get("custom_emoji_id") or "—"
        type_names = {"fixed": "фіксований", "range": "діапазон", "group": "набір кнопок"}
        if p["kind"] == "fixed":
            body = f"⭐ Кількість Stars: <b>{p['amount']}</b>"
            if p.get("fixed_price") is not None:
                body += f"\n💰 Ціна: <b>{p['fixed_price']:.0f} грн</b> (задано вручну)"
            linked = get_gift_item(p["linked_gift_key"]) if p.get("linked_gift_key") else None
            if linked:
                qty = int(p.get("linked_gift_qty") or 1)
                qty_display = f" × {qty} шт." if qty > 1 else ""
                body += f"\n🎁 Замість Stars надсилається: <b>{linked['emoji']} {linked['name']}{qty_display}</b>"
        elif p["kind"] == "range":
            rng = f"{p['range_min']}–{p['range_max']}" if p.get("range_max") else f"від {p['range_min']} (без ліміту)"
            body = f"✏️ Діапазон: <b>{rng}</b>"
        else:
            n = len(get_stars_package_children(key, enabled_only=False))
            body = f"🧩 Кнопок у наборі: <b>{n}</b>"
            if p.get("description"):
                body += "\n📝 Текст при відкритті вже заданий (натисніть кнопку нижче, щоб змінити)"
        text = (
            f"{p['emoji']} <b>{p.get('label') or p['item_key']}</b>\n\n"
            f"{body}\n"
            f"🖼 Прем-емодзі: <code>{ceid_display}</code>\n"
            f"Тип: <b>{type_names.get(p['kind'], p['kind'])}</b>\n"
            f"Статус: <b>{status}</b>"
        )
        await edit(text, admin_star_package_kb(key))

    elif action.startswith("spchildren_"):
        parent_key = action.replace("spchildren_", "", 1)
        p = get_stars_package(parent_key)
        if not p:
            await cb.message.answer("❌ Позицію не знайдено"); return
        await edit(f"🧩 <b>Кнопки набору «{p.get('label') or parent_key}»</b>\n\nОберіть кнопку для редагування:",
                   admin_sp_children_kb(parent_key))

    elif action.startswith("spaddchild_"):
        parent_key = action.replace("spaddchild_", "", 1)
        await state.update_data(sp_add_kind="fixed", sp_add_parent=parent_key)
        await cb.message.answer("⭐ Введіть кількість Stars для нової кнопки (ціле число):", reply_markup=cancel_kb())
        await state.set_state(S.admin_sp_add)

    elif action.startswith("splink_"):
        key = action.replace("splink_", "", 1)
        if not get_gift_items():
            await cb.answer("❌ Спочатку додайте товари в каталог подарунків («🎁 Каталог подарунків»)", show_alert=True)
            return
        await edit("🎁 <b>Оберіть подарунок, який буде надсилатись замість зарахування Stars:</b>", admin_sp_link_gift_kb(key))

    elif action.startswith("spdolink_"):
        rest = action.replace("spdolink_", "", 1)
        key, gift_key = rest.split("_", 1)
        set_stars_package_field(key, "linked_gift_key", gift_key)
        await cb.answer("✅ Прив'язано")
        await edit("🎁 <b>Оберіть подарунок, який буде надсилатись замість зарахування Stars:</b>", admin_sp_link_gift_kb(key))

    elif action.startswith("spunlink_"):
        key = action.replace("spunlink_", "", 1)
        set_stars_package_field(key, "linked_gift_key", None)
        set_stars_package_field(key, "linked_gift_qty", 1)
        await cb.answer("✅ Відв'язано")
        p = get_stars_package(key)
        status = "✅ Увімкнено" if p.get("enabled") else "🚫 Вимкнено"
        text = (f"{p['emoji']} <b>{p.get('label') or p['item_key']}</b>\n\n"
                f"⭐ Кількість Stars: <b>{p['amount']}</b>\n"
                f"Статус: <b>{status}</b>")
        await edit(text, admin_star_package_kb(key))

    elif action.startswith("spgiftqty_"):
        key = action.replace("spgiftqty_", "", 1)
        p = get_stars_package(key)
        if not p or not p.get("linked_gift_key"):
            await cb.answer("❌ Спочатку прив'яжіть подарунок", show_alert=True); return
        await state.update_data(sp_key=key, sp_field="giftqty")
        cur = int(p.get("linked_gift_qty") or 1)
        await cb.message.answer(
            f"🔢 <b>Скільки копій подарунка надсилати за одну покупку цього паку?</b>\n\n"
            f"Поточне значення: <b>{cur}</b>\n\n"
            f"Введіть ціле число (наприклад, «3» — щоб при покупці одразу надсилалось 3 подарунки):",
            reply_markup=cancel_kb(), parse_mode="HTML")
        await state.set_state(S.admin_sp_edit)

    elif action.startswith("spedit_"):
        rest = action.replace("spedit_", "", 1)
        field, key = rest.split("_", 1)
        p = get_stars_package(key)
        if not p:
            await cb.message.answer("❌ Позицію не знайдено"); return
        field_names = {"emoji": "емодзі", "label": "підпис кнопки (або «-» для авто-тексту)",
                       "amount": "кількість Stars (ціле число)",
                       "price": "ціну в грн вручну (число, або «-» щоб рахувати автоматично з курсу)",
                       "min": "мінімальну суму (ціле число)",
                       "max": "максимальну суму (ціле число, або «-» без ліміту)",
                       "sticker": "прем-емодзі (надішліть сам емодзі повідомленням, або «-» щоб прибрати)",
                       "description": "текст, що показується при відкритті набору (можна кілька рядків і базове HTML-форматування; «-» щоб прибрати)"}
        await state.update_data(sp_key=key, sp_field=field)
        await cb.message.answer(
            safe_html(f"✏️ Введіть нове значення для «{field_names.get(field, field)}»:"),
            reply_markup=cancel_kb())
        await state.set_state(S.admin_sp_edit)

    elif action.startswith("sptoggle_"):
        key = action.replace("sptoggle_", "", 1)
        p = get_stars_package(key)
        if p:
            set_stars_package_field(key, "enabled", 0 if p.get("enabled") else 1)
        await cb.answer("✅ Статус змінено")
        if p and p.get("parent_key"):
            parent = get_stars_package(p["parent_key"])
            await edit(f"🧩 <b>Кнопки набору «{parent.get('label') or p['parent_key']}»</b>\n\nОберіть кнопку для редагування:",
                       admin_sp_children_kb(p["parent_key"]))
        else:
            await edit("⭐ <b>Паки Stars — редагування каталогу</b>\n\nОберіть позицію:", admin_star_packages_kb())

    elif action.startswith("spdel_"):
        key = action.replace("spdel_", "", 1)
        p = get_stars_package(key)
        parent_key = p.get("parent_key") if p else None
        delete_stars_package(key)
        await cb.answer("🗑 Видалено")
        if parent_key:
            parent = get_stars_package(parent_key)
            await edit(f"🧩 <b>Кнопки набору «{parent.get('label') or parent_key}»</b>\n\nОберіть кнопку для редагування:" if parent
                       else "⭐ <b>Паки Stars — редагування каталогу</b>\n\nОберіть позицію:",
                       admin_sp_children_kb(parent_key) if parent else admin_star_packages_kb())
        else:
            await edit("⭐ <b>Паки Stars — редагування каталогу</b>\n\nОберіть позицію:", admin_star_packages_kb())

    elif action.startswith("sppos_"):
        parts = action.replace("sppos_", "", 1).rsplit("_", 1)
        key, direction = parts[0], parts[1]
        p = get_stars_package(key)
        if p:
            pos = p.get("position") or 0
            new_pos = pos - 1 if direction == "up" else pos + 1
            conn = get_conn(); c = conn.cursor()
            c.execute("UPDATE stars_packages SET position=? WHERE position=? AND item_key!=?", (pos, new_pos, key))
            c.execute("UPDATE stars_packages SET position=? WHERE item_key=?", (new_pos, key))
            conn.commit(); conn.close()
        await cb.answer("✅ Порядок оновлено")
        await edit("⭐ <b>Паки Stars — редагування каталогу</b>\n\nОберіть позицію:", admin_star_packages_kb())

    elif action == "spadd":
        await edit("➕ <b>Новий пак Stars</b>\n\nОберіть тип:", admin_sp_add_kind_kb())

    elif action.startswith("spaddkind_"):
        kind = action.replace("spaddkind_", "", 1)
        await state.update_data(sp_add_kind=kind)
        if kind == "fixed":
            await cb.message.answer("⭐ Введіть кількість Stars для нового паку (ціле число):", reply_markup=cancel_kb())
            await state.set_state(S.admin_sp_add)
        elif kind == "range":
            await cb.message.answer("🔽 Введіть мінімальну суму для діапазону (ціле число):", reply_markup=cancel_kb())
            await state.set_state(S.admin_sp_add)
        else:  # group
            key = add_stars_package(kind="group", label="Набір подарунків", emoji="🎁")
            await cb.message.answer("✅ Набір створено! Тепер додайте до нього кнопки.")
            await cb.message.answer(f"🧩 <b>Кнопки набору «Набір подарунків»</b>\n\nОберіть кнопку для редагування:",
                                     reply_markup=admin_sp_children_kb(key), parse_mode="HTML")

    elif action == "find_user":
        await cb.message.answer("🔍 Введіть ID або @username користувача:", reply_markup=cancel_kb())
        await state.set_state(S.admin_find_user)

    elif action == "orders":
        orders = get_pending_orders()
        if not orders:
            await cb.message.answer("📋 Немає активних замовлень."); return
        text = "📋 <b>Активні замовлення:</b>\n\n"
        for o in orders[:10]:
            uname = f"@{o['username']}" if o['username'] else f"ID:{o['user_id']}"
            text += f"#{o['id']} — {o['order_type']} | {uname} | {o['price_uah']} грн\n"
        await cb.message.answer(text)

    elif action == "banned":
        banned = get_banned_users()
        if not banned:
            await cb.message.answer("✅ Немає забанених користувачів."); return
        text = "🚫 <b>Забанені:</b>\n\n"
        for u in banned:
            uname = f"@{u['username']}" if u['username'] else f"ID:{u['user_id']}"
            text += f"{uname} — {u['ban_reason'] or 'без причини'}\n"
        await cb.message.answer(text)

    elif action.startswith("give_stars_"):
        uid = int(action.replace("give_stars_","",1))
        await state.update_data(target_uid=uid)
        await cb.message.answer("⭐ Введіть кількість Stars для нарахування:", reply_markup=cancel_kb())
        await state.set_state(S.admin_give_stars)

    elif action.startswith("take_stars_"):
        uid = int(action.replace("take_stars_","",1))
        await state.update_data(target_uid=uid)
        await cb.message.answer("⭐ Введіть кількість Stars для списання:", reply_markup=cancel_kb())
        await state.set_state(S.admin_take_stars)

    elif action.startswith("ban_"):
        uid = int(action.replace("ban_","",1))
        await state.update_data(target_uid=uid)
        await cb.message.answer("✏️ Введіть причину бану:", reply_markup=cancel_kb())
        await state.set_state(S.admin_ban)

    elif action.startswith("unban_"):
        uid = int(action.replace("unban_","",1))
        update_user(uid, banned=0, ban_reason="")
        await cb.message.answer(f"✅ Користувача {uid} розбанено!")
        try: await bot.send_message(uid, "✅ Вас було розблоковано!")
        except: pass

    elif action.startswith("msg_"):
        uid = int(action.replace("msg_","",1))
        await state.update_data(target_uid=uid)
        await cb.message.answer("✏️ Введіть повідомлення для користувача:", reply_markup=cancel_kb())
        await state.set_state(S.admin_msg_user)

    elif action == "exit":
        await state.set_state(S.menu)
        await send_menu(cb.from_user.id, T("main_menu"))

    elif action == "back":
        try: await cb.message.edit_text("🛠 <b>Панель адміністратора</b>", reply_markup=admin_main_kb())
        except: await cb.message.answer("🛠 <b>Панель адміністратора</b>", reply_markup=admin_main_kb())

@dp.message(S.admin_find_user)
async def admin_find_user(msg: Message, state: FSMContext):
    if is_cancel(msg.text): await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
    conn = get_conn(); c = conn.cursor()
    query = msg.text.strip().lstrip("@")
    try:
        uid = int(query)
        c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    except:
        c.execute("SELECT * FROM users WHERE username=?", (query,))
    row = c.fetchone(); conn.close()
    if not row:
        await msg.answer("❌ Користувача не знайдено.")
        await state.set_state(S.admin); return
    u = dict(row)
    text = (
        f"👤 <b>Профіль користувача</b>\n\n"
        f"🆔 ID: <code>{u['user_id']}</code>\n"
        f"👤 @{u['username'] or 'Без ніка'}\n"
        f"🚫 Бан: {'Так — '+u['ban_reason'] if u.get('banned') else 'Ні'}\n\n"
        f"⭐ Баланс Stars: <b>{u.get('stars_balance',0)}</b>\n"
        f"📦 Куплено Stars: <b>{u['stars_bought']}</b>\n"
        f"💰 Витрачено: <b>{round(u['total_spent'],2)} грн</b>\n"
        f"👥 Запрошено друзів: <b>{u.get('ref_count',0)}</b>\n\n"
        f"📅 Реєстрація: <b>{u['registered_at'][:10]}</b>"
    )
    await msg.answer(text, reply_markup=user_profile_admin_kb(u['user_id']), parse_mode="HTML")
    await state.set_state(S.admin)

@dp.message(S.admin_gset)
async def admin_gset_handler(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    if is_cancel(msg.text):
        await state.set_state(S.admin)
        await msg.answer("❌ Скасовано", reply_markup=admin_back_kb())
        return
    data = await state.get_data()
    admin_action = data.get("admin_action","")

    if admin_action == "set_sub_channel":
        ch = msg.text.strip().lstrip("@").replace("https://t.me/", "").replace("http://t.me/", "")
        channels = [c.strip() for c in (get_setting("sub_channels") or REVIEWS_CHANNEL).split(",") if c.strip()]
        if ch not in channels:
            channels.append(ch)
        set_setting("sub_channels", ",".join(channels))
        await state.set_state(S.admin)
        enabled = get_setting("sub_required") == "1"
        status_txt = "✅ Включена" if enabled else "❌ Вимкнена"
        ch_list = "\n".join([f"• @{c}" for c in channels])
        rows = [[InlineKeyboardButton(text="✅ Включити" if not enabled else "❌ Вимкнути", callback_data="adm_sub_toggle")]]
        rows += [[InlineKeyboardButton(text=f"🗑 Видалити @{c}", callback_data=f"adm_sub_del_{c}")] for c in channels]
        rows += [[InlineKeyboardButton(text="➕ Додати канал", callback_data="adm_sub_channel")]]
        rows += [[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]]
        await msg.answer(
            f"✅ <b>Канал @{ch} додано!</b>\n\n🔔 <b>Обов'язкова підписка</b>\nСтатус: <b>{status_txt}</b>\n\n<b>Канали:</b>\n{ch_list}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
        return

    if admin_action == "set_ref_percent":
        try:
            pct = int(msg.text.strip())
            set_setting("ref_percent_purchase", str(pct))
            await state.set_state(S.admin)
            await msg.answer(f"✅ Відсоток реферальної винагороди: <b>{pct}%</b>", reply_markup=admin_back_kb(), parse_mode="HTML")
        except:
            await msg.answer("❌ Введіть ціле число")
        return

    skey = data.get("gset_key")
    val = msg.text.strip().replace(",", ".")
    try:
        float(val)
    except:
        await msg.answer("❌ Введіть число")
        return
    set_setting(skey, val)
    await state.set_state(S.admin)
    await msg.answer(f"✅ Налаштування оновлено: {skey} = <b>{val}</b>", reply_markup=admin_back_kb())

@dp.message(S.admin_give_stars)
async def admin_give_stars(msg: Message, state: FSMContext):
    if is_cancel(msg.text) or is_back(msg.text):
        await state.set_state(S.admin)
        await msg.answer("🔙 Скасовано", reply_markup=admin_main_kb())
        return
    try:
        amount = int(msg.text.strip())
        data = await state.get_data()
        uid = data["target_uid"]
        add_stars_balance(uid, amount)
        u2 = get_user(uid)
        new_bal = u2.get('stars_balance', 0) if u2 else '?'
        await msg.answer(f"✅ Нараховано <b>{amount} Stars</b> користувачу <code>{uid}</code>", parse_mode="HTML")
        try: await bot.send_message(uid, f"🎁 Вам нараховано <b>{amount} ⭐ Stars</b>!\n\n💰 Ваш баланс: <b>{new_bal} ⭐</b>", parse_mode="HTML")
        except: pass
    except: await msg.answer("❌ Введіть ціле число")
    await state.set_state(S.admin)

@dp.message(S.admin_take_stars)
async def admin_take_stars(msg: Message, state: FSMContext):
    if is_cancel(msg.text): await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
    try:
        amount = int(msg.text.strip())
        data = await state.get_data()
        uid = data["target_uid"]
        u = get_user(uid)
        actual = min(amount, u.get("stars_balance",0))
        conn = get_conn(); c = conn.cursor()
        c.execute("UPDATE users SET stars_balance=stars_balance-? WHERE user_id=?", (actual, uid))
        conn.commit(); conn.close()
        await msg.answer(f"✅ Списано <b>{actual} Stars</b> у користувача <code>{uid}</code>", parse_mode="HTML")
    except: await msg.answer("❌ Введіть ціле число")
    await state.set_state(S.admin)

@dp.message(S.admin_ban)
async def admin_ban(msg: Message, state: FSMContext):
    if is_cancel(msg.text): await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
    data = await state.get_data()
    uid = data["target_uid"]
    update_user(uid, banned=1, ban_reason=msg.text.strip())
    await msg.answer(f"🚫 Користувача <code>{uid}</code> забанено!\nПричина: {msg.text}", parse_mode="HTML")
    try: await bot.send_message(uid, T("banned",reason=msg.text))
    except: pass
    await state.set_state(S.admin)

@dp.message(S.admin_msg_user)
async def admin_msg_user(msg: Message, state: FSMContext):
    if is_cancel(msg.text): await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
    data = await state.get_data()
    uid = data["target_uid"]
    try:
        await bot.send_message(uid, f"📩 <b>Повідомлення від адміністратора:</b>\n\n{msg.text}", parse_mode="HTML")
        await msg.answer("✅ Повідомлення надіслано!")
    except: await msg.answer("❌ Не вдалося надіслати повідомлення")
    await state.set_state(S.admin)

# --- КНОПКИ МЕНЮ ADMIN (тільки UK, без вибору мови) ---
@dp.callback_query(F.data.startswith("admbtn_"))
async def admin_btn_callback(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer(); return
    await state.set_state(S.admin)
    action = cb.data.replace("admbtn_","",1)
    await cb.answer()

    async def edit(text, kb):
        try: await cb.message.edit_text(text, reply_markup=kb)
        except: await cb.message.answer(text, reply_markup=kb)

    if action == "back":
        await edit("🎨 <b>Налаштування кнопок меню</b>", admin_menu_btns_kb())
    elif action == "text":
        await state.update_data(edit_mode="text_uk")
        await edit("Оберіть кнопку:", admin_select_btn_kb())
    elif action == "style":
        await state.update_data(edit_mode="style")
        await edit("Оберіть кнопку для зміни стилю:", admin_select_btn_kb())
    elif action == "order":
        btns = get_menu_buttons()
        btn_list = "\n".join([f"{i+1}. {b['emoji']} {b['text_uk']}" for i,b in enumerate(btns)])
        await cb.message.answer(
            f"📋 Порядок:\n{btn_list}\n\nНадішліть новий порядок:\n1 2 3\n4 5 6\n7 8 9",
            reply_markup=cancel_kb())
        await state.set_state(S.admin_btn_order)

@dp.callback_query(F.data.startswith("admbtnsel_"))
async def admin_btn_select(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer(); return
    await state.set_state(S.admin)
    key = cb.data.replace("admbtnsel_","",1)
    await state.update_data(selected_key=key)
    data = await state.get_data()
    btns = get_menu_buttons()
    selected = next((b for b in btns if b["button_key"]==key), None)
    mode = data.get("edit_mode","text_uk")
    await cb.answer()

    async def edit(text, kb=None):
        try: await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except: await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")

    if mode == "text_uk":
        await edit(f"Кнопка: <b>{selected['emoji']} {selected['text_uk']}</b>\n\nПоточне: <b>{selected['text_uk']}</b>\n\nНадішліть: <code>емодзі Текст</code>\n💡 Можна вставити преміум емодзі!")
        await cb.message.answer("✏️ Введіть:", reply_markup=cancel_kb())
        await state.set_state(S.admin_edit_text)
    elif mode == "style":
        await edit(
            f"Кнопка: <b>{selected['emoji']} {selected['text_uk']}</b>\nСтиль: <b>{selected.get('style','default')}</b>\n\nОберіть:",
            admin_style_kb())

@dp.callback_query(F.data.startswith("admbtnstl_"))
async def admin_btn_style_cb(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: await cb.answer(); return
    await state.set_state(S.admin)
    style = cb.data.replace("admbtnstl_","",1)
    data = await state.get_data()
    update_btn_style(data["selected_key"], style)
    names = {"primary":"🔵 Primary","success":"🟢 Success","danger":"🔴 Danger","default":"⬜ Default"}
    await cb.answer(f"✅ {names.get(style,style)}")
    try: await cb.message.edit_text(f"✅ Стиль: <b>{names.get(style,style)}</b>", reply_markup=admin_menu_btns_kb())
    except: await cb.message.answer(f"✅ Стиль: <b>{names.get(style,style)}</b>", reply_markup=admin_menu_btns_kb())

# --- ВВІД ТЕКСТІВ КНОПОК ---
@dp.message(S.admin_edit_text)
async def admin_edit_text(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await msg.answer("🎨 Кнопки меню", reply_markup=admin_menu_btns_kb())
        await state.set_state(S.admin); return
    data = await state.get_data()
    key = data["selected_key"]
    custom_emoji_id = ""
    if msg.entities:
        for entity in msg.entities:
            if entity.type == "custom_emoji":
                custom_emoji_id = entity.custom_emoji_id; break
    raw = msg.text.strip() if msg.text else ""
    parts = raw.split(" ", 1)
    emoji = parts[0] if len(parts) >= 1 else "⭐"
    text  = parts[1] if len(parts) == 2 else parts[0]
    btns = get_menu_buttons()
    current = next((b for b in btns if b["button_key"]==key), {})
    update_btn_text(key, text, emoji, custom_emoji_id, text)
    await msg.answer(f"✅ {emoji} {text}", reply_markup=admin_menu_btns_kb())
    await state.set_state(S.admin)

@dp.message(S.admin_btn_order)
async def admin_btn_order(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await msg.answer("🎨 Кнопки меню", reply_markup=admin_menu_btns_kb())
        await state.set_state(S.admin); return
    btns = get_menu_buttons()
    keys = [b["button_key"] for b in btns]
    try:
        nums = [int(n)-1 for line in msg.text.strip().split("\n") for n in line.split()]
        update_btn_order([keys[i] for i in nums])
        await msg.answer("✅ Порядок оновлено!", reply_markup=admin_menu_btns_kb())
    except: await msg.answer("❌ Невірний формат.")
    await state.set_state(S.admin)

@dp.message(S.admin_text_edit)
async def admin_text_edit(msg: Message, state: FSMContext):
    if is_cancel(msg.text): await msg.answer("📝 Тексти", reply_markup=admin_texts_kb()); await state.set_state(S.admin); return
    data = await state.get_data(); key = data.get("text_key")
    custom_emoji_entities = [e for e in (msg.entities or []) if e.type == "custom_emoji"]
    has_custom_emoji = bool(custom_emoji_entities)
    if has_custom_emoji:
        raw = (msg.html_text or "").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        # Прибираємо звичайні emoji, що стоять одразу поруч (через пробіл) із преміум-емодзі —
        # це старі значки, які лишились в тексті після того як адмін вставив преміум-емодзі
        # замість них, але не видалив попередній символ (як було зі способами оплати).
        import re as _re_adj
        plain_carriers = []
        for ent in custom_emoji_entities:
            t16 = (msg.text or "").encode("utf-16-le")
            start = ent.offset * 2
            end = (ent.offset + ent.length) * 2
            carrier = t16[start:end].decode("utf-16-le", errors="ignore")
            if carrier:
                plain_carriers.append(carrier)
        tg_emoji_tag_re = _re_adj.compile(r'<tg-emoji[^>]*>.*?</tg-emoji>')
        ordinary_emoji_re = _re_adj.compile(
            "["
            "\U0001F300-\U0001FAFF"
            "\U00002600-\U000027BF"
            "\U0001F1E6-\U0001F1FF"
            "\U00002190-\U000021FF"
            "\U00002B00-\U00002BFF"
            "\uFE0F"
            "]"
        )
        def _strip_adjacent(m):
            tag = m.group(0)
            return tag
        # Видаляємо звичайний emoji-символ безпосередньо перед/після кожного <tg-emoji>...</tg-emoji> блоку,
        # якщо цей символ збігається з носієм преміум-емодзі (тобто це дублікат того самого значка).
        for carrier in set(plain_carriers):
            if not carrier:
                continue
            esc = _re_adj.escape(carrier)
            raw = _re_adj.sub(rf'{esc}\s*(<tg-emoji)', r'\1', raw)
            raw = _re_adj.sub(rf'(</tg-emoji>)\s*{esc}', r'\1', raw)
        # Додатково прибираємо випадки коли поруч стоїть ІНШИЙ звичайний emoji (не точний дублікат носія),
        # але лише прямо перед/після тегу — щоб не зачепити emoji в інших частинах тексту.
        raw = _re_adj.sub(rf'({ordinary_emoji_re.pattern})\s*(<tg-emoji)', r'\2', raw)
        raw = _re_adj.sub(rf'(</tg-emoji>)\s*({ordinary_emoji_re.pattern})', r'\1', raw)
    else:
        import html as _html
        plain = msg.text or ""
        allowed_tags_pattern = r'</?(?:b|i|u|s|code|pre|blockquote|tg-spoiler)(?:\s[^>]*)?>'
        import re as _re
        placeholders = {}
        def _stash(m):
            ph = f"\x00{len(placeholders)}\x00"
            placeholders[ph] = m.group(0)
            return ph
        stashed = _re.sub(allowed_tags_pattern, _stash, plain)
        escaped = _html.escape(stashed)
        for ph, tag in placeholders.items():
            escaped = escaped.replace(_html.escape(ph), tag)
        raw = escaped
    set_bot_text(key, value_ru=raw.strip(), value_uk=raw.strip())
    await msg.answer("✅ Збережено!\n\nПерегляд:\n" + raw.strip(), reply_markup=admin_texts_kb(), parse_mode='HTML')
    await state.set_state(S.admin)

@dp.message(S.admin_photo_upload)
async def admin_photo_upload(msg: Message, state: FSMContext):
    data = await state.get_data()
    section = data.get("photo_section", "")

    if msg.photo:
        file_id = msg.photo[-1].file_id
        set_setting(f"photo_{section}", file_id)
        await msg.answer(f"✅ Фото для розділу '{section}' завантажено!")
    elif msg.text and "пропустити" in msg.text.lower():
        await msg.answer("⏭️ Пропущено")

    await state.set_state(S.admin)
    await msg.answer("🛠 <b>Панель адміністратора</b>", reply_markup=admin_main_kb(), parse_mode="HTML")

@dp.message(S.admin_gift_add_emoji)
async def admin_gift_add_emoji_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.admin)
        await msg.answer("❌ Скасовано", reply_markup=admin_back_kb())
        return
    val = (msg.text or "").strip()
    if not val:
        await msg.answer("❌ Надішліть емодзі"); return
    await state.update_data(new_gift_emoji=val[:8])
    await msg.answer("💰 <b>Введіть ціну подарунка в грн (число):</b>", reply_markup=cancel_kb(), parse_mode="HTML")
    await state.set_state(S.admin_gift_add_price)

@dp.message(S.admin_gift_add_price)
async def admin_gift_add_price_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.admin)
        await msg.answer("❌ Скасовано", reply_markup=admin_back_kb())
        return
    val = (msg.text or "").strip().replace(",", ".")
    try:
        price = float(val)
        if price <= 0: raise ValueError
    except ValueError:
        await msg.answer("❌ Введіть коректну ціну (число)"); return
    data = await state.get_data()
    key = add_gift_item(emoji=data.get("new_gift_emoji", "🎁"), name="", price=price)
    await state.set_state(S.admin)
    await msg.answer("✅ Подарунок додано! Не забудьте вказати Telegram Gift ID для автовидачі.", reply_markup=admin_back_kb())
    item = get_gift_item(key)
    status = "✅ Увімкнено" if item.get("enabled") else "🚫 Вимкнено"
    text = (f"{item['emoji']} <b>{item.get('name') or '(без назви)'}</b>\n\n"
            f"💰 Ціна: <b>{item['price']:.0f} грн</b>\n"
            f"🆔 Telegram Gift ID: <code>{item.get('telegram_gift_id') or '—'}</code>\n"
            f"Статус: <b>{status}</b>")
    await msg.answer(text, reply_markup=admin_gift_item_kb(key), parse_mode="HTML")

@dp.message(S.admin_gift_edit)
async def admin_gift_edit_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.admin)
        await msg.answer("❌ Скасовано", reply_markup=admin_back_kb())
        return
    data = await state.get_data()
    key = data.get("gift_key")
    field = data.get("gift_field")
    item = get_gift_item(key) if key else None
    if not item:
        await state.set_state(S.admin)
        await msg.answer("❌ Позицію не знайдено", reply_markup=admin_back_kb())
        return

    val = (msg.text or "").strip()
    if field == "name":
        if not val or len(val) > 60:
            await msg.answer("❌ Введіть коректну назву (до 60 символів)"); return
        set_gift_field(key, "name", val)
    elif field == "emoji":
        if not val:
            await msg.answer("❌ Введіть емодзі"); return
        set_gift_field(key, "emoji", val[:8])
    elif field == "price":
        try:
            price = float(val.replace(",", "."))
            if price < 0: raise ValueError
        except ValueError:
            await msg.answer("❌ Введіть коректну ціну (число)"); return
        set_gift_field(key, "price", price)
    elif field == "pricestars":
        if val in ("-", "0", "авто", "auto"):
            set_gift_field(key, "price_stars", None)
        else:
            try:
                stars = int(val)
                if stars < 0: raise ValueError
            except ValueError:
                await msg.answer("❌ Введіть ціле число Stars, або «-» для авто-розрахунку з ціни в грн"); return
            set_gift_field(key, "price_stars", stars)
    elif field == "qty":
        if val in ("-", "0", "∞", "безлим", "unlimited"):
            set_gift_field(key, "quantity", None)
        else:
            try:
                qty = int(val)
                if qty < 0: raise ValueError
            except ValueError:
                await msg.answer("❌ Введіть ціле число, або «-» для необмеженої кількості"); return
            set_gift_field(key, "quantity", qty)
    elif field == "tgid":
        if not val.isdigit():
            await msg.answer("❌ Telegram Gift ID має бути числом"); return
        set_gift_field(key, "telegram_gift_id", val)
    elif field == "sticker":
        custom_emoji_id = ""
        if msg.entities:
            for entity in msg.entities:
                if entity.type == "custom_emoji":
                    custom_emoji_id = entity.custom_emoji_id
                    break
        if not custom_emoji_id:
            await msg.answer("❌ Це не преміум-емодзі. Надішліть саме преміум-емодзі повідомленням."); return
        set_gift_field(key, "sticker_id", custom_emoji_id)
    else:
        await state.set_state(S.admin)
        await msg.answer("❌ Невідоме поле", reply_markup=admin_back_kb())
        return

    await state.set_state(S.admin)
    await msg.answer("✅ Оновлено!", reply_markup=admin_back_kb())
    item = get_gift_item(key)
    status = "✅ Увімкнено" if item.get("enabled") else "🚫 Вимкнено"
    qty = "без обмежень" if item.get("quantity") is None else str(item["quantity"])
    stars_display = f"{item['price_stars']} Stars" if item.get("price_stars") else f"~{gift_price_stars(item)} Stars (авто)"
    text = (
        f"{item['emoji']} <b>{item['name']}</b>\n\n"
        f"💰 Ціна: <b>{item['price']:.0f} грн</b>\n"
        f"⭐ Ціна в Stars: <b>{stars_display}</b>\n"
        f"🔢 Кількість: <b>{qty}</b>\n"
        f"🆔 Telegram Gift ID: <code>{item.get('telegram_gift_id') or '—'}</code>\n"
        f"🖼 Прем-стикер: <code>{item.get('sticker_id') or '—'}</code>\n"
        f"Статус: <b>{status}</b>"
    )
    await msg.answer(text, reply_markup=admin_gift_item_kb(key), parse_mode="HTML")

@dp.message(S.admin_sp_edit)
async def admin_sp_edit_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.admin)
        await msg.answer("❌ Скасовано", reply_markup=admin_back_kb())
        return
    data = await state.get_data()
    key = data.get("sp_key")
    field = data.get("sp_field")
    p = get_stars_package(key) if key else None
    if not p:
        await state.set_state(S.admin)
        await msg.answer("❌ Позицію не знайдено", reply_markup=admin_back_kb())
        return

    val = (msg.text or "").strip()
    if field == "emoji":
        if not val:
            await msg.answer("❌ Введіть емодзі"); return
        set_stars_package_field(key, "emoji", val[:8])
    elif field == "label":
        if val == "-":
            set_stars_package_field(key, "label", "")
        else:
            set_stars_package_field(key, "label", val[:300])
    elif field == "description":
        if val == "-":
            set_stars_package_field(key, "description", "")
        else:
            set_stars_package_field(key, "description", val[:900])
    elif field == "amount":
        if not val.isdigit() or int(val) <= 0:
            await msg.answer("❌ Введіть ціле додатне число"); return
        set_stars_package_field(key, "amount", int(val))
    elif field == "price":
        if val == "-":
            set_stars_package_field(key, "fixed_price", None)
        else:
            try:
                price = float(val.replace(",", "."))
                if price <= 0: raise ValueError
            except ValueError:
                await msg.answer("❌ Введіть коректну ціну (число), або «-» для авто-розрахунку"); return
            set_stars_package_field(key, "fixed_price", price)
    elif field == "min":
        if not val.isdigit() or int(val) <= 0:
            await msg.answer("❌ Введіть ціле додатне число"); return
        set_stars_package_field(key, "range_min", int(val))
    elif field == "max":
        if val == "-":
            set_stars_package_field(key, "range_max", None)
        else:
            if not val.isdigit() or int(val) <= 0:
                await msg.answer("❌ Введіть ціле додатне число, або «-» без ліміту"); return
            set_stars_package_field(key, "range_max", int(val))
    elif field == "giftqty":
        if not val.isdigit() or int(val) <= 0:
            await msg.answer("❌ Введіть ціле додатне число"); return
        set_stars_package_field(key, "linked_gift_qty", int(val))
    elif field == "sticker":
        if val == "-":
            set_stars_package_field(key, "custom_emoji_id", "")
        else:
            custom_emoji_id = ""
            if msg.entities:
                for entity in msg.entities:
                    if entity.type == "custom_emoji":
                        custom_emoji_id = entity.custom_emoji_id
                        break
            if not custom_emoji_id:
                await msg.answer("❌ Це не преміум-емодзі. Надішліть саме преміум-емодзі повідомленням, або «-» щоб прибрати."); return
            set_stars_package_field(key, "custom_emoji_id", custom_emoji_id)
    else:
        await state.set_state(S.admin)
        await msg.answer("❌ Невідоме поле", reply_markup=admin_back_kb())
        return

    await state.set_state(S.admin)
    await msg.answer("✅ Оновлено!", reply_markup=admin_back_kb())
    if p.get("parent_key"):
        parent = get_stars_package(p["parent_key"])
        await msg.answer(f"🧩 <b>Кнопки набору «{parent.get('label') or p['parent_key']}»</b>\n\nОберіть кнопку для редагування:",
                          reply_markup=admin_sp_children_kb(p["parent_key"]), parse_mode="HTML")
    else:
        await msg.answer("⭐ <b>Паки Stars — редагування каталогу</b>\n\nОберіть позицію:",
                          reply_markup=admin_star_packages_kb(), parse_mode="HTML")

@dp.message(S.admin_sp_add)
async def admin_sp_add_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.admin)
        await msg.answer("❌ Скасовано", reply_markup=admin_back_kb())
        return
    data = await state.get_data()
    kind = data.get("sp_add_kind", "fixed")
    val = (msg.text or "").strip()

    if kind == "fixed":
        if not val.isdigit() or int(val) <= 0:
            await msg.answer("❌ Введіть ціле додатне число"); return
        parent = data.get("sp_add_parent")
        add_stars_package(kind="fixed", amount=int(val), emoji="⭐", parent_key=parent)
        await state.set_state(S.admin)
        if parent:
            await msg.answer(f"✅ Кнопку додано! ({val} Stars)", reply_markup=admin_back_kb())
            p = get_stars_package(parent)
            await msg.answer(f"🧩 <b>Кнопки набору «{p.get('label') or parent}»</b>\n\nОберіть кнопку для редагування:",
                              reply_markup=admin_sp_children_kb(parent), parse_mode="HTML")
        else:
            await msg.answer(f"✅ Пак додано! ({val} Stars)", reply_markup=admin_back_kb())
            await msg.answer("⭐ <b>Паки Stars — редагування каталогу</b>\n\nОберіть позицію:",
                              reply_markup=admin_star_packages_kb(), parse_mode="HTML")
        return

    # kind == "range" — двокроковий ввід: спочатку мінімум, потім максимум
    if "sp_add_min" not in data:
        if not val.isdigit() or int(val) <= 0:
            await msg.answer("❌ Введіть ціле додатне число"); return
        await state.update_data(sp_add_min=int(val))
        await msg.answer("🔼 Тепер введіть максимальну суму (ціле число, або «-» без ліміту):", reply_markup=cancel_kb())
        return

    range_min = data["sp_add_min"]
    if val == "-":
        range_max = None
    else:
        if not val.isdigit() or int(val) <= range_min:
            await msg.answer(f"❌ Максимум має бути числом більшим за {range_min}, або «-» без ліміту"); return
        range_max = int(val)
    add_stars_package(kind="range", range_min=range_min, range_max=range_max, emoji="✏️")
    await state.set_state(S.admin)
    rng_display = f"{range_min}-{range_max}" if range_max else f"{range_min}+"
    await msg.answer(f"✅ Пак додано! (діапазон {rng_display})", reply_markup=admin_back_kb())
    await msg.answer("⭐ <b>Паки Stars — редагування каталогу</b>\n\nОберіть позицію:",
                      reply_markup=admin_star_packages_kb(), parse_mode="HTML")

@dp.message(S.admin_gift_api_creds)
async def admin_gift_api_creds_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.admin)
        await msg.answer("❌ Скасовано", reply_markup=admin_back_kb())
        return
    parts = (msg.text or "").strip().split()
    if len(parts) != 2 or not parts[0].isdigit():
        await msg.answer("❌ Формат: <code>api_id api_hash</code> (через пробіл)", parse_mode="HTML")
        return
    api_id, api_hash = int(parts[0]), parts[1]
    set_gift_api_creds(api_id, api_hash)
    await reset_gift_client()
    await state.set_state(S.admin)
    await msg.answer(
        f"✅ Дані Telethon-акаунта збережено!\napi_id: <code>{api_id}</code>\n\n"
        f"Тепер натисніть «📱 Увійти в акаунт», щоб авторизувати сесію.",
        reply_markup=admin_gifts_kb(), parse_mode="HTML")

# ------------------- 🎁 Логін Telethon-акаунта прямо з чату бота -------------------

@dp.message(S.gift_login_phone)
async def gift_login_phone_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.admin)
        await msg.answer("❌ Скасовано", reply_markup=admin_back_kb())
        return
    phone = (msg.text or "").strip()
    if not phone.startswith("+") or not phone[1:].replace(" ", "").isdigit():
        await msg.answer("❌ Введіть номер у форматі +380XXXXXXXXX")
        return
    creds = get_gift_api_creds()
    wait_msg = await msg.answer("⏳ Надсилаю код підтвердження...")
    result = await gift_login_send_code(int(creds["api_id"]), creds["api_hash"], phone)
    try: await wait_msg.delete()
    except Exception: pass
    if not result.get("ok"):
        await msg.answer(f"❌ {result.get('error', 'Помилка')}", reply_markup=admin_back_kb())
        await state.set_state(S.admin)
        return
    await state.update_data(gift_phone=phone, gift_phone_code_hash=result["phone_code_hash"])
    await state.set_state(S.gift_login_code)
    await msg.answer(
        "📩 <b>Код надіслано!</b>\n\nВведіть код підтвердження, який прийшов в Telegram-акаунт "
        "(можна через пробіл, напр. <code>1 2 3 4 5</code>, або просто <code>12345</code>):",
        reply_markup=cancel_kb(), parse_mode="HTML")

@dp.message(S.gift_login_code)
async def gift_login_code_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.admin)
        await msg.answer("❌ Скасовано", reply_markup=admin_back_kb())
        return
    code = (msg.text or "").strip().replace(" ", "")
    if not code.isdigit():
        await msg.answer("❌ Код має складатись лише з цифр, спробуйте ще раз")
        return
    data = await state.get_data()
    creds = get_gift_api_creds()
    result = await gift_login_sign_in(
        int(creds["api_id"]), creds["api_hash"],
        data.get("gift_phone"), data.get("gift_phone_code_hash"), code)
    if result.get("ok"):
        await state.set_state(S.admin)
        await msg.answer("✅ <b>Вхід виконано! Автовидача подарунків готова до роботи.</b>",
                          reply_markup=admin_gifts_kb(), parse_mode="HTML")
        return
    if result.get("need_password"):
        await state.set_state(S.gift_login_password)
        await msg.answer(
            "🔐 На цьому акаунті увімкнена двофакторна автентифікація.\nВведіть пароль (2FA):",
            reply_markup=cancel_kb())
        return
    await msg.answer(
        f"❌ {result.get('error', 'Невірний код')}\n\nВведіть код ще раз, або натисніть "
        f"«📱 Увійти в акаунт» заново, якщо код застарів:",
        reply_markup=cancel_kb())

@dp.message(S.gift_login_password)
async def gift_login_password_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await state.set_state(S.admin)
        await msg.answer("❌ Скасовано", reply_markup=admin_back_kb())
        return
    password = (msg.text or "").strip()
    creds = get_gift_api_creds()
    result = await gift_login_check_password(int(creds["api_id"]), creds["api_hash"], password)
    if result.get("ok"):
        await state.set_state(S.admin)
        await msg.answer("✅ <b>Вхід виконано! Автовидача подарунків готова до роботи.</b>",
                          reply_markup=admin_gifts_kb(), parse_mode="HTML")
        return
    await msg.answer(f"❌ {result.get('error', 'Невірний пароль')}\n\nСпробуйте ще раз:", reply_markup=cancel_kb())

@dp.message(S.admin_pkg_emoji)
async def admin_pkg_emoji_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
    if msg.text and msg.text.strip() == "-":
        set_setting("btn_pkg_emoji_id", "")
        await msg.answer("✅ Емодзі прибрано. Кнопки пакетів тепер без значка.", reply_markup=admin_menu_btns_kb())
        await state.set_state(S.admin)
        return
    custom_emoji_id = ""
    if msg.entities:
        for entity in msg.entities:
            if entity.type == "custom_emoji":
                custom_emoji_id = entity.custom_emoji_id
                break
    if not custom_emoji_id:
        await msg.answer("❌ Преміум-емодзі не знайдено в повідомленні. Спробуйте ще раз — вставте емодзі з клавіатури:")
        return
    set_setting("btn_pkg_emoji_id", custom_emoji_id)
    await msg.answer("✅ Емодзі збережено! Тепер кнопки пакетів Stars матимуть цей значок.", reply_markup=admin_menu_btns_kb())
    await state.set_state(S.admin)

@dp.message(S.admin_copyref_text)
async def admin_copyref_text_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
    text = (msg.text or "").strip()
    if not text:
        await msg.answer("❌ Текст не може бути порожнім. Введіть ще раз:")
        return
    set_setting("btn_copyref_text", text)
    await msg.answer("✅ Текст кнопки збережено.", reply_markup=admin_back_kb())
    await state.set_state(S.admin)

@dp.message(S.admin_copyref_emoji)
async def admin_copyref_emoji_handler(msg: Message, state: FSMContext):
    if is_cancel(msg.text):
        await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
    if msg.text and msg.text.strip() == "-":
        set_setting("btn_copyref_emoji_id", "")
        await msg.answer("✅ Емодзі прибрано.", reply_markup=admin_back_kb())
        await state.set_state(S.admin)
        return
    custom_emoji_id = ""
    if msg.entities:
        for entity in msg.entities:
            if entity.type == "custom_emoji":
                custom_emoji_id = entity.custom_emoji_id
                break
    if not custom_emoji_id:
        await msg.answer("❌ Преміум-емодзі не знайдено в повідомленні. Спробуйте ще раз — вставте емодзі з клавіатури:")
        return
    set_setting("btn_copyref_emoji_id", custom_emoji_id)
    await msg.answer("✅ Емодзі збережено!", reply_markup=admin_back_kb())
    await state.set_state(S.admin)

@dp.message(S.admin_card_edit)
async def admin_card_edit(msg: Message, state: FSMContext):
    if is_cancel(msg.text): await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
    data = await state.get_data()
    field = data.get("medit_field", "details")
    mk = data.get("medit_key") or data.get("card_key")
    if field == "name":
        custom_emoji_id = ""
        emoji_entity = None
        if msg.entities:
            for entity in msg.entities:
                if entity.type == "custom_emoji":
                    custom_emoji_id = entity.custom_emoji_id
                    emoji_entity = entity
                    break

        raw = msg.text or ""
        if emoji_entity:
            # Telegram offset/length рахуються в UTF-16 code units — працюємо через encode/decode,
            # щоб коректно вирізати саме той символ-носій preміум-емодзі, що описаний в entity.
            raw_u16 = raw.encode("utf-16-le")
            start = emoji_entity.offset * 2
            end = (emoji_entity.offset + emoji_entity.length) * 2
            before = raw_u16[:start].decode("utf-16-le", errors="ignore")
            after = raw_u16[end:].decode("utf-16-le", errors="ignore")
            name = (before + after)
        else:
            name = raw

        # Прибираємо будь-які звичайні (не преміум) емодзі та пробіли, що залишились на початку рядка —
        # це старі текстові значки, які адмін не видалив перед відправкою нового.
        import re as _re_emoji
        emoji_pattern = _re_emoji.compile(
            "["
            "\U0001F300-\U0001FAFF"
            "\U00002600-\U000027BF"
            "\U0001F1E6-\U0001F1FF"
            "\U00002190-\U000021FF"
            "\U00002B00-\U00002BFF"
            "\uFE0F"
            "]+"
        )
        name = emoji_pattern.sub("", name).strip()
        name = _re_emoji.sub(r"\s{2,}", " ", name).strip()

        update_payment_method(mk, "name_ru", name)
        update_payment_method(mk, "name_uk", name)
        update_payment_method(mk, "custom_emoji_id", custom_emoji_id)
        # Старе текстове поле emoji більше не використовується для відображення —
        # значок тепер або преміум (icon_custom_emoji_id), або зовсім немає.
        update_payment_method(mk, "emoji", "")

        preview_prefix = "💎 " if custom_emoji_id else ""
        await msg.answer(f"✅ <b>Назву оновлено!</b>\n{preview_prefix}{name}", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "owner":
        value = msg.text.strip()
        if value == "-":
            value = ""
        update_payment_method(mk, "owner", value)
        if value:
            await msg.answer(f"✅ <b>Власник оновлено!</b>\n👤 {value}", reply_markup=admin_methods_kb(), parse_mode="HTML")
        else:
            await msg.answer("✅ <b>Власника прибрано.</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "emoji":
        if (msg.text or "").strip() == "-":
            update_payment_method(mk, "custom_emoji_id", "")
            await msg.answer("✅ <b>Прем-емодзі прибрано.</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
        else:
            custom_emoji_id = ""
            if msg.entities:
                for entity in msg.entities:
                    if entity.type == "custom_emoji":
                        custom_emoji_id = entity.custom_emoji_id
                        break
            if not custom_emoji_id:
                await msg.answer("❌ Це не преміум-емодзі. Надішліть саме преміум-емодзі повідомленням, або «-» щоб прибрати.")
                return
            update_payment_method(mk, "custom_emoji_id", custom_emoji_id)
            await msg.answer("✅ <b>Прем-емодзі кнопки оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "ctext":
        # html_text (а не text) — щоб зберігалися преміум-емодзі (<tg-emoji>) та інша розмітка,
        # яку адмін вставив прямо у повідомлення, а не тільки простий текст.
        value = (msg.html_text or "").strip()
        set_setting("cryptobot_pay_text", "" if value == "-" else value[:900])
        await msg.answer("✅ <b>Текст оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "cctext":
        value = (msg.html_text or "").strip()
        set_setting("cryptobot_currency_text", "" if value == "-" else value[:900])
        await msg.answer("✅ <b>Текст оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "ctontext":
        value = (msg.text or "").strip()
        set_setting("cryptobot_ton_btn_text", "" if value == "-" else value[:40])
        await msg.answer("✅ <b>Текст кнопки TON оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "cusdttext":
        value = (msg.text or "").strip()
        set_setting("cryptobot_usdt_btn_text", "" if value == "-" else value[:40])
        await msg.answer("✅ <b>Текст кнопки USDT оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "ctonbtn":
        if (msg.text or "").strip() == "-":
            set_setting("cryptobot_ton_emoji", "")
            await msg.answer("✅ <b>Прем-емодзі прибрано.</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
        else:
            custom_emoji_id = ""
            if msg.entities:
                for entity in msg.entities:
                    if entity.type == "custom_emoji":
                        custom_emoji_id = entity.custom_emoji_id
                        break
            if not custom_emoji_id:
                await msg.answer("❌ Це не преміум-емодзі. Надішліть саме преміум-емодзі повідомленням, або «-» щоб прибрати.")
                return
            set_setting("cryptobot_ton_emoji", custom_emoji_id)
            await msg.answer("✅ <b>Прем-емодзі кнопки «TON» оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "cusdtbtn":
        if (msg.text or "").strip() == "-":
            set_setting("cryptobot_usdt_emoji", "")
            await msg.answer("✅ <b>Прем-емодзі прибрано.</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
        else:
            custom_emoji_id = ""
            if msg.entities:
                for entity in msg.entities:
                    if entity.type == "custom_emoji":
                        custom_emoji_id = entity.custom_emoji_id
                        break
            if not custom_emoji_id:
                await msg.answer("❌ Це не преміум-емодзі. Надішліть саме преміум-емодзі повідомленням, або «-» щоб прибрати.")
                return
            set_setting("cryptobot_usdt_emoji", custom_emoji_id)
            await msg.answer("✅ <b>Прем-емодзі кнопки «USDT» оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "cpaybtn":
        if (msg.text or "").strip() == "-":
            set_setting("cryptobot_pay_btn_emoji", "")
            await msg.answer("✅ <b>Прем-емодзі прибрано.</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
        else:
            custom_emoji_id = ""
            if msg.entities:
                for entity in msg.entities:
                    if entity.type == "custom_emoji":
                        custom_emoji_id = entity.custom_emoji_id
                        break
            if not custom_emoji_id:
                await msg.answer("❌ Це не преміум-емодзі. Надішліть саме преміум-емодзі повідомленням, або «-» щоб прибрати.")
                return
            set_setting("cryptobot_pay_btn_emoji", custom_emoji_id)
            await msg.answer("✅ <b>Прем-емодзі кнопки «Оплатити» оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "ccheckbtn":
        if (msg.text or "").strip() == "-":
            set_setting("cryptobot_check_btn_emoji", "")
            await msg.answer("✅ <b>Прем-емодзі прибрано.</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
        else:
            custom_emoji_id = ""
            if msg.entities:
                for entity in msg.entities:
                    if entity.type == "custom_emoji":
                        custom_emoji_id = entity.custom_emoji_id
                        break
            if not custom_emoji_id:
                await msg.answer("❌ Це не преміум-емодзі. Надішліть саме преміум-емодзі повідомленням, або «-» щоб прибрати.")
                return
            set_setting("cryptobot_check_btn_emoji", custom_emoji_id)
            await msg.answer("✅ <b>Прем-емодзі кнопки «Перевірити» оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "cpaytext":
        value = (msg.text or "").strip()
        set_setting("cryptobot_pay_btn_text", "" if value == "-" else value[:40])
        await msg.answer("✅ <b>Текст кнопки «Оплатити» оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "cchecktext":
        value = (msg.text or "").strip()
        set_setting("cryptobot_check_btn_text", "" if value == "-" else value[:40])
        await msg.answer("✅ <b>Текст кнопки «Перевірити» оновлено!</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    elif field == "instructions":
        value = msg.text.strip()
        if value == "-":
            value = ""
        update_payment_method(mk, "instructions", value)
        if value:
            await msg.answer("✅ <b>Текст оплати оновлено!</b>\n\nПопередній перегляд:\n\n" + value,
                              reply_markup=admin_methods_kb(), parse_mode="HTML")
        else:
            await msg.answer("✅ <b>Повернуто стандартний шаблон.</b>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    else:
        update_payment_method(mk, "details", msg.text.strip())
        await msg.answer(f"✅ <b>Реквізити оновлено!</b>\n<code>{msg.text.strip()}</code>", reply_markup=admin_methods_kb(), parse_mode="HTML")
    await state.set_state(S.admin)

# --- ЧИСЛОВІ НАЛАШТУВАННЯ ---
def make_num_handler(setting_key, success_text, is_float=False, min_val=None, max_val=None):
    async def handler(msg: Message, state: FSMContext):
        if is_cancel(msg.text): await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
        try:
            val = float(msg.text.replace(",",".")) if is_float else int(msg.text)
            if min_val is not None and val < min_val: raise ValueError
            if max_val is not None and val > max_val: raise ValueError
            set_setting(setting_key, val)
            await msg.answer(f"✅ {success_text}: <b>{val}</b>", reply_markup=admin_main_kb(), parse_mode="HTML")
            await state.set_state(S.admin)
        except: await msg.answer(f"❌ Введіть число" + (f" від {min_val} до {max_val}" if min_val is not None else ""))
    return handler

dp.message.register(make_num_handler("review_reward_min","Мін. нагорода за відгук",False,1), S.admin_review_reward_min)
dp.message.register(make_num_handler("review_reward_max","Макс. нагорода за відгук",False,1), S.admin_review_reward_max)

@dp.message(S.admin_prem_price)
async def set_prem_price(msg: Message, state: FSMContext):
    if is_cancel(msg.text): await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
    data = await state.get_data()
    try:
        set_setting(data["prem_key"], float(msg.text.replace(",",".")))
        await msg.answer(f"✅ Premium: <b>{msg.text} грн</b>", reply_markup=admin_main_kb(), parse_mode="HTML")
        await state.set_state(S.admin)
    except: await msg.answer("❌ Введіть число")

@dp.message(S.admin_broadcast)
async def admin_broadcast(msg: Message, state: FSMContext):
    if is_cancel(msg.text): await msg.answer("🛠", reply_markup=admin_main_kb()); await state.set_state(S.admin); return
    users = get_all_users(); sent = failed = 0
    for uid in users:
        try:
            # copy_to зберігає повне форматування повідомлення (жирний, курсив,
            # преміум-емодзі тощо) — на відміну від пересилання лише msg.text/.caption,
            # яке губить усі entities розмітки.
            await msg.copy_to(chat_id=uid)
            sent += 1
        except: failed += 1
    await msg.answer(f"📢 <b>Готово!</b>\n✅ {sent}\n❌ {failed}", reply_markup=admin_main_kb())
    await state.set_state(S.admin)

# ========================================================
# HEALTHCHECK SERVER (для Railway)
# ========================================================

async def healthcheck(request):
    return web.Response(text="ok")

def build_health_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/healthz", healthcheck)
    return app

async def start_health_server():
    app = build_health_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f'🌐 Healthcheck сервер запущено на порту {port}')

# ========================================================
# ЗАПУСК БОТА
# ========================================================

async def main():
    global BOT_USERNAME
    init_db()
    if not BOT_USERNAME:
        try:
            BOT_USERNAME = (await bot.get_me()).username
            print(f'🤖 username: @{BOT_USERNAME}')
        except Exception as e:
            print(f'⚠️ getMe помилка: {e}')
    print(f'🤖 {BOT_NAME} запущен!')
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="🚀 Головне меню"),
        ])
        print('✅ Команди встановлено')
    except Exception as e:
        print(f'⚠️ Commands не встановлено: {e}')

    await start_health_server()

    await bot.delete_webhook(drop_pending_updates=True)
    print(f'🔄 Polling mode активен')
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == '__main__':
    asyncio.run(main())
