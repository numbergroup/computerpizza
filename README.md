# Computer Pizza

Order Domino's pizza and pay with USDC on Ethereum.

## Adding to an OpenClaw Bot

### 1. Clone the repo into your bot's skills directory

```sh
cd your-openclaw-bot/
git clone git@github.com:numbergroup/computerpizza.git skills/computerpizza
```

### 2. Install dependencies

```sh
pip install -r skills/computerpizza/requirements.txt
```

### 3. Register the skill

Add the following to your bot's `openclaw.yaml` (or equivalent config):

```yaml
skills:
  - name: computerpizza
    path: skills/computerpizza
    description: Order Domino's pizza paid with USDC on Ethereum mainnet
    tools:
      - name: menu
        description: >
          Fetch the Domino's menu for a delivery address.
          Returns a JSON object with storeId and an array of menu items.
        parameters:
          street: { type: string, required: true, description: "Delivery street address" }
          city: { type: string, required: true, description: "Delivery city" }
          state: { type: string, required: true, description: "2-letter state code" }
          zip: { type: string, required: true, description: "5-digit zip code" }
        command: python skills/computerpizza/pizza.py --street "{street}" --city "{city}" --state "{state}" --zip "{zip}" menu

      - name: order
        description: >
          Place a Domino's order and pay with USDC. Requires an Ethereum private key
          with sufficient USDC balance. Returns order confirmation JSON.
        parameters:
          street: { type: string, required: true }
          city: { type: string, required: true }
          state: { type: string, required: true }
          zip: { type: string, required: true }
          key: { type: string, required: true, description: "Ethereum private key (hex)" }
          rpc: { type: string, required: true, description: "Ethereum RPC URL" }
          name: { type: string, required: true, description: "Customer name" }
          phone: { type: string, required: true, description: "Customer phone" }
          email: { type: string, required: true, description: "Customer email" }
          items: { type: string, required: true, description: 'JSON array, e.g. [{"code":"14SCREEN","quantity":1}]' }
          store: { type: string, required: true, description: "Store ID from menu output" }
        command: >
          python skills/computerpizza/pizza.py
          --street "{street}" --city "{city}" --state "{state}" --zip "{zip}"
          --key "{key}" --rpc "{rpc}"
          --name "{name}" --phone "{phone}" --email "{email}"
          order --items '{items}' --store {store}

      - name: retry-order
        description: >
          Retry a failed order using an existing USDC transaction hash.
          Use this when payment succeeded but order placement failed.
        parameters:
          street: { type: string, required: true }
          city: { type: string, required: true }
          state: { type: string, required: true }
          zip: { type: string, required: true }
          key: { type: string, required: true }
          name: { type: string, required: true }
          phone: { type: string, required: true }
          email: { type: string, required: true }
          items: { type: string, required: true }
          store: { type: string, required: true }
          tx_hash: { type: string, required: true, description: "Existing USDC tx hash" }
        command: >
          python skills/computerpizza/pizza.py
          --street "{street}" --city "{city}" --state "{state}" --zip "{zip}"
          --key "{key}" --name "{name}" --phone "{phone}" --email "{email}"
          retry-order --tx-hash {tx_hash} --items '{items}' --store {store}
```

### 4. Set secrets

Store the Ethereum private key and RPC URL as bot secrets rather than hardcoding them. How you do this depends on your OpenClaw deployment:

**Environment variables:**
```sh
export COMPUTERPIZZA_ETH_KEY="0x..."
export COMPUTERPIZZA_ETH_RPC="https://eth.llamarpc.com"
```

Then reference them in your config:
```yaml
key: ${COMPUTERPIZZA_ETH_KEY}
rpc: ${COMPUTERPIZZA_ETH_RPC}
```

### 5. Bot workflow

The typical three-step flow for a bot:

1. **`menu`** — Fetch the store ID and available items for the user's address
2. **`order`** — Send USDC and place the order with selected items
3. **`retry-order`** — If step 2 fails after USDC was sent, retry with the same tx hash

All three commands produce JSON on stdout, making them easy to parse.

## Requirements

- Python 3
- An Ethereum wallet with USDC balance on mainnet
- An Ethereum RPC endpoint (e.g. `https://eth.llamarpc.com`)

## Full documentation

See [SKILL.md](SKILL.md) for the complete API reference, EIP-712 schema, on-chain details, and troubleshooting guide.
