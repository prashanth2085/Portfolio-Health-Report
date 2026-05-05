import pandas as pd
import yfinance as yf
import requests
import os
import time

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Telegram API Error: {response.text}")
    except Exception as e:
        print(f"Telegram Error: {e}")

def send_telegram_document(text_content, filename="Holding_Steady.txt"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    # Create the text file
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(text_content)
    # Send the file to Telegram
    with open(filename, 'rb') as f:
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID}, files={'document': f})

def calculate_rsi(prices, window=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/window, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/window, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def run_watchlist_scanner():
    # Your Updated Smallcase Watchlist (Mapped to Yahoo Finance)
    watchlist = [
        "AIIL.NS", "AJANTPHARM.NS", "ANGELONE.NS", "APLAPOLLO.NS", "BHARTIARTL.NS", "BPCL.NS", 
        "CASTROLIND.NS", "COALINDIA.NS", "COLPAL.NS", "ERIS.NS", "GMDCLTD.NS", "GOLDBEES.NS", 
        "HUDCO.NS", "ICICIBANK.NS", "IPCALAB.NS", "JUNIORBEES.NS", "KPITTECH.NS", "KSB.NS", 
        "LT.NS", "MARICO.NS", "MINDSPACE.NS", "MOTHERSON.NS", "NATCOPHARM.NS", "NESTLEIND.NS", 
        "NIFTYBEES.NS", "NXST.NS", "OIL.NS", "RAINBOW.NS", "RELIANCE.NS", "SBIN.NS", "SCI.NS", 
        "SILVERBEES.NS", "SANGHVIMOV.NS", "TCS.NS", "TECHM.NS", "TORNTPHARM.NS", "VGUARD.NS", "VIJAYA.NS", "WABAG.NS"
    ]
    
    actions_to_take = []
    holding_steady = []
    
    for yf_symbol in watchlist:
        time.sleep(0.25)
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

            if current_price > ema_200 and current_rsi <= 40:
                actions_to_take.append(f"🟢 <b>BUY / SIP</b>: {symbol_name} (₹{current_price:.2f} | RSI: {current_rsi:.0f})")
            elif current_rsi >= 75:
                actions_to_take.append(f"🟡 <b>TRIM PROFITS</b>: {symbol_name} (₹{current_price:.2f} | RSI: {current_rsi:.0f})")
            elif current_price < ema_200 and float(hist['Close'].iloc[-2]) >= float(hist['EMA_200'].iloc[-2]):
                actions_to_take.append(f"🔴 <b>TREND BROKEN</b>: {symbol_name} (₹{current_price:.2f})")
            else:
                holding_steady.append(f"▫️ {symbol_name}: ₹{current_price:.2f} (RSI: {current_rsi:.0f})")
        except Exception:
            pass

    if actions_to_take:
        urgent_message = "🚨 <b>ACTION REQUIRED:</b>\n" + "\n".join(actions_to_take)
        send_telegram_message(urgent_message)
    else:
        send_telegram_message("✅ <b>Smallcase Watchlist: No urgent actions today.</b>")

    # --- SEND MESSAGE 2: THE SILENT TEXT FILE ATTACHMENT ---
    if holding_steady:
        time.sleep(1.5)
        steady_text = "🛡 HOLDING STEADY (No Action Needed):\n\n" + "\n".join(holding_steady)
        send_telegram_document(steady_text, filename="Holding_Steady.txt")

if __name__ == "__main__":
    run_watchlist_scanner()
