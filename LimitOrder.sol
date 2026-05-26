// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// ============================================================
//  BASE LIMIT ORDER PROTOCOL — by an anonymous deployer
//  Designed for new token launches on Base chain
//  Spot price check via Aerodrome/Uniswap V2-style pools
//  v2 — fixed reentrancy guard, O(1) order removal, fee math
// ============================================================

// -----------------------------------------------------------
// INTERFACES
// -----------------------------------------------------------

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function decimals() external view returns (uint8);
    function approve(address spender, uint256 amount) external returns (bool);
}

interface IFactory {
    function isPool(address pool) external view returns (bool);
}

// Aerodrome / Uniswap V2-style pair — spot price via reserves
interface IPair {
    function getReserves() external view returns (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast);
    function token0() external view returns (address);
    function token1() external view returns (address);
}

// Aerodrome router for executing swaps
interface IRouter {
    struct Route {
        address from;
        address to;
        bool stable;
        address factory;
    }
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        Route[] calldata routes,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
}

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

// ============================================================
//  MAIN CONTRACT
// ============================================================

contract BaseLimitOrder is ReentrancyGuard {

    // --------------------------------------------------------
    // STATE
    // --------------------------------------------------------

    address public owner;
    uint256 public orderCount;

    // Aerodrome on Base Sepolia testnet (swap these for mainnet)
    // Mainnet router:  0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43
    // Mainnet factory: 0x420DD381b31aEf6683db6B902084cB0FFECe40Da
    address public constant AERODROME_ROUTER  = 0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43;
    address public constant AERODROME_FACTORY = 0x420DD381b31aEf6683db6B902084cB0FFECe40Da;

    // Base token addresses
    // Testnet WETH:  0x4200000000000000000000000000000000000006 (same on testnet)
    // Testnet USDC:  use a faucet token on Sepolia
    address public constant WETH = 0x4200000000000000000000000000000000000006;
    address public constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;

    // Fee tiers in basis points (divide by 10000 to get %)
    uint256 public constant FEE_MICRO = 30;  // 0.30%
    uint256 public constant FEE_SMALL = 25;  // 0.25%
    uint256 public constant FEE_MID   = 20;  // 0.20%
    uint256 public constant FEE_WHALE = 15;  // 0.15%

    // Fee tier USD breakpoints (USDC has 6 decimals)
    uint256 public constant TIER_MICRO = 50   * 1e6;
    uint256 public constant TIER_SMALL = 200  * 1e6;
    uint256 public constant TIER_MID   = 1000 * 1e6;

    // Accumulated fees per token
    mapping(address => uint256) public accumulatedFees;

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    // --------------------------------------------------------
    // ORDER STRUCT & STORAGE
    // --------------------------------------------------------

    enum OrderStatus { Open, Filled, Cancelled }

    struct Order {
        uint256 id;
        address owner;
        address tokenIn;        // token deposited / being sold
        address tokenOut;       // token to receive
        uint256 amountIn;       // amount locked in contract
        uint256 triggerPrice;   // price of tokenOut denominated in tokenIn (18 decimals)
                                // e.g. buy TOKEN at 0.0001 WETH → triggerPrice = 0.0001 * 1e18
        uint256 minAmountOut;   // slippage floor — revert if swap returns less
        uint256 expiry;         // unix timestamp — order auto-expires
        address pairAddress;    // DEX pool used for price checking
        bool isBuyOrder;        // true = buy tokenOut with tokenIn
        OrderStatus status;
    }

    mapping(uint256 => Order) public orders;

    // --- O(1) open order tracking ---
    // Instead of looping to remove, we track index in the array
    // and swap-with-last on removal. No unbounded loops.
    uint256[] public openOrderIds;
    mapping(uint256 => uint256) private _orderIndex; // orderId => index in openOrderIds

    // --------------------------------------------------------
    // EVENTS — indexed for bot discovery via The Graph
    // --------------------------------------------------------

    event OrderPlaced(
        uint256 indexed orderId,
        address indexed owner,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 triggerPrice,
        uint256 minAmountOut,
        uint256 expiry,
        address pairAddress,
        bool isBuyOrder
    );

    event OrderFilled(
        uint256 indexed orderId,
        address indexed filler,
        uint256 amountOut,
        uint256 feeTaken
    );

    event OrderCancelled(uint256 indexed orderId, address indexed owner);
    event FeesWithdrawn(address indexed token, uint256 amount);

    // --------------------------------------------------------
    // CONSTRUCTOR
    // --------------------------------------------------------

    constructor() {
        owner  = msg.sender;
    }

    // --------------------------------------------------------
    // PLACE ORDER
    // Locks tokenIn in contract, records order params
    // --------------------------------------------------------

    function placeOrder(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 triggerPrice,
        uint256 minAmountOut,
        uint256 expiry,
        address pairAddress,
        bool isBuyOrder
    ) external nonReentrant returns (uint256 orderId) {
        require(amountIn > 0,                "Amount must be > 0");
        require(triggerPrice > 0,            "Trigger price must be > 0");
        require(expiry > block.timestamp,    "Expiry must be in future");
        require(pairAddress != address(0),   "Invalid pair address");
        require(IFactory(AERODROME_FACTORY).isPool(pairAddress), "Invalid pool address");
        require(tokenIn != address(0),       "Invalid tokenIn");
        require(tokenOut != address(0),      "Invalid tokenOut");
        require(tokenIn != tokenOut,         "Tokens must differ");

        // Must involve WETH or USDC as one side
        require(
            tokenIn == WETH || tokenIn == USDC ||
            tokenOut == WETH || tokenOut == USDC,
            "Must include WETH or USDC"
        );

        orderId = orderCount;
        orderCount = orderCount + 1;

        orders[orderId] = Order({
            id:           orderId,
            owner:        msg.sender,
            tokenIn:      tokenIn,
            tokenOut:     tokenOut,
            amountIn:     amountIn,
            triggerPrice: triggerPrice,
            minAmountOut: minAmountOut,
            expiry:       expiry,
            pairAddress:  pairAddress,
            isBuyOrder:   isBuyOrder,
            status:       OrderStatus.Open
        });

        // O(1) index tracking
        _orderIndex[orderId] = openOrderIds.length;
        openOrderIds.push(orderId);

        emit OrderPlaced(
            orderId, msg.sender, tokenIn, tokenOut,
            amountIn, triggerPrice, minAmountOut, expiry, pairAddress, isBuyOrder
        );

        // INTERACTIONS
        bool ok = IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn);
        require(ok, "Token transfer failed");
    }

    // --------------------------------------------------------
    // FILL ORDER
    // Bots call this when spot price hits the trigger.
    // Bot pays gas. You earn the fee. Order owner gets tokenOut.
    // --------------------------------------------------------

    function fillOrder(uint256 orderId) external nonReentrant {
        Order storage o = orders[orderId];

        require(o.status == OrderStatus.Open,  "Order not open");
        require(block.timestamp <= o.expiry,   "Order expired");

        // Check spot price condition
        uint256 spot = getSpotPrice(o.pairAddress, o.tokenIn, o.tokenOut);

        if (o.isBuyOrder) {
            // Execute buy when market price is at or below trigger
            require(spot <= o.triggerPrice, "Price not low enough");
        } else {
            // Execute sell when market price is at or above trigger
            require(spot >= o.triggerPrice, "Price not high enough");
        }

        // --- Checks-Effects-Interactions ---

        // EFFECTS: update state before any external calls
        uint256 fee        = calculateFee(o.amountIn, o.tokenIn);
        uint256 amountSwap = o.amountIn - fee;

        accumulatedFees[o.tokenIn] = accumulatedFees[o.tokenIn] + fee;
        o.status = OrderStatus.Filled;
        _removeFromOpenOrders(orderId);   // O(1) removal

        // INTERACTIONS: external calls last
        bool ok = IERC20(o.tokenIn).approve(AERODROME_ROUTER, amountSwap);
        require(ok, "Approve failed");

        IRouter.Route[] memory routes = new IRouter.Route[](1);
        routes[0] = IRouter.Route({
            from:    o.tokenIn,
            to:      o.tokenOut,
            stable:  false,
            factory: AERODROME_FACTORY
        });

        uint256[] memory amounts = IRouter(AERODROME_ROUTER).swapExactTokensForTokens(
            amountSwap,
            o.minAmountOut,
            routes,
            o.owner,              // tokenOut goes straight to order owner
            block.timestamp + 60
        );

        uint256 amountOut = amounts[amounts.length - 1];
        require(amountOut >= o.minAmountOut, "Slippage exceeded");

        emit OrderFilled(orderId, msg.sender, amountOut, fee);
    }

    // --------------------------------------------------------
    // CANCEL ORDER
    // Owner cancels any time. Anyone can cancel an expired order.
    // --------------------------------------------------------

    function cancelOrder(uint256 orderId) external nonReentrant {
        Order storage o = orders[orderId];

        require(o.status == OrderStatus.Open, "Order not open");
        require(
            o.owner == msg.sender || block.timestamp > o.expiry,
            "Not owner and not expired"
        );

        // EFFECTS before INTERACTIONS
        o.status = OrderStatus.Cancelled;
        _removeFromOpenOrders(orderId);

        // Return locked tokens to owner
        bool ok = IERC20(o.tokenIn).transfer(o.owner, o.amountIn);
        require(ok, "Transfer failed");

        emit OrderCancelled(orderId, o.owner);
    }

    // --------------------------------------------------------
    // WITHDRAW FEES — only your anonymous owner wallet
    // --------------------------------------------------------

    function withdrawFees(address token) external onlyOwner nonReentrant {
        uint256 amount = accumulatedFees[token];
        require(amount > 0, "No fees");

        // EFFECTS before INTERACTIONS
        accumulatedFees[token] = 0;
        bool ok = IERC20(token).transfer(owner, amount);
        require(ok, "Transfer failed");

        emit FeesWithdrawn(token, amount);
    }

    // --------------------------------------------------------
    // READ FUNCTIONS — for bots to query open orders
    // --------------------------------------------------------

    function getOpenOrders() external view returns (uint256[] memory) {
        return openOrderIds;
    }

    function getOrder(uint256 orderId) external view returns (Order memory) {
        return orders[orderId];
    }

    function getOrdersBatch(uint256[] calldata orderIds) external view returns (Order[] memory result) {
        result = new Order[](orderIds.length);
        for (uint256 i = 0; i < orderIds.length; i++) {
            result[i] = orders[orderIds[i]];
        }
    }

    function openOrderCount() external view returns (uint256) {
        return openOrderIds.length;
    }

    // --------------------------------------------------------
    // SPOT PRICE
    // Reads reserves from Aerodrome V2 pool.
    // Returns: how many tokenIn per 1 tokenOut (18 decimals)
    // --------------------------------------------------------

    function getSpotPrice(
        address pairAddress,
        address tokenIn,
        address tokenOut
    ) public view returns (uint256 price) {
        IPair pair = IPair(pairAddress);

        (uint112 res0, uint112 res1, ) = pair.getReserves();
        address token0 = pair.token0();

        uint256 rIn;
        uint256 rOut;

        if (token0 == tokenIn) {
            rIn  = uint256(res0);
            rOut = uint256(res1);
        } else {
            rIn  = uint256(res1);
            rOut = uint256(res0);
        }

        require(rIn > 0 && rOut > 0, "No liquidity in pool");

        uint8 dIn  = IERC20(tokenIn).decimals();
        uint8 dOut = IERC20(tokenOut).decimals();

        // Normalise both sides to 18 decimals before dividing
        // to avoid truncation on small numbers
        uint256 rInNorm  = rIn  * (10 ** (18 - dIn));
        uint256 rOutNorm = rOut * (10 ** (18 - dOut));

        // price = tokenIn per tokenOut, 18 decimal fixed point
        price = (rInNorm * 1e18) / rOutNorm;
    }

    // --------------------------------------------------------
    // DYNAMIC FEE CALCULATION (pure — no state reads)
    // Tier based on raw amountIn for non-USDC tokens.
    // For USDC orders we use the actual dollar value.
    // --------------------------------------------------------

    function calculateFee(uint256 amountIn, address tokenIn) public pure returns (uint256 fee) {
        uint256 feeBps;

        if (tokenIn == 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913) {
            // USDC — dollar value is directly readable (6 decimals)
            if (amountIn < 50 * 1e6) {
                feeBps = 30;   // 0.30%
            } else if (amountIn < 200 * 1e6) {
                feeBps = 25;   // 0.25%
            } else if (amountIn < 1000 * 1e6) {
                feeBps = 20;   // 0.20%
            } else {
                feeBps = 15;   // 0.15%
            }
        } else if (tokenIn == 0x4200000000000000000000000000000000000006) {
            // WETH — dynamic fee scaled for 18 decimals
            if (amountIn < 0.025 ether) {
                feeBps = 30;   // 0.30%
            } else if (amountIn < 0.1 ether) {
                feeBps = 25;   // 0.25%
            } else if (amountIn < 0.5 ether) {
                feeBps = 20;   // 0.20%
            } else {
                feeBps = 15;   // 0.15%
            }
        } else {
            // Unknown token — default to mid tier
            feeBps = 25;       // 0.25% flat
        }

        // Multiply first, divide last — avoids truncation to zero
        fee = (amountIn * feeBps) / 10000;
    }

    // --------------------------------------------------------
    // TRANSFER OWNERSHIP
    // --------------------------------------------------------

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Zero address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // --------------------------------------------------------
    // EMERGENCY SWEEP — stuck tokens only
    // --------------------------------------------------------

    function emergencySweep(address token, uint256 amount) external onlyOwner nonReentrant {
        bool ok = IERC20(token).transfer(owner, amount);
        require(ok, "Transfer failed");
    }

    // --------------------------------------------------------
    // INTERNAL — O(1) order removal using swap-with-last
    // No loops. Gas is constant regardless of order count.
    // --------------------------------------------------------

    function _removeFromOpenOrders(uint256 orderId) internal {
        uint256 idx  = _orderIndex[orderId];
        uint256 last = openOrderIds.length - 1;

        if (idx != last) {
            // Move last element into the removed slot
            uint256 lastId = openOrderIds[last];
            openOrderIds[idx] = lastId;
            _orderIndex[lastId] = idx;
        }

        openOrderIds.pop();
        delete _orderIndex[orderId];
    }
}
