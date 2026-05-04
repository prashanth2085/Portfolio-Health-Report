import pandas as pd
import yfinance as yf
import requests
import os
import time

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Switched to HTML parsing which is 100x safer for Telegram
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Telegram API Error: {response.text}")
    except Exception as e:
        print(f"Telegram Error: {e}")

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

def run_scanner():
    try:
        file_path = None
        if os.path.exists('holdings.xlsx'):
            file_path = 'holdings.xlsx'
            df_raw = pd.read_excel(file_path, header=None)
        elif os.path.exists('holdings.csv'):
            file_path = 'holdings.csv'
            df_raw = pd.read_csv(file_path, header=None)
        else:
            send_telegram_message("⚠️ <b>Bot Alert</b>: I cannot find holdings.xlsx or holdings.csv in GitHub!")
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
        send_telegram_message(f"⚠️ <b>Bot Alert</b>: Error reading file: {e}")
        return

    fresh_capital = 100000 
    min_roe = 0.15 
    actions_to_take = []
    
    for index, row in df_clean.iterrows():
        symbol = str(row['Symbol']).strip()
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

            if current_price <= auto_stop_price:
                actions_to_take.append(f"🔴 <b>EXIT (Stop-Loss)</b>: {symbol}\nSell all {quantity} shares at ₹{current_price:.2f}.")
            elif change_pct <= -15 and long_term_bullish:
                if is_high_quality and macd_bullish:
                    alloc_pct = 0.30 if change_pct <= -35 else 0.25 if change_pct <= -25 else 0.10
                    shares_to_buy = int((fresh_capital * alloc_pct) / current_price) if current_price > 0 else 0
                    actions_to_take.append(f"🟢 <b>SCALE IN ({int(alloc_pct*100)}% Tranche)</b>: {symbol}\nBuy {shares_to_buy} shares at ₹{current_price:.2f}.")
                else:
                    actions_to_take.append(f"⚠️ <b>VALUE TRAP</b>: {symbol}\nFailed quality filter.")
            elif change_pct >= 25 and current_rsi > 70:
                sell_pct = 1.0 if change_pct >= 100 else 0.40 if change_pct >= 60 else 0.30 if change_pct >= 45 else 0.20 if change_pct >= 35 else 0.10
                shares_to_sell = max(1, int(quantity * sell_pct))
                actions_to_take.append(f"🟡 <b>TAKE PROFIT</b>: {symbol}\nSell {shares_to_sell} shares at ₹{current_price:.2f}.")
            elif not long_term_bullish and change_pct < -20:
                actions_to_take.append(f"🔴 <b>HIGH-RISK EXIT</b>: {symbol}\nBroken 200-EMA.")
        except Exception:
            pass

    if actions_to_take:
        critical_exits = [a for a in actions_to_take if "🔴" in a]
        profit_targets = [a for a in actions_to_take if "🟡" in a]
        buy_setups = [a for a in actions_to_take if "🟢" in a or "⚠️" in a]

        main_message = "📊 <b>Execution Plan (Trade Triage)</b>\n\n"
        
        if critical_exits:
            main_message += "🚨 <b>PRIORITY 1: CRITICAL EXITS</b>\n"
            main_message += "\n\n".join(critical_exits[:5])
            if len(critical_exits) > 5:
                main_message += f"\n<i>...and {len(critical_exits) - 5} more exits pending.</i>\n"
            main_message += "\n\n"
            
        if profit_targets:
            main_message += "💰 <b>PRIORITY 2: PRIME PROFIT TAKING</b>\n"
            main_message += "\n\n".join(profit_targets[:5])
            if len(profit_targets) > 5:
                main_message += f"\n<i>...and {len(profit_targets) - 5} more profit targets.</i>\n"
            main_message += "\n\n"
            
        if buy_setups:
            main_message += "🛒 <b>PRIORITY 3: BUY SETUPS</b>\n"
            main_message += "\n\n".join(buy_setups[:5])
            if len(buy_setups) > 5:
                main_message += f"\n<i>...and {len(buy_setups) - 5} more buy setups.</i>\n"

        send_telegram_message(main_message)

        chunk_size = 20
        if len(critical_exits) > 5:
            time.sleep(1.5) 
            for i in range(5, len(critical_exits), chunk_size):
                chunk = critical_exits[i : i + chunk_size]
                send_telegram_message("📂 <b>Full List of Exits (Continued):</b>\n\n" + "\n\n".join(chunk))
                time.sleep(1.5)
            
        if len(profit_targets) > 5:
            time.sleep(1.5)
            for i in range(5, len(profit_targets), chunk_size):
                chunk = profit_targets[i : i + chunk_size]
                send_telegram_message("📂 <b>Full List of Profits (Continued):</b>\n\n" + "\n\n".join(chunk))
                time.sleep(1.5)
            
        if len(buy_setups) > 5:
            time.sleep(1.5)
            for i in range(5, len(buy_setups), chunk_size):
                chunk = buy_setups[i : i + chunk_size]
                send_telegram_message("📂 <b>Full List of Buys (Continued):</b>\n\n" + "\n\n".join(chunk))
                time.sleep(1.5)
    else:
        send_telegram_message("📊 <b>Strategic Wealth Report</b>\nScan complete. Hold steady.")

if __name__ == "__main__":
    run_scanner()
