#!/usr/bin/env python3
"""
Ether Pizza CLI — Browse Domino's menu and pay with USDC on Ethereum mainnet.

Usage:
    # Interactive mode (default)
    python pizza.py --street "123 Main St" --city "Austin" --state "TX" --zip "78701" \
        --key 0xabc... --rpc https://eth.llamarpc.com \
        --name "John Doe" --phone "5551234567" --email "john@example.com"

    # Menu subcommand (JSON output)
    python pizza.py menu --street "123 Main St" --city "Austin" --state "TX" --zip "78701"

    # Order subcommand (non-interactive, JSON output)
    python pizza.py order --street "123 Main St" --city "Austin" --state "TX" --zip "78701" \
        --key 0xabc... --rpc https://eth.llamarpc.com \
        --name "John Doe" --phone "5551234567" --email "john@example.com" \
        --items '[{"code":"14SCREEN","quantity":1}]' --store 4336
"""

import argparse
import json
import sys

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

USDC_ABI = [
    {
        "name": "transfer",
        "type": "function",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    }
]

EIP712_DOMAIN = {"name": "EtherPizza", "version": "1", "chainId": 1}

EIP712_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
    ],
    "PizzaOrder": [
        {"name": "txHash", "type": "bytes32"},
        {"name": "deliveryAddress", "type": "DeliveryAddress"},
        {"name": "customerName", "type": "string"},
        {"name": "customerPhone", "type": "string"},
        {"name": "customerEmail", "type": "string"},
        {"name": "items", "type": "OrderItem[]"},
    ],
    "DeliveryAddress": [
        {"name": "street", "type": "string"},
        {"name": "city", "type": "string"},
        {"name": "state", "type": "string"},
        {"name": "zip", "type": "string"},
    ],
    "OrderItem": [
        {"name": "code", "type": "string"},
        {"name": "quantity", "type": "uint256"},
    ],
}

# Categories worth showing from the Domino's menu
MENU_CATEGORIES = {"Pizza", "Sandwich", "Pasta", "Wings", "Bread", "Salad", "Dessert", "Drinks"}


def parse_args():
    parser = argparse.ArgumentParser(description="Order Domino's pizza, paid with USDC on Ethereum.")

    # Shared address flags on the parent parser
    parser.add_argument("--street", required=True, help="Delivery street address")
    parser.add_argument("--city", required=True, help="Delivery city")
    parser.add_argument("--state", required=True, help="Delivery state (2-letter)")
    parser.add_argument("--zip", required=True, help="Delivery zip code (5-digit)")
    parser.add_argument("--api", default="https://api.computerpizza.xyz", help="Backend API base URL")

    # Optional flags used by interactive mode and order subcommand
    parser.add_argument("--key", help="Ethereum private key (hex)")
    parser.add_argument("--rpc", help="Ethereum RPC URL")
    parser.add_argument("--name", help="Customer name for delivery")
    parser.add_argument("--phone", help="Customer phone number")
    parser.add_argument("--email", help="Customer email")

    subparsers = parser.add_subparsers(dest="command")

    # menu subcommand
    subparsers.add_parser("menu", help="Fetch menu and output JSON")

    # order subcommand
    order_parser = subparsers.add_parser("order", help="Place an order non-interactively (JSON output)")
    order_parser.add_argument("--items", required=True, help='JSON array of items, e.g. \'[{"code":"14SCREEN","quantity":1}]\'')
    order_parser.add_argument("--store", required=True, help="Store ID (from menu output)")

    # retry-order subcommand
    retry_parser = subparsers.add_parser("retry-order", help="Retry a failed order using an existing tx hash (JSON output)")
    retry_parser.add_argument("--tx-hash", required=True, help="Existing USDC tx hash to retry")
    retry_parser.add_argument("--items", required=True, help='JSON array of items, e.g. \'[{"code":"14SCREEN","quantity":1}]\'')
    retry_parser.add_argument("--store", required=True, help="Store ID")

    return parser.parse_args()


def fetch_config(api_base):
    resp = requests.get(f"{api_base}/config")
    resp.raise_for_status()
    return resp.json()


def fetch_menu(api_base, address):
    resp = requests.post(f"{api_base}/menu", json=address)
    resp.raise_for_status()
    return resp.json()


def extract_menu_items(menu_data):
    """Parse menu data into a list of (code, name, description, category) tuples."""
    menu = menu_data.get("menu", [])

    # New format: flat list of {code, name, category, description, price}
    if isinstance(menu, list):
        items = []
        for item in menu:
            code = item.get("code", "")
            name = item.get("name", code)
            desc = item.get("description", "")
            price = item.get("price", "")
            cat = item.get("category", "Menu")
            if price:
                desc = f"${price}" + (f" - {desc}" if desc else "")
            items.append((code, name, desc, cat))
        return items

    # Legacy format: nested menu.categories / menu.products dicts
    categories = menu.get("categories", {}) if isinstance(menu, dict) else {}
    products = menu.get("products", {}) if isinstance(menu, dict) else {}

    items = []

    for cat_key, cat_val in sorted(categories.items()):
        cat_name = cat_val.get("name", cat_key) if isinstance(cat_val, dict) else cat_key

        show = False
        for wanted in MENU_CATEGORIES:
            if wanted.lower() in cat_name.lower():
                show = True
                break
        if not show:
            continue

        product_codes = cat_val.get("products", []) if isinstance(cat_val, dict) else []
        if not product_codes:
            continue

        for code in product_codes:
            product = products.get(code, {})
            name = product.get("name", code)
            desc = product.get("description", "")
            items.append((code, name, desc, cat_name))

    if not items:
        # Fallback: list all products
        for code, product in sorted(products.items()):
            if isinstance(product, dict):
                name = product.get("name", code)
                desc = product.get("description", "")
                items.append((code, name, desc, "Menu"))

    return items


def display_menu(menu_items):
    """Print menu items as a numbered list grouped by category. Returns the same list."""
    current_cat = None
    for idx, (code, name, desc, cat) in enumerate(menu_items, 1):
        if cat != current_cat:
            current_cat = cat
            print(f"\n  === {cat} ===")
        desc_str = f" - {desc}" if desc else ""
        print(f"  {idx:3d}. [{code}] {name}{desc_str}")
    return menu_items


def select_items(menu_items):
    """Interactive prompt for selecting items and quantities."""
    selected = []
    print("\nEnter item number and quantity (e.g. '3 2' for 2x item #3).")
    print("Type 'done' when finished.\n")

    while True:
        try:
            line = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if line.lower() == "done":
            break

        if not line:
            continue

        parts = line.split()
        try:
            item_num = int(parts[0])
            qty = int(parts[1]) if len(parts) > 1 else 1
        except (ValueError, IndexError):
            print("    Invalid input. Enter item number [quantity], or 'done'.")
            continue

        if item_num < 1 or item_num > len(menu_items):
            print(f"    Item number must be between 1 and {len(menu_items)}.")
            continue

        if qty < 1:
            print("    Quantity must be at least 1.")
            continue

        code, name, _, _ = menu_items[item_num - 1]
        selected.append({"code": code, "quantity": qty})
        print(f"    Added: {name} x{qty}")

    if not selected:
        print("No items selected. Exiting.")
        sys.exit(0)

    # Merge duplicates
    merged = {}
    for item in selected:
        code = item["code"]
        merged[code] = merged.get(code, 0) + item["quantity"]

    return [{"code": c, "quantity": q} for c, q in merged.items()]


def fetch_price(api_base, address, items, store_id=None):
    params = {
        "street": address["street"],
        "city": address["city"],
        "state": address["state"],
        "zip": address["zip"],
        "items": json.dumps(items),
    }
    if store_id:
        params["storeId"] = store_id
    resp = requests.get(f"{api_base}/price", params=params)
    resp.raise_for_status()
    return resp.json()


def send_usdc(w3, account, usdc_address, to_address, amount_raw):
    """Send USDC ERC-20 transfer and wait for receipt."""
    usdc = w3.eth.contract(address=Web3.to_checksum_address(usdc_address), abi=USDC_ABI)
    nonce = w3.eth.get_transaction_count(account.address)

    priority_fee = w3.to_wei(1, "gwei")
    base_fee = w3.eth.gas_price
    max_fee = max(base_fee * 2, priority_fee + base_fee)

    tx = usdc.functions.transfer(
        Web3.to_checksum_address(to_address),
        int(amount_raw),
    ).build_transaction({
        "from": account.address,
        "nonce": nonce,
        "gas": 100_000,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority_fee,
        "chainId": 1,
    })

    signed = w3.eth.account.sign_transaction(tx, account.key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  USDC tx sent: {tx_hash.hex()}")
    print("  Waiting for confirmation...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    if receipt.status != 1:
        print("  Transaction failed on-chain!")
        sys.exit(1)
    print(f"  Confirmed in block {receipt.blockNumber}")
    return tx_hash.hex()


def sign_order(private_key, tx_hash_hex, address, customer_name, customer_phone, customer_email, items):
    """Sign the PizzaOrder EIP-712 typed data."""
    # Ensure tx_hash is bytes32
    tx_hash_bytes = bytes.fromhex(tx_hash_hex.replace("0x", ""))

    message = {
        "txHash": tx_hash_bytes,
        "deliveryAddress": address,
        "customerName": customer_name,
        "customerPhone": customer_phone,
        "customerEmail": customer_email,
        "items": [{"code": i["code"], "quantity": i["quantity"]} for i in items],
    }

    signable = encode_typed_data(
        domain_data=EIP712_DOMAIN,
        message_types={k: v for k, v in EIP712_TYPES.items() if k != "EIP712Domain"},
        message_data=message,
    )

    signed = Account.sign_message(signable, private_key)
    return signed.signature.hex()


def place_order(api_base, tx_hash, signature, address, customer_name, customer_phone, customer_email, items, store_id=None):
    body = {
        "txHash": tx_hash if tx_hash.startswith("0x") else f"0x{tx_hash}",
        "signature": signature if signature.startswith("0x") else f"0x{signature}",
        "deliveryAddress": address,
        "customerName": customer_name,
        "customerPhone": customer_phone,
        "customerEmail": customer_email,
        "items": items,
    }
    if store_id:
        body["storeId"] = store_id
    resp = requests.post(f"{api_base}/order", json=body)
    resp.raise_for_status()
    return resp.json()


def cmd_menu(args):
    """Menu subcommand: fetch menu and print JSON to stdout."""
    address = {
        "street": args.street,
        "city": args.city,
        "state": args.state,
        "zip": args.zip,
    }

    menu_data = fetch_menu(args.api, address)
    store_id = menu_data.get("storeId", "")
    menu_items = extract_menu_items(menu_data)

    output = {
        "storeId": store_id,
        "items": [
            {"code": code, "name": name, "category": cat, "description": desc}
            for code, name, desc, cat in menu_items
        ],
    }
    print(json.dumps(output))


def cmd_order(args):
    """Order subcommand: non-interactive order with JSON output."""
    # Validate required flags
    for flag in ("key", "rpc", "name", "phone", "email"):
        if not getattr(args, flag, None):
            print(json.dumps({"error": f"--{flag} is required for the order subcommand"}))
            sys.exit(1)

    private_key = args.key if args.key.startswith("0x") else f"0x{args.key}"
    acct = Account.from_key(private_key)

    address = {
        "street": args.street,
        "city": args.city,
        "state": args.state,
        "zip": args.zip,
    }

    items = json.loads(args.items)
    store_id = args.store

    # 1. Fetch config
    config = fetch_config(args.api)
    wallet_address = config["walletAddress"]
    usdc_address = config["usdcAddress"]

    # 2. Price the order
    price = fetch_price(args.api, address, items, store_id=store_id)
    usdc_amount = price["usdcAmount"]

    # 3. Send USDC
    w3 = Web3(Web3.HTTPProvider(args.rpc))
    if not w3.is_connected():
        print(json.dumps({"error": "Failed to connect to Ethereum RPC"}))
        sys.exit(1)

    tx_hash = send_usdc(w3, acct, usdc_address, wallet_address, int(usdc_amount))

    # 4. Sign EIP-712
    signature = sign_order(
        private_key, tx_hash, address,
        args.name, args.phone, args.email, items,
    )

    # 5. Place order
    result = place_order(
        args.api, tx_hash, signature, address,
        args.name, args.phone, args.email, items,
        store_id=store_id,
    )

    # 6. Output JSON
    print(json.dumps(result))


def cmd_retry_order(args):
    """Retry-order subcommand: re-submit a failed order with an existing tx hash."""
    for flag in ("key", "name", "phone", "email"):
        if not getattr(args, flag, None):
            print(json.dumps({"error": f"--{flag} is required for the retry-order subcommand"}))
            sys.exit(1)

    private_key = args.key if args.key.startswith("0x") else f"0x{args.key}"
    acct = Account.from_key(private_key)

    address = {
        "street": args.street,
        "city": args.city,
        "state": args.state,
        "zip": args.zip,
    }

    items = json.loads(args.items)
    store_id = args.store
    tx_hash = args.tx_hash if args.tx_hash.startswith("0x") else f"0x{args.tx_hash}"

    # Sign EIP-712 with the existing tx hash
    signature = sign_order(
        private_key, tx_hash, address,
        args.name, args.phone, args.email, items,
    )

    # Place order
    result = place_order(
        args.api, tx_hash, signature, address,
        args.name, args.phone, args.email, items,
        store_id=store_id,
    )

    print(json.dumps(result))


def cmd_interactive(args):
    """Default interactive mode (no subcommand)."""
    # Validate required flags
    for flag in ("key", "rpc", "name", "phone", "email"):
        if not getattr(args, flag, None):
            print(f"Error: --{flag} is required for interactive mode.", file=sys.stderr)
            sys.exit(1)

    # Normalize private key
    private_key = args.key if args.key.startswith("0x") else f"0x{args.key}"
    acct = Account.from_key(private_key)
    print(f"Wallet: {acct.address}")

    address = {
        "street": args.street,
        "city": args.city,
        "state": args.state,
        "zip": args.zip,
    }

    # Step 0: Fetch config
    print("\nFetching config...")
    config = fetch_config(args.api)
    wallet_address = config["walletAddress"]
    usdc_address = config["usdcAddress"]
    print(f"  Payment wallet: {wallet_address}")

    # Step 1: Fetch menu
    print("\nFetching menu...")
    menu_data = fetch_menu(args.api, address)
    print(f"  Store: {menu_data.get('storeId', 'unknown')}")
    menu_items = extract_menu_items(menu_data)
    display_menu(menu_items)

    if not menu_items:
        print("No menu items found. Exiting.")
        sys.exit(1)

    # Step 2: Select items
    items = select_items(menu_items)

    print("\nYour order:")
    for item in items:
        # Find name from menu_items
        name = next((m[1] for m in menu_items if m[0] == item["code"]), item["code"])
        print(f"  - {name} x{item['quantity']}")

    # Step 3: Price the order
    print("\nPricing order...")
    price = fetch_price(args.api, address, items)
    total_usd = price["totalUsd"]
    usdc_amount = price["usdcAmount"]
    print(f"  Total: ${total_usd} ({usdc_amount} USDC raw units)")

    if "breakdown" in price:
        breakdown = price["breakdown"]
        for key, val in breakdown.items():
            print(f"    {key}: {val}")

    # Step 4: Confirm
    usdc_display = int(usdc_amount) / 1_000_000
    confirm = input(f"\nSend {usdc_display:.2f} USDC and place order? [y/n] ").strip().lower()
    if confirm != "y":
        print("Cancelled.")
        sys.exit(0)

    # Step 5: Send USDC
    print("\nSending USDC...")
    w3 = Web3(Web3.HTTPProvider(args.rpc))
    if not w3.is_connected():
        print("Failed to connect to Ethereum RPC. Check --rpc URL.")
        sys.exit(1)

    tx_hash = send_usdc(w3, acct, usdc_address, wallet_address, int(usdc_amount))

    # Step 6: Sign EIP-712
    print("\nSigning order...")
    signature = sign_order(
        private_key, tx_hash, address,
        args.name, args.phone, args.email, items,
    )
    print(f"  Signature: {signature[:20]}...")

    # Step 7: Place order
    print("\nPlacing order...")
    result = place_order(
        args.api, tx_hash, signature, address,
        args.name, args.phone, args.email, items,
    )

    # Step 8: Display result
    print("\n=== Order Placed! ===")
    print(f"  Order ID: {result.get('id', 'unknown')}")
    print(f"  Status: {result.get('status', 'unknown')}")
    if result.get("dominosOrderId"):
        print(f"  Domino's Order ID: {result['dominosOrderId']}")
    if result.get("estimatedWait"):
        print(f"  Estimated Wait: {result['estimatedWait']} minutes")


def main():
    args = parse_args()

    if args.command == "menu":
        cmd_menu(args)
    elif args.command == "order":
        cmd_order(args)
    elif args.command == "retry-order":
        cmd_retry_order(args)
    else:
        cmd_interactive(args)


if __name__ == "__main__":
    main()
