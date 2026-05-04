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
            return # Silent exit if file is missing
            
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
        return

    critical_exits = []
    profit_targets = []
    
    # 2. Scan Portfolio
    for index, row in df_clean.iterrows():
        symbol = str(row['Symbol']).strip()
        avg_price = float(row['Average Price'])
        quantity = int(row['Quantity Available'])
        yf_symbol = f"{symbol}.NS"
        
        time.sleep(0.25) # Stealth delay
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
            
            # THE ORIGINAL LOGIC RESTORED
            if current_price <= auto_stop_price or (not long_term_bullish and change_pct < -20):
                critical_exits.append({'symbol': symbol, 'qty': quantity, 'price': current_price, 'pl': change_pct})
            elif change_pct >= 25 and current_rsi > 70:
                sell_pct = 1.0 if change_pct >= 100 else 0.40 if change_pct >= 60 else 0.30 if change_pct >= 45 else 0.20 if change_pct >= 35 else 0.10
                shares_to_sell = max(1, int(quantity * sell_pct))
                profit_targets.append({'symbol': symbol, 'qty': shares_to_sell, 'price': current_price, 'pl': change_pct})
                
        except Exception:
            pass

    # Sort the lists: Worst losses first, Biggest gains first
    critical_exits = sorted(critical_exits, key=lambda x: x['pl'])
    profit_targets = sorted(profit_targets, key=lambda x: x['pl'], reverse=True)

    # Recreate the exact text formatting you liked
    formatted_exits = [f"{i+1}. 🔴 {item['symbol']}: Sell {item['qty']} shares @ ₹{item['price']:.2f} (P&L: {item['pl']:.1f}%)" for i, item in enumerate(critical_exits)]
    formatted_profits = [f"{i+1}. 🟡 {item['symbol']}: Sell {item['qty']} shares @ ₹{item['price']:.2f} (Gain: +{item['pl']:.1f}%)" for i, item in enumerate(profit_targets)]

    if not formatted_exits and not formatted_profits:
        send_telegram_message("📊 *Strategic Wealth Report*\nScan complete. No mechanical actions triggered today. Hold steady.")
        return

    # ==========================================
    # 3. SEND MESSAGE 1: MAIN DASHBOARD
    # ==========================================
    main_message = "📊 *Execution Plan (Trade Triage)*\n\n"
    
    if formatted_exits:
        main_message += "🚨 *PRIORITY 1: CRITICAL EXITS (Stop-Loss/Weak)*\n"
        main_message += "\n".join(formatted_exits[:5])
        if len(formatted_exits) > 5:
            main_message += f"\n_+ {len(formatted_exits) - 5} more exits pending._\n"
        main_message += "\n\n"
        
    if formatted_profits:
        main_message += "💰 *PRIORITY 2: PRIME PROFIT TAKING (Overextended)*\n"
        main_message += "\n".join(formatted_profits[:5])
        if len(formatted_profits) > 5:
            main_message += f"\n_+ {len(formatted_profits) - 5} more profit targets._\n"

    send_telegram_message(main_message.strip())

    # ==========================================
    # 4. SEND MESSAGE 2 & 3: THE OVERFLOW TEXTS
    # ==========================================
    if len(formatted_exits) > 5:
        time.sleep(1) # Wait 1 second so messages arrive in order
        overflow_exits_msg = "📂 *Full List of Pending Exits (Continued):*\n" + "\n".join(formatted_exits[5:])
        send_telegram_message(overflow_exits_msg[:4000])

    if len(formatted_profits) > 5:
        time.sleep(1)
        overflow_profits_msg = "📂 *Full List of Profit Targets (Continued):*\n" + "\n".join(formatted_profits[5:])
        send_telegram_message(overflow_profits_msg[:4000])

if __name__ == "__main__":
    run_scanner()
