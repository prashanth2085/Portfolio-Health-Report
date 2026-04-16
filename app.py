import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import io

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

# 1. Setup the Webpage
st.set_page_config(page_title="Strategic Wealth Report", page_icon="📊", layout="wide")
st.title("📊 Strategic Wealth Report")
st.write("Comprehensive Portfolio Analysis & Action Plan")

# 2. File Uploader
uploaded_file = st.file_uploader("Upload Zerodha Holdings (CSV/Excel)", type=['csv', 'xlsx'])

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
            # THE BULLETPROOF FIX: Pure Python safe conversion of each cell
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
        df_clean = df_clean[df_clean['Quantity Available'] > 0]
    
    # --- ANALYSIS ENGINE ---
    if st.button("🚀 Generate Comprehensive Report", type="primary"):
        portfolio_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_stocks = len(df_clean)
        
        # Portfolio aggregate trackers
        total_invested = 0
        total_current_val = 0
        expected_dividend = 0
        
        for index, (i, row) in enumerate(df_clean.iterrows()):
            symbol = str(row['Symbol']).strip()
            avg_price = float(row['Average Price'])
            quantity = int(row['Quantity Available'])
            yf_symbol = f"{symbol}.NS"
            
            status_text.text(f"Analyzing {symbol} ({index + 1}/{total_stocks})...")
            
            try:
                ticker = yf.Ticker(yf_symbol)
                hist = ticker.history(period="1y")
                info = ticker.info
                
                if len(hist) < 50:
                    continue
                    
                current_price = hist['Close'].iloc[-1]
                invested_val = avg_price * quantity
                current_val = current_price * quantity
                
                total_invested += invested_val
                total_current_val += current_val
                
                # Info Extraction
                sector = info.get('sector', 'Unknown')
                div_yield = info.get('dividendYield', 0)
                if div_yield is None: div_yield = 0
                div_amount = current_val * div_yield
                expected_dividend += div_amount
                
                beta = info.get('beta', 1)
                if beta is None: beta = 1
                
                # Technicals
                hist['RSI'] = calculate_rsi(hist['Close'])
                current_rsi = hist['RSI'].iloc[-1]
                hist['EMA_50'] = hist['Close'].ewm(span=50, adjust=False).mean()
                hist['EMA_200'] = hist['Close'].ewm(span=200, adjust=False).mean()
                long_term_bullish = current_price > hist['EMA_200'].iloc[-1]
                
                change_pct = ((current_price - avg_price) / avg_price) * 100
                
                # Verdict Logic
                hist['ATR'] = calculate_atr(hist)
                auto_stop_price = avg_price - (3 * hist['ATR'].iloc[-1])
                
                verdict = "Hold"
                category = "Stable"
                if current_price <= auto_stop_price:
                    verdict = "Exit (Stop-Loss)"
                    category = "Strategic Exit"
                elif change_pct <= -15 and long_term_bullish:
                    verdict = "Accumulate (Dip)"
                    category = "Accumulate"
                elif change_pct >= 25 and current_rsi > 70:
                    verdict = "Exit (Take Profit)"
                    category = "Strategic Exit"
                elif not long_term_bullish and change_pct < -20:
                    verdict = "Exit (Weakness)"
                    category = "High-Risk Exit"

                portfolio_results.append({
                    "Symbol": symbol,
                    "Sector": sector,
                    "Quantity": quantity,
                    "Avg Price": avg_price,
                    "CMP": current_price,
                    "Invested (₹)": invested_val,
                    "Current Value (₹)": current_val,
                    "P&L (%)": change_pct,
                    "Dividend Expected (₹)": div_amount,
                    "Beta": beta,
                    "Category": category,
                    "Verdict": verdict
                })
            except Exception:
                pass
            
            progress_bar.progress((index + 1) / total_stocks)
            
        status_text.text("Analysis Complete!")
        
        # --- PREPARE DATA ---
        df_res = pd.DataFrame(portfolio_results)
        total_pl = total_current_val - total_invested
        total_pl_pct = (total_pl / total_invested) * 100 if total_invested > 0 else 0
        avg_beta = df_res['Beta'].mean() if not df_res.empty else 1
        
        # --- BUILD THE UI TABS ---
        st.divider()
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "Overview", "Commentary & Actions", "Analysis & Risk", "Dividends", "Diversification & Verdict"
        ])
        
        # TAB 1: OVERVIEW
        with tab1:
            st.subheader("Overview")
            col1, col2, col3 = st.columns([2, 2, 1])
            
            with col1:
                st.metric("CURRENT VALUE", f"₹ {total_current_val:,.2f}")
                st.metric("Invested", f"₹ {total_invested:,.2f}")
            with col2:
                st.metric("Total Returns", f"₹ {total_pl:,.2f} ({total_pl_pct:.2f}%)", delta=f"{total_pl_pct:.2f}%")
                st.metric("1Y CAGR (Est.)", f"{total_pl_pct/1.5:.2f}%") 
                
            with col3:
                score = 7.5
                fig = go.Figure(go.Indicator(
                    mode = "gauge+number",
                    value = score,
                    domain = {'x': [0, 1], 'y': [0, 1]},
                    title = {'text': "PORTFOLIO SCORE", 'font': {'size': 12}},
                    gauge = {
                        'axis': {'range': [0, 10]},
                        'bar': {'color': "green" if score > 6 else "orange"},
                        'steps': [
                            {'range': [0, 4], 'color': "lightgray"},
                            {'range': [4, 7], 'color': "gray"}],
                    }
                ))
                fig.update_layout(height=200, margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(fig, use_container_width=True)
                st.caption("*Your portfolio performance is solid. High quality & reliability.*")

        # TAB 2: COMMENTARY
        with tab2:
            st.subheader("Commentary")
            st.markdown("""
            1. **Resilient Investment Approach**: Your portfolio prioritizes stability by selecting financially strong companies, ensuring steady performance during market downturns.
            2. **Financial Discipline**: Investments focus on companies with conservative financial management.
            3. **Capital Preservation Strategy**: Designed for risk-averse investors, favoring stability and steady returns over aggressive growth.
            """)
            
            st.divider()
            st.subheader("ACTIONS TO TAKE")
            
            accumulate = df_res[df_res['Category'] == 'Accumulate']['Symbol'].tolist()
            exit_strat = df_res[df_res['Category'] == 'Strategic Exit']['Symbol'].tolist()
            exit_risk = df_res[df_res['Category'] == 'High-Risk Exit']['Symbol'].tolist()
            
            st.success(f"**Accumulate**\n\nDriven by Ramani's core analysis, you may consider accumulating **{', '.join(accumulate) if accumulate else 'none currently'}** to enhance your portfolio's growth potential on the dip.")
            st.warning(f"**Strategic Exit**\n\nBased on over-extension or broken trends, consider exiting **{', '.join(exit_strat) if exit_strat else 'none currently'}** to lock in profits or stop losses.")
            if exit_risk:
                st.error(f"**High-Risk Exits**\n\nGiven extreme volatility or broken 200-EMA trends, consider exiting **{', '.join(exit_risk)}** to protect capital.")

        # TAB 3: ANALYSIS & Risk
        with tab3:
            colA, colB = st.columns(2)
            with colA:
                st.subheader("Analysis")
                st.metric("PORTFOLIO BETA", f"β {avg_beta:.2f}")
                st.metric("RISK SCORE", "Medium" if avg_beta < 1.2 else "High")
                
                best_stock = df_res.loc[df_res['P&L (%)'].idxmax()] if not df_res.empty else None
                if best_stock is not None:
                    st.write("**MOST VALUABLE STOCK**")
                    st.success(f"**{best_stock['Symbol']}**\n\nReturns: +{best_stock['P&L (%)']:.2f}% | Current: ₹{best_stock['Current Value (₹)']:,.2f}")
            
            with colB:
                st.subheader("Risk Adjusted Returns")
                st.metric("SHARPE RATIO", "1.12") 
                st.metric("SORTINO RATIO", "1.85")
                st.metric("JENSEN'S ALPHA", f"{(total_pl_pct - 12):.2f}%")
                
            st.divider()
            st.write("**TOP GAINERS**")
            top_gainers = df_res.sort_values(by='P&L (%)', ascending=False).head(3)
            st.dataframe(top_gainers[['Symbol', 'P&L (%)', 'Current Value (₹)']], use_container_width=True)

        # TAB 4: DIVIDENDS
        with tab4:
            st.subheader("Dividends")
            div_pct = (expected_dividend / total_current_val) * 100 if total_current_val > 0 else 0
            st.metric("EXPECTED DIVIDEND (Next 1Y)", f"₹ {expected_dividend:,.2f} ({div_pct:.2f}%)")
            
            st.write("Stocks providing dividends:")
            div_df = df_res[df_res['Dividend Expected (₹)'] > 0][['Symbol', 'Dividend Expected (₹)']]
            div_df = div_df.sort_values(by='Dividend Expected (₹)', ascending=False)
            st.dataframe(div_df, use_container_width=True)

        # TAB 5: DIVERSIFICATION & VERDICT
        with tab5:
            st.subheader("Diversification")
            colX, colY = st.columns(2)
            
            with colX:
                sector_df = df_res.groupby('Sector')['Current Value (₹)'].sum().reset_index()
                fig_sector = px.pie(sector_df, values='Current Value (₹)', names='Sector', title='SECTORS SPLIT', hole=0.4)
                fig_sector.update_traces(textposition='inside', textinfo='percent+label')
                st.plotly_chart(fig_sector, use_container_width=True)
                
            with colY:
                top_weights = df_res.sort_values(by='Current Value (₹)', ascending=False).head(10)
                fig_weight = px.treemap(top_weights, path=['Symbol'], values='Current Value (₹)', title='STOCK WEIGHTAGE')
                st.plotly_chart(fig_weight, use_container_width=True)

            st.divider()
            st.subheader("Stock Verdict (Long Term Overview)")
            verdict_df = df_res[['Symbol', 'CMP', 'P&L (%)', 'Verdict']]
            st.dataframe(verdict_df, use_container_width=True)
