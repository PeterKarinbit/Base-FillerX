# BaseRadar Limit Protocol

**The first decentralized, zero-slippage limit order protocol natively built for the Base L2 ecosystem.**

BaseRadar allows traders to set exact entry and exit prices on any Aerodrome liquidity pool without constantly monitoring charts or falling victim to massive slippage and frontrunning bots. 

Instead of fighting MEV bots, BaseRadar turns them into your employees. A decentralized network of searchers monitors your order 24/7 and races to execute it the exact second your price target is met.

### Base Mainnet Contract:
`0x84ED932B376a205aC34B007b0C09546573B6085E`

---

## 🚀 For Traders: How to Place an Order

Right now, you can interact directly with the verified smart contract on BaseScan.

1. **Approve Tokens:** 
   Go to the token contract you want to sell (e.g., WETH) and call the standard ERC-20 `approve` function. 
   - `spender`: `0x84ED932B376a205aC34B007b0C09546573B6085E`
   - `amount`: The amount of tokens you want to sell (in WEI).

2. **Place Your Order:**
   Go to the [BaseRadar Contract on BaseScan](https://basescan.org/address/0x84ED932B376a205aC34B007b0C09546573B6085E#writeContract) and call the `placeOrder` function with the following parameters:
   - `tokenIn`: The token you are selling.
   - `tokenOut`: The token you want to receive.
   - `amountIn`: How much of `tokenIn` you are selling.
   - `minAmountOut`: The absolute minimum amount of `tokenOut` you will accept (this sets your exact limit price).
   - `pairAddress`: The official Aerodrome Liquidity Pool address for this pair.
   - `isBuyOrder`: `true` if buying an asset, `false` if taking profits.

3. **Walk Away:**
   Your funds are safely escrowed in the audited smart contract. If your limit price is never reached, your order never executes. You can call `cancelOrder` at any time to instantly retrieve your funds.

---

## 🤖 For MEV Bots: How to Fill Orders and Earn

BaseRadar relies on decentralized Keepers/Searchers to execute profitable limit orders. If you run the `searcher.py` bot, you can passively earn arbitrage and gas spreads by executing users' trades when market conditions are met.

### Running the Searcher Bot Locally

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment Variables:**
   Create a `.env` file in the root directory:
   ```env
   SEARCHER_PRIVATE_KEY=your_wallet_private_key
   SEARCHER_ADDRESS=your_wallet_address
   EXECUTION_RPC_URL=https://base-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY
   ```
   *(Note: The bot uses the free public Base RPC for scanning and switches to your high-speed Alchemy RPC only for execution).*

3. **Start the Bot:**
   ```bash
   python searcher.py
   ```
   The bot will now continuously scan the BaseRadar contract for open orders and execute them the second they cross the spot price.

### Deploying the Bot to Render.com (24/7 Execution)

To keep your bot running forever without keeping your laptop open:
1. Push this repository to your GitHub account.
2. Log into [Render.com](https://render.com) and create a new **Background Worker**.
3. Connect your GitHub repository.
4. Set the Start Command to: `python searcher.py`
5. Add your `.env` variables into Render's "Environment Variables" section.
6. Click Deploy! 

---

## 🔒 Security & Trust
* **Non-Custodial:** BaseRadar never holds access to your private keys.
* **Audited Escrow:** Built with standard OpenZeppelin ReentrancyGuards.
* **Shadow Pool Protection:** Orders only execute if the provided pool is a verified Aerodrome Factory pool.
* **Pay-on-Execution:** Placing and canceling orders is free. A dynamic execution fee (0.15% - 0.30%) is only applied when the network successfully fills your order.
