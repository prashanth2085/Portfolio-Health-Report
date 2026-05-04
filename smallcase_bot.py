import pandas as pd
import yfinance as yf
import requests
import os
import time

# --- SETUP TELEGRAM ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Error: {e}")

def calculate_rsi(prices, window=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/window, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/window, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def run_watchlist_scanner():
    # Your Exact Smallcase Watchlist (Mapped to Yahoo Finance Tickers)
    watchlist = [
        "AIIL.NS", "AJANTPHARM.NS", "ANGELONE.NS", "APLAPOLLO.NS", "BPCL.NS",
        "CASTROLIND.NS", "COALINDIA.NS", "COLPAL.NS", "ERIS.NS", "GMDCLTD.NS",
        "GOLDBEES.NS", "IPCALAB.NS", "JUNIORBEES.NS", "KPITTECH.NS", "KSB.NS", 
        "MARICO.NS", "MINDSPACE.NS", "MOTHERSON.NS", "NATCOPHARM.NS", "NESTLEIND.NS", 
        "NIFTYBEES.NS", "NXST.NS", "OIL.NS", "RAINBOW.NS", "SILVERBEES.NS", 
        "TCS.NS", "TORNTPHARM.NS", "VGUARD.NS", "VIJAYA.NS"
    ]
    
    actions_to_take = []
    
    for yf_symbol in watchlist:
        time.sleep(0.25) # Stealth delay so Yahoo doesn't block the bot
        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="1y")
            if len(hist) < 200: continue
            
            current_price = float(hist['Close'].iloc[-1])
            hist['RSI'] = calculate_rsi(hist['Close'])
            current_rsi = float(hist['RSI'].iloc[-1])
            hist['EMA_200'] = hist['Close'].ewm(span=200, adjust=False).mean()
            ema_200 = float(hist['EMA_200'].iloc[-1])
            
            symbol_name = yf_symbol.replace('.NS', '')

            # Watchlist Mechanical Rules
            if current_price > ema_200 and current_rsi <= 40:
                actions_to_take.append(f"🟢 *BUY / SIP SETUP*: {symbol_name}\nUptrending but currently oversold (RSI: {current_rsi:.1f}). Good spot to add. Price: ₹{current_price:.2f}")
            elif current_rsi >= 75:
                actions_to_take.append(f"🟡 *OVERBOUGHT*: {symbol_name}\nRunning very hot (RSI: {current_rsi:.1f}). Consider trimming profits. Price: ₹{current_price:.2f}")
            elif current_price < ema_200 and float(hist['Close'].iloc[-2]) >= float(hist['EMA_200'].iloc[-2]):
                actions_to_take.append(f"🔴 *TREND BROKEN*: {symbol_name}\nJust crossed below the 200-EMA support. Price: ₹{current_price:.2f}")
                
        except Exception:
            pass

    # Send Telegram Alert
    if actions_to_take:
        message = "🎯 *Smallcase Watchlist Alert*\n\n" + "\n\n".join(actions_to_take)
        send_telegram_message(message)
    else:
        send_telegram_message("🎯 *Smallcase Watchlist*\nScan complete. No extreme setups triggered today. Hold steady.")

if __name__ == "__main__":
    run_watchlist_scanner()
