import os
import sys
import json
import time
from web3 import Web3
from dotenv import load_dotenv

# Load mainnet credentials
load_dotenv()
private_key = os.getenv("MAINNET_PRIVATE_KEY")
owner_address = os.getenv("MAINNET_ADDRESS")

if not private_key or not owner_address:
    print("[ERROR] Credentials not found in .env file!")
    sys.exit(1)

# Connect to Base Mainnet
w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))
if not w3.is_connected():
    print("[ERROR] Failed to connect to Base Mainnet!")
    sys.exit(1)

print(f"[CONNECTED] Connected to Base Mainnet.")
print(f"[ACCOUNT] Wallet: {owner_address}")

# Contract addresses
CONTRACT_ADDRESS = "0x84ED932B376a205aC34B007b0C09546573B6085E"
WETH_ADDRESS = "0x4200000000000000000000000000000000000006"
USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
POOL_ADDRESS = "0xcDAC0d6c6C59727a65F871236188350531885C43"

# Load LimitOrder ABI
try:
    with open("out/LimitOrder.sol/BaseLimitOrder.json") as f:
        contract_abi = json.load(f)["abi"]
except Exception as e:
    print(f"[ERROR] Failed to load contract ABI: {e}")
    sys.exit(1)

contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=contract_abi)

# Check WETH balance
weth_abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
weth = w3.eth.contract(address=WETH_ADDRESS, abi=weth_abi)
weth_balance = weth.functions.balanceOf(owner_address).call()

print(f"[BALANCES] WETH: {w3.from_wei(weth_balance, 'ether')} WETH")

# Step 3: Query current WETH/USDC spot price
spot_price = contract.functions.getSpotPrice(POOL_ADDRESS, WETH_ADDRESS, USDC_ADDRESS).call()
weth_price_usd = 1e18 / (spot_price / 1e18)
print(f"\n[PRICE] Current USDC Spot Price in WETH: {spot_price}")
print(f"[PRICE] Implied WETH Price: ${weth_price_usd:.2f} USDC")

# Set trigger price slightly ABOVE current spot price (+2%) to make it instantly fillable!
trigger_price = int(spot_price * 1.02)
print(f"[ORDER] Setting Trigger Price: {trigger_price} (Instantly fillable!)")

# Step 4: Place the limit order
wrap_amount = w3.to_wei(0.00045, "ether")
min_amount_out = int(0.90 * 1e6) # 0.90 USDC minimum floor (extremely safe)
expiry = int(time.time()) + 3600 # 1 hour expiry

print(f"\n[STEP 4] Submitting Limit Order to Base Mainnet...")
nonce = w3.eth.get_transaction_count(owner_address)
print(f"[NONCE] Using Nonce: {nonce}")

tx = contract.functions.placeOrder(
    WETH_ADDRESS,
    USDC_ADDRESS,
    wrap_amount,
    trigger_price,
    min_amount_out,
    expiry,
    POOL_ADDRESS,
    True # isBuyOrder = True
).build_transaction({
    "from": owner_address,
    "gas": 500000, # Increased from 250000 to 500000 to prevent out of gas error
    "maxFeePerGas": w3.eth.gas_price,
    "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei"),
    "nonce": nonce,
    "chainId": 8453
})

signed_tx = w3.eth.account.sign_transaction(tx, private_key)
tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
print(f"[TX] PlaceOrder transaction sent: https://basescan.org/tx/{tx_hash.hex()}")
w3.eth.wait_for_transaction_receipt(tx_hash)

print(f"\n[CONGRATULATIONS] Limit order successfully placed on Base Mainnet!")
print(f"[INFO] View your contract events here: https://basescan.org/address/{CONTRACT_ADDRESS}#events")
