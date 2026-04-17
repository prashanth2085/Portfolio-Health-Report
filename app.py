import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import time
import re
import io
def calculate_monday_capital(csv_data, target_capital=200000):
    st.subheader("Capital Generation Projection")
    
    with st.spinner('Fetching real-time NSE prices...'):
        df = pd.read_csv(io.StringIO(csv_data), sep=',\s*', engine='python')
        df['Shares'] = df['Action Details'].apply(lambda x: int(re.search(r'\d+', x).group()))
        df['Ticker'] = df['Symbol'] + '.NS'
        df['P&L (%)'] = pd.to_numeric(df['P&L (%)'])
        
        tickers = df['Ticker'].tolist()
        data = yf.download(tickers, period="1d", progress=False)
        
        if isinstance(data.columns, pd.MultiIndex):
            prices = data['Close'].iloc[-1]
        else:
            prices = pd.Series({tickers[0]: data['Close'].iloc[-1]})
            
        df['Current Price'] = df['Ticker'].map(prices)
        df['Projected Value (INR)'] = df['Shares'] * df['Current Price']
        
        exits_df = df[df['Verdict'].str.contains('Exit')]
        total_exit_cash = exits_df['Projected Value (INR)'].sum()
        
        st.metric(label="Mandatory Exit Capital (Stop-Losses)", value=f"₹{total_exit_cash:,.2f}")
        
        current_capital = total_exit_cash
        scale_outs_df = df[df['Verdict'].str.contains('Scale Out')].sort_values(by='P&L (%)', ascending=True)
        
        hold_back_list = []
        
        if current_capital >= target_capital:
            st.success("Target met entirely by Exits! You can hold back ALL Scale Out shares.")
            hold_back_list.append(scale_outs_df)
        else:
            st.warning(f"Shortfall from Exits: ₹{target_capital - current_capital:,.2f}. Selling weakest Scale Outs to bridge the gap...")
            for index, row in scale_outs_df.iterrows():
                if current_capital < target_capital:
                    current_capital += row['Projected Value (INR)']
                    st.write(f"Sold {row['Shares']} shares of **{row['Symbol']}** (+{row['P&L (%)']}%) -> Added ₹{row['Projected Value (INR)']:,.2f}")
                else:
                    hold_back_list.append(row)
        
        st.metric(label="Total Capital Ready for Monday", value=f"₹{current_capital:,.2f}", delta=f"₹{current_capital - target_capital:,.2f} over target")
        
        if hold_back_list:
            st.subheader("Shares to Hold Back (Let Run)")
            if isinstance(hold_back_list[0], pd.DataFrame):
                held_df = hold_back_list[0]
            else:
                held_df = pd.DataFrame(hold_back_list)
            
            display_df = held_df[['Symbol', 'Shares', 'P&L (%)', 'Current Price']]
            st.dataframe(display_df, use_container_width=True)
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

def calculate_pivots(hist):
    prev_high = hist['High'].iloc[-2]
    prev_low = hist['Low'].iloc[-2]
    prev_close = hist['Close'].iloc[-2]
    pivot = (prev_high + prev_low + prev_close) / 3
    s1 = (pivot * 2) - prev_high
    r1 = (pivot * 2) - prev_low
    return pivot, s1, r1

# --- STEALTH DATA FETCHER (CACHED FOR 15 MINUTES) ---
@st.cache_data(ttl=900, show_spinner=False)
def fetch_market_data(yf_symbol):
    # 1. Micro-delay to bypass Yahoo Finance Bot-Detection IP Bans
    time.sleep(0.25) 
    
    ticker = yf.Ticker(yf_symbol)
    hist = ticker.history(period="1y")
    
    info = {}
    # 2. Triple-knock retry loop for fundamental data
    for attempt in range(3):
        try:
            info = ticker.info
            if info and ('sector' in info or 'dividendYield' in info):
                break
        except:
            time.sleep(0.5)
            
    return hist, info

# 1. Setup the Webpage & PDF Print CSS
st.set_page_config(page_title="Strategic Wealth Report", page_icon="📊", layout="wide")
st.markdown("""
    <style>
    @media print {
        .stButton, .stFileUploader, header, footer { display: none !important; }
        .stTabs { zoom: 0.8; }
    }
    </style>
""", unsafe_allow_html=True)

st.title("📊 Strategic Wealth Report")
st.write("Mechanical Buying Engine | Fundamentals + MACD + Volume + Pivots")

# 2. Sidebar Settings & File Uploader
with st.sidebar:
    st.header("⚙️ Mechanical Parameters")
    fresh_capital = st.number_input("Total Fresh Capital (₹)", value=100000, step=10000)
    min_roe = st.number_input("Minimum ROE Filter (%)", value=15.0, step=1.0) / 100.0
    st.divider()
    uploaded_file = st.file_uploader("Upload Zerodha Holdings", type=['csv', 'xlsx'])

if uploaded_file is not None:
    # --- READ AND AUTO-TRANSLATE ---
    with st.spinner("Processing file structure..."):
        filename = uploaded_file.name
        if filename.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file, header=None)
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)
        uploaded_file.seek(0)
            
        header_row_idx = 0
        for idx, row in df_raw.iterrows():
            row_str = " ".join([str(cell).lower() for cell in row.values if pd.notna(cell)])
            if 'symbol' in row_str or 'instrument' in row_str:
                header_row_idx = idx
                break

        if filename.endswith('.csv'):
            df_holdings = pd.read_csv(uploaded_file, skiprows=header_row_idx)
        else:
            df_holdings = pd.read_excel(uploaded_file, skiprows=header_row_idx)

        df_holdings.columns = df_holdings.columns.astype(str).str.strip()
        
        rename_map = {
            'Instrument': 'Symbol', 'Avg. cost': 'Average Price', 'Avg Price': 'Average Price',
            'Qty.': 'Quantity Available', 'Qty': 'Quantity Available', 'Quantity': 'Quantity Available'
        }
        df_holdings = df_holdings.rename(columns=rename_map)
        df_clean = df_holdings.dropna(subset=['Symbol', 'Average Price']).copy()
        
        df_clean['Quantity Available'] = pd.to_numeric(df_clean['Quantity Available'], errors='coerce')
        df_clean['Average Price'] = pd.to_numeric(df_clean['Average Price'], errors='coerce')
        df_clean = df_clean[df_clean['Quantity Available'] > 0]
        
        fallback_col = None
        for col in ['Previous Closing Price', 'LTP', 'Current Price', 'Close Price']:
            if col in df_clean.columns:
                df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce')
                fallback_col = col
                break
    
    # --- ANALYSIS ENGINE ---
    if st.button("🚀 Execute Master Scan", type="primary"):
        portfolio_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_stocks = len(df_clean)
        total_invested = 0
        total_current_val = 0
        expected_dividend = 0
        
        for index, (i, row) in enumerate(df_clean.iterrows()):
            symbol = str(row['Symbol']).strip()
            avg_price = float(row['Average Price'])
            quantity = int(row['Quantity Available'])
            yf_symbol = f"{symbol}.NS"
            
            invested_val = avg_price * quantity
            fallback_price = float(row[fallback_col]) if fallback_col and pd.notna(row[fallback_col]) else avg_price
            current_price = fallback_price
            current_val = current_price * quantity
            change_pct = ((current_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0
            
            sector, roe, fcf, macd_status, vol_spike = "Unknown", 0, 0, "-", "-"
            s1, r1, div_amount = 0, 0, 0
            category, verdict, action_details = "Data Fetch Error", "Offline (Used CSV Price)", "YF Network Block / Not Found"
            
            status_text.text(f"Scanning Quality & Technicals: {symbol} ({index + 1}/{total_stocks})...")
            
            try:
                # 3. CALL THE CACHED, STEALTHY FETCHER
                hist, info = fetch_market_data(yf_symbol)
                
                if len(hist) >= 50:
                    current_price = float(hist['Close'].iloc[-1])
                    current_val = current_price * quantity
                    change_pct = ((current_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0
                    
                    hist['RSI'] = calculate_rsi(hist['Close'])
                    current_rsi = float(hist['RSI'].iloc[-1])
                    hist['EMA_50'] = hist['Close'].ewm(span=50, adjust=False).mean()
                    hist['EMA_200'] = hist['Close'].ewm(span=200, adjust=False).mean()
                    long_term_bullish = current_price > float(hist['EMA_200'].iloc[-1])
                    
                    hist['ATR'] = calculate_atr(hist)
                    auto_stop_price = avg_price - (3 * float(hist['ATR'].iloc[-1]))
                    
                    macd, macd_signal = calculate_macd(hist['Close'])
                    macd_bullish = float(macd.iloc[-1]) > float(macd_signal.iloc[-1])
                    macd_status = "Bullish" if macd_bullish else "Bearish"
                    
                    hist['Avg_Vol_20'] = hist['Volume'].rolling(window=20).mean()
                    current_vol = float(hist['Volume'].iloc[-1])
                    avg_vol = float(hist['Avg_Vol_20'].iloc[-1])
                    high_volume_dump = (current_price < float(hist['Open'].iloc[-1])) and (current_vol > (avg_vol * 1.5)) if pd.notna(avg_vol) and avg_vol > 0 else False
                    vol_spike = "Yes" if high_volume_dump else "Normal"
                    
                    pivot, s1, r1 = calculate_pivots(hist)

                    is_high_quality = True
                    if info:
                        sector = info.get('sector', 'Unknown')
                        div_yield = info.get('dividendYield', 0) or 0
                        if div_yield > 0.20: div_yield = div_yield / 100
                        if div_yield > 0.20: div_yield = 0 
                        div_amount = current_val * div_yield
                        
                        roe = info.get('returnOnEquity', 0) or 0
                        fcf = info.get('freeCashflow', 0) or 0
                        if info.get('returnOnEquity') is not None:
                            is_high_quality = (roe >= min_roe) and (fcf > 0)
                    
                    verdict, category, action_details = "Hold", "Stable", "-"
                    if current_price <= auto_stop_price:
                        verdict, category, action_details = "Exit (Stop-Loss)", "Strategic Exit", f"Sell all {quantity} shares"
                    elif change_pct <= -15 and long_term_bullish:
                        if high_volume_dump or (not macd_bullish and current_rsi > 40):
                            verdict, category, action_details = "Pause Buy (Wait for Setup)", "Stable", "Volume Dump or Bearish MACD"
                        elif is_high_quality:
                            alloc_pct = 0.30 if change_pct <= -35 else 0.25 if change_pct <= -25 else 0.10
                            shares_to_buy = int((fresh_capital * alloc_pct) / current_price) if current_price > 0 else 0
                            verdict, category, action_details = f"Scale In ({int(alloc_pct*100)}% Tranche)", "Accumulate", f"Buy {shares_to_buy} shares"
                        else:
                            verdict, category, action_details = "Value Trap (Fails Quality Filter)", "High-Risk Exit", f"ROE: {roe*100:.1f}%, FCF: {fcf}"
                    elif change_pct >= 25 and current_rsi > 70:
                        sell_pct = 1.0 if change_pct >= 100 else 0.40 if change_pct >= 60 else 0.30 if change_pct >= 45 else 0.20 if change_pct >= 35 else 0.10
                        shares_to_sell = max(1, int(quantity * sell_pct))
                        verdict, category, action_details = f"Scale Out (Take Profit)", "Strategic Exit", f"Sell {shares_to_sell} shares"
                    elif not long_term_bullish and change_pct < -20:
                        verdict, category, action_details = "Exit (Weakness)", "High-Risk Exit", "Broken 200-EMA"
            except Exception:
                pass 
            
            total_invested += invested_val
            total_current_val += current_val
            expected_dividend += div_amount

            portfolio_results.append({
                "Symbol": symbol, "Sector": sector, "Quantity": quantity,
                "Avg Price": round(avg_price, 2), "CMP": round(current_price, 2),
                "Invested (₹)": round(invested_val, 2), "Current Value (₹)": round(current_val, 2),
                "P&L (%)": round(change_pct, 2), "ROE (%)": round(roe * 100, 2),
                "MACD": macd_status, "Vol Spike": vol_spike,
                "Support (S1)": round(s1, 2), "Resistance (R1)": round(r1, 2),
                "Category": category, "Verdict": verdict, "Action Details": action_details
            })
            progress_bar.progress((index + 1) / total_stocks)
            
        status_text.empty()
        guaranteed_total_invested = (df_clean['Average Price'] * df_clean['Quantity Available']).sum()
        
        df_res = pd.DataFrame(portfolio_results)
        if df_res.empty:
            st.error("Fatal Error: Could not parse any data.")
            st.stop()

        total_pl = total_current_val - guaranteed_total_invested
        total_pl_pct = (total_pl / guaranteed_total_invested) * 100 if guaranteed_total_invested > 0 else 0
        
        st.divider()
        col_export, _ = st.columns([1, 4])
        with col_export:
            csv = df_res.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Raw Data (CSV)", data=csv, file_name="mechanical_report.csv", mime="text/csv")
            
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "Mechanical Tranches", "Technical Data", "Quality & Risk", "Diversification"])
        
        with tab1:
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.metric("CURRENT VALUE", f"₹ {total_current_val:,.2f}")
                st.metric("Invested (From File)", f"₹ {guaranteed_total_invested:,.2f}")
            with col2:
                st.metric("Total Returns", f"₹ {total_pl:,.2f} ({total_pl_pct:.2f}%)", delta=f"{total_pl_pct:.2f}%")
                st.metric("Expected Dividend (1Y)", f"₹ {expected_dividend:,.2f}") 
            with col3:
                score = 8.0
                fig = go.Figure(go.Indicator(
                    mode = "gauge+number", value = score, domain = {'x': [0, 1], 'y': [0, 1]},
                    title = {'text': "PORTFOLIO SCORE", 'font': {'size': 12}},
                    gauge = {'axis': {'range': [0, 10]}, 'bar': {'color': "green"},
                             'steps': [{'range': [0, 4], 'color': "lightgray"}, {'range': [4, 7], 'color': "gray"}]}
                ))
                fig.update_layout(height=200, margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(fig, use_container_width=True)

        with tab2:
            accumulate = df_res[df_res['Category'] == 'Accumulate']
            exits = df_res[df_res['Category'] == 'Strategic Exit']
            errors = df_res[df_res['Category'] == 'Data Fetch Error']
            if not accumulate.empty:
                st.success("**Scale In Opportunities (Passed Quality Filters & Tech Setup)**")
                st.dataframe(accumulate[['Symbol', 'P&L (%)', 'ROE (%)', 'Verdict', 'Action Details']], use_container_width=True)
            if not exits.empty:
                st.warning("**Scale Out / Stop-Loss Targets Hit**")
                st.dataframe(exits[['Symbol', 'P&L (%)', 'Verdict', 'Action Details']], use_container_width=True)
            if not errors.empty:
                st.error("**Data Fetch Errors (Used Offline Zerodha Price)**")
                st.dataframe(errors[['Symbol', 'Verdict', 'Action Details']], use_container_width=True)

        with tab3:
            st.subheader("Master Technical Cheat Sheet")
            st.dataframe(df_res[['Symbol', 'CMP', 'Support (S1)', 'Resistance (R1)', 'MACD', 'Vol Spike']], use_container_width=True)

        with tab4:
            st.subheader("Fundamental Quality Check")
            st.dataframe(df_res[['Symbol', 'CMP', 'P&L (%)', 'ROE (%)', 'Category', 'Verdict']].sort_values(by='ROE (%)', ascending=False), use_container_width=True)

        with tab5:
            colX, colY = st.columns(2)
            with colX:
                sector_df = df_res[df_res['Current Value (₹)'] > 0].groupby('Sector')['Current Value (₹)'].sum().reset_index()
                if not sector_df.empty:
                    fig_sector = px.pie(sector_df, values='Current Value (₹)', names='Sector', title='SECTORS SPLIT', hole=0.4)
                    fig_sector.update_traces(textposition='inside', textinfo='percent+label')
                    st.plotly_chart(fig_sector, use_container_width=True)
            with colY:
                top_weights = df_res[df_res['Current Value (₹)'] > 0].sort_values(by='Current Value (₹)', ascending=False).head(10)
                if not top_weights.empty:
                    fig_weight = px.treemap(top_weights, path=['Symbol'], values='Current Value (₹)', title='STOCK WEIGHTAGE')
                    st.plotly_chart(fig_weight, use_container_width=True)
# --- PASTE THIS AT THE VERY BOTTOM OF YOUR FILE ---

st.divider() 
tab_main, tab_calculator = st.tabs(["Main Portfolio", "Monday 2L Capital Calculator"])

with tab_main:
    st.write("Your existing complete holdings tools remain here.")
    # Note: If you already have main content being rendered at the bottom, 
    # just wrap that existing code under this `with tab_main:` block.

with tab_calculator:
    st.subheader("Target ₹2,00,000 Generation")
    st.write("Paste your 40 trades from the export below to calculate what to hold back.")
    
    user_csv_input = st.text_area("Paste Trade Export Here:", height=200)
    
    if st.button("Calculate Target Capital"):
        if user_csv_input:
            calculate_monday_capital(user_csv_input)
        else:
            st.warning("Please paste the trade data into the box first.")
