# BaseLimitOrder Searcher & Arbitrage Bot Guide

This repository contains the interface details and execution script for searchers to extract arbitrage profits by executing limit orders on the **BaseLimitOrder** protocol.

### Contract Address
*   **Base Mainnet:** `0x84ED932B376a205aC34B007b0C09546573B6085E`
*   **Aerodrome Factory:** `0x420DD381b31aEf6683db6B902084cB0FFECe40Da`

---

## How It Works for Searchers

The `BaseLimitOrder` contract allows users to lock ERC-20 tokens (e.g. WETH or USDC) and specify a target execution price. 
Anyone can execute these trades by calling `fillOrder(uint256 orderId)` when the spot price on **Aerodrome** crosses the user's `triggerPrice`.

### The Arbitrage Opportunity
1.  **Direct Execution:** When you call `fillOrder`, the contract performs an on-chain swap via Aerodrome. 
2.  **Price Discrepancy:** If the spot price on Aerodrome is better than the user's `triggerPrice`, the excess output tokens remain in the pool or can be captured via flash loans/backrunning swaps.
3.  **Clean Execution:** Since Base has a private FIFO sequencer, there are no frontrunning/sandwich risks for searchers. The first transaction to submit the fill gets the execution.

---

## Integration Details

### 1. Monitor Placed Orders
Listen to the `OrderPlaced` event log on Base Mainnet:
*   **Topic0 Hash:** `0x85753865c533b24a66ef5a7cdac46eb8e97d907e1e1a3ecbf1608b1a14ac86c1`
*   **Signature:** `OrderPlaced(indexed uint256 orderId, indexed address owner, address tokenIn, address tokenOut, uint256 amountIn, uint256 triggerPrice, uint256 minAmountOut, uint256 expiry, address pairAddress, bool isBuyOrder)`

### 2. Check Order Status
Call the read function:
```solidity
function getOrder(uint256 orderId) external view returns (
    uint256 id,
    address owner,
    address tokenIn,
    address tokenOut,
    uint256 amountIn,
    uint256 triggerPrice,
    uint256 minAmountOut,
    uint256 expiry,
    address pairAddress,
    bool isBuyOrder,
    OrderStatus status // 0 = Open, 1 = Filled, 2 = Cancelled
)
```

### 3. Check Fillability
Verify the execution condition:
*   **Buy Orders (`isBuyOrder == true`):** `spotPrice <= triggerPrice`
*   **Sell Orders (`isBuyOrder == false`):** `spotPrice >= triggerPrice`

Query the current spot price from the contract:
```solidity
function getSpotPrice(address pair, address tokenIn, address tokenOut) public view returns (uint256)
```

### 4. Execute the Fill
Call the public execution function:
```solidity
function fillOrder(uint256 orderId) external;
```

---

## Python Execution Template

```python
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://mainnet.base.org"))

CONTRACT_ADDRESS = "0x84ED932B376a205aC34B007b0C09546573B6085E"
ABI = [...] # Load verified ABI from BaseScan

contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=ABI)

def execute_fill(order_id, private_key, my_address):
    tx = contract.functions.fillOrder(order_id).build_transaction({
        "from": my_address,
        "gas": 400000,
        "maxFeePerGas": w3.eth.gas_price,
        "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei"),
        "nonce": w3.eth.get_transaction_count(my_address),
        "chainId": 8453
    })
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    print(f"Filled Order {order_id}! Tx: https://basescan.org/tx/{tx_hash.hex()}")

# Run in event loop...
```
