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
    watchlist = [
        "AIIL.NS", "AJANTPHARM.NS", "ANGELONE.NS", "APLAPOLLO.NS", "BPCL.NS",
        "CASTROLIND.NS", "COALINDIA.NS", "COLPAL.NS", "ERIS.NS", "GMDCLTD.NS",
        "GOLDBEES.NS", "IPCALAB.NS", "JUNIORBEES.NS", "KPITTECH.NS", "KSB.NS", 
        "MARICO.NS", "MINDSPACE.NS", "MOTHERSON.NS", "NATCOPHARM.NS", "NESTLEIND.NS", 
        "NIFTYBEES.NS", "NXST.NS", "OIL.NS", "RAINBOW.NS", "SILVERBEES.NS", 
        "TCS.NS", "TORNTPHARM.NS", "VGUARD.NS", "VIJAYA.NS"
    ]
    
    actions_to_take = []
    holding_steady = []
    
    for yf_symbol in watchlist:
        time.sleep(0.25) # Stealth delay
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
                actions_to_take.append(f"🟢 *BUY / SIP*: {symbol_name} (₹{current_price:.2f} | RSI: {current_rsi:.0f})")
            elif current_rsi >= 75:
                actions_to_take.append(f"🟡 *TRIM PROFITS*: {symbol_name} (₹{current_price:.2f} | RSI: {current_rsi:.0f})")
            elif current_price < ema_200 and float(hist['Close'].iloc[-2]) >= float(hist['EMA_200'].iloc[-2]):
                actions_to_take.append(f"🔴 *TREND BROKEN*: {symbol_name} (₹{current_price:.2f})")
            else:
                # Catching the "hidden" stocks that don't need action
                holding_steady.append(f"▫️ {symbol_name}: ₹{current_price:.2f} (RSI: {current_rsi:.0f})")
                
        except Exception:
            pass

        # 1. Send the URGENT Actions Message First
    if actions_to_take:
        urgent_message = "🚨 *ACTION REQUIRED:*\n" + "\n".join(actions_to_take)
        send_telegram_message(urgent_message)
    else:
        send_telegram_message("✅ *Smallcase Watchlist: No urgent actions required today.*")

    # 2. Send the "Holding Steady" list as a completely separate, quiet message
    if holding_steady:
        time.sleep(1) # Ensures this text arrives second
        steady_message = "🛡 *HOLDING STEADY (No Action Needed):*\n" + "\n".join(holding_steady)
        
        # Check if the holding list is too long for one Telegram message (4096 char limit)
        if len(steady_message) > 4000:
            send_telegram_message(steady_message[:4000])
        else:
            send_telegram_message(steady_message)


if __name__ == "__main__":
    run_watchlist_scanner()
