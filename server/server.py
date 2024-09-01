import os
from flask import Flask, request, jsonify
import threading
import asyncio
from discord.ext import commands
import discord
import requests
import logging
import re
import json
import imaplib
import email
from email.header import decode_header
import ssl

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot_threads = {}
bot_clients = {}
bot_usernames = {}
stop_flags = {}

user_interactions = {}
USER_DATA_FILE = "user_data.json"
PRODUCTS_FILE = "products.json"
SOLD_PRODUCTS_FILE = "sold_products.json"


def get_discord_headers(token):
    return {'Authorization': token}

def fetch_discord_data(url, token):
    try:
        response = requests.get(url, headers=get_discord_headers(token))
        response.raise_for_status()
        return response.json(), response.status_code
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error occurred: {e}")
        return None, getattr(e.response, 'status_code', 500)

def get_channel_info(token, channel_id):
    url = f'https://discord.com/api/channels/{channel_id}'
    return fetch_discord_data(url, token)

def get_guild_info(token, guild_id):
    url = f'https://discord.com/api/guilds/{guild_id}'
    return fetch_discord_data(url, token)

def create_initial_product_file(one_time_products, unlimited_use_products):
    products = {
        "one_time_products": one_time_products,
        "unlimited_use_products": unlimited_use_products
    }
    with open(PRODUCTS_FILE, 'w') as f:
        json.dump(products, f, indent=4)

def load_products():
    if os.path.exists(PRODUCTS_FILE):
        with open(PRODUCTS_FILE, 'r') as f:
            return json.load(f)
    else:
        return None

def save_sold_product(product):
    if os.path.exists(SOLD_PRODUCTS_FILE):
        with open(SOLD_PRODUCTS_FILE, 'r') as f:
            sold_products = json.load(f)
    else:
        sold_products = {"sold_products": []}

    sold_products["sold_products"].append(product)
    with open(SOLD_PRODUCTS_FILE, 'w') as f:
        json.dump(sold_products, f, indent=4)

async def send_message(channel, message, slowmode_duration, infinite_loop, stop_flag):
    while not stop_flag.is_set():
        await channel.send(message)
        if not infinite_loop:
            break
        await asyncio.sleep(slowmode_duration)

async def run_bot(token, channel_id, message, slowmode_duration, infinite_loop, client_key):
    intents = discord.Intents.default()
    bot_client = commands.Bot(command_prefix='!', self_bot=True, intents=intents)
    bot_clients[client_key] = bot_client
    stop_flags[client_key] = threading.Event()

    @bot_client.event
    async def on_ready():
        bot_usernames[client_key] = f"{bot_client.user.name}#{bot_client.user.discriminator}"
        logger.info(f"Bot started: {bot_usernames[client_key]}")
        channel = bot_client.get_channel(int(channel_id))
        if channel:
            await send_message(channel, message, slowmode_duration, infinite_loop, stop_flags[client_key])
        else:
            logger.error(f"Channel ID {channel_id} not found for token {token}")
            stop_flags[client_key].set()

    try:
        await bot_client.start(token, bot=False)
    except Exception as e:
        logger.error(f"Error running bot: {e}")
    finally:
        await bot_client.close()
        cleanup_bot_resources(client_key)

def cleanup_bot_resources(client_key):
    bot_clients.pop(client_key, None)
    bot_threads.pop(client_key, None)
    bot_usernames.pop(client_key, None)
    stop_flags.pop(client_key, None)
    logger.info(f"Cleaned up resources for {client_key}")

@app.route('/send_data', methods=['POST'])
def receive_data():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No data received"}), 400

    token = data.get('token')
    channel_id = data.get('channel_id')
    message = data.get('message')
    infinite_loop = data.get('infinite_loop', False)

    if not all([token, channel_id, message]):
        return jsonify({"status": "error", "message": "Token, channel_id, or message missing"}), 400

    client_key = (token, channel_id)
    if client_key in bot_threads and bot_threads[client_key].is_alive():
        username = bot_usernames.get(client_key, "Unknown")
        return jsonify({"status": "error", "message": f"Bot already running for {username} in channel {channel_id}"}), 400

    channel_info, status_code = get_channel_info(token, channel_id)
    if not channel_info or status_code != 200:
        return jsonify({"status": "error", "message": "Failed to fetch channel info"}), status_code

    slowmode_duration = channel_info.get('rate_limit_per_user', 0)

    loop = asyncio.new_event_loop()
    bot_thread = threading.Thread(target=lambda: loop.run_until_complete(run_bot(token, channel_id, message, slowmode_duration, infinite_loop, client_key)))
    bot_threads[client_key] = bot_thread
    bot_thread.start()

    return jsonify({"status": "success", "message": "Bot started. Username will be logged after login."}), 200

@app.route('/stop_autoad', methods=['POST'])
def stop_autoad():
    data = request.get_json()
    token = data.get('token')
    channel_id = data.get('channel_id')

    if not token or not channel_id:
        return jsonify({"status": "error", "message": "Token and channel_id are required"}), 400

    client_key = (token, channel_id)
    if client_key in stop_flags:
        stop_flags[client_key].set()
        if client_key in bot_clients:
            bot_client = bot_clients[client_key]
            asyncio.run_coroutine_threadsafe(bot_client.close(), bot_client.loop)
        cleanup_bot_resources(client_key)
        return jsonify({"status": "success", "message": "Auto-ad stopped"}), 200
    return jsonify({"status": "error", "message": f"No running auto-ad found for the provided token in channel {channel_id}"}), 400

@app.route('/stop_bot', methods=['POST'])
def stop_bot():
    return stop_autoad()

@app.route('/get_username', methods=['POST'])
def get_username():
    data = request.get_json()
    token = data.get('token')

    if not token:
        return jsonify({"status": "error", "message": "Token is required"}), 400

    user_info, status_code = fetch_discord_data('https://discord.com/api/users/@me', token)
    if user_info:
        username = user_info.get('username')
        discriminator = user_info.get('discriminator')
        logger.info(f"{username}#{discriminator} requested their username.")
        return jsonify({"status": "success", "username": f"{username}#{discriminator}"}), 200
    return jsonify({"status": "error", "message": f"Failed to fetch user info. Status code: {status_code}"}), status_code

@app.route('/get_slowmode', methods=['POST'])
def get_slowmode():
    data = request.get_json()
    token = data.get('token')
    channel_id = data.get('channel_id')

    if not token or not channel_id:
        return jsonify({"status": "error", "message": "Token and channel_id are required"}), 400

    channel_info, status_code = get_channel_info(token, channel_id)
    if channel_info:
        slowmode_duration = channel_info.get('rate_limit_per_user', 0)
        return jsonify({"status": "success", "slowmode_duration": slowmode_duration}), 200
    return jsonify({"status": "error", "message": f"Failed to fetch channel info. Status code: {status_code}"}), status_code

@app.route('/get_channel_name', methods=['POST'])
def get_channel_name():
    data = request.get_json()
    token = data.get('token')
    channel_id = data.get('channel_id')

    if not token or not channel_id:
        return jsonify({"status": "error", "message": "Token and channel_id are required"}), 400

    channel_info, status_code = get_channel_info(token, channel_id)
    if channel_info:
        channel_name = channel_info.get('name')
        return jsonify({"status": "success", "channel_name": channel_name}), 200
    return jsonify({"status": "error", "message": f"Failed to fetch channel info. Status code: {status_code}"}), status_code

@app.route('/get_server_name', methods=['POST'])
def get_server_name():
    data = request.get_json()
    token = data.get('token')
    channel_id = data.get('channel_id')

    if not token or not channel_id:
        return jsonify({"status": "error", "message": "Token and channel_id are required"}), 400

    channel_info, status_code = get_channel_info(token, channel_id)
    if channel_info:
        guild_id = channel_info.get('guild_id')
        if guild_id:
            guild_info, guild_status_code = get_guild_info(token, guild_id)
            if guild_info:
                guild_name = guild_info.get('name')
                return jsonify({"status": "success", "server_name": guild_name}), 200
            return jsonify({"status": "error", "message": f"Failed to fetch guild info. Status code: {guild_status_code}"}), guild_status_code
        return jsonify({"status": "error", "message": "Guild ID not found in channel information"}), 400
    return jsonify({"status": "error", "message": f"Failed to fetch channel info. Status code: {status_code}"}), status_code

def create_user_folder_structure(bot_token, user_id, username):
    base_folder = "User_Data"
    if not os.path.exists(base_folder):
        os.makedirs(base_folder)

    bot_user_folder = os.path.join(base_folder, f"user_{bot_token[-6:]}")
    if not os.path.exists(bot_user_folder):
        os.makedirs(bot_user_folder)

    user_folder = os.path.join(bot_user_folder, f"User_{user_id}_{username}")
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)

    return user_folder

def load_user_data(user_folder):
    try:
        with open(os.path.join(user_folder, "user_data.json"), "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_user_data(user_folder, data):
    with open(os.path.join(user_folder, "user_data.json"), "w") as f:
        json.dump(data, f, indent=4)

def save_checked_emails(user_folder, checked_emails):
    with open(os.path.join(user_folder, "checked_emails.json"), "w", encoding="utf-8") as f:
        json.dump(checked_emails, f, ensure_ascii=False, indent=4)
        
def check_paypal_transaction(email_credentials, transaction_id, user_folder):
    username = email_credentials.get("email")
    password = email_credentials.get("app_password")

    if not username or not password:
        logger.error("Missing email or app password in email credentials.")
        return False

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(username, password)
        mail.select("inbox")

        status, messages = mail.search(None, "ALL")
        mail_ids = messages[0].split()

        last_10 = mail_ids[-10:]
        transaction_found = False
        checked_emails = []

        for email_id in last_10:
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])

                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8")

                    from_ = msg.get("From")
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            if content_type in ["text/plain", "text/html"]:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body += payload.decode()
                    else:
                        body = msg.get_payload(decode=True).decode()

                    logger.info(f"Checking email from {from_} with subject '{subject}'")
                    if transaction_id in body:
                        logger.info(f"Transaction ID {transaction_id} found!")
                        transaction_found = True
                        break

                    checked_emails.append({
                        "subject": subject,
                        "from": from_,
                        "body": body
                    })

            if transaction_found:
                break

        save_checked_emails(user_folder, checked_emails)

        mail.close()
        mail.logout()

        return transaction_found
    except Exception as e:
        logger.error(f"Failed to check PayPal transaction: {e}")
        return False

def extract_numeric_value(price_str):
    """Extract the numeric value from a price string if it's a string."""
    if isinstance(price_str, str):
        return float(price_str.replace(" USD", ""))
    return price_str

def is_valid_transaction_id(transaction_id):
    """Check if the PayPal transaction ID is valid."""
    return bool(re.match(r'^[A-Z0-9]{17}$', transaction_id, re.IGNORECASE))

    
async def handle_user_interaction(bot_client, message, custom_phrases, payment_methods, email_credentials, products, paypal_info):
    user = message.author
    user_id = str(user.id)
    username = user.name
    bot_token = bot_client.http.token

    one_time_products = products.get('one_time_products', {})
    unlimited_use_products = products.get('unlimited_use_products', {})
    
    user_folder = create_user_folder_structure(bot_token, user_id, username)
    user_interactions = load_user_data(user_folder)

    if user_id not in user_interactions:
        user_interactions[user_id] = {
            "initial_greeting": False,
            "stop_communication": False,
            "buying_mode": False,
            "await_buy_again": False,
            "product_selected": False,
            "awaiting_confirmation": False,
            "awaiting_payment_method": False,
            "awaiting_transaction_id": False,
            "awaiting_more_products": False,
            "products": [],
            "payment_method": "",
            "transaction_id": "",
            "final_products": []
        }

    user_data = user_interactions[user_id]

    if user_data["stop_communication"]:
        logger.info(f"User {user} has opted out of further communication.")
        return

    if not user_data["initial_greeting"]:
        await user.send(custom_phrases["initial_greeting"])
        user_data["initial_greeting"] = True
        save_user_data(user_folder, user_interactions)
        return

    content = message.content.strip().lower()
    logger.info(f"Handling response: {content}")
    logger.info(f"Current State: {user_data}")

    if content == custom_phrases["no"] and not user_data["buying_mode"]:
        await user.send("Bye!")
        user_data["stop_communication"] = True

    elif content == custom_phrases["buy"] and not user_data["buying_mode"]:
        await user.send(custom_phrases["buy_response"])
        await user.send(custom_phrases["one_time_product_message"])
        await user.send(custom_phrases["unlimited_product_message"])
        await user.send(custom_phrases["choose_question"])
        user_data["buying_mode"] = True

    elif user_data["buying_mode"] and not user_data["awaiting_confirmation"] and not user_data["product_selected"]:
        if content in one_time_products.keys():
            category_info = one_time_products[content]
            category_name = category_info[0]
            products_list = category_info[1]

            await user.send(f"You have selected the category: '{category_name}'. Please choose the specific product and quantity, in this format ['Product number' 'Quantity']. Example: 1 2 (Product number 1 - Quantity 2)")

            for i, product in enumerate(products_list, start=1):
                product_name = product[0]
                product_price = product[1]
                await user.send(f"{i}. {product_name} --> {product_price} USD")

            user_data["product_selected"] = True
            user_data["selected_category"] = content
            user_data["awaiting_quantity_selection"] = True

        elif content in unlimited_use_products.keys():
            product_info = unlimited_use_products[content]
            product_name = product_info[0]
            product_price = product_info[1]
            final_product = product_info[2]

            if product_name in user_data["products"]:
                await user.send("You selected the same thing! Please choose a different product.")
                await user.send(custom_phrases["choose_question"])
            else:
                user_data["products"].append((product_name, product_price))
                user_data["final_products"].append(final_product)
                await user.send(f"Do you confirm buying {product_name} for {product_price} USD? Write 'confirm' or 'change' to change the product.")
                user_data["awaiting_confirmation"] = True
        else:
            await user.send("Invalid choice. " + custom_phrases["choose_question"])

    elif user_data.get("awaiting_quantity_selection"):
        try:
            product_choice, quantity = map(int, content.split())
            category = user_data["selected_category"]
            products_list = one_time_products[category][1]

            if 1 <= product_choice <= len(products_list) and quantity > 0:
                selected_product = products_list[product_choice - 1]
                product_name = selected_product[0]
                product_price = extract_numeric_value(selected_product[1]) 
                final_product = selected_product[2]

                total_price = product_price * quantity

                user_data["products"].append((f"{quantity}x {product_name}", total_price))
                user_data["final_products"].append(final_product)
                await user.send(f"Do you confirm buying {quantity}x {product_name} for {total_price:.2f} USD? Write 'confirm' or 'change' to change the product.")
                user_data["awaiting_confirmation"] = True
                user_data["awaiting_quantity_selection"] = False
            else:
                await user.send("Invalid selection. Please enter the product number and quantity again.")
        except ValueError:
            await user.send("Please enter the product number and quantity in the correct format (e.g., '1 3' to buy 3 units of product 1).")

    elif user_data["awaiting_confirmation"]:
        if content == "confirm":
            user_data["product_selected"] = True
            user_data["awaiting_confirmation"] = False
            try:
                final_amount = sum(product[1] for product in user_data["products"])
            except Exception as e:
                logger.error(f"Error calculating final amount: {e}")
                await user.send("An error occurred while processing your order. Please try again.")
                return
            
            await user.send(f"Your final amount is {final_amount:.2f} USD.")
            payment_options_message = "\n".join([f"{key}. {method}" for key, method in payment_methods.items()])
            await user.send(f"Please select a payment method:\n{payment_options_message}")

            user_data["awaiting_payment_method"] = True

        elif content == "change":
            user_data["product_selected"] = False
            user_data["awaiting_confirmation"] = False
            user_data["awaiting_quantity_selection"] = False
            user_data["products"] = [] 
            user_data["final_products"] = [] 

            await user.send(custom_phrases["choose_question"])
        else:
            await user.send("Please write 'confirm' or 'change'.")

    elif user_data["awaiting_payment_method"]:
        if content in payment_methods.keys():
            selected_method = payment_methods[content]
            user_data["payment_method"] = selected_method

            if selected_method == "PayPal":
                if paypal_info and "email" in paypal_info:
                    paypal_email = paypal_info["email"]
                    await user.send(f"Send the payment to {paypal_email}.")
                    await user.send(f"Rules: {paypal_info.get('rules', '')}")
                    await user.send("Please provide your PayPal transaction ID after payment.")
                else:
                    await user.send("PayPal information is missing. Please contact support.")
                    return

            user_data["awaiting_transaction_id"] = True
            user_data["awaiting_payment_method"] = False
        else:
            await user.send("Invalid payment method selected. Please choose a valid payment method from the list.")
    elif user_data["awaiting_transaction_id"]:
        user_input = content.strip().upper()
        if is_valid_transaction_id(user_input):
            user_data["transaction_id"] = user_input
            if check_paypal_transaction(email_credentials, user_data["transaction_id"], user_folder):
                product_list = ", ".join(product for product, _ in user_data["products"])
                await user.send(f"Payment confirmed! Your order for {product_list} has been processed.")
                
                for product in user_data["final_products"]:
                    await user.send(f"Here is your product: {product}")
                
                user_data["awaiting_transaction_id"] = False
                user_data["await_buy_again"] = True
                user_data["buying_mode"] = False
            else:
                await user.send("Transaction ID not found. Please make sure you have paid and provided the correct PayPal transaction ID.")
        else:
            await user.send("Invalid transaction ID. Please enter a valid 17-character PayPal transaction ID.")

        save_user_data(user_folder, user_interactions)

    elif content == custom_phrases["stop_bot_buying"] and user_data["buying_mode"]:
        await user.send(custom_phrases["stop_bot_buying_response"])
        user_data["stop_communication"] = True

    elif content == custom_phrases["buy_again"] and user_data["await_buy_again"]:
        await user.send(custom_phrases["buy_again_response"])
        user_interactions[user_id] = {
            "initial_greeting": True,
            "stop_communication": False,
            "buying_mode": True,
            "await_buy_again": False,
            "product_selected": False,
            "awaiting_confirmation": False,
            "awaiting_payment_method": False,
            "awaiting_transaction_id": False,
            "awaiting_more_products": False,
            "products": [],
            "payment_method": "",
            "transaction_id": "",
            "final_products": []
        }
        await user.send(custom_phrases["one_time_product_message"])
        await user.send(custom_phrases["unlimited_product_message"])
        await user.send(custom_phrases["choose_question"])
    else:
        if not user_data["await_buy_again"]:
            await user.send("Sorry, I didn't understand that. Please provide the correct input.")

    save_user_data(user_folder, user_interactions)

@app.route('/start_dm_listener', methods=['POST'])
def start_dm_listener():
    data = request.get_json()

    required_fields = [
        'token', 'one_time_products', 'unlimited_use_products', 'paypal_info',
        'initial_greeting', 'buy', 'stop_bot_buying', 'no', 'buy_again', 'buy_response',
        'stop_bot_buying_response', 'buy_again_response', 'one_time_product_message',
        'unlimited_product_message', 'choose_question', 'payment_methods',
        'gmail_account', 'gmail_app_password' 
    ]
    
    for field in required_fields:
        if not data.get(field):
            logger.error(f"Missing required field: {field}")
            return jsonify({"status": "error", "message": f"Missing required field: {field}"}), 400

    token = data.get('token')
    one_time_products = data.get('one_time_products')
    unlimited_use_products = data.get('unlimited_use_products')
    paypal_info = data.get('paypal_info') 
    gmail_account = data.get('gmail_account')
    gmail_app_password = data.get('gmail_app_password')

    custom_phrases = {
        "initial_greeting": data.get('initial_greeting'),
        "buy": data.get('buy'),
        "stop_bot_buying": data.get('stop_bot_buying'),
        "no": data.get('no'),
        "buy_again": data.get('buy_again'),
        "buy_response": data.get('buy_response'),
        "stop_bot_buying_response": data.get('stop_bot_buying_response'),
        "buy_again_response": data.get('buy_again_response'),
        "one_time_product_message": data.get('one_time_product_message'),
        "unlimited_product_message": data.get('unlimited_product_message'),
        "choose_question": data.get('choose_question'),
    }

    payment_methods = data.get('payment_methods')
    email_credentials = {
        'email': gmail_account,
        'app_password': gmail_app_password,
    }

    client_key = (token, "DM Listener")
    if client_key in bot_threads and bot_threads[client_key].is_alive():
        username = bot_usernames.get(client_key, "Unknown")
        return jsonify({"status": "error", "message": f"DM Listener already running for {username}"}), 400

    loop = asyncio.new_event_loop()
    bot_thread = threading.Thread(target=lambda: loop.run_until_complete(
        start_direct_message_listener(
            token, custom_phrases, payment_methods, email_credentials, one_time_products, unlimited_use_products, paypal_info
        )
    ))
    bot_threads[client_key] = bot_thread
    bot_thread.start()

    return jsonify({"status": "success", "message": "DM Listener started."}), 200

async def start_direct_message_listener(token, custom_phrases, payment_methods, email_credentials, one_time_products, unlimited_use_products, paypal_info):
    intents = discord.Intents.default()
    intents.messages = True
    intents.dm_messages = True

    bot_client = commands.Bot(command_prefix='!', self_bot=True, intents=intents)
    client_key = (token, "DM Listener")
    bot_clients[client_key] = bot_client
    stop_flags[client_key] = threading.Event()

    @bot_client.event
    async def on_ready():
        logger.info(f"DM Listener Bot started for {bot_client.user.name}#{bot_client.user.discriminator}")

    @bot_client.event
    async def on_message(message):
        if isinstance(message.channel, discord.DMChannel) and message.author != bot_client.user:
            logger.info(f"Received a DM from {message.author}: {message.content}")
            await handle_user_interaction(bot_client, message, custom_phrases, payment_methods, email_credentials, {
                'one_time_products': one_time_products,
                'unlimited_use_products': unlimited_use_products
            }, paypal_info)  

    try:
        await bot_client.start(token, bot=False)
    except Exception as e:
        logger.error(f"Error running DM Listener bot: {e}")
    finally:
        await bot_client.close()
        cleanup_bot_resources(client_key)

@app.route('/get_user_data', methods=['GET'])
def get_user_data():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"status": "error", "message": "User ID is required"}), 400

    user_data = user_interactions.get(user_id)
    if not user_data:
        return jsonify({"status": "error", "message": "User not found"}), 404

    return jsonify({
        "status": "success",
        "data": {
            "paypal_email": user_data.get("paypal_email"),
            "product_number": user_data.get("product_number")
        }
    }), 200

@app.route('/get_available_products', methods=['POST'])
def get_available_products():
    products = load_products()
    return jsonify({"status": "success", "products": products}), 200

@app.route('/get_sold_products', methods=['POST'])
def get_sold_products():
    if os.path.exists(SOLD_PRODUCTS_FILE):
        with open(SOLD_PRODUCTS_FILE, 'r') as f:
            sold_products = json.load(f)
        return jsonify({"status": "success", "sold_products": sold_products}), 200
    else:
        return jsonify({"status": "success", "sold_products": []}), 200

if __name__ == '__main__':
    # Path to your SSL certificate and key files
    cert_file = 'cert.pem'
    key_file = 'key.pem'

    # Check if the SSL certificate and key files exist
    if not os.path.exists(cert_file) or not os.path.exists(key_file):
        raise RuntimeError(f"SSL certificate or key file not found: {cert_file}, {key_file}")

    # Create an SSL context
    context = ssl.SSLContext(ssl.PROTOCOL_TLS)
    context.load_cert_chain(cert_file, key_file)

    # Run Flask with HTTPS
    app.run(port=5001, debug=True, ssl_context=context)