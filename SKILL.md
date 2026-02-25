# Ether Pizza CLI

Order Domino's pizza paid with USDC on Ethereum mainnet.

## How It Works

```
CLI (pizza.py)              Backend (api.computerpizza.xyz)         Domino's
──────────────              ───────────────────────────────         ────────
     │                                   │                             │
     │  GET /config                      │                             │
     │──────────────────────────────────>│                             │
     │  { walletAddress, chainId,        │                             │
     │    usdcAddress }                  │                             │
     │<──────────────────────────────────│                             │
     │                                   │                             │
     │  POST /menu { address }           │  GraphQL BFF               │
     │──────────────────────────────────>│────────────────────────────>│
     │  { storeId, menu[] }              │  store + menu data          │
     │<──────────────────────────────────│<────────────────────────────│
     │                                   │                             │
     │  GET /price?items=...             │  price validation           │
     │──────────────────────────────────>│────────────────────────────>│
     │  { totalCents, usdcAmount, ... }  │                             │
     │<──────────────────────────────────│<────────────────────────────│
     │                                   │                             │
     │  USDC transfer on-chain ───> Ethereum mainnet                  │
     │  (ERC-20 transfer to payment wallet)                           │
     │                                   │                             │
     │  Sign EIP-712 PizzaOrder          │                             │
     │  (locally, with same key)         │                             │
     │                                   │                             │
     │  POST /order { txHash,            │  verify tx + signature      │
     │    signature, address,            │  solve reCAPTCHA             │
     │    items, customer info }         │  place order via BFF        │
     │──────────────────────────────────>│────────────────────────────>│
     │  { id, status,                    │  Domino's order ID          │
     │    dominosOrderId }               │                             │
     │<──────────────────────────────────│<────────────────────────────│
```

Three actors:
- **CLI (`pizza.py`)** — local Python script that drives the flow: fetches config, prices the order, sends USDC on-chain, signs an EIP-712 message, and POSTs to the backend.
- **Backend (`api.computerpizza.xyz`)** — verifies the USDC payment on-chain, validates the EIP-712 signature, solves Domino's reCAPTCHA, and places the order through the Domino's GraphQL BFF.
- **Domino's GraphQL BFF** — Domino's ordering API. The backend creates a cart, adds items, queries charges, and places the order.

## Setup

```sh
pip install -r requirements.txt
```

## Modes

### 1. Interactive (default)

Browse the menu, pick items, confirm, and pay — all in one session.

```sh
python pizza.py \
  --street "123 Main St" --city "Austin" --state "TX" --zip "78701" \
  --key 0xYOUR_PRIVATE_KEY --rpc https://eth.llamarpc.com \
  --name "John Doe" --phone "5551234567" --email "john@example.com"
```

### 2. `menu` — fetch menu as JSON

Returns the store ID and all menu items. Only needs an address.

```sh
python pizza.py \
  --street "123 Main St" --city "Austin" --state "TX" --zip "78701" \
  menu
```

Output:

```json
{
  "storeId": "4336",
  "items": [
    {"code": "14SCREEN", "name": "Large Hand Tossed Pizza", "category": "Pizza", "description": "..."},
    ...
  ]
}
```

### 3. `order` — place an order non-interactively

Pass items and store ID (from `menu` output) directly. No prompts, JSON output.

```sh
python pizza.py \
  --street "123 Main St" --city "Austin" --state "TX" --zip "78701" \
  --key 0xYOUR_PRIVATE_KEY --rpc https://eth.llamarpc.com \
  --name "John Doe" --phone "5551234567" --email "john@example.com" \
  order \
  --items '[{"code":"14SCREEN","quantity":1}]' \
  --store 4336
```

## Flags

```
python pizza.py [parent flags] <subcommand> [subcommand flags]
```

### Parent flags (before the subcommand)

| Flag | Required | Used by | Description |
|------|----------|---------|-------------|
| `--street` | yes | all | Delivery street address |
| `--city` | yes | all | Delivery city |
| `--state` | yes | all | 2-letter state code |
| `--zip` | yes | all | 5-digit zip code |
| `--key` | yes | interactive, order, retry-order | Ethereum private key (hex) |
| `--rpc` | yes | interactive, order | Ethereum RPC URL |
| `--name` | yes | interactive, order, retry-order | Customer name for delivery |
| `--phone` | yes | interactive, order, retry-order | Customer phone number |
| `--email` | yes | interactive, order, retry-order | Customer email |
| `--api` | no | all | Backend URL (default: `https://api.computerpizza.xyz`) |

### Subcommand-specific flags (after the subcommand keyword)

| Flag | Subcommand | Required | Description |
|------|------------|----------|-------------|
| `--items` | order, retry-order | yes | JSON array of `{"code", "quantity"}` objects |
| `--store` | order, retry-order | yes | Store ID from `menu` output |
| `--tx-hash` | retry-order | yes | Existing USDC transaction hash to retry |

## Typical bot workflow

```
1.  menu         →  get storeId + item codes
2.  order        →  pass storeId, items, wallet, and customer info
3.  retry-order  →  if step 2 failed but USDC was already sent
```

## Backend API Reference

Base URL: `https://api.computerpizza.xyz`

### `GET /config`

Returns the payment wallet address and chain configuration.

**Response:**

```json
{
  "walletAddress": "0xA872806C1BEc97E0FaBa4825c9B9271Ef1392A35",
  "chainId": 1,
  "usdcAddress": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
}
```

### `POST /menu`

Returns the nearest store ID and menu items for a delivery address.

**Request body:**

```json
{
  "street": "420 Honky Tonk Ln",
  "city": "Nashville",
  "state": "TN",
  "zip": "00000"
}
```

**Response:**

```json
{
  "storeId": "5420",
  "menu": [
    {"code": "S_PIZUH", "name": "Honolulu Hawaiian", "category": "Pizza", "description": "...", "price": "19.99"},
    ...
  ]
}
```

### `GET /price`

Prices an order (items + delivery address). Returns the total in cents, USD, and USDC raw units (6 decimals).

**Query parameters:**

| Param | Description |
|-------|-------------|
| `street` | Delivery street |
| `city` | Delivery city |
| `state` | 2-letter state |
| `zip` | 5-digit zip |
| `items` | JSON-encoded array of `{"code","quantity"}` |
| `storeId` | (optional) Store ID |

**Response:**

```json
{
  "storeId": "5420",
  "totalCents": 2851,
  "totalUsd": "28.51",
  "usdcAmount": "28510000",
  "breakdown": {
    "total": 28.51,
    "details": [
      {"name": "Food and beverage", "value": 19.99},
      {"name": "Delivery Fee", "value": 5.99},
      {"name": "Tax", "value": 2.53}
    ]
  }
}
```

### `POST /order`

The main order placement endpoint. Verifies the USDC payment on-chain, validates the EIP-712 signature, solves reCAPTCHA, and places the order with Domino's.

**Request body:**

```json
{
  "txHash": "0x63c1...42e4",
  "signature": "0xabc...def",
  "deliveryAddress": {
    "street": "420 Honky Tonk Ln",
    "city": "Nashville",
    "state": "TN",
    "zip": "00000"
  },
  "customerName": "Pizza Guy",
  "customerPhone": "666666666666",
  "customerEmail": "email@example.com",
  "items": [{"code": "S_PIZUH", "quantity": 1}],
  "storeId": "6969"
}
```

**Success response (200):**

```json
{
  "id": "8dad4d3b-e734-4d25-a359-c910e88e9eac",
  "status": "ordered",
  "dominosOrderId": "qhMa3XiPoqSWVHyCXavN",
  "estimatedWait": "unknown"
}
```

**Error responses:**

| Status | Meaning | Example |
|--------|---------|---------|
| 402 | Insufficient USDC payment — amount sent was less than order total | `{"error": "insufficient payment"}` |
| 403 | Signature does not match — wrong private key or tx hash mismatch | `{"error": "invalid signature length"}` |
| 409 | Transaction already used — this tx hash was already used for a completed order | `{"error": "transaction already used"}` |
| 500 | Internal server error — reCAPTCHA browser failure, Domino's API error, etc. | `{"error": "Unknown error"}` |

### `GET /order/:id`

Look up an order by its ID.

**Response:** Same shape as the `POST /order` success response.

### `GET /orders`

List orders placed by a wallet. Requires an `x-signature` header for authentication.

**Headers:**

| Header | Description |
|--------|-------------|
| `x-signature` | EIP-712 signature proving wallet ownership |

## On-Chain Payment Details

| Field | Value |
|-------|-------|
| Chain | Ethereum mainnet (chainId `1`) |
| USDC contract | `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` |
| Payment wallet | `0xA872806C1BEc97E0FaBa4825c9B9271Ef1392A35` |
| USDC decimals | 6 (so `$28.51` = `28510000` raw units) |

The CLI sends a standard ERC-20 `transfer(to, amount)` to the payment wallet. After the transaction is confirmed, it signs an EIP-712 typed data message binding the tx hash to the order details.

### EIP-712 Schema

**Domain:**

```json
{
  "name": "EtherPizza",
  "version": "1",
  "chainId": 1
}
```

**Types:**

```
PizzaOrder {
  bytes32  txHash
  DeliveryAddress deliveryAddress
  string   customerName
  string   customerPhone
  string   customerEmail
  OrderItem[] items
}

DeliveryAddress {
  string street
  string city
  string state
  string zip
}

OrderItem {
  string  code
  uint256 quantity
}
```

The signer must be the same address that sent the USDC transfer. The backend recovers the signer from the EIP-712 signature and verifies it matches the `from` address of the USDC transaction.

## Troubleshooting

### "500 Internal Server Error" on `/order`

The backend places the order through a headless browser (Puppeteer) to solve Domino's reCAPTCHA. Common causes:
- Chromium failed to launch (container missing deps, crashpad errors)
- reCAPTCHA script didn't load in time
- Domino's API returned an unexpected error

If USDC was already sent, use `retry-order` with the existing tx hash once the issue is resolved. Your USDC is safe — it can be retried.

### "Insufficient USDC payment" (402)

The USDC amount sent on-chain was less than the order total returned by `/price`. This can happen if the price changed between the `/price` call and the `/order` call. Re-run the full `order` flow to get a fresh price.

### "Signature does not match" / "invalid signature length" (403)

- Wrong private key: the key used to sign EIP-712 doesn't match the key that sent the USDC transaction
- Malformed signature: the `--key` flag value is not a valid hex private key

### "Transaction already used" (409)

The tx hash has already been used for a successfully completed order. Each USDC transaction can only be used once. If the original order failed and you want to retry, use `retry-order` — but only if the original order status is not `"ordered"`.

### USDC sent but order failed

This is the most common failure mode. The USDC transfer succeeded on-chain but the backend `/order` call returned an error (usually 500).

1. Note the tx hash from the CLI output (e.g. `USDC tx sent: 63c13574...`)
2. Wait for the backend issue to be resolved (or check if it's transient)
3. Re-run with `retry-order`:

```sh
python pizza.py \
  --street "..." --city "..." --state "..." --zip "..." \
  --key 0x... --name "..." --phone "..." --email "..." \
  retry-order \
  --tx-hash 0x63c13574022a1f73eac0efa4fd03464dbc8c27c5c931c2bac3a54cea67fc42e4 \
  --items '[{"code":"S_PIZUH","quantity":1}]' \
  --store 5420
```
