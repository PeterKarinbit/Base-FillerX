import os, time, json, requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from web3 import Web3
from eth_account import Account

Account.enable_unaudited_hdwallet_features()
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RPC_URL = os.getenv("EXECUTION_RPC_URL", "https://mainnet.base.org")
w3 = Web3(Web3.HTTPProvider(RPC_URL))

CONTRACT_ADDRESS = "0x84ED932B376a205aC34B007b0C09546573B6085E"
WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
POOL = "0xcDAC0d6c6C59727a65F871236188350531885C43"

try:
    with open("abis/BaseLimitOrder.json") as f:
        abi_data = json.load(f)
except FileNotFoundError:
    with open("out/LimitOrder.sol/BaseLimitOrder.json") as f:
        abi_data = json.load(f)
ABI = abi_data["abi"] if "abi" in abi_data else abi_data
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=ABI)

WETH_ABI = [
    {"inputs":[],"name":"deposit","outputs":[],"stateMutability":"payable","type":"function"},
    {"inputs":[{"name":"guy","type":"address"},{"name":"wad","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
]
weth_contract = w3.eth.contract(address=WETH, abi=WETH_ABI)

user_wallets = {}
user_state = {}  # Track what each user is doing (for text input flows)

# ── Helpers ──────────────────────────────────────────────

def get_spot_price_usd():
    # MUST read from the blockchain AMM to ensure the UI matches execution exactly
    raw = contract.functions.getSpotPrice(POOL, WETH, USDC).call()
    return round(1 / (raw / 1e18), 2)

def get_user_orders(address):
    """Get all open orders belonging to this address"""
    try:
        open_ids = contract.functions.getOpenOrders().call()
        user_orders = []
        for oid in open_ids:
            order = contract.functions.getOrder(oid).call()
            if order[1].lower() == address.lower():
                user_orders.append(order)
        return user_orders
    except:
        return []

def fmt_addr(addr):
    return f"{addr[:6]}...{addr[-4:]}"

def send_raw(signed):
    """Compatible with both web3 v6 (rawTransaction) and v7 (raw_transaction)"""
    raw = getattr(signed, 'raw_transaction', None) or signed.rawTransaction
    return w3.eth.send_raw_transaction(raw)

# ── Keyboards ────────────────────────────────────────────

def kb_main(order_count=0):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎣 Buy the Dip", callback_data='buy'),
         InlineKeyboardButton("💰 Sell High", callback_data='sell')],
        [InlineKeyboardButton(f"⏳ Pending Orders ({order_count})", callback_data='orders'),
         InlineKeyboardButton("📤 Withdraw", callback_data='withdraw')],
        [InlineKeyboardButton("💳 Deposit", callback_data='deposit'),
         InlineKeyboardButton("🔄 Refresh", callback_data='refresh')],
    ])

def kb_buy_amount():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("0.01 ETH (~$20)", callback_data='ba_0.01'),
         InlineKeyboardButton("0.05 ETH (~$100)", callback_data='ba_0.05')],
        [InlineKeyboardButton("0.1 ETH (~$200)", callback_data='ba_0.1'),
         InlineKeyboardButton("0.5 ETH (~$1000)", callback_data='ba_0.5')],
        [InlineKeyboardButton("1.0 ETH (~$2000)", callback_data='ba_1.0'),
         InlineKeyboardButton("✏️ Custom", callback_data='ba_custom')],
        [InlineKeyboardButton("🔙 Back", callback_data='home')]
    ])

def kb_buy_target(amt, spot):
    d5 = round(spot * 0.95, 2)
    d10 = round(spot * 0.90, 2)
    d20 = round(spot * 0.80, 2)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🟢 At Current (${spot})", callback_data=f'exec_buy_{amt}_{spot}')],
        [InlineKeyboardButton(f"🟡 -5% (${d5})", callback_data=f'exec_buy_{amt}_{d5}')],
        [InlineKeyboardButton(f"🟠 -10% (${d10})", callback_data=f'exec_buy_{amt}_{d10}')],
        [InlineKeyboardButton(f"🔴 -20% (${d20})", callback_data=f'exec_buy_{amt}_{d20}')],
        [InlineKeyboardButton("✏️ Custom Target", callback_data=f'bt_custom_{amt}')],
        [InlineKeyboardButton("🔙 Back", callback_data='buy')]
    ])

def kb_sell_amount():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("0.01 ETH", callback_data='sa_0.01'),
         InlineKeyboardButton("0.05 ETH", callback_data='sa_0.05')],
        [InlineKeyboardButton("0.1 ETH", callback_data='sa_0.1'),
         InlineKeyboardButton("0.5 ETH", callback_data='sa_0.5')],
        [InlineKeyboardButton("🔙 Back", callback_data='home')]
    ])

def kb_sell_target(amt, spot):
    u5 = round(spot * 1.05, 2)
    u10 = round(spot * 1.10, 2)
    u20 = round(spot * 1.20, 2)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🟢 At Current (${spot})", callback_data=f'exec_sell_{amt}_{spot}')],
        [InlineKeyboardButton(f"🟡 +5% (${u5})", callback_data=f'exec_sell_{amt}_{u5}')],
        [InlineKeyboardButton(f"🟠 +10% (${u10})", callback_data=f'exec_sell_{amt}_{u10}')],
        [InlineKeyboardButton(f"🔴 +20% (${u20})", callback_data=f'exec_sell_{amt}_{u20}')],
        [InlineKeyboardButton("✏️ Custom Target", callback_data=f'st_custom_{amt}')],
        [InlineKeyboardButton("🔙 Back", callback_data='sell')]
    ])

def kb_back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data='home')]])

def kb_withdraw():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Withdraw 25%", callback_data='wd_25'),
         InlineKeyboardButton("📤 Withdraw 50%", callback_data='wd_50')],
        [InlineKeyboardButton("📤 Withdraw ALL", callback_data='wd_100')],
        [InlineKeyboardButton("🔙 Back", callback_data='home')]
    ])

# ── Core Messages ────────────────────────────────────────

async def send_home(update, context):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        acct = Account.create()
        user_wallets[user_id] = {"address": acct.address, "private_key": acct.key.hex()}
        # w3.provider.make_request("anvil_setBalance", [acct.address, hex(w3.to_wei(10, "ether"))])

    addr = user_wallets[user_id]["address"]
    bal = round(float(w3.from_wei(w3.eth.get_balance(addr), 'ether')), 4)
    orders = get_user_orders(addr)
    spot = get_spot_price_usd()

    msg = (
        f"🟢 *FillerX — MEV-Protected Trading*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 `{addr}`\n"
        f"💎 *Balance:* `{bal} ETH` (~${round(bal * spot, 2)})\n"
        f"📊 *ETH Price:* `${spot}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🛡️ *Why FillerX?*\n"
        f"• Zero MEV — bots can't sandwich you\n"
        f"• Set your price — buy the dip automatically\n"
        f"• Non-custodial — your keys, your coins\n"
        f"• Lowest fees on Base — only 0.25%\n"
    )

    try:
        if update.message:
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=kb_main(len(orders)))
        elif update.callback_query:
            if update.callback_query.message.photo:
                await update.callback_query.message.delete()
                await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='Markdown', reply_markup=kb_main(len(orders)))
            else:
                await update.callback_query.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_main(len(orders)))
    except Exception as e:
        if "not modified" in str(e).lower() and update.callback_query:
            await update.callback_query.answer("Already up to date ✅")

# ── /start with Onboarding ──────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_new = user_id not in user_wallets

    if is_new:
        acct = Account.create()
        user_wallets[user_id] = {"address": acct.address, "private_key": acct.key.hex()}
        # w3.provider.make_request("anvil_setBalance", [acct.address, hex(w3.to_wei(10, "ether"))])

        welcome = (
            f"👋 *Welcome to FillerX!*\n\n"
            f"FillerX is the *safest way to trade on Base*.\n\n"
            f"🛡️ *Here's what makes us different:*\n\n"
            f"1️⃣ *MEV Protection* — No bots can front-run or sandwich your trades. Ever.\n\n"
            f"2️⃣ *Set Your Price* — Don't chase pumps. Set your target price and we auto-execute when it hits.\n\n"
            f"3️⃣ *Lowest Fees* — Only 0.25% per trade. BasedBot charges 1%. Maestro charges 1%. We charge 0.25%.\n\n"
            f"4️⃣ *Non-Custodial* — Your funds sit in a smart contract, not our servers. Withdraw anytime.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 *Your new trading wallet:*\n"
            f"`{acct.address}`\n\n"
            f"Send ETH to this address to start trading!"
        )
        await update.message.reply_photo(photo=open('FillerX_logo.png', 'rb'), caption=welcome, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Let's Trade!", callback_data='home')]]))
    else:
        await send_home(update, context)

# ── Button Router ────────────────────────────────────────

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id

    # ── Navigation ──
    if data == 'home' or data == 'refresh':
        await send_home(update, context)

    # ── BUY FLOW ──
    elif data == 'buy':
        spot = get_spot_price_usd()
        msg = (f"🎣 *Buy the Dip*\n\n"
               f"Current ETH Price: *${spot}*\n\n"
               f"Pick how much ETH to spend.\n"
               f"Then set your target buy price.\n"
               f"We'll auto-execute when the price drops! 🎯")
        await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_buy_amount())

    elif data.startswith('ba_'):
        if data == 'ba_custom':
            user_state[uid] = 'awaiting_buy_amount'
            await q.edit_message_text("✏️ *Custom Amount*\n\nType the ETH amount you want to spend (e.g. `0.25`):", parse_mode='Markdown', reply_markup=kb_back())
            return
        amt = data[3:]
        spot = get_spot_price_usd()
        msg = f"🎣 *Buy the Dip*\n\nSpending: *{amt} ETH*\n\nWhen should we buy? Pick a target price:"
        await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_buy_target(amt, spot))

    elif data.startswith('exec_buy_'):
        parts = data.split('_')
        eth_amt = float(parts[2])
        target = float(parts[3])
        await execute_order(q, uid, eth_amt, target, is_buy=True)

    # ── SELL FLOW ──
    elif data == 'sell':
        spot = get_spot_price_usd()
        msg = (f"💰 *Sell High*\n\n"
               f"Current ETH Price: *${spot}*\n\n"
               f"Pick how much ETH to sell.\n"
               f"Then set your target sell price.\n"
               f"We'll auto-execute when the price pumps! 🚀")
        await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_sell_amount())

    elif data.startswith('sa_'):
        amt = data[3:]
        spot = get_spot_price_usd()
        msg = f"💰 *Sell High*\n\nSelling: *{amt} ETH*\n\nWhen should we sell? Pick a target price:"
        await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_sell_target(amt, spot))

    elif data.startswith('exec_sell_'):
        parts = data.split('_')
        eth_amt = float(parts[2])
        target = float(parts[3])
        await execute_order(q, uid, eth_amt, target, is_buy=False)

    elif data.startswith('bt_custom_'):
        amt = data.split('_')[2]
        user_state[uid] = f'awaiting_buy_target_{amt}'
        await q.edit_message_text("✏️ *Custom Target Price*\n\nType the exact price in USD you want to trigger this buy (e.g. `1950`):", parse_mode='Markdown', reply_markup=kb_back())

    elif data.startswith('st_custom_'):
        amt = data.split('_')[2]
        user_state[uid] = f'awaiting_sell_target_{amt}'
        await q.edit_message_text("✏️ *Custom Target Price*\n\nType the exact price in USD you want to trigger this sell (e.g. `2100`):", parse_mode='Markdown', reply_markup=kb_back())

    # ── ORDERS ──
    elif data == 'orders':
        addr = user_wallets[uid]["address"]
        orders = get_user_orders(addr)
        if not orders:
            msg = "⏳ *Pending Orders*\n\nYou have no active orders right now.\n\nUse 🎣 *Buy the Dip* or 💰 *Sell High* to place one!"
        else:
            msg = f"⏳ *Pending Orders ({len(orders)})*\n\n"
            for o in orders:
                oid = o[0]
                amt = round(o[4] / 1e18, 4)
                tp = round(1 / (o[5] / 1e18), 2) if o[5] > 0 else 0
                side = "BUY" if o[9] else "SELL"
                msg += f"#{oid} | {side} | {amt} ETH | Target: ${tp}\n"
        await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_back())

    # ── DEPOSIT ──
    elif data == 'deposit':
        addr = user_wallets[uid]["address"]
        msg = (f"💳 *Deposit Funds*\n\n"
               f"Send ETH (on Base network) to your trading wallet:\n\n"
               f"`{addr}`\n\n"
               f"⚡ Deposits appear instantly.\n"
               f"🔒 Only YOU can withdraw from this wallet.\n\n"
               f"_Tap the address above to copy it._")
        await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_back())

    # ── WITHDRAW ──
    elif data == 'withdraw':
        addr = user_wallets[uid]["address"]
        bal = round(float(w3.from_wei(w3.eth.get_balance(addr), 'ether')), 4)
        user_state[uid] = 'awaiting_withdraw_address'
        msg = (f"📤 *Withdraw Funds*\n\n"
               f"Available: *{bal} ETH*\n\n"
               f"First, type your destination wallet address below:")
        await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_back())

    elif data.startswith('wd_'):
        pct = int(data[3:])
        addr = user_wallets[uid]["address"]
        dest = user_state.get(f'{uid}_wd_dest')
        if not dest:
            await q.edit_message_text("❌ No destination set. Try again.", reply_markup=kb_back())
            return
        bal = w3.eth.get_balance(addr)
        gas_cost = 21000 * w3.eth.gas_price
        send_amt = int((bal - gas_cost) * pct / 100)
        if send_amt <= 0:
            await q.edit_message_text("❌ Insufficient balance for gas.", reply_markup=kb_back())
            return
        try:
            tx = {'to': w3.to_checksum_address(dest), 'value': send_amt, 'gas': 21000,
                  'gasPrice': w3.eth.gas_price, 'nonce': w3.eth.get_transaction_count(addr),
                  'chainId': w3.eth.chain_id}
            signed = w3.eth.account.sign_transaction(tx, user_wallets[uid]['private_key'])
            tx_hash = send_raw(signed)
            eth_sent = round(send_amt / 1e18, 4)
            msg = (f"✅ *Withdrawal Successful!*\n\n"
                   f"Sent: *{eth_sent} ETH*\n"
                   f"To: `{fmt_addr(dest)}`\n"
                   f"Tx: `...{tx_hash.hex()[-8:]}`")
            await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_back())
        except Exception as e:
            await q.edit_message_text(f"❌ *Withdrawal Failed*\n`{e}`", parse_mode='Markdown', reply_markup=kb_back())

# ── Order Execution ──────────────────────────────────────

async def execute_order(q, uid, eth_amt, target_price, is_buy):
    wallet = user_wallets[uid]
    addr, pk = wallet["address"], wallet["private_key"]
    side = "BUY" if is_buy else "SELL"

    await q.edit_message_text(f"⏳ *Placing {side} order...*\nWrapping → Approving → Submitting...", parse_mode='Markdown')

    try:
        amt_wei = w3.to_wei(eth_amt, "ether")
        trigger = int(1e18 / target_price * 1e18)

        # Wrap
        tx = weth_contract.functions.deposit().build_transaction({
            'from': addr, 'value': amt_wei, 'nonce': w3.eth.get_transaction_count(addr),
            'gas': 100000, 'gasPrice': w3.eth.gas_price})
        send_raw(w3.eth.account.sign_transaction(tx, pk))

        # Approve
        tx = weth_contract.functions.approve(CONTRACT_ADDRESS, amt_wei).build_transaction({
            'from': addr, 'nonce': w3.eth.get_transaction_count(addr),
            'gas': 100000, 'gasPrice': w3.eth.gas_price})
        send_raw(w3.eth.account.sign_transaction(tx, pk))

        # Place
        min_out = int((eth_amt * target_price) * 0.95 * 1e6)
        expiry = int(time.time()) + 86400
        tx = contract.functions.placeOrder(
            WETH, USDC, amt_wei, trigger, min_out, expiry, POOL, is_buy
        ).build_transaction({
            'from': addr, 'nonce': w3.eth.get_transaction_count(addr),
            'gas': 500000, 'gasPrice': w3.eth.gas_price})
        tx_hash = send_raw(w3.eth.account.sign_transaction(tx, pk))
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

        logs = contract.events.OrderPlaced().process_receipt(receipt)
        oid = logs[0]['args']['orderId']

        msg = (
            f"✅ *{side} Order #{oid} Placed!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Amount: `{eth_amt} ETH`\n"
            f"🎯 Target: `${target_price}`\n"
            f"🔗 Tx: `...{tx_hash.hex()[-8:]}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🤖 Our searcher network is watching 24/7.\n"
            f"You'll be notified when it fills!"
        )
        await q.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb_back())
    except Exception as e:
        await q.edit_message_text(f"❌ *{side} Order Failed*\n`{e}`", parse_mode='Markdown', reply_markup=kb_back())

# ── Text Input Handler ───────────────────────────────────

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_state.get(uid)

    if state == 'awaiting_withdraw_address':
        dest = update.message.text.strip()
        if not dest.startswith('0x') or len(dest) != 42:
            await update.message.reply_text("❌ Invalid address. Must be a 42-character hex address starting with 0x.")
            return
        user_state[f'{uid}_wd_dest'] = dest
        user_state[uid] = None
        addr = user_wallets[uid]["address"]
        bal = round(float(w3.from_wei(w3.eth.get_balance(addr), 'ether')), 4)
        msg = (f"📤 *Withdraw to:* `{fmt_addr(dest)}`\n\n"
               f"Available: *{bal} ETH*\n\n"
               f"How much do you want to withdraw?")
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=kb_withdraw())

    elif state == 'awaiting_buy_amount':
        try:
            amt = float(update.message.text.strip())
            user_state[uid] = None
            spot = get_spot_price_usd()
            msg = f"🎣 *Buy the Dip*\n\nSpending: *{amt} ETH*\n\nPick your target price:"
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=kb_buy_target(str(amt), spot))
        except ValueError:
            await update.message.reply_text("❌ Invalid number. Try again (e.g. `0.25`).", parse_mode='Markdown')

    elif state and state.startswith('awaiting_buy_target_'):
        try:
            target = float(update.message.text.strip())
            amt = float(state.split('_')[3])
            user_state[uid] = None
            msg = f"🎣 *Custom Buy Ready*\n\nAmount: `{amt} ETH`\nTarget: `${target}`"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Execute Buy", callback_data=f'exec_buy_{amt}_{target}')], [InlineKeyboardButton("🔙 Cancel", callback_data='buy')]])
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=kb)
        except ValueError:
            await update.message.reply_text("❌ Invalid price. Try again (e.g. `1950`).", parse_mode='Markdown')

    elif state and state.startswith('awaiting_sell_target_'):
        try:
            target = float(update.message.text.strip())
            amt = float(state.split('_')[3])
            user_state[uid] = None
            msg = f"💰 *Custom Sell Ready*\n\nAmount: `{amt} ETH`\nTarget: `${target}`"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Execute Sell", callback_data=f'exec_sell_{amt}_{target}')], [InlineKeyboardButton("🔙 Cancel", callback_data='sell')]])
            await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=kb)
        except ValueError:
            await update.message.reply_text("❌ Invalid price. Try again (e.g. `2100`).", parse_mode='Markdown')

# ── Main ─────────────────────────────────────────────────

if __name__ == '__main__':
    print("🟢 FillerX Telegram Bot starting...")
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()
