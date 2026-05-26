from web3 import Web3

w3 = Web3(Web3.HTTPProvider('https://mainnet.base.org'))
tx_hash = '0x99b7c12e328d7cd46a1db91df1ae2a216ad0daa6383c963017b05d82cec0da81'

try:
    tx = w3.eth.get_transaction(tx_hash)
    w3.eth.call({
        'from': tx['from'],
        'to': tx['to'],
        'data': tx['input'],
        'value': tx['value'],
        'gas': tx['gas']
    }, tx['blockNumber'] - 1)
    print("No revert? That's strange.")
except Exception as e:
    print("Revert Reason:", e)
