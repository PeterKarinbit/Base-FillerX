import os
import sys
import json
import time
from web3 import Web3
from web3.middleware import geth_poa_middleware

# Connect to Public Base RPC for polling (saves money/rate limits)
READ_RPC_URL = os.getenv("RPC_URL", "https://mainnet.base.org")
w3_read = Web3(Web3.HTTPProvider(READ_RPC_URL))
w3_read.middleware_onion.inject(geth_poa_middleware, layer=0)

if not w3_read.is_connected():
    print("[ERROR] Failed to connect to Base Public RPC network!")
    sys.exit(1)

# Connect to Execution RPC for ultra-fast tx broadcasting (Alchemy/Infura)
EXECUTION_RPC_URL = os.getenv("EXECUTION_RPC_URL", READ_RPC_URL)
w3_write = Web3(Web3.HTTPProvider(EXECUTION_RPC_URL))
w3_write.middleware_onion.inject(geth_poa_middleware, layer=0)

# Contract Configurations
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "0x84ED932B376a205aC34B007b0C09546573B6085E")

# Load ABI
try:
    with open("abis/BaseLimitOrder.json") as f:
        contract_abi = json.load(f)
except Exception as e:
    print(f"[ERROR] Could not load ABI: {e}")
    sys.exit(1)

contract = w3_read.eth.contract(address=CONTRACT_ADDRESS, abi=contract_abi)

print(f"[ACTIVE] BaseLimitOrder Searcher is running...")
print(f"[READ RPC] Node: {READ_RPC_URL}")
print(f"[EXEC RPC] Node: {EXECUTION_RPC_URL}")
print(f"[CONTRACT] Address: {CONTRACT_ADDRESS}")

def check_and_fill_orders(private_key=None, executor_address=None):
    try:
        # Fetch all open orders
        open_order_ids = contract.functions.getOpenOrders().call()
        if not open_order_ids:
            print(f"[{time.strftime('%H:%M:%S')}] No open orders found in the contract.")
            return

        print(f"\n[{time.strftime('%H:%M:%S')}] Found {len(open_order_ids)} open orders. Checking fillability...")
        
        for order_id in open_order_ids:
            try:
                order = contract.functions.getOrder(order_id).call()
            except Exception as e:
                print(f"  [SKIP] Could not fetch Order {order_id}: {e}")
                continue
                
            owner = order[1]
            token_in = order[2]
            token_out = order[3]
            amount_in = order[4]
            trigger_price = order[5]
            pair_address = order[8]
            is_buy_order = order[9]

            # Query current spot price from the contract
            try:
                spot_price = contract.functions.getSpotPrice(pair_address, token_in, token_out).call()
            except Exception as e:
                print(f"  [SKIP] Order {order_id}: Could not query spot price ({e})")
                continue

            # Check if execution condition is met
            is_fillable = False
            if is_buy_order:
                # Buy orders execute if spot is lower than or equal to trigger price
                is_fillable = spot_price <= trigger_price
            else:
                # Sell orders execute if spot is greater than or equal to trigger price
                is_fillable = spot_price >= trigger_price

            print(f"  * Order {order_id} | Spot: {spot_price} | Trigger: {trigger_price} | Fillable: {is_fillable}")

            if is_fillable:
                print(f"  [PROFITABLE] Order {order_id} is ready to be filled!")
                
                # If credentials are provided, attempt to execute the fill
                if private_key and executor_address:
                    try:
                        print(f"  [EXECUTION] Submitting fill transaction for Order {order_id} via execution RPC...")
                        nonce = w3_write.eth.get_transaction_count(executor_address)
                        tx = contract.functions.fillOrder(order_id).build_transaction({
                            "from": executor_address,
                            "gas": 400000,
                            "maxFeePerGas": w3_write.eth.gas_price,
                            "maxPriorityFeePerGas": w3_write.to_wei(0.001, "gwei"),
                            "nonce": nonce,
                            "chainId": 8453
                        })
                        signed_tx = w3_write.eth.account.sign_transaction(tx, private_key)
                        tx_hash = w3_write.eth.send_raw_transaction(signed_tx.rawTransaction)
                        print(f"  [SUCCESS] Transaction broadcasted: https://basescan.org/tx/{tx_hash.hex()}")
                        w3_read.eth.wait_for_transaction_receipt(tx_hash)
                        print(f"  [CONFIRMED] Order {order_id} successfully executed!")
                    except Exception as e:
                        print(f"  [ERROR] Execution failed for Order {order_id}: {e}")

    except Exception as e:
        print(f"[ERROR] Loop iteration failed: {e}")

# If run directly as a daemon
if __name__ == "__main__":
    # --- DUMMY SERVER FOR RENDER ---
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class DummyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"BaseRadar Searcher Bot is running!")
    
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[SERVER] Dummy web server running on port {port}")
    # -------------------------------

    # Check if user passed credentials to actively execute fills
    pkey = os.getenv("SEARCHER_PRIVATE_KEY")
    addr = os.getenv("SEARCHER_ADDRESS")
    
    if pkey and addr:
        print(f"[MODE] Running in EXECUTION mode with address {addr}")
    else:
        print("[MODE] Running in MONITORING mode (Read-only). To execute fills, set SEARCHER_PRIVATE_KEY and SEARCHER_ADDRESS environment variables.")

    while True:
        check_and_fill_orders(pkey, addr)
        time.sleep(15)
