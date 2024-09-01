import requests
import json


token_input = input("Please enter your Discord token: ")


gmail_account = "digitalsuccess999@gmail.com"
gmail_app_password = "qcei yvuy xwoq lwfh"


initial_greeting = "Hello! If you are just here to talk and are a friend, type 'friend'. If you would like to buy something, type 'buy' :)"
buy_keyword = "buy"
stop_bot_buying_keyword = "stop"
no_keyword = "friend"
buy_again_keyword = "buy again"
buy_response = "Thank you for buying with us! Please type which category you would like from this selection:"
stop_bot_buying_response = "Purchasing has been canceled. Please wait for further instructions."
buy_again_response = "What would you like to purchase this time?"


one_time_products = {
    "1": ("Tiktok Accounts", [
        ("Fresh TikTok CPB Account (0 followers - No CRP activated)", 2, "TikTok_CPB_Account_1.txt"),
        ("Fresh TikTok CPB Account (100 followers)", 12.64, "TikTok_CPB_Account_2.txt")
    ])
}


unlimited_use_products = {
    "2": ("GTA 5 gameplay Google Drive Link", 12.64, "GTA_5_Gameplay_Link.txt")
}


one_time_product_message = "\n".join([f"{key}. {value[0]}" for key, value in one_time_products.items()])
unlimited_product_message = "\n".join([f"{key}. {value[0]} --> {value[1]}" for key, value in unlimited_use_products.items()])


payment_methods = {
    "1": "PayPal",
    "2": "Revolut",
    "3": "Skrill",
    "4": "Binance",
    "5": "Coinbase"
}


paypal_info = {
    "email": "digitalsuccesdsdsdss999@gmail.com",
    "rules": "No refunds. Please make sure to double-check the amount before sending."
}


url_start_dm_bot = 'http://127.0.0.1:5001/start_dm_listener'


data_start_dm_bot = {
    'token': token_input,
    'initial_greeting': initial_greeting,
    'buy': buy_keyword,
    'stop_bot_buying': stop_bot_buying_keyword,
    'no': no_keyword,
    'buy_again': buy_again_keyword,
    'buy_response': buy_response,
    'stop_bot_buying_response': stop_bot_buying_response,
    'buy_again_response': buy_again_response,
    'one_time_products': one_time_products,
    'unlimited_use_products': unlimited_use_products,
    'one_time_product_message': one_time_product_message,
    'unlimited_product_message': unlimited_product_message,
    'choose_question': "Write the number corresponding to what category you would like!",
    'payment_methods': payment_methods,
    'paypal_info': paypal_info,
    'gmail_account': gmail_account,  
    'gmail_app_password': gmail_app_password  
}



try:
    response_start_dm_bot = requests.post(url_start_dm_bot, json=data_start_dm_bot)
    response_start_dm_bot.raise_for_status()  
    response_data_start_dm_bot = response_start_dm_bot.json()


    if response_data_start_dm_bot.get('status') == 'success':
        print("DM Bot started successfully. It will now listen for direct messages.")
    else:
        print(f"Error: {response_data_start_dm_bot.get('message')}")
except requests.exceptions.RequestException as e:
    print(f"Failed to start DM Bot: {e}")
