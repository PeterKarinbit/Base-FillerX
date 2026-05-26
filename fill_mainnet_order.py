import os
import sys
import json
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

# Contract address
CONTRACT_ADDRESS = "0x84ED932B376a205aC34B007b0C09546573B6085E"

# Load LimitOrder ABI
try:
    with open("out/LimitOrder.sol/BaseLimitOrder.json") as f:
        contract_abi = json.load(f)["abi"]
except Exception as e:
    print(f"[ERROR] Failed to load contract ABI: {e}")
    sys.exit(1)

contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=contract_abi)

# Check order details before filling
try:
    order = contract.functions.getOrder(0).call()
    status_idx = order[10]
    status = ['Open', 'Filled', 'Cancelled'][status_idx]
    print(f"[ORDER 0] Status: {status}")
    if status_idx != 0:
        print("[WARNING] Order 0 is not in 'Open' status. Cannot fill.")
        sys.exit(0)
except Exception as e:
    print(f"[ERROR] Failed to fetch order 0 details: {e}")
    sys.exit(1)

# Step A: Call fillOrder(0) with a safe gas limit
print(f"\n[STEP A] Executing fillOrder(0) on Base Mainnet...")
nonce = w3.eth.get_transaction_count(owner_address)
print(f"[NONCE] Using Nonce: {nonce}")

tx = contract.functions.fillOrder(0).build_transaction({
    "from": owner_address,
    "gas": 500000, # Generous gas limit to prevent out of gas reverts
    "maxFeePerGas": w3.eth.gas_price,
    "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei"),
    "nonce": nonce,
    "chainId": 8453
})

signed_tx = w3.eth.account.sign_transaction(tx, private_key)
tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
print(f"[TX] Fill transaction sent: https://basescan.org/tx/{tx_hash.hex()}")
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

if receipt["status"] != 1:
    print("[ERROR] Fill transaction reverted!")
    sys.exit(1)

print(f"\n[CONGRATULATIONS] Limit order 0 has been successfully filled on Base Mainnet!")
print(f"[INFO] View the fill logs here: https://basescan.org/tx/{tx_hash.hex()}#eventlog")
