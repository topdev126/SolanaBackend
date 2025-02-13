from flask import Flask, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pymongo
from pymongo import MongoClient
import os, time
import pickle

app = Flask(__name__)

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
        db.create_collection(MONGO_COLLECTION)

# Function to insert data into MongoDB
def insert_leaders_data(leaders_data):
    db = get_mongo_client()
    collection = db[MONGO_COLLECTION]

    # Insert the leaderboard data into the collection
    if leaders_data:
        collection.insert_many(leaders_data)
        print("Data inserted into MongoDB successfully.")

# Function to start Selenium WebDriver
def start_driver(option):
    chrome_options = Options()
    # chrome_options.add_argument("--headless")  # Run in headless mode
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920x1080")
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
        ## plase install phantom wallet and connect the wallet in kolscan.io manually
        # Save cookies and local storage
        cookies = driver.get_cookies()
        local_storage = driver.execute_script("return window.localStorage;")

        with open(session_file, 'wb') as file:
            pickle.dump({'cookies': cookies, 'local_storage': local_storage}, file)
    return driver



driver_trades = start_driver("trades")
driver_leaders = start_driver("leaderboard")
# Scraper for /trades
def scrape_trades(driver):
    
    try:
        trades_transaction_items = driver.find_elements(By.XPATH, "//*[contains(@class, 'transaction_transactionContainer')]")
        trades = []

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
                trades.append({
                    "Buy_Sell": buy_sell,
                    "Token_Amount": token_amount,
                    "Token": token,
                    "Sol_Amount": sol_amount,
                    "Time": time,
                    "Time_Ago": timeAgo,
                    "Link": link

                })
            except Exception as e:
                print(f"Error extracting data from a transaction: {e}")
        return trades

    finally:
        driver.quit()

# Scraper for /leaderboard
def scrape_leaderboard(driver):
    driver.get("https://kolscan.io/leaderboard")

    try:
        wait = WebDriverWait(driver, 10)
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

            leaders.append({"avatar": avatar, "username":username, "twitter_link":twitter_link, "wallet_address": wallet_address, "buy": buy, "sell": sell, "total_profit":total_profit, "usd_value": usd_value})

        return leaders

    finally:
        driver.quit()

# Flask Routes
@app.route("/trades", methods=["GET"])
def get_trades():
    return jsonify({"trades": scrape_trades(driver_trades)})

@app.route("/leader", methods=["GET"])
def get_leaderboard():
    # Ensure the leaders collection exists
    ensure_leaders_collection()

    # Scrape the leaderboard data
    leaderboard_data = scrape_leaderboard(driver_leaders)

    # Insert the data into MongoDB
    insert_leaders_data(leaderboard_data)

    # Return the data as a JSON response
    return jsonify({"leaderboard": leaderboard_data})

if __name__ == "__main__":
    app.run()
