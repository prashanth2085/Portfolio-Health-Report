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

# --- CUSTOM MATH FUNCTIONS ---
def calculate_rsi(prices, window=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/window, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/window, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(hist, window=14):
    high_low = hist['High'] - hist['Low']
    high_close = (hist['High'] - hist['Close'].shift()).abs()
    low_close = (hist['Low'] - hist['Close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(window).mean()

def calculate_macd(prices, fast=12, slow=26, signal=9):
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    return macd, macd_signal

# --- MAIN ENGINE ---
def run_scanner():
    # 1. Read the local holdings file
    try:
        file_path = None
        if os.path.exists('holdings.xlsx'):
            file_path = 'holdings.xlsx'
            df_raw = pd.read_excel(file_path, header=None)
        elif os.path.exists('holdings.csv'):
            file_path = 'holdings.csv'
            df_raw = pd.read_csv(file_path, header=None)
        else:
            send_telegram_message("⚠️ *Bot Alert*: I cannot find `holdings.xlsx` or `holdings.csv` in GitHub!")
            return

        header_row_idx = 0
        for idx, row in df_raw.iterrows():
            row_str = " ".join([str(cell).lower() for cell in row.values if pd.notna(cell)])
            if 'symbol' in row_str or 'instrument' in row_str:
                header_row_idx = idx
                break
                
        if file_path.endswith('.xlsx'):
            df_clean = pd.read_excel(file_path, skiprows=header_row_idx)
        else:
            df_clean = pd.read_csv(file_path, skiprows=header_row_idx)
            
        df_clean.columns = df_clean.columns.astype(str).str.strip()
        rename_map = {'Instrument': 'Symbol', 'Avg. cost': 'Average Price', 'Avg Price': 'Average Price', 'Qty.': 'Quantity Available', 'Qty': 'Quantity Available', 'Quantity': 'Quantity Available'}
        df_clean = df_clean.rename(columns=rename_map)
        df_clean = df_clean.dropna(subset=['Symbol', 'Average Price']).copy()
        df_clean['Quantity Available'] = pd.to_numeric(df_clean['Quantity Available'], errors='coerce')
        df_clean['Average Price'] = pd.to_numeric(df_clean['Average Price'], errors='coerce')
        df_clean = df_clean[df_clean['Quantity Available'] > 0]
    except Exception as e:
        send_telegram_message(f"⚠️ *Bot Alert*: Error reading file: {e}")
        return

     # --- RING-FENCED STOCKS (SMALLCASE & ETFs) ---
    smallcase_ignore_list = [
        'AIIL', 'AJANTPHARM', 'ANGELONE', 'APLAPOLLO', 'BPCL', 'CASTROLIND', 
        'COALINDIA', 'COLPAL', 'ERIS', 'GMDCLTD', 'GOLDCASE', 'IPCALAB', 
        'JUNIORBEES', 'KPITTECH', 'KSB', 'MARICO', 'MINDSPACE-RR', 'MOTHERSON', 
        'NATCOPHARM', 'NESTLEIND', 'NIFTYBEES', 'NXST', 'OIL', 'RAINBOW', 
        'SILVERCASE', 'TCS', 'TORNTPHARM', 'VGUARD', 'VIJAYA'
    ]

    fresh_capital = 100000 
    min_roe = 0.15 
    
    actions = {'exits': [], 'profits': [], 'buys': []}
    
    # 2. Scan Portfolio
    for index, row in df_clean.iterrows():
        symbol = str(row['Symbol']).strip()
        
        # 🛡️ THE RING-FENCE CHECK: If it's in your Smallcase list, skip it instantly!
        if symbol in smallcase_ignore_list:
            continue

        avg_price = float(row['Average Price'])
        quantity = int(row['Quantity Available'])
        yf_symbol = f"{symbol}.NS"
        
        time.sleep(0.25)
        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="1y")
            if len(hist) < 50: continue
            
            current_price = float(hist['Close'].iloc[-1])
            change_pct = ((current_price - avg_price) / avg_price) * 100
            
            hist['RSI'] = calculate_rsi(hist['Close'])
            current_rsi = float(hist['RSI'].iloc[-1])
            hist['EMA_200'] = hist['Close'].ewm(span=200, adjust=False).mean()
            long_term_bullish = current_price > float(hist['EMA_200'].iloc[-1])
            
            hist['ATR'] = calculate_atr(hist)
            auto_stop_price = avg_price - (3 * float(hist['ATR'].iloc[-1]))
            
            macd, macd_signal = calculate_macd(hist['Close'])
            macd_bullish = float(macd.iloc[-1]) > float(macd_signal.iloc[-1])
            
            is_high_quality = True
            for attempt in range(3):
                try:
                    info = ticker.info
                    if info:
                        roe = info.get('returnOnEquity', 0) or 0
                        fcf = info.get('freeCashflow', 0) or 0
                        if info.get('returnOnEquity') is not None:
                            is_high_quality = (roe >= min_roe) and (fcf > 0)
                        break
                except: time.sleep(0.5)

            if current_price <= auto_stop_price or (not long_term_bullish and change_pct < -20):
                msg = f"🔴 *{symbol}*: Sell {quantity} shares @ ₹{current_price:.2f} *(P&L: {change_pct:.1f}%)*"
                actions['exits'].append({'msg': msg, 'score': change_pct})
                
            elif change_pct >= 25 and current_rsi > 70:
                sell_pct = 1.0 if change_pct >= 100 else 0.40 if change_pct >= 60 else 0.30 if change_pct >= 45 else 0.20 if change_pct >= 35 else 0.10
                shares_to_sell = max(1, int(quantity * sell_pct))
                msg = f"🟡 *{symbol}*: Sell {shares_to_sell} shares @ ₹{current_price:.2f} *(Gain: +{change_pct:.1f}%)*"
                actions['profits'].append({'msg': msg, 'score': change_pct})
                
            elif change_pct <= -15 and long_term_bullish and is_high_quality and macd_bullish:
                alloc_pct = 0.30 if change_pct <= -35 else 0.25 if change_pct <= -25 else 0.10
                shares_to_buy = int((fresh_capital * alloc_pct) / current_price) if current_price > 0 else 0
                msg = f"🟢 *{symbol}*: Buy {shares_to_buy} shares @ ₹{current_price:.2f} *(Dip: {change_pct:.1f}%)*"
                actions['buys'].append({'msg': msg, 'score': change_pct})
                
        except Exception:
            pass

    # 3. Format the Prioritized Telegram Message
    final_message = "📊 *Execution Plan (Trade Triage)*\n\n"
    has_actions = False

    actions['exits'] = sorted(actions['exits'], key=lambda x: x['score'])
    if actions['exits']:
        has_actions = True
        final_message += "🚨 *PRIORITY 1: CRITICAL EXITS (Stop-Loss/Weak)*\n"
        for i, item in enumerate(actions['exits'][:5]):
            final_message += f"{i+1}. {item['msg']}\n"
        if len(actions['exits']) > 5:
            final_message += f"_+ {len(actions['exits']) - 5} more exits pending._\n"
        final_message += "\n"

    actions['profits'] = sorted(actions['profits'], key=lambda x: x['score'], reverse=True)
    if actions['profits']:
        has_actions = True
        final_message += "💰 *PRIORITY 2: PRIME PROFIT TAKING (Overextended)*\n"
        for i, item in enumerate(actions['profits'][:5]):
            final_message += f"{i+1}. {item['msg']}\n"
        if len(actions['profits']) > 5:
            final_message += f"_+ {len(actions['profits']) - 5} more profit targets._\n"
        final_message += "\n"

    actions['buys'] = sorted(actions['buys'], key=lambda x: x['score'])
    if actions['buys']:
        has_actions = True
        final_message += "🌱 *PRIORITY 3: BEST SCALE-IN VALUE (Deepest Dips)*\n"
        for i, item in enumerate(actions['buys'][:5]):
            final_message += f"{i+1}. {item['msg']}\n"
        if len(actions['buys']) > 5:
            final_message += f"_+ {len(actions['buys']) - 5} more buy targets._\n"

    if has_actions:
        send_telegram_message(final_message)
    else:
        send_telegram_message("📊 *Strategic Wealth Report*\nScan complete. No mechanical actions triggered today. Hold steady.")

if __name__ == "__main__":
    run_scanner()
