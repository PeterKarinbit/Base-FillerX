import os
import time
import json
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

# Setup Web3
RPC_URL = os.getenv("EXECUTION_RPC_URL")
w3 = Web3(Web3.HTTPProvider(RPC_URL))

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
erc20_abi = [
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
]

with open("abis/BaseLimitOrder.json", "r") as f:
    data = json.load(f)
    limit_abi = data if isinstance(data, list) else data["abi"]

weth_contract = w3.eth.contract(address=WETH, abi=erc20_abi)
limit_contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=limit_abi)

# Check WETH balance we just received
amount_weth = weth_contract.functions.balanceOf(WALLET_ADDRESS).call()
if amount_weth == 0:
    print("[-] You don't have any WETH. The previous order might not have transferred it yet, or you don't have balance.")
    exit()

print(f"[*] Found {w3.from_wei(amount_weth, 'ether')} WETH to sell for USDC.")

# Check Allowance
allowance = weth_contract.functions.allowance(WALLET_ADDRESS, CONTRACT_ADDRESS).call()
if allowance < amount_weth:
    print(f"[*] Approving LimitOrder contract to spend WETH...")
    tx_app = weth_contract.functions.approve(CONTRACT_ADDRESS, amount_weth).build_transaction({
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
    print(f"[*] Already approved.")

# We want the bot to execute immediately to test speed.
# isBuyOrder = False (Sell WETH for USDC)
# Condition in bot: spot_price >= triggerPrice
# We set triggerPrice = 1 wei so it's guaranteed to be greater.
print(f"[*] Placing Limit Order (Sell WETH for USDC)...")
trigger_price = 1 # 1 wei (Guarantees execution)
min_amount_out = 1 # 1 wei of USDC

start_time = time.time()

tx_place = limit_contract.functions.placeOrder(
    WETH,               # tokenIn
    USDC,               # tokenOut
    amount_weth,        # amountIn
    trigger_price,      # triggerPrice
    min_amount_out,     # minAmountOut
    int(time.time()) + 3600,
    AERODROME_POOL,
    False               # isBuyOrder (SELL)
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

logs = limit_contract.events.OrderPlaced().process_receipt(receipt)
if logs:
    order_id = logs[0]['args']['orderId']
    print(f"\n[SUCCESS] Order #{order_id} is live! START THE TIMER! ⏱️")
    print(f"  --> Sent at: {time.strftime('%H:%M:%S', time.localtime(start_time))}")
    print(f"[*] Watch Render logs and Basescan to see how fast it fills!")
