from flask import Flask, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import schedule
import pymongo
from pymongo import MongoClient
import os, time
import pickle
import threading
from datetime import datetime
from flask_cors import CORS
from flask_caching import Cache
from flask_socketio import SocketIO


app = Flask(__name__)
CORS(app, origins="*", supports_credentials=True, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
cache = Cache(app, config={'CACHE_TYPE': 'simple'})  # Simple cache
socketio = SocketIO(app, cors_allowed_origins="*")
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
MONGO_USER = "doadmin"
MONGO_PASSWORD = "s6CqWNz9142eH378"
MONGO_HOST = MONGO_URI
MONGO_DATABASE = MONGO_DB

# MongoDB Connection
def get_mongo_client():
    # Connect to MongoDB using the URI provided
    client = MongoClient(MONGO_HOST, username=MONGO_USER, password=MONGO_PASSWORD, authSource="admin")
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
    driver = webdriver.Chrome(options=chrome_options)
    if option == "trades":
        driver.get("https://kolscan.io/trades")
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Kolscan')]")))   
        return getSessionData(driver)
    else:    
        driver.get("https://kolscan.io/leaderboard")
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Realized PnL Leaderboard')]")))        

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

# Flask Routes
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
  
def save_leaderboard():
    # Ensure the leaders collection exists
    
    print("...................")

    # Scrape the leaderboard data
    leaderboard_data = scrape_leaderboard(driver_leaders)

    # Insert the data into MongoDB
    insert_leaders_data(leaderboard_data)

    # Return the data as a JSON response
    print("Success Saved !!!")

def watch_trades():
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
    watch_counts = 0
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
                Trades_history[wallet].insert(0, trade)
            else:
                Trades_history[wallet] = [trade]
            watch_counts += 1
            if watch_counts > 60: 
                driver_trades.refresh()
                watch_counts = 0
            socketio.emit("new_trade", {**trade, "Wallet": wallet})
        except:
            print("Error ==> ", )
            pass


@app.route("/leader", methods=["GET"])
@cache.cached(timeout=3600)  # Cache for 60 seconds
def get_leader():
    print(f"------time start {time.time()}--------------")
    try:
        leaders = list(db.leaders.find())  # Retrieve all documents from the leaders collection

        if not leaders:
            return jsonify({"message": "No data found"}), 404
        
        # Convert MongoDB ObjectId to string
        for leader in leaders:
            leader["_id"] = str(leader["_id"])
        print(f"----------- time end {time.time()}--------------")

        return jsonify(leaders), 200

    except Exception as e:
        print("❌ Error fetching leader data:", e)
        return jsonify({"message": "Server error", "error": str(e)}), 500
    
# Function to run the scheduled tasks
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(10)

db = ensure_leaders_collection()
driver_trades = start_driver("trades")
driver_leaders = start_driver("leaderboard")
Trades_history = {}
if __name__ == "__main__":
    # Start the schedule in a separate thread
    schedule_thread = threading.Thread(target=run_schedule)
    schedule_thread.daemon = True
    schedule_thread.start()
    
    # start to get real time trade
    threading.Thread(target=watch_trades, daemon=True).start()

    # Get all trades
    scrape_trades(driver_trades)

    # Schedule the save_leaderboard function to run every 10 seconds
    schedule.every(120).minutes.do(save_leaderboard)

    # Run Flask app
    # app.run()
    socketio.run(app, host="0.0.0.0", port=5000)
