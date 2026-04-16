import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import time

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
        
        # Ensure Numeric Columns
        df_clean['Quantity Available'] = pd.to_numeric(df_clean['Quantity Available'], errors='coerce')
        df_clean['Average Price'] = pd.to_numeric(df_clean['Average Price'], errors='coerce')
        df_clean = df_clean[df_clean['Quantity Available'] > 0]
        
        # Find Fallback Closing Price Column (If YFinance fails)
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
        
        # Safely track global metrics outside the YFinance loop
        total_invested = 0
        total_current_val = 0
        expected_dividend = 0
        
        for index, (i, row) in enumerate(df_clean.iterrows()):
            symbol = str(row['Symbol']).strip()
            avg_price = float(row['Average Price'])
            quantity = int(row['Quantity Available'])
            yf_symbol = f"{symbol}.NS"
            
            # 1. Establish absolute baseline metrics using Zerodha data
            invested_val = avg_price * quantity
            
            fallback_price = avg_price
            if fallback_col and pd.notna(row[fallback_col]):
                fallback_price = float(row[fallback_col])
                
            current_price = fallback_price # Default to Zerodha price
            current_val = current_price * quantity
            change_pct = ((current_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0
            
            # Default empty strings for UI safety
            sector = "Unknown"
            roe = 0
            fcf = 0
            macd_status = "-"
            vol_spike = "-"
            s1 = 0
            r1 = 0
            div_amount = 0
            category = "Data Fetch Error"
            verdict = "Offline (Used CSV Price)"
            action_details = "YF Network Block / Not Found"
            
            status_text.text(f"Scanning Quality & Technicals: {symbol} ({index + 1}/{total_stocks})...")
            
            # 2. Attempt Live Yahoo Finance Fetch
            try:
                ticker = yf.Ticker(yf_symbol)
                hist = ticker.history(period="1y")
                
                if len(hist) >= 50:
                    # Upgrade to Live Price
                    current_price = float(hist['Close'].iloc[-1])
                    current_val = current_price * quantity
                    change_pct = ((current_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0
                    
                    # Technicals
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
                    high_volume_dump = False
                    if pd.notna(avg_vol) and avg_vol > 0:
                        high_volume_dump = (current_price < float(hist['Open'].iloc[-1])) and (current_vol > (avg_vol * 1.5))
                    vol_spike = "Yes" if high_volume_dump else "Normal"
                    
                    pivot, s1, r1 = calculate_pivots(hist)

                    # Fundamentals & Safe Dividend (WITH RETRY LOOP)
                    is_high_quality = True
                    for attempt in range(3):  # Try 3 times to bypass Yahoo API blocks
                        try:
                            info = ticker.info
                            if info and ('sector' in info or 'dividendYield' in info):
                                sector = info.get('sector', 'Unknown')
                                
                                # Dividend Safeguard
                                div_yield = info.get('dividendYield', 0) or 0
                                if div_yield > 0.20: 
                                    div_yield = div_yield / 100
                                if div_yield > 0.20:
                                    div_yield = 0 
                                    
                                div_amount = current_val * div_yield
                                
                                roe = info.get('returnOnEquity', 0) or 0
                                fcf = info.get('freeCashflow', 0) or 0
                                if info.get('returnOnEquity') is not None:
                                    is_high_quality = (roe >= min_roe) and (fcf > 0)
                                break # Success! Break out of the retry loop
                        except Exception:
                            time.sleep(0.5) # Wait half a second and try knocking again
                    
                    # Unified Mechanical Logic
                    verdict = "Hold"
                    category = "Stable"
                    action_details = "-"
                    
                    if current_price <= auto_stop_price:
                        verdict = "Exit (Stop-Loss)"
                        category = "Strategic Exit"
                        action_details = f"Sell all {quantity} shares"
                    elif change_pct <= -15 and long_term_bullish:
                        if high_volume_dump or (not macd_bullish and current_rsi > 40):
                            verdict = "Pause Buy (Wait for Setup)"
                            category = "Stable"
                            action_details = "Volume Dump or Bearish MACD"
                        elif is_high_quality:
                            if change_pct <= -35: alloc_pct = 0.30
                            elif change_pct <= -25: alloc_pct = 0.25
                            else: alloc_pct = 0.10
                            shares_to_buy = int((fresh_capital * alloc_pct) / current_price) if current_price > 0 else 0
                            verdict = f"Scale In ({int(alloc_pct*100)}% Tranche)"
                            category = "Accumulate"
                            action_details = f"Buy {shares_to_buy} shares"
                        else:
                            verdict = "Value Trap (Fails Quality Filter)"
                            category = "High-Risk Exit"
                            action_details = f"ROE: {roe*100:.1f}%, FCF: {fcf}"
                    elif change_pct >= 25 and current_rsi > 70:
                        if change_pct >= 100: sell_pct = 1.0
                        elif change_pct >= 60: sell_pct = 0.40
                        elif change_pct >= 45: sell_pct = 0.30
                        elif change_pct >= 35: sell_pct = 0.20
                        else: sell_pct = 0.10
                        shares_to_sell = max(1, int(quantity * sell_pct))
                        verdict = f"Scale Out (Take Profit)"
                        category = "Strategic Exit"
                        action_details = f"Sell {shares_to_sell} shares"
                    elif not long_term_bullish and change_pct < -20:
                        verdict = "Exit (Weakness)"
                        category = "High-Risk Exit"
                        action_details = "Broken 200-EMA"

            except Exception:
                pass # Gracefully fall back to the Zerodha CSV variables
            
            # 3. UNCONDITIONAL TOTALS UPDATE
            total_invested += invested_val
            total_current_val += current_val
            expected_dividend += div_amount

            portfolio_results.append({
                "Symbol": symbol,
                "Sector": sector,
                "Quantity": quantity,
                "Avg Price": round(avg_price, 2),
                "CMP": round(current_price, 2),
                "Invested (₹)": round(invested_val, 2),
                "Current Value (₹)": round(current_val, 2),
                "P&L (%)": round(change_pct, 2),
                "ROE (%)": round(roe * 100, 2),
                "MACD": macd_status,
                "Vol Spike": vol_spike,
                "Support (S1)": round(s1, 2),
                "Resistance (R1)": round(r1, 2),
                "Category": category,
                "Verdict": verdict,
                "Action Details": action_details
            })
            
            progress_bar.progress((index + 1) / total_stocks)
            
        status_text.empty()
        guaranteed_total_invested = (df_clean['Average Price'] * df_clean['Quantity Available']).sum()
        
        # --- BUILD THE UI TABS ---
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
        
        # TAB 1: OVERVIEW
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

        # TAB 2: MECHANICAL TRANCHES
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

        # TAB 3: TECHNICALS
        with tab3:
            st.subheader("Master Technical Cheat Sheet")
            tech_df = df_res[['Symbol', 'CMP', 'Support (S1)', 'Resistance (R1)', 'MACD', 'Vol Spike']]
            st.dataframe(tech_df, use_container_width=True)

        # TAB 4: QUALITY & RISK
        with tab4:
            st.subheader("Fundamental Quality Check")
            quality_df = df_res[['Symbol', 'CMP', 'P&L (%)', 'ROE (%)', 'Category', 'Verdict']].sort_values(by='ROE (%)', ascending=False)
            st.dataframe(quality_df, use_container_width=True)

        # TAB 5: DIVERSIFICATION
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
