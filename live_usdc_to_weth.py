import os
import time
import json
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

# Setup Web3
RPC_URL = os.getenv("EXECUTION_RPC_URL")
w3 = Web3(Web3.HTTPProvider(RPC_URL))

if not w3.is_connected():
    print("[-] Failed to connect to Base Mainnet.")
    exit()

print("[+] Connected to Base Mainnet Alchemy RPC")

# Wallet
WALLET_ADDRESS = w3.to_checksum_address(os.getenv("MAINNET_ADDRESS"))
PRIVATE_KEY = os.getenv("MAINNET_PRIVATE_KEY")

# Contracts
CONTRACT_ADDRESS = w3.to_checksum_address("0x84ED932B376a205aC34B007b0C09546573B6085E")
USDC = w3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
WETH = w3.to_checksum_address("0x4200000000000000000000000000000000000006")
AERODROME_POOL = w3.to_checksum_address("0xcdac0d6c6c59727a65f871236188350531885c43")

# ABIs
usdc_abi = [
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
]

try:
    with open("abis/BaseLimitOrder.json", "r") as f:
        limit_abi = json.load(f)["abi"]
except:
    with open("out/LimitOrder.sol/BaseLimitOrder.json", "r") as f:
        limit_abi = json.load(f)["abi"]

usdc_contract = w3.eth.contract(address=USDC, abi=usdc_abi)
limit_contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=limit_abi)

amount_usdc = int(0.95 * 10**6) # 0.95 USDC

print(f"[*] Checking USDC Balance...")
balance = usdc_contract.functions.balanceOf(WALLET_ADDRESS).call()
if balance < amount_usdc:
    print(f"[-] Insufficient USDC. You have {balance/10**6} USDC.")
    exit()

print(f"[*] Checking allowance...")
allowance = usdc_contract.functions.allowance(WALLET_ADDRESS, CONTRACT_ADDRESS).call()

if allowance < amount_usdc:
    print(f"[*] Approving LimitOrder contract to spend 0.95 USDC...")
    tx_app = usdc_contract.functions.approve(CONTRACT_ADDRESS, amount_usdc).build_transaction({
        'from': WALLET_ADDRESS,
        'nonce': w3.eth.get_transaction_count(WALLET_ADDRESS, "pending"),
        'gas': 100000,
        'gasPrice': w3.eth.gas_price
    })
    signed_app = w3.eth.account.sign_transaction(tx_app, PRIVATE_KEY)
    tx_hash_app = w3.eth.send_raw_transaction(signed_app.raw_transaction)
    print(f"  [Tx Pending] https://basescan.org/tx/{tx_hash_app.hex()}")
    w3.eth.wait_for_transaction_receipt(tx_hash_app)
    print(f"  [Tx Confirmed] Approval successful!")
else:
    print(f"[*] Already approved. Skipping approval.")

# We want the bot to execute immediately to test it.
# If isBuyOrder=True, the bot executes if: spot_price <= triggerPrice
# So we just set triggerPrice artificially HIGH (e.g. 1,000,000 WETH per USDC)
# and minAmountOut artificially LOW (e.g. 1 wei of WETH)
print(f"[*] Placing Limit Order (Buy WETH with 0.95 USDC)...")
trigger_price = 99999999 * 10**18 # Guarantee execution
min_amount_out = 1 # 1 wei of WETH, just so it doesn't revert on slippage for our tiny test

tx_place = limit_contract.functions.placeOrder(
    USDC,
    WETH,
    amount_usdc,
    trigger_price,
    min_amount_out,
    int(time.time()) + 3600,
    AERODROME_POOL,
    True # isBuyOrder
).build_transaction({
    'from': WALLET_ADDRESS,
    'nonce': w3.eth.get_transaction_count(WALLET_ADDRESS, "pending"),
    'gas': 500000,
    'gasPrice': w3.eth.gas_price
})

signed_place = w3.eth.account.sign_transaction(tx_place, PRIVATE_KEY)
tx_hash_place = w3.eth.send_raw_transaction(signed_place.raw_transaction)
print(f"  [Tx Pending] https://basescan.org/tx/{tx_hash_place.hex()}")
receipt = w3.eth.wait_for_transaction_receipt(tx_hash_place)
print(f"  [Tx Confirmed] Order successfully placed on-chain!")

# Get Order ID
logs = limit_contract.events.OrderPlaced().process_receipt(receipt)
if logs:
    order_id = logs[0]['args']['orderId']
    print(f"[SUCCESS] Order #{order_id} is live!")
    print(f"[*] Now check your Render.com dashboard logs! The bot should pick this up in 15 seconds and execute it automatically.")
