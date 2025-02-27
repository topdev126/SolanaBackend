from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import schedule
import pymongo
from pymongo import MongoClient
import os, time
import pickle
import threading
from datetime import datetime, timedelta
from flask_cors import CORS
from flask_caching import Cache
from flask_socketio import SocketIO
import ssl
import numpy as np
from bson.objectid import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = '12345'
CORS(app, origins="*", supports_credentials=True, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
cache = Cache(app, config={'CACHE_TYPE': 'simple'})  # Simple cache
socketio = SocketIO(app, cors_allowed_origins="*", engineio_logger=True)
# Check if session data exists
session_file = 'session_data.pkl'
if os.path.exists(session_file):
    # Load session data
    with open(session_file, 'rb') as file:
        session_data = pickle.load(file)
else:
    session_data = None

MONGO_URI = "mongodb+srv://db-mongodb-sfo3-43626-3f408016.mongo.ondigitalocean.com"
MONGO_DB = "kolscan"
MONGO_COLLECTION = "leaders"
MONGO_USER_COLLECTION = "users"
MONGO_USER = "doadmin"
MONGO_PASSWORD = "s6CqWNz9142eH378"
MONGO_HOST = MONGO_URI
MONGO_DATABASE = MONGO_DB

# MongoDB Connection
def get_mongo_client():
    # Connect to MongoDB using the URI provided
    client = MongoClient(MONGO_HOST, username=MONGO_USER, password=MONGO_PASSWORD, authSource="admin", tls=True, tlsAllowInvalidCertificates=True)
    return client[MONGO_DATABASE]

# Function to check if the "leaders" collection exists, if not create it
def ensure_leaders_collection():
    # Get the MongoDB client and database
    db = get_mongo_client()

    # Check if the 'leaders' collection exists
    if MONGO_COLLECTION not in db.list_collection_names():
        print("Creating leaders collection...")
        # If not, create a new collection for leaders (MongoDB will auto-create it when inserting)

        db[MONGO_COLLECTION].create_index([("total_profit", pymongo.DESCENDING)])
    if MONGO_USER_COLLECTION not in db.list_collection_names():
        print("Creating leaders collection...")
        # If not, create a new collection for leaders (MongoDB will auto-create it when inserting)
        db[MONGO_USER_COLLECTION].create_index([("username", pymongo.DESCENDING)])        
    return db

# Function to insert data into MongoDB
def insert_leaders_data(leaders_data):
    collection = db[MONGO_COLLECTION]

    # Delete all existing documents in the collection
    collection.delete_many({})

    # Insert the new leaderboard data into the collection
    if leaders_data:
        collection.insert_many(leaders_data)
        print("Data inserted into MongoDB successfully.")


# Function to start Selenium WebDriver
def start_driver(option):
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in headless mode
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    if option == "trades":
        driver.get("https://kolscan.io/trades")
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Kolscan')]")))
        return getSessionData(driver)
    elif option == "leaderboard":    
        driver.get("https://kolscan.io/leaderboard")
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Realized PnL Leaderboard')]")))        

        return driver
    else:
        driver.get(f"https://kolscan.io/account/example_wallet")
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Kolscan')]")))     

        return driver

def extract_trade_info(text):
    """Removes the last line (time) from the trade text."""
    lines = text.split("\n")
    return "\n".join(lines[:-1])  # Exclude the last line (time)
def parse_time(time_str):
    """Parses the Time field, removing the timezone information."""
    time_str = time_str.split(" GMT")[0]  # Remove timezone
    return datetime.strptime(time_str, "%a %b %d %Y %H:%M:%S")
  
def getSessionData(driver):
    if session_data:
        # Set cookies
        for cookie in session_data['cookies']:
            driver.add_cookie(cookie)

        # Set local storage
        for key, value in session_data['local_storage'].items():
            driver.execute_script(f"window.localStorage.setItem('{key}', '{value}');")

        # Refresh the page to apply the session data
        driver.refresh()
        time.sleep(5)  # Wait for the page to load with the restored session
    else:
        time.sleep(1000)  # Wait for the page to load and connect the wallet
        ## please install phantom wallet and connect the wallet in kolscan.io manually
        # Save cookies and local storage
        cookies = driver.get_cookies()
        local_storage = driver.execute_script("return window.localStorage;")

        with open(session_file, 'wb') as file:
            pickle.dump({'cookies': cookies, 'local_storage': local_storage}, file)
    return driver
# Scraper for /trades
def scrape_trades(driver):
    global Trades_history
    try:
        trade_boxes = driver.find_elements(By.XPATH, "//*[contains(@class, 'trades_kolBox')]")
        for trade_box in trade_boxes:
            trades_transaction_items = trade_box.find_elements(By.XPATH, ".//*[contains(@class, 'transaction_transactionContainer')]")
            print("***********************************", len(trades_transaction_items))
            user_url = trade_box.find_element(By.XPATH, ".//a[contains(@class, 'trades_kolHeader')]")
            username = user_url.text
            wallet = user_url.get_attribute("href").split("/")[-1]
            avatar = trade_box.find_element(By.XPATH, ".//img[contains(@alt, 'pfp')]").get_attribute("src")
            for transaction in trades_transaction_items:
                try:
                    transactionInfo = transaction.text.split()
                    buy_sell = transactionInfo[0]
                    if buy_sell == "Buy":
                        sol_amount, token_amount, token, timeAgo = transactionInfo[1], transactionInfo[3], transactionInfo[4], transactionInfo[5]
                    else:
                        sol_amount, token_amount, token, timeAgo = transactionInfo[3], transactionInfo[1], transactionInfo[2], transactionInfo[5]

                    # Extract Time (from the <a> tag's title attribute)
                    time = transaction.find_element(By.TAG_NAME, 'a').get_attribute('title')
                    # Extract Link (from the <a> tag's href attribute)
                    link = transaction.find_element(By.TAG_NAME, 'a').get_attribute('href')
                    trade = {
                        "Avatar": avatar,
                        "User_Name": username, 
                        "Buy_Sell": buy_sell,
                        "Token_Amount": token_amount,
                        "Token": token,
                        "Sol_Amount": sol_amount,
                        "Time": time,
                        "Link": link,
                        "Wallet": wallet,
                    }
                    if wallet in Trades_history:
                        Trades_history[wallet].append(trade)
                    else:
                        Trades_history[wallet] = [trade]
                        
                    Trades_history[wallet] = sorted(Trades_history[wallet], key=lambda x: parse_time(x['Time']), reverse=True)

                                            

                except Exception as e:
                    print(f"Error extracting data from a transaction: {e}")
    except:
        driver.quit()

# Scraper for /leaderboard
def scrape_leaderboard(driver):

    try:
        driver.refresh()
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Realized PnL Leaderboard')]")))

        leaderboard_items = driver.find_elements(By.XPATH, "//*[contains(@class, 'leaderboard_leaderboardUser')]")
        leaders = []

        for item in leaderboard_items:
            avatar = item.find_element(By.XPATH, ".//img[contains(@alt, 'pfp')]").get_attribute("src")
            username = item.find_element(By.XPATH, ".//a//h1").text.strip()
            twitter_link = f"https://x.com/{username}"
            wallet_address = item.find_element(By.XPATH, ".//a[contains(@href, '/account')]").get_attribute("href")
            buy_sell = item.find_element(By.XPATH, ".//div[contains(@class, 'remove-mobile')]").text.strip().split("/")
            buy = buy_sell[0].strip()
            sell = buy_sell[1].strip()
            total_profit = item.find_element(By.XPATH, ".//div[contains(@class, 'leaderboard_totalProfitNum')]//h1[1]").text.strip()
            usd_value = item.find_element(By.XPATH, ".//div[contains(@class, 'leaderboard_totalProfitNum')]//h1[2]").text.strip()

            leaders.append({"avatar": avatar, "username": username, "twitter_link": twitter_link, "wallet_address": wallet_address, "buy": buy, "sell": sell, "total_profit": total_profit, "usd_value": usd_value})

        return leaders
    except:
        driver.quit()

def save_leaderboard():
    driver_leaders = start_driver("leaderboard")
    # Ensure the leaders collection exists
    print("...................")
    # Scrape the leaderboard data
    leaderboard_data = scrape_leaderboard(driver_leaders)

    # Insert the data into MongoDB
    insert_leaders_data(leaderboard_data)

    # Return the data as a JSON response
    print("Success Saved !!!")

def watch_trades():
    import time
    global Trades_history
    wait = WebDriverWait(driver_trades, 20)
    wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(@class, 'trades_kolBox')]")))   
    trade_box = driver_trades.find_element(By.XPATH, "//*[contains(@class, 'trades_kolBox')]")
    user_url = trade_box.find_element(By.XPATH, ".//a[contains(@class, 'trades_kolHeader')]")
    username = user_url.text
    wallet = user_url.get_attribute("href").split("/")[-1]
    first_item_xpath = "(.//*[contains(@class, 'transaction_transactionContainer')])[1]"
    avatar = trade_box.find_element(By.XPATH, ".//img[contains(@alt, 'pfp')]").get_attribute("src") 
    previous_value = extract_trade_info(trade_box.find_element(By.XPATH, first_item_xpath).text)
    start_time = time.time()
    while True:
        try: 
            WebDriverWait(trade_box, 500).until_not(
                EC.text_to_be_present_in_element((By.XPATH, first_item_xpath), previous_value)
            )
            trade_box = driver_trades.find_element(By.XPATH, "//*[contains(@class, 'trades_kolBox')]")
            user_url = trade_box.find_element(By.XPATH, ".//a[contains(@class, 'trades_kolHeader')]")
            username = user_url.text
            wallet = user_url.get_attribute("href").split("/")[-1]    
            avatar = trade_box.find_element(By.XPATH, ".//img[contains(@alt, 'pfp')]").get_attribute("src") 
                
            transaction = trade_box.find_element(By.XPATH, first_item_xpath)
            previous_value = extract_trade_info(transaction.text)
            print(f"****** Updated Value: {wallet}- {username}", transaction.text)
            
            
            transactionInfo = transaction.text.split()
            buy_sell = transactionInfo[0]
            if buy_sell == "Buy":
                sol_amount, token_amount, token, timeAgo = transactionInfo[1], transactionInfo[3], transactionInfo[4], transactionInfo[5]
            else:
                sol_amount, token_amount, token, timeAgo = transactionInfo[3], transactionInfo[1], transactionInfo[2], transactionInfo[5]

            # Extract Time (from the <a> tag's title attribute)
            time_transaction = transaction.find_element(By.TAG_NAME, 'a').get_attribute('title')
            # Extract Link (from the <a> tag's href attribute)
            link = transaction.find_element(By.TAG_NAME, 'a').get_attribute('href')
            trade = {
                "Avatar": avatar,
                "User_Name": username, 
                "Buy_Sell": buy_sell,
                "Token_Amount": token_amount,
                "Token": token,
                "Sol_Amount": sol_amount,
                "Time": time_transaction,
                "Link": link,
                "Wallet": wallet,
            }
                    
            if wallet in Trades_history:
                Trades_history[wallet].insert(0, trade)
            else:
                Trades_history[wallet] = [trade]
            end_time = time.time()
            if end_time - start_time > 600: 
                # trade_box.click()
                start_time = time.time()
                Trades_history = {key: value[:10] for key, value in Trades_history.items()}
            socketio.emit("new_trade", {**trade, "Wallet": wallet})
        except:
            print("Error ==> ", )
            driver_trades.refresh()
            time.sleep(3)
            pass

# Function to run the scheduled tasks
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(10)

def run_background_tasks():
    """ Start background threads when the app starts """
    print("Starting background tasks...")
    
    # Start the schedule in a separate thread
    schedule_thread = threading.Thread(target=run_schedule, daemon=True)
    schedule_thread.start()
    
    # Start real-time trade monitoring
    threading.Thread(target=watch_trades, daemon=True).start()

    # Get all trades
    scrape_trades(driver_trades)

    # Schedule the leaderboard function
    schedule.every(120).minutes.do(save_leaderboard)

# Flask Routes
@app.route('/')
def hello_world():
    return 'Welcome to KolsOnline'


@app.route("/trades", methods=["GET"])
def get_trades():
    Trades_history_cpy = Trades_history.copy()
    wallet_latest_times = {
      wallet: max(parse_time(tx["Time"]) for tx in tx_list) for wallet, tx_list in Trades_history_cpy.items()
    }
    sorted_wallets = sorted(Trades_history_cpy.keys(), key=lambda w: wallet_latest_times[w], reverse=True)

    # Sort transactions within each wallet by time (latest first)
    sorted_transactions = {
        wallet: sorted(Trades_history_cpy[wallet], key=lambda tx: parse_time(tx["Time"]), reverse=True)
        for wallet in sorted_wallets
    }
    return jsonify({"trades": sorted_transactions})

@app.route("/latest", methods=["GET"])
def get_latest_trades():
    Trades_history_cpy = Trades_history.copy()
    all_transactions = [tx for wallet in Trades_history_cpy.values() for tx in wallet]
    sorted_transactions = sorted(all_transactions, key=lambda x: parse_time(x['Time']), reverse=True)[0:10]

    return jsonify({"trades": sorted_transactions})

# @app.route("/getTrend", methods=["GET"])
# def getTrend():
#     tokens = np.array([entry['Token'] for entry in Trades_history])
#     buy_sell = np.array([entry['Buy_Sell'] for entry in Trades_history])
#     sol_amounts = np.array([entry['Sol_Amount'] for entry in Trades_history])
#     token_amounts = np.array([entry['Token_Amount'] for entry in Trades_history])
#     time_strings = np.array([entry['Time'] for entry in Trades_history])

#     # Convert time to datetime format
#     times = np.array([datetime.strptime(time, '%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)') for time in time_strings])

#     # Get the current time and calculate the 10 minutes ago timestamp
#     now = datetime.utcnow()
#     ten_minutes_ago = now - timedelta(minutes=10)

#     # Filter out the trades that are within the last 10 minutes
#     time_mask = times >= ten_minutes_ago

#     # Filtered data
#     filtered_tokens = tokens[time_mask]
#     filtered_buy_sell = buy_sell[time_mask]
#     filtered_sol_amounts = sol_amounts[time_mask]
#     filtered_token_amounts = token_amounts[time_mask]

#     # Get unique tokens in the last 10 minutes
#     unique_tokens = np.unique(filtered_tokens)

#     # Prepare results for token trends within the last 10 minutes
#     token_trends = {}

#     for token in unique_tokens:
#         token_mask = (filtered_tokens == token)  # Mask for the current token
#         token_buy_sell = filtered_buy_sell[token_mask]  # Buy/Sell actions for the current token
#         token_sol_amount = filtered_sol_amounts[token_mask]  # SOL amounts for the current token
#         token_token_amount = filtered_token_amounts[token_mask]  # Token amounts for the current token
        
#         # Calculate total bought and sold in SOL
#         total_bought = np.sum(token_sol_amount[token_buy_sell == 'Buy'])
#         total_sold = np.sum(token_sol_amount[token_buy_sell == 'Sell'])
        
#         # Calculate the profit (Total Bought - Total Sold)
#         total_profit = total_bought - total_sold

#         # Store the trend in the dictionary
#         token_trends[token] = {
#             'Total_Bought': total_bought,
#             'Total_Sold': total_sold,
#             'Net_Amount': total_profit,  # Net amount for trend indication (profit)
#             'Buy_Count': np.sum(token_buy_sell == 'Buy'),
#             'Sell_Count': np.sum(token_buy_sell == 'Sell'),
#             'Total_SOL': np.sum(token_sol_amount)  # Total SOL traded for the token
#         }

#     # Sort the tokens by Total SOL traded in descending order
#     sorted_tokens = sorted(token_trends.items(), key=lambda x: x[1]['Total_SOL'], reverse=True)

#     print("")

#     return jsonify({"trend": sorted_tokens})    

@app.route("/account/<wallet>", methods=["GET"])
def get_account_info(wallet):
    global driver_account
    # try:
    driver_account.get(f"https://kolscan.io/account/{wallet}")
    wait = WebDriverWait(driver_account, 5)
    wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(@class, 'transaction_transactionContainer')]")))
    holding_items = driver_account.find_elements(By.XPATH, "//*[contains(@class, 'account_accountHolding')]")
    defi_items = driver_account.find_elements(By.XPATH, "//*[contains(@class, 'transaction_transactionContainer')]")
    holding, defi_trades = [], []
    
    for holding_item in holding_items:
        token_avatar = holding_item.find_element(By.CSS_SELECTOR, 'div[style*="position: relative"] img').get_attribute('src')
        # Locate the token amount
        token_amount = holding_item.find_element(By.CSS_SELECTOR, 'div.cursor-pointer').text.split()[0]
        # Locate the token name
        token_name = holding_item.find_element(By.CSS_SELECTOR, 'div.cursor-pointer strong').text
        # Locate the USD value
        usd_value = holding_item.find_element(By.CSS_SELECTOR, 'div[style*="margin-left: auto"]').text
        holding.append({"Token_Avatar": token_avatar, "Token_Amount": token_amount, "Token_Name": token_name, "Usd_Value": usd_value})
    
    for defi_item in defi_items:
        transactionInfo = defi_item.text.split()
        buy_sell = transactionInfo[0]
        if buy_sell == "Buy":
            sol_amount, token_amount, token = transactionInfo[1], transactionInfo[3], transactionInfo[4]
        else:
            sol_amount, token_amount, token = transactionInfo[3], transactionInfo[1], transactionInfo[2]
        # Locate the Time
        time = defi_item.find_element(By.TAG_NAME, 'a').get_attribute('title')
        link = defi_item.find_element(By.TAG_NAME, 'a').get_attribute('href')
        trade = {
            "Buy_Sell": buy_sell,
            "Token_Amount": token_amount,
            "Token": token,
            "Sol_Amount": sol_amount,
            "Time": time,
            "Link": link,
        }
        defi_trades.append(trade)

    print("=====>", len(holding), len(defi_trades))
    # except:
    #     # driver_account = start_driver("account")
    #     pass
        
    return jsonify({"holding": holding, "defi": defi_trades})

@app.route("/leader", methods=["GET"])
@cache.cached(timeout=3600)  # Cache for 60 seconds
def get_leader():
    try:
        leaders = list(db.leaders.find())  # Retrieve all documents from the leaders collection

        if not leaders:
            return jsonify({"message": "No data found"}), 404
        
        # Convert MongoDB ObjectId to string
        for leader in leaders:
            leader["_id"] = str(leader["_id"])

        return jsonify(leaders), 200

    except Exception as e:
        print("❌ Error fetching leader data:", e)
        return jsonify({"message": "Server error", "error": str(e)}), 500
    
db = ensure_leaders_collection()
driver_trades = start_driver("trades")
driver_account = start_driver("account")
Trades_history = {}
run_background_tasks()

# Admin Route
@app.route('/admin')
def admin():
    users = list(db[MONGO_USER_COLLECTION].find())
    leaderboard = list(db[MONGO_COLLECTION].find())
    return render_template('admin.html', users=users, leaderboard=leaderboard)

# Toggle User Active/Inactive
@app.route('/admin/toggle_user/<user_id>')
def toggle_user(user_id):
    user = db[MONGO_USER_COLLECTION].find_one({"_id": ObjectId(user_id)})
    new_status = not user["active"]
    db[MONGO_USER_COLLECTION].update_one({"_id": ObjectId(user_id)}, {"$set": {"active": new_status}})
    flash(f"User {user['username']} status updated!", "success")
    return redirect(url_for('admin'))

# Remove User
@app.route('/admin/remove_user/<user_id>')
def remove_user(user_id):
    db[MONGO_USER_COLLECTION].delete_one({"_id": ObjectId(user_id)})
    flash("User removed!", "success")
    return redirect(url_for('admin'))

# Remove Leaderboard Entry
@app.route('/admin/remove_leaderboard/<entry_id>')
def remove_leaderboard(entry_id):
    db[MONGO_COLLECTION].delete_one({"_id": ObjectId(entry_id)})
    flash("Leaderboard entry removed!", "success")
    return redirect(url_for('admin'))

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000)
