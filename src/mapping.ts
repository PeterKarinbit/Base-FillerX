import { BigInt } from "@graphprotocol/graph-ts"
import {
  OrderPlaced,
  OrderFilled,
  OrderCancelled
} from "../generated/BaseLimitOrder/BaseLimitOrder"
import { Order, ProtocolStat } from "../generated/schema"

function getOrCreateProtocolStat(): ProtocolStat {
  let stats = ProtocolStat.load("1")
  if (stats == null) {
    stats = new ProtocolStat("1")
    stats.totalOrdersPlaced = BigInt.fromI32(0)
    stats.totalOrdersFilled = BigInt.fromI32(0)
    stats.totalOrdersCancelled = BigInt.fromI32(0)
  }
  return stats
}

export function handleOrderPlaced(event: OrderPlaced): void {
  let orderId = event.params.orderId.toString()
  let order = new Order(orderId)
  
  order.owner = event.params.owner
  order.tokenIn = event.params.tokenIn
  order.tokenOut = event.params.tokenOut
  order.amountIn = event.params.amountIn
  order.triggerPrice = event.params.triggerPrice
  order.minAmountOut = event.params.minAmountOut
  order.expiry = event.params.expiry
  order.pairAddress = event.params.pairAddress
  order.isBuyOrder = event.params.isBuyOrder
  order.status = "Open"
  order.createdAt = event.block.timestamp
  order.createdAtTx = event.transaction.hash
  
  order.save()

  let stats = getOrCreateProtocolStat()
  stats.totalOrdersPlaced = stats.totalOrdersPlaced.plus(BigInt.fromI32(1))
  stats.save()
}

export function handleOrderFilled(event: OrderFilled): void {
  let orderId = event.params.orderId.toString()
  let order = Order.load(orderId)
  if (order != null) {
    order.status = "Filled"
    order.filledAt = event.block.timestamp
    order.filledAtTx = event.transaction.hash
    order.feeTaken = event.params.feeTaken
    order.save()
  }

  let stats = getOrCreateProtocolStat()
  stats.totalOrdersFilled = stats.totalOrdersFilled.plus(BigInt.fromI32(1))
  stats.save()
}

export function handleOrderCancelled(event: OrderCancelled): void {
  let orderId = event.params.orderId.toString()
  let order = Order.load(orderId)
  if (order != null) {
    order.status = "Cancelled"
    order.cancelledAt = event.block.timestamp
    order.cancelledAtTx = event.transaction.hash
    order.save()
  }

  let stats = getOrCreateProtocolStat()
  stats.totalOrdersCancelled = stats.totalOrdersCancelled.plus(BigInt.fromI32(1))
  stats.save()
}
