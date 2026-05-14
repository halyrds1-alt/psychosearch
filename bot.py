#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Psycho Search Bot — FINAL WORKING VERSION
Windows / Linux / Termux
"""

import telebot, requests, sqlite3, os, sys, time, re, hashlib, threading, json
from telebot import types
from datetime import datetime, timedelta

# ========== КОНФИГУРАЦИЯ ==========
MAIN_TOKEN    = "8719309913:AAHNEEMZ98_8HWI-sImHafF8UEAmcScQSCs"
CRYPTO_TOKEN  = "581560:AAo9TOHClCxqbvxi4Qi0hHn45goH8jqaByM"
ADMINS        = [7811061945, 8679197041, 6747528307]
API_URL       = "https://api.depsearch.sbs"
API_KEY       = "cGo0fxW0t9yqcXKLJgCw0AIwbFaLAZPA"

# Путь к БД – в одной папке со скриптом
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH       = os.path.join(SCRIPT_DIR, "psycho.db")

PRICES = {
    '1day':   {'days':1,   'usdt':0.5},
    '7days':  {'days':7,   'usdt':2},
    '30days': {'days':30,  'usdt':3.5},
    '90days': {'days':90,  'usdt':8},
    '180days':{'days':180, 'usdt':16},
    '365days':{'days':365, 'usdt':26}
}

# ========== БАЗА ДАННЫХ ==========
def init_db():
    """Создаёт БД и таблицы, если их нет. Добавляет недостающие колонки."""
    try:
        # Создаём папку, если её нет (на всякий случай)
        os.makedirs(SCRIPT_DIR, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            # Таблица пользователей
            c.execute("""CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                reg_date TEXT,
                last_active TEXT,
                searches INTEGER DEFAULT 0,
                last_reset TEXT,
                premium INTEGER DEFAULT 0,
                premium_until TEXT
            )""")
            # Таблица зеркал
            c.execute("""CREATE TABLE IF NOT EXISTS mirrors(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_token TEXT UNIQUE,
                bot_username TEXT,
                created_by INTEGER,
                created_at TEXT,
                is_active INTEGER DEFAULT 1
            )""")
            # Таблица платежей
            c.execute("""CREATE TABLE IF NOT EXISTS payments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                invoice_id TEXT UNIQUE,
                amount REAL,
                plan TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                paid_at TEXT
            )""")
            # Автодобавление колонок (если таблица уже была, но без них)
            for col in ['searches','last_reset','premium','premium_until']:
                try:
                    c.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT ''")
                except:
                    pass  # колонка уже есть
            conn.commit()
        print(f"[DB] Готово: {DB_PATH}")
        return True
    except Exception as e:
        print(f"[DB] Ошибка создания БД: {e}")
        return False

# ========== ФУНКЦИИ БД ==========
def add_user(uid, username, first_name):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
        if not c.fetchone():
            c.execute("INSERT INTO users(user_id,username,first_name,reg_date,last_active,searches,last_reset,premium,premium_until) VALUES(?,?,?,?,?,0,?,0,'')",
                     (uid, username or '', first_name or '', datetime.now().isoformat(), datetime.now().isoformat(), datetime.now().date().isoformat()))
        else:
            c.execute("UPDATE users SET last_active=? WHERE user_id=?", (datetime.now().isoformat(), uid))
        conn.commit()

def get_user(uid):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT searches,premium,premium_until FROM users WHERE user_id=?", (uid,))
        r = c.fetchone()
    if r: return {'s':r[0] or 0,'p':r[1] or 0,'pu':r[2] or ''}
    return {'s':0,'p':0,'pu':''}

def can_search(uid):
    u = get_user(uid)
    # Premium?
    if u['p'] and u['pu']:
        try:
            if datetime.fromisoformat(u['pu']) > datetime.now():
                return True, 999, True
        except: pass
    # Сброс дневного лимита
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        today = datetime.now().date().isoformat()
        c.execute("SELECT last_reset FROM users WHERE user_id=?", (uid,))
        r = c.fetchone()
        if r and r[0] != today:
            c.execute("UPDATE users SET searches=0, last_reset=? WHERE user_id=?", (today, uid))
        conn.commit()
    u = get_user(uid)
    if u['s'] < 6: return True, 6 - u['s'], False
    return False, 0, False

def use_search(uid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET searches=searches+1 WHERE user_id=?", (uid,))
        conn.commit()

def add_premium(uid, days):
    u = get_user(uid)
    now = datetime.now()
    if u['p'] and u['pu']:
        try:
            cur = datetime.fromisoformat(u['pu'])
            if cur > now: now = cur
        except: pass
    new_until = (now + timedelta(days=days)).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET premium=1, premium_until=? WHERE user_id=?", (new_until, uid))
        conn.commit()

def remove_premium(uid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET premium=0, premium_until='' WHERE user_id=?", (uid,))
        conn.commit()

def all_users():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT user_id FROM users").fetchall()

def get_stats():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(searches),0), (SELECT COUNT(*) FROM users WHERE premium=1) FROM users")
        return c.fetchone()

# ========== ЗЕРКАЛА (упрощённо) ==========
def add_mirror(token, uname, creator):
    with sqlite3.connect(DB_PATH) as conn:
        try:
            conn.execute("INSERT INTO mirrors(bot_token,bot_username,created_by,created_at,is_active) VALUES(?,?,?,?,1)",
                        (token, uname, creator, datetime.now().isoformat()))
            conn.commit()
            return True
        except: return False

def get_mirrors():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT bot_token,bot_username FROM mirrors WHERE is_active=1").fetchall()

def del_mirror(token):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM mirrors WHERE bot_token=?", (token,))
        conn.commit()

# ========== CRYPTOBOT ==========
def create_invoice(uid, plan):
    try:
        price = PRICES[plan]
        resp = requests.post("https://pay.crypt.bot/api/createInvoice",
            headers={"Crypto-Pay-API-Token": CRYPTO_TOKEN},
            json={"asset":"USDT","amount":str(price['usdt']),
                  "description":f"Psycho Search Premium {price['days']}дн",
                  "payload":json.dumps({"user_id":uid,"plan":plan}),
                  "allow_comments":False,"allow_anonymous":False},
            timeout=10)
        if resp.status_code==200 and resp.json().get('ok'):
            inv = resp.json()['result']
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("INSERT INTO payments(user_id,invoice_id,amount,plan,created_at) VALUES(?,?,?,?,?)",
                           (uid, inv['invoice_id'], price['usdt'], plan, datetime.now().isoformat()))
                conn.commit()
            return inv['pay_url'], inv['invoice_id']
    except Exception as e: print(f"[CRYPTO] {e}")
    return None, None

def check_invoice(invoice_id):
    try:
        resp = requests.post("https://pay.crypt.bot/api/getInvoices",
            headers={"Crypto-Pay-API-Token": CRYPTO_TOKEN},
            json={"invoice_ids":invoice_id}, timeout=10)
        if resp.status_code==200 and resp.json().get('ok'):
            items = resp.json()['result']['items']
            if items and items[0]['status'] == 'paid':
                return True
    except: pass
    return False

# ========== DEPSEARCH API ==========
def search_api(q):
    try:
        r = requests.get(f"{API_URL}/quest={q}&token={API_KEY}&lang=ru", timeout=30)
        if r.status_code==200: return r.json()
    except: pass
    return None

def parse_data(d):
    if not d: return None
    ph,fi,nm,em,ad,ps,bd,lg,nk,vk,ip,src = [],[],[],[],[],[],[],[],[],[],[],[]
    pi = d.get('phone_info',{}); op = pi.get('operator',''); rg = pi.get('region','')
    ii = d.get('ip_info',{}); ic = ii.get('country',''); it = ii.get('city',''); ipr = ii.get('provider','')
    for i in d.get('results',[]):
        p = i.get('📞Телефон') or i.get('Телефон')
        if p and p!='None': ph.append(str(p))
        f = i.get('👤ФИО') or i.get('ФИО')
        if f: fi.append(str(f))
        n = i.get('👤Имя') or i.get('Имя')
        if n and n!='None': nm.append(str(n))
        e = i.get('✉️Почта') or i.get('Почта')
        if e and '@' in str(e): em.append(str(e))
        a = i.get('📍Адрес') or i.get('Адрес')
        if a and a!='None': ad.append(str(a))
        ps_ = i.get('🆔Паспорт') or i.get('Паспорт')
        if ps_: ps.append(str(ps_))
        b = i.get('🎂Дата рождения') or i.get('Дата рождения')
        if b and b!='None': bd.append(str(b))
        l = i.get('👤Логин') or i.get('Логин')
        if l: lg.append(str(l))
        nk_ = i.get('🔸Никнейм') or i.get('Никнейм')
        if nk_ and nk_!='None': nk.append(str(nk_))
        v = i.get('🪪Ид вк') or i.get('VK ID')
        if v: vk.append(str(v))
        ip_ = i.get('🌐IP-адрес') or i.get('IP')
        if ip_ and ip_!='None': ip.append(str(ip_))
        s = i.get('🏫Источник') or i.get('Источник')
        if s: src.append(str(s))
    def u(lst): s=set(); return [x for x in lst if x and x!='None' and not(x in s or s.add(x))]
    return {'op':op,'rg':rg,'ic':ic,'it':it,'ipr':ipr,'ph':u(ph),'fi':u(fi),'nm':u(nm),'em':u(em),'ad':u(ad),'ps':u(ps),'bd':u(bd),'lg':u(lg),'nk':u(nk),'vk':u(vk),'ip':u(ip),'src':u(src)}

def has_data(p):
    if not p: return False
    return any([p['ph'],p['fi'],p['em'],p['ad'],p['ps'],p['bd'],p['lg'],p['vk'],p['ip']])

def html_report(p,q):
    total = sum(len(v) for v in p.values() if isinstance(v,list))
    h = f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><title>Psycho Search — {q[:30]}</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0a0f;color:#c0c0c0;font-family:system-ui;padding:24px}}
.c{{max-width:960px;margin:0 auto;background:#0d0d14;border:1px solid #1a1a24;border-radius:16px;padding:28px}}
.hd{{text-align:center;padding:20px 0 24px;border-bottom:2px solid #1a0000;margin-bottom:24px}}
.logo{{font-size:32px;font-weight:900;background:linear-gradient(135deg,#8b0000,#cc0000);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.q{{color:#888;font-size:14px;margin-top:8px}}.st{{display:flex;justify-content:center;gap:16px;margin:20px 0}}
.sb{{background:#0f0f18;border:1px solid #1a1a24;border-radius:12px;padding:14px 22px;text-align:center}}
.sn{{font-size:30px;font-weight:800;color:#cc0000}}.stx{{font-size:10px;color:#666;text-transform:uppercase;letter-spacing:2px;margin-top:4px}}
.bl{{background:#0f0f18;border:1px solid #1a1a24;border-radius:12px;padding:14px;margin-bottom:10px}}
.bt{{font-size:13px;font-weight:700;color:#cc0000;margin-bottom:10px;padding-left:10px;border-left:3px solid #8b0000;text-transform:uppercase}}
.rw{{display:flex;padding:5px 0;border-bottom:1px solid #14141c}}.lb{{width:100px;color:#666;font-size:10px;font-weight:600;text-transform:uppercase;flex-shrink:0}}
.vl{{flex:1;color:#ccc;font-size:12px;word-break:break-all;font-family:monospace}}.tg{{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}}
.t{{background:#1a0000;color:#cc0000;padding:2px 10px;border-radius:12px;font-size:10px}}
.ft{{text-align:center;margin-top:20px;padding-top:14px;border-top:1px solid #1a1a24;color:#444;font-size:10px}}
</style></head><body><div class="c"><div class="hd"><div class="logo">Psycho Search</div><div class="q">{q[:60]}</div></div>
<div class="st"><div class="sb"><div class="sn">{total}</div><div class="stx">найдено</div></div></div>"""
    if p['op'] or p['rg']:
        h += '<div class="bl"><div class="bt">Оператор / Регион</div>'
        if p['op']: h += f'<div class="rw"><span class="lb">Оператор</span><span class="vl">{p["op"]}</span></div>'
        if p['rg']: h += f'<div class="rw"><span class="lb">Регион</span><span class="vl">{p["rg"]}</span></div>'
        h += '</div>'
    if p['ic']:
        h += '<div class="bl"><div class="bt">IP Информация</div>'
        if p['ic']: h += f'<div class="rw"><span class="lb">Страна</span><span class="vl">{p["ic"]}</span></div>'
        if p['it']: h += f'<div class="rw"><span class="lb">Город</span><span class="vl">{p["it"]}</span></div>'
        if p['ipr']: h += f'<div class="rw"><span class="lb">Провайдер</span><span class="vl">{p["ipr"]}</span></div>'
        h += '</div>'
    for title,key in [('Телефоны','ph'),('ФИО','fi'),('Имена','nm'),('Email','em'),('Адреса','ad'),('Паспорта','ps'),('Даты рождения','bd'),('Логины','lg'),('Никнеймы','nk'),('VK ID','vk'),('IP','ip')]:
        if p[key]:
            h += f'<div class="bl"><div class="bt">{title}</div>'
            for i in p[key][:15]: h += f'<div class="rw"><span class="lb">{title}</span><span class="vl">{i}</span></div>'
            h += '</div>'
    if p['src']:
        h += '<div class="bl"><div class="bt">Источники</div><div class="tg">'
        for s in p['src'][:20]: h += f'<span class="t">{s[:60]}</span>'
        h += '</div></div>'
    h += f'<div class="ft">Psycho Search · {datetime.now().strftime("%d.%m.%Y %H:%M")}</div></div></body></html>'
    return h

# ========== РАССЫЛКА ==========
def broadcast(text, sender_bot=None):
    users = all_users()
    total = 0
    bots = []
    if sender_bot: bots.append(sender_bot)
    for token, _ in get_mirrors():
        try: bots.append(telebot.TeleBot(token))
        except: pass
    for bot_inst in bots:
        for u in users:
            try:
                bot_inst.send_message(u[0], text)
                total += 1
            except: pass
            time.sleep(0.03)
    return total

# ========== КЛАВИАТУРЫ ==========
def main_menu(uid):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🔍 Поиск", callback_data="search"))
    kb.add(types.InlineKeyboardButton("👤 Профиль", callback_data="profile"))
    kb.add(types.InlineKeyboardButton("💎 Подписка", callback_data="subscription"))
    kb.add(types.InlineKeyboardButton("🪞 Зеркала", callback_data="mirrors"))
    kb.add(types.InlineKeyboardButton("❓ Поддержка", callback_data="support"))
    if uid in ADMINS:
        kb.add(types.InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin"))
    return kb

def admin_panel():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("📊 Статистика", callback_data="adm_stats"))
    kb.add(types.InlineKeyboardButton("💳 Выдать Premium", callback_data="adm_give_prem"))
    kb.add(types.InlineKeyboardButton("🚫 Забрать Premium", callback_data="adm_rem_prem"))
    kb.add(types.InlineKeyboardButton("🪞 Создать зеркало", callback_data="adm_add_mirror"))
    kb.add(types.InlineKeyboardButton("📋 Список зеркал", callback_data="adm_list_mirrors"))
    kb.add(types.InlineKeyboardButton("🗑 Удалить зеркало", callback_data="adm_del_mirror"))
    kb.add(types.InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu"))
    return kb

# ========== ЗЕРКАЛО (ПОЛНАЯ КОПИЯ) ==========
def run_mirror(token):
    def _run():
        while True:
            try:
                bot_m = telebot.TeleBot(token)
                
                @bot_m.message_handler(commands=['start'])
                def start_msg(m):
                    uid = m.from_user.id
                    add_user(uid, m.from_user.username or '', m.from_user.first_name or '')
                    bot_m.send_message(uid, "Psycho Search\n\nДобро пожаловать!\nВыберите действие:", reply_markup=main_menu(uid))
                
                @bot_m.message_handler(func=lambda m: True)
                def search_msg(m):
                    uid = m.from_user.id
                    q = m.text.strip()
                    if q.startswith('/'): return
                    can, rem, prem = can_search(uid)
                    if not can:
                        kb = types.InlineKeyboardMarkup()
                        kb.add(types.InlineKeyboardButton("💎 Купить Premium", callback_data="subscription"))
                        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu"))
                        bot_m.send_message(uid, "Лимит 6 запросов/день исчерпан.\nPremium — безлимит.", reply_markup=kb)
                        return
                    msg = bot_m.send_message(uid, "🔍 Поиск...")
                    d = search_api(q)
                    p = parse_data(d)
                    try: bot_m.delete_message(uid, msg.message_id)
                    except: pass
                    if d and has_data(p):
                        use_search(uid)
                        h = html_report(p, q)
                        fn = f"psycho_{hashlib.md5(q.encode()).hexdigest()[:8]}.html"
                        with open(fn, 'w', encoding='utf-8') as f: f.write(h)
                        with open(fn, 'rb') as f: bot_m.send_document(uid, f, caption=f"Запрос: {q[:50]}")
                        os.remove(fn)
                        kb = types.InlineKeyboardMarkup()
                        kb.add(types.InlineKeyboardButton("🔍 Новый поиск", callback_data="search"))
                        kb.add(types.InlineKeyboardButton("🔙 Меню", callback_data="menu"))
                        bot_m.send_message(uid, "Готово", reply_markup=kb)
                    else:
                        kb = types.InlineKeyboardMarkup()
                        kb.add(types.InlineKeyboardButton("🔄 Попробовать снова", callback_data="search"))
                        kb.add(types.InlineKeyboardButton("🔙 Меню", callback_data="menu"))
                        bot_m.send_message(uid, "Ничего не найдено", reply_markup=kb)
                
                @bot_m.callback_query_handler(func=lambda c: True)
                def callback_handler(call):
                    uid = call.from_user.id
                    try:
                        if call.data == "menu":
                            bot_m.edit_message_text("Psycho Search\n\nВыберите действие:", uid, call.message.message_id, reply_markup=main_menu(uid))
                        elif call.data == "search":
                            bot_m.edit_message_text("Введите данные для поиска:", uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu")))
                            bot_m.register_next_step_handler_by_chat_id(uid, lambda m: search_msg(m))
                        elif call.data == "profile":
                            u = get_user(uid)
                            prem_status = "✅ Активна" if (u['p'] and u['pu'] and datetime.fromisoformat(u['pu']) > datetime.now()) else "❌ Не активна"
                            bot_m.edit_message_text(f"👤 Профиль\n\nID: {uid}\nПоисков: {u['s']}/6\nPremium: {prem_status}", uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu")))
                        elif call.data == "subscription":
                            text = "💎 Подписка\n\n"
                            for k, v in PRICES.items():
                                text += f"• {v['days']} дн. — {v['usdt']} USDT\n"
                            text += "\nВыберите тариф для оплаты:"
                            kb = types.InlineKeyboardMarkup(row_width=2)
                            for k, v in PRICES.items():
                                kb.add(types.InlineKeyboardButton(f"{v['days']}дн - {v['usdt']}$", callback_data=f"buy_{k}"))
                            kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu"))
                            bot_m.edit_message_text(text, uid, call.message.message_id, reply_markup=kb)
                        elif call.data.startswith("buy_"):
                            plan = call.data[4:]
                            url, inv_id = create_invoice(uid, plan)
                            if url:
                                kb = types.InlineKeyboardMarkup()
                                kb.add(types.InlineKeyboardButton("💳 Оплатить", url=url))
                                kb.add(types.InlineKeyboardButton("✅ Проверить оплату", callback_data=f"check_{inv_id}"))
                                kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="subscription"))
                                bot_m.edit_message_text(f"Счёт создан!\nСумма: {PRICES[plan]['usdt']} USDT\n\nНажмите «Оплатить» и после оплаты — «Проверить оплату»", uid, call.message.message_id, reply_markup=kb)
                            else:
                                bot_m.answer_callback_query(call.id, "Ошибка создания счёта")
                        elif call.data.startswith("check_"):
                            inv_id = call.data[6:]
                            if check_invoice(inv_id):
                                with sqlite3.connect(DB_PATH) as conn:
                                    c = conn.cursor()
                                    c.execute("SELECT user_id, plan FROM payments WHERE invoice_id=?", (inv_id,))
                                    pay = c.fetchone()
                                    if pay and pay[0] == uid:
                                        c.execute("UPDATE payments SET status='paid', paid_at=? WHERE invoice_id=?", (datetime.now().isoformat(), inv_id))
                                        conn.commit()
                                        add_premium(uid, PRICES[pay[1]]['days'])
                                        bot_m.answer_callback_query(call.id, "Оплата прошла! Premium активирован!")
                                        bot_m.edit_message_text("✅ Premium активирован!", uid, call.message.message_id)
                                    else:
                                        bot_m.answer_callback_query(call.id, "Счёт не найден")
                            else:
                                bot_m.answer_callback_query(call.id, "Оплата ещё не прошла. Попробуйте позже.")
                        elif call.data == "mirrors":
                            mrs = get_mirrors()
                            text = "🪞 Зеркала:\n\n" + "\n".join([f"@{m[1]}" for m in mrs]) if mrs else "Нет активных зеркал"
                            bot_m.edit_message_text(text, uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu")))
                        elif call.data == "support":
                            bot_m.edit_message_text("❓ Поддержка\n\nПо всем вопросам: @give_id\nВладелец: @runet3", uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu")))
                        elif call.data == "admin" and uid in ADMINS:
                            bot_m.edit_message_text("⚙️ Админ-панель", uid, call.message.message_id, reply_markup=admin_panel())
                        elif call.data == "adm_stats":
                            t,s,p = get_stats()
                            bot_m.edit_message_text(f"📊 Статистика\n\nПользователей: {t or 0}\nПоисков: {s or 0}\nPremium: {p or 0}\nЗеркал: {len(get_mirrors())}", uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin")))
                        elif call.data == "adm_give_prem":
                            bot_m.edit_message_text("Введите ID пользователя и количество дней (макс 365):\nПример: 123456789 30", uid, call.message.message_id)
                            bot_m.register_next_step_handler(call.message, lambda m: (add_premium(int(m.text.split()[0]), min(int(m.text.split()[1]),365)), bot_m.send_message(m.chat.id, "✅ Premium выдан!")))
                        elif call.data == "adm_rem_prem":
                            bot_m.edit_message_text("Введите ID пользователя для снятия Premium:", uid, call.message.message_id)
                            bot_m.register_next_step_handler(call.message, lambda m: (remove_premium(int(m.text.strip())), bot_m.send_message(m.chat.id, "✅ Premium снят!")))
                        elif call.data == "adm_add_mirror":
                            bot_m.edit_message_text("Отправьте токен бота для создания зеркала:", uid, call.message.message_id)
                            bot_m.register_next_step_handler(call.message, add_mirror_handler)
                        elif call.data == "adm_list_mirrors":
                            mrs = get_mirrors()
                            text = "📋 Список зеркал:\n\n" + "\n".join([f"@{m[1]}" for m in mrs]) if mrs else "Нет зеркал"
                            bot_m.edit_message_text(text, uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin")))
                        elif call.data == "adm_del_mirror":
                            bot_m.edit_message_text("Отправьте токен зеркала для удаления:", uid, call.message.message_id)
                            bot_m.register_next_step_handler(call.message, lambda m: (del_mirror(m.text.strip()), bot_m.send_message(m.chat.id, "✅ Зеркало удалено!")))
                        elif call.data == "adm_broadcast":
                            bot_m.edit_message_text("Введите текст рассылки:", uid, call.message.message_id)
                            bot_m.register_next_step_handler(call.message, lambda m: bot_m.send_message(m.chat.id, f"✅ Рассылка завершена! Отправлено: {broadcast(m.text, bot_m)}"))
                    except Exception as e:
                        print(f"[MIRROR CB] {e}")
                
                def add_mirror_handler(m):
                    token = m.text.strip()
                    try:
                        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
                        if r.status_code==200 and r.json().get('ok'):
                            uname = r.json()['result']['username']
                            if add_mirror(token, uname, m.from_user.id):
                                run_mirror(token)
                                bot_m.send_message(m.chat.id, f"✅ Зеркало создано: @{uname}")
                            else:
                                bot_m.send_message(m.chat.id, "❌ Токен уже используется")
                        else:
                            bot_m.send_message(m.chat.id, "❌ Невалидный токен")
                    except:
                        bot_m.send_message(m.chat.id, "❌ Ошибка проверки токена")
                
                bot_m.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                print(f"[MIRROR FATAL] {e}")
                time.sleep(5)
    threading.Thread(target=_run, daemon=True).start()

def start_mirrors():
    for token, uname in get_mirrors():
        try:
            run_mirror(token)
            print(f"[MIRROR] Запущено: @{uname}")
        except Exception as e:
            print(f"[MIRROR] Ошибка запуска @{uname}: {e}")

# ========== ОСНОВНОЙ БОТ ==========
bot = telebot.TeleBot(MAIN_TOKEN)

@bot.message_handler(commands=['start'])
def start_cmd(m):
    uid = m.from_user.id
    add_user(uid, m.from_user.username or '', m.from_user.first_name or '')
    bot.send_message(uid, "Psycho Search\n\nДобро пожаловать в Psycho Search — бесплатный бот для поиска информации.\n\nВыберите действие в меню ниже:", reply_markup=main_menu(uid))

@bot.message_handler(func=lambda m: True)
def search_handler(m):
    uid = m.from_user.id
    q = m.text.strip()
    if q.startswith('/'): return
    can, rem, prem = can_search(uid)
    if not can:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💎 Купить Premium", callback_data="subscription"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu"))
        bot.send_message(uid, "Лимит 6 запросов/день исчерпан.\nPremium — безлимит.", reply_markup=kb)
        return
    msg = bot.send_message(uid, "🔍 Поиск...")
    d = search_api(q)
    p = parse_data(d)
    try: bot.delete_message(uid, msg.message_id)
    except: pass
    if d and has_data(p):
        use_search(uid)
        h = html_report(p, q)
        fn = f"psycho_{hashlib.md5(q.encode()).hexdigest()[:8]}.html"
        with open(fn, 'w', encoding='utf-8') as f: f.write(h)
        with open(fn, 'rb') as f: bot.send_document(uid, f, caption=f"Запрос: {q[:50]}")
        os.remove(fn)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔍 Новый поиск", callback_data="search"))
        kb.add(types.InlineKeyboardButton("🔙 Меню", callback_data="menu"))
        bot.send_message(uid, "Готово", reply_markup=kb)
    else:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Попробовать снова", callback_data="search"))
        kb.add(types.InlineKeyboardButton("🔙 Меню", callback_data="menu"))
        bot.send_message(uid, "Ничего не найдено", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: True)
def main_cb(call):
    uid = call.from_user.id
    try:
        if call.data == "menu":
            bot.edit_message_text("Psycho Search\n\nВыберите действие:", uid, call.message.message_id, reply_markup=main_menu(uid))
        elif call.data == "search":
            bot.edit_message_text("Введите данные для поиска:", uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu")))
            bot.register_next_step_handler_by_chat_id(uid, lambda m: search_handler(m))
        elif call.data == "profile":
            u = get_user(uid)
            prem_status = "✅ Активна" if (u['p'] and u['pu'] and datetime.fromisoformat(u['pu']) > datetime.now()) else "❌ Не активна"
            bot.edit_message_text(f"👤 Профиль\n\nID: {uid}\nПоисков: {u['s']}/6\nPremium: {prem_status}", uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu")))
        elif call.data == "subscription":
            text = "💎 Подписка\n\n"
            for k, v in PRICES.items():
                text += f"• {v['days']} дн. — {v['usdt']} USDT\n"
            text += "\nВыберите тариф для оплаты:"
            kb = types.InlineKeyboardMarkup(row_width=2)
            for k, v in PRICES.items():
                kb.add(types.InlineKeyboardButton(f"{v['days']}дн - {v['usdt']}$", callback_data=f"buy_{k}"))
            kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu"))
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=kb)
        elif call.data.startswith("buy_"):
            plan = call.data[4:]
            url, inv_id = create_invoice(uid, plan)
            if url:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("💳 Оплатить", url=url))
                kb.add(types.InlineKeyboardButton("✅ Проверить оплату", callback_data=f"check_{inv_id}"))
                kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="subscription"))
                bot.edit_message_text(f"Счёт создан!\nСумма: {PRICES[plan]['usdt']} USDT\n\nНажмите «Оплатить» и после оплаты — «Проверить оплату»", uid, call.message.message_id, reply_markup=kb)
            else:
                bot.answer_callback_query(call.id, "Ошибка создания счёта")
        elif call.data.startswith("check_"):
            inv_id = call.data[6:]
            if check_invoice(inv_id):
                with sqlite3.connect(DB_PATH) as conn:
                    c = conn.cursor()
                    c.execute("SELECT user_id, plan FROM payments WHERE invoice_id=?", (inv_id,))
                    pay = c.fetchone()
                    if pay and pay[0] == uid:
                        c.execute("UPDATE payments SET status='paid', paid_at=? WHERE invoice_id=?", (datetime.now().isoformat(), inv_id))
                        conn.commit()
                        add_premium(uid, PRICES[pay[1]]['days'])
                        bot.answer_callback_query(call.id, "Оплата прошла! Premium активирован!")
                        bot.edit_message_text("✅ Premium активирован!", uid, call.message.message_id)
                    else:
                        bot.answer_callback_query(call.id, "Счёт не найден")
            else:
                bot.answer_callback_query(call.id, "Оплата ещё не прошла. Попробуйте позже.")
        elif call.data == "mirrors":
            mrs = get_mirrors()
            text = "🪞 Зеркала:\n\n" + "\n".join([f"@{m[1]}" for m in mrs]) if mrs else "Нет активных зеркал"
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu")))
        elif call.data == "support":
            bot.edit_message_text("❓ Поддержка\n\nПо всем вопросам: @give_id\nВладелец: @runet3", uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="menu")))
        elif call.data == "admin" and uid in ADMINS:
            bot.edit_message_text("⚙️ Админ-панель", uid, call.message.message_id, reply_markup=admin_panel())
        elif call.data == "adm_stats":
            t,s,p = get_stats()
            bot.edit_message_text(f"📊 Статистика\n\nПользователей: {t or 0}\nПоисков: {s or 0}\nPremium: {p or 0}\nЗеркал: {len(get_mirrors())}", uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin")))
        elif call.data == "adm_give_prem":
            bot.edit_message_text("Введите ID пользователя и количество дней (макс 365):\nПример: 123456789 30", uid, call.message.message_id)
            bot.register_next_step_handler(call.message, lambda m: (add_premium(int(m.text.split()[0]), min(int(m.text.split()[1]),365)), bot.send_message(m.chat.id, "✅ Premium выдан!")))
        elif call.data == "adm_rem_prem":
            bot.edit_message_text("Введите ID пользователя для снятия Premium:", uid, call.message.message_id)
            bot.register_next_step_handler(call.message, lambda m: (remove_premium(int(m.text.strip())), bot.send_message(m.chat.id, "✅ Premium снят!")))
        elif call.data == "adm_add_mirror":
            bot.edit_message_text("Отправьте токен бота для создания зеркала:", uid, call.message.message_id)
            bot.register_next_step_handler(call.message, add_mirror_main)
        elif call.data == "adm_list_mirrors":
            mrs = get_mirrors()
            text = "📋 Список зеркал:\n\n" + "\n".join([f"@{m[1]}" for m in mrs]) if mrs else "Нет зеркал"
            bot.edit_message_text(text, uid, call.message.message_id, reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin")))
        elif call.data == "adm_del_mirror":
            bot.edit_message_text("Отправьте токен зеркала для удаления:", uid, call.message.message_id)
            bot.register_next_step_handler(call.message, lambda m: (del_mirror(m.text.strip()), bot.send_message(m.chat.id, "✅ Зеркало удалено!")))
        elif call.data == "adm_broadcast":
            bot.edit_message_text("Введите текст рассылки:", uid, call.message.message_id)
            bot.register_next_step_handler(call.message, lambda m: bot.send_message(m.chat.id, f"✅ Рассылка завершена! Отправлено: {broadcast(m.text, bot)}"))
    except Exception as e:
        print(f"[MAIN CB] {e}")

def add_mirror_main(m):
    token = m.text.strip()
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if r.status_code==200 and r.json().get('ok'):
            uname = r.json()['result']['username']
            if add_mirror(token, uname, m.from_user.id):
                run_mirror(token)
                bot.send_message(m.chat.id, f"✅ Зеркало создано: @{uname}")
            else:
                bot.send_message(m.chat.id, "❌ Токен уже используется")
        else:
            bot.send_message(m.chat.id, "❌ Невалидный токен")
    except:
        bot.send_message(m.chat.id, "❌ Ошибка проверки токена")

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("Psycho Search v18 – запуск...")
    if not init_db():
        print("Критическая ошибка: не удалось создать БД.")
        sys.exit(1)
    start_mirrors()
    print("Бот запущен. Ожидание сообщений...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"[MAIN FATAL] {e}")
            time.sleep(5)