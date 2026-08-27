import streamlit as st
import pandas as pd
import numpy as np
from scipy import stats
from sqlalchemy import text
import urllib.parse
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import os

# 嘗試匯入 AI 套件
try:
    import google.generativeai as genai
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# ========== 1. 頁面配置 ==========
st.set_page_config(
    page_title="公告行為研究室 4.4 | StockRevenueLab", 
    layout="wide",
    page_icon="📊"
)

# ========== 2. 安全資料庫連線（共用模組） ==========
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from db_connection import get_engine
from data_status import read_data_status
from analysis_periods import available_analysis_years, year_label

@st.cache_data(ttl=300)
def get_period_context():
    engine = get_engine()
    return available_analysis_years(engine), read_data_status(engine)

# ========== 3. 數據輔助函數 ==========
def get_ai_summary_dist(df, col_name):
    """生成分佈摘要文字"""
    data = df[col_name].dropna()
    if data.empty: 
        return "無數據"
    
    total = len(data)
    bins = [-float('inf'), -5, -1, 1, 5, float('inf')]
    labels = ["大跌(<-5%)", "小跌", "持平", "小漲", "大漲(>5%)"]
    counts, _ = np.histogram(data, bins=bins)
    summary = []
    for label, count in zip(labels, counts):
        if count > 0:
            summary.append(f"{label}:{int(count)}檔({(count/total*100):.1f}%)")
    return " / ".join(summary)

def get_advanced_stats(df, col):
    """計算進階統計指標"""
    data = df[col].dropna()
    if len(data) < 2:
        return None
    
    # 基本統計量
    mean_val = data.mean()
    median_val = data.median()
    std_val = data.std()
    
    # 偏度與峰度
    skew_val = round(data.skew(), 3)
    kurtosis_val = round(data.kurtosis(), 3)
    
    # 變異係數 (Coefficient of Variation)
    cv_val = round(std_val / abs(mean_val) * 100, 2) if mean_val != 0 else float('inf')
    
    # 四分位數
    q25 = data.quantile(0.25)
    q75 = data.quantile(0.75)
    iqr_val = q75 - q25
    
    # 上漲機率
    win_rate = round((data > 0).sum() / len(data) * 100, 1)
    
    # 尾部分佈比例
    left_tail = (data < -5).sum()
    right_tail = (data > 5).sum()
    tail_ratio = round(right_tail / left_tail, 2) if left_tail > 0 else float('inf')
    
    # 峰態檢定 (超過 ±2 視為顯著)
    kurtosis_sig = "高峰態" if kurtosis_val > 2 else "低峰態" if kurtosis_val < -2 else "常態峰態"
    
    # 偏度檢定 (超過 ±0.5 視為顯著)
    skew_sig = "顯著右偏" if skew_val > 0.5 else "顯著左偏" if skew_val < -0.5 else "接近對稱"
    
    return {
        'mean': round(mean_val, 2),
        'median': round(median_val, 2),
        'std': round(std_val, 2),
        'skew': skew_val,
        'kurtosis': kurtosis_val,
        'cv': cv_val,
        'q25': round(q25, 2),
        'q75': round(q75, 2),
        'iqr': round(iqr_val, 2),
        'win_rate': win_rate,
        'tail_ratio': tail_ratio,
        'left_tail': int(left_tail),
        'right_tail': int(right_tail),
        'skew_significance': skew_sig,
        'kurtosis_significance': kurtosis_sig,
        'mean_median_diff': round(mean_val - median_val, 2),
        'data_points': len(data)
    }

def create_big_hist(df, col_name, title, color, desc):
    """繪製直方圖並顯示進階統計指標"""
    data = df[col_name].dropna()
    if data.empty: 
        return None
    
    # 計算統計指標
    stats_vals = get_advanced_stats(df, col_name)
    
    # 直方圖數據
    counts, bins = np.histogram(data, bins=25)
    bin_centers = 0.5 * (bins[:-1] + bins[1:])
    
    fig = go.Figure(data=[
        go.Bar(
            x=bin_centers, 
            y=counts, 
            marker_color=color,
            opacity=0.7,
            name='頻數'
        )
    ])
    
    # 添加統計參考線
    fig.add_vline(x=0, line_dash="dash", line_color="black", line_width=1)
    
    # 平均值線
    fig.add_vline(
        x=stats_vals['mean'], 
        line_color="red", 
        line_width=2, 
        annotation_text=f"平均 {stats_vals['mean']}%",
        annotation_position="top right"
    )
    
    # 中位數線
    fig.add_vline(
        x=stats_vals['median'], 
        line_color="blue", 
        line_width=2, 
        annotation_text=f"中位 {stats_vals['median']}%",
        annotation_position="bottom right"
    )
    
    # 四分位數區域
    fig.add_vrect(
        x0=stats_vals['q25'], 
        x1=stats_vals['q75'],
        fillcolor="lightgray", 
        opacity=0.2,
        line_width=0,
        annotation_text=f"IQR: {stats_vals['iqr']}%",
        annotation_position="bottom left"
    )
    
    # 標題包含統計摘要
    stats_text = (f"偏度: {stats_vals['skew']} ({stats_vals['skew_significance']}) | "
                  f"峰度: {stats_vals['kurtosis']} ({stats_vals['kurtosis_significance']}) | "
                  f"CV: {stats_vals['cv']}% | 上漲機率: {stats_vals['win_rate']}%")
    
    fig.update_layout(
        title=dict(
            text=f"{title}<br><sub>{stats_text}</sub>",
            font=dict(size=18)
        ),
        height=420,
        margin=dict(t=100, b=40, l=40, r=40),
        showlegend=False,
        hovermode="x unified"
    )
    
    return fig

def detect_outliers(df, col, threshold=1.5):
    """檢測異常值"""
    data = df[col].dropna()
    if len(data) < 4:
        return pd.DataFrame()
    
    Q1 = data.quantile(0.25)
    Q3 = data.quantile(0.75)
    IQR = Q3 - Q1
    
    lower_bound = Q1 - threshold * IQR
    upper_bound = Q3 + threshold * IQR
    
    outliers = df[(df[col] < lower_bound) | (df[col] > upper_bound)]
    return outliers

# ========== 4. 核心 SQL 邏輯 (初次爆發) - 修改為支援價格計算方式 ==========
@st.cache_data(ttl=3600)
def fetch_timing_data(year, metric_col, limit, keyword, price_field="w_close"):
    """
    修改SQL查詢以支援不同的價格計算方式
    price_field: 可以是 'w_close' (收盤價) 或 'w_high' (最高價)
    """
    engine = get_engine()
    minguo_year = int(year) - 1911
    
    # 根據價格計算方式選擇欄位
    if price_field == "w_high":
        price_select = "w_high"
    else:
        price_select = "w_close"
    
    query = f"""
    WITH raw_events AS (
        SELECT stock_id, stock_name, report_month, {metric_col}, remark,
               LAG({metric_col}) OVER (PARTITION BY stock_id ORDER BY report_month) as prev_metric
        FROM monthly_revenue
        WHERE report_month LIKE '{minguo_year}_%' OR report_month LIKE '{int(minguo_year)-1}_12'
    ),
    spark_events AS (
        SELECT *,
               CASE 
                 WHEN RIGHT(report_month, 2) = '12' THEN (LEFT(report_month, 3)::int + 1 + 1911)::text || '-01-10'
                 ELSE (LEFT(report_month, 3)::int + 1911)::text || '-' || LPAD((RIGHT(report_month, 2)::int + 1)::text, 2, '0') || '-10'
               END::date as base_date
        FROM raw_events
        WHERE {metric_col} >= {limit} 
          AND (prev_metric < {limit} OR prev_metric IS NULL)
          AND report_month LIKE '{minguo_year}_%'
          AND (remark LIKE '%%{keyword}%%' OR stock_name LIKE '%%{keyword}%%')
    ),
    weekly_calc AS (
        SELECT symbol, date, {price_select},
               ({price_select} - LAG({price_select}) OVER (PARTITION BY symbol ORDER BY date)) / 
               NULLIF(LAG({price_select}) OVER (PARTITION BY symbol ORDER BY date), 0) * 100 as weekly_ret
        FROM stock_weekly_k
    ),
    final_detail AS (
        SELECT 
            e.stock_id, e.stock_name, e.report_month, e.{metric_col} as growth_val, e.remark,
            AVG(CASE WHEN c.date >= e.base_date - interval '38 days' AND c.date < e.base_date - interval '9 days' THEN c.weekly_ret END) * 4 as pre_month,
            AVG(CASE WHEN c.date >= e.base_date - interval '9 days' AND c.date <= e.base_date - interval '3 days' THEN c.weekly_ret END) as pre_week,
            AVG(CASE WHEN c.date > e.base_date - interval '3 days' AND c.date <= e.base_date + interval '4 days' THEN c.weekly_ret END) as announce_week,
            AVG(CASE WHEN c.date > e.base_date + interval '4 days' AND c.date <= e.base_date + interval '11 days' THEN c.weekly_ret END) as after_week_1,
            AVG(CASE WHEN c.date > e.base_date + interval '11 days' AND c.date <= e.base_date + interval '30 days' THEN c.weekly_ret END) as after_month
        FROM spark_events e
        JOIN weekly_calc c ON e.stock_id::text = SPLIT_PART(c.symbol, '.', 1)
        GROUP BY e.stock_id, e.stock_name, e.report_month, e.{metric_col}, e.remark, e.base_date
    )
    SELECT * FROM final_detail WHERE pre_week IS NOT NULL ORDER BY pre_month DESC;
    """
    with engine.connect() as conn:
        return pd.read_sql_query(text(query), conn)

# ========== 5. 使用介面區 ==========
with st.sidebar:
    st.title("🔬 參數設定")
    
    st.markdown("---")
    analysis_years, freshness = get_period_context()
    latest_price_date = freshness.get("stock_prices", {}).get("max_value")
    revenue_cutoff = freshness.get("monthly_revenue", {}).get("max_value") or "資料不足"
    target_year = st.selectbox(
        "分析年度",
        analysis_years,
        index=0,
        format_func=lambda value: year_label(value, latest_price_date),
    )
    st.caption(f"股價截止：{latest_price_date or '資料不足'}｜月營收截止：{revenue_cutoff}")
    if latest_price_date and target_year == latest_price_date[:4]:
        st.info("目前年度為 YTD 事件研究，不代表完整年度結果。")
    study_metric = st.radio("指標選擇", ["yoy_pct", "mom_pct"])
    threshold = st.slider(f"爆發門檻 %", 30, 300, 100)
    search_remark = st.text_input("🔍 關鍵字搜尋", "")
    
    st.markdown("---")
    # 新增：股價計算方式選單
    st.markdown("### 📈 股價計算方式")
    price_calc = st.radio(
        "選擇計算基準",
        ["收盤價 (實戰版)", "最高價 (極限版)"],
        help="""
        收盤價 (實戰版)：使用周收盤價計算，代表實際可實現的報酬
        最高價 (極限版)：使用周最高價計算，代表理論最大潛力漲幅
        """,
        index=0
    )
    
    # 根據選擇決定 SQL 中的價格欄位
    if price_calc == "收盤價 (實戰版)":
        price_field = "w_close"
        price_label = "收盤價"
        st.info("使用周收盤價計算，代表實際可實現的報酬")
    else:
        price_field = "w_high"
        price_label = "最高價"
        st.warning("使用周最高價計算，代表理論最大潛力漲幅")
    
    st.markdown("### 📊 統計設定")
    show_advanced = st.checkbox("顯示進階統計", value=True)
    detect_outliers_opt = st.checkbox("檢測異常值", value=False)
    
    st.markdown("---")
    st.markdown("### ℹ️ 使用說明")
    st.info("""
    1. 選擇分析年度與指標
    2. 調整爆發門檻值
    3. 選擇股價計算方式
    4. 可選關鍵字篩選
    5. 查看各階段統計分析
    6. 使用AI深度診斷
    """)

# 主標題
st.title(f"📊 {target_year}年 公告行為研究室 4.4")
st.caption(f"增強版 - {price_calc} | 含偏度、峰度、變異係數等進階統計分析")
# 加入數據侷限性說明
st.warning(f"""
> 💡 **注意：本分析僅為概念示範（demo）** 
> - 為簡化計算，「公告前後一個月漲跌幅」係以 **周K線資料近似估算**（取公告日前後約4週的平均週報酬推算），
> - 股價計算方式：**{price_calc}**（使用周{price_label}計算漲跌幅）
> - 未使用日頻數據或真實月K線，亦未進行複利累積調整。
> - 因此數值僅供「趨勢參考」，**不建議作為投資依據**。
> - 若您希望進行嚴謹分析，請自行取得高頻行情資料並採用標準事件研究法（Event Study）流程。
""")

# 獲取數據
with st.spinner("正在載入數據..."):
    df = fetch_timing_data(target_year, study_metric, threshold, search_remark, price_field)

if not df.empty:
    # ========== A. 數據看板 (Mean vs Median) ==========
    total_n = len(df)
    
    # 定義統計計算函數
    def get_stats(col):
        data = df[col].dropna()
        if len(data) > 0:
            return round(data.mean(), 2), round(data.median(), 2), len(data)
        return 0, 0, 0
    
    # 計算各階段統計
    m_mean, m_med, m_count = get_stats('pre_month')
    w_mean, w_med, w_count = get_stats('pre_week')
    a_mean, a_med, a_count = get_stats('announce_week')
    fw_mean, fw_med, fw_count = get_stats('after_week_1')  # T+1周
    fm_mean, fm_med, fm_count = get_stats('after_month')   # T+1月
    
    # 顯示數據看板
    st.subheader(f"📈 核心數據看板 - {price_calc}")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    
    col1.metric("樣本總數", f"{total_n} 檔", delta=None)
    col2.metric("T-1月", f"{m_mean}%", f"中位: {m_med}%")
    col3.metric("T-1周", f"{w_mean}%", f"中位: {w_med}%")
    col4.metric("T周公告", f"{a_mean}%", f"中位: {a_med}%")
    col5.metric("T+1周", f"{fw_mean}%", f"中位: {fw_med}%")
    col6.metric("T+1月", f"{fm_mean}%", f"中位: {fm_med}%")
    
    st.markdown("---")
    
    # ========== B. 原始明細清單 ==========
    st.subheader(f"📋 原始數據明細 - {price_calc}")
    
    # 控制按鈕
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    with col_btn1:
        st.download_button(
            label="📥 下載 CSV", 
            data=df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'), 
            file_name=f'stock_revenue_{target_year}_{price_label}.csv',
            mime='text/csv'
        )
    with col_btn2:
        if st.button("📊 顯示統計摘要"):
            st.session_state.show_stats = True
    
    # 生成AI分析用的表格
    if st.checkbox("🔍 產生AI分析表格"):
        # 只取關鍵欄位，避免字數過多
        copy_data = df[['stock_id', 'stock_name', 'growth_val', 'pre_month', 'pre_week', 'after_week_1', 'after_month', 'remark']].head(300)
        md_table = copy_data.to_markdown(index=False)
        
        st.code(f"""請針對以下 {target_year} 年營收爆發股數據進行診斷（使用{price_calc}）：

{md_table}

分析重點：
1. 右尾效應分析：檢查T-1月的高報酬股票特徵
2. 資訊不對稱：比較T-1月與T-1周的報酬分佈
3. 策略有效性：評估T+1月報酬的持續性
4. 計算方式影響：{price_calc}對分析結果的影響""", language="text")
    
    # 添加連結欄位
    df['技術圖表'] = df['stock_id'].apply(lambda x: f"https://www.wantgoo.com/stock/{x}/technical-chart")
    df['財報資料'] = df['stock_id'].apply(lambda x: f"https://statementdog.com/analysis/{x}")
    
    # 顯示數據框
    st.dataframe(
        df, 
        use_container_width=True, 
        height=400,
        column_config={
            "技術圖表": st.column_config.LinkColumn("技術圖表", display_text="📈"),
            "財報資料": st.column_config.LinkColumn("財報資料", display_text="📊")
        }
    )
    
    st.markdown("---")
    
    # ========== C. 進階統計指標 ==========
    if show_advanced:
        st.subheader(f"🔬 進階統計分析 - {price_calc}")
        
        # 定義分析階段
        stages = {
            'T-1月': 'pre_month',
            'T-1周': 'pre_week', 
            'T周': 'announce_week',
            'T+1周': 'after_week_1',
            'T+1月': 'after_month'
        }
        
        # 計算各階段進階統計
        advanced_stats = {}
        for stage_name, col_name in stages.items():
            stats_data = get_advanced_stats(df, col_name)
            if stats_data:
                advanced_stats[stage_name] = stats_data
        
        if advanced_stats:
            # 轉換為DataFrame顯示
            stats_df = pd.DataFrame(advanced_stats).T
            
            # 選擇要顯示的欄位
            display_cols = ['mean', 'median', 'skew', 'kurtosis', 'cv', 'win_rate', 'iqr', 'tail_ratio']
            display_df = stats_df[display_cols]
            
            # 重新命名欄位
            display_df.columns = ['均值%', '中位數%', '偏度', '峰度', '變異係數%', '上漲機率%', 'IQR%', '右尾/左尾比']
            
            col_stat1, col_stat2 = st.columns([2, 1])
            
            with col_stat1:
                st.write(f"**統計指標表 ({price_calc})**")
                # 格式化顯示
                formatted_df = display_df.style.format({
                    '均值%': '{:.1f}',
                    '中位數%': '{:.1f}',
                    '變異係數%': '{:.1f}',
                    '上漲機率%': '{:.1f}',
                    'IQR%': '{:.1f}',
                    '偏度': '{:.3f}',
                    '峰度': '{:.3f}',
                    '右尾/左尾比': '{:.2f}'
                })
                st.dataframe(formatted_df, use_container_width=True)
            
            with col_stat2:
                st.write(f"**統計圖示 ({price_label})**")
                
                # 選擇要視覺化的指標
                metric_choice = st.selectbox(
                    "選擇指標圖表",
                    ["偏度與峰度", "均值與中位數", "上漲機率", "變異係數"]
                )
                
                if metric_choice == "偏度與峰度":
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        x=list(advanced_stats.keys()),
                        y=[s['skew'] for s in advanced_stats.values()],
                        name='偏度',
                        marker_color='coral'
                    ))
                    fig.add_trace(go.Scatter(
                        x=list(advanced_stats.keys()),
                        y=[s['kurtosis'] for s in advanced_stats.values()],
                        name='峰度',
                        yaxis='y2',
                        mode='lines+markers',
                        line=dict(color='blue', width=2)
                    ))
                    fig.update_layout(
                        title=f"偏度與峰度趨勢 ({price_calc})",
                        yaxis=dict(title='偏度'),
                        yaxis2=dict(title='峰度', overlaying='y', side='right'),
                        height=300
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                elif metric_choice == "均值與中位數":
                    fig = go.Figure()
                    stages_list = list(advanced_stats.keys())
                    fig.add_trace(go.Scatter(
                        x=stages_list,
                        y=[s['mean'] for s in advanced_stats.values()],
                        name='均值',
                        mode='lines+markers',
                        line=dict(color='green', width=3)
                    ))
                    fig.add_trace(go.Scatter(
                        x=stages_list,
                        y=[s['median'] for s in advanced_stats.values()],
                        name='中位數',
                        mode='lines+markers',
                        line=dict(color='blue', width=3)
                    ))
                    fig.update_layout(
                        title=f"均值 vs 中位數 ({price_calc})",
                        yaxis_title="報酬率 %",
                        height=300
                    )
                    st.plotly_chart(fig, use_container_width=True)
            
            # 異常值檢測
            if detect_outliers_opt:
                st.subheader(f"⚠️ 異常值檢測 - {price_calc}")
                
                outlier_col = st.selectbox(
                    "選擇檢測階段",
                    list(stages.keys()),
                    key="outlier_select"
                )
                
                col_name = stages[outlier_col]
                outliers = detect_outliers(df, col_name, threshold=1.5)
                
                if not outliers.empty:
                    st.write(f"在 {outlier_col} 檢測到 {len(outliers)} 個異常值 ({price_calc}):")
                    st.dataframe(outliers[['stock_id', 'stock_name', col_name, 'remark']], use_container_width=True)
                else:
                    st.info(f"在 {outlier_col} 未檢測到明顯異常值")
        
        st.markdown("---")
    
    # ========== D. 完整五張分佈圖 ==========
    st.subheader(f"📊 階段報酬分佈分析 - {price_calc}")
    
    # 使用tabs組織分佈圖
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "⓪ T-1月 (大戶佈局區)", 
        "❶ T-1周 (短線預跑區)", 
        "❷ T周 (市場反應)", 
        "❸ T+1周 (公告後續)", 
        "❹ T+1月 (趨勢結局)"
    ])
    
    with tab1:
        fig1 = create_big_hist(df, "pre_month", 
                              f"T-1月 大戶佈局區 ({price_calc})", 
                              "#8a2be2",
                              f"若平均值顯著大於中位數且偏度為正，代表大資金早已進場『拉抬少數權值股』。計算方式：{price_calc}")
        if fig1:
            st.plotly_chart(fig1, use_container_width=True)
            st.info(f"""
            **科學解讀 ({price_calc})**:
            - **偏度 > 0.5**: 強烈右偏，顯示少數股票被大幅拉抬
            - **峰度 > 3**: 高峰態，報酬集中於極端值
            - **變異係數高**: 個股間差異大，選擇困難
            - **IQR寬**: 事前預測區間大，風險較高
            - **計算方式影響**: {price_calc}可能放大或縮小右尾效應
            """)
    
    with tab2:
        fig2 = create_big_hist(df, "pre_week", 
                              f"T-1周 短線預跑區 ({price_calc})", 
                              "#ff4b4b",
                              f"若中位數趨近於0但平均值為正，代表只有極少數業內資訊領先者在偷跑。計算方式：{price_calc}")
        if fig2:
            st.plotly_chart(fig2, use_container_width=True)
            st.info(f"""
            **科學解讀 ({price_calc})**:
            - **偏度接近0**: 對稱分佈，無明顯資訊優勢
            - **上漲機率低**: 多數股票在公告前並無明顯漲勢
            - **IQR窄**: 報酬集中，預測相對容易
            - **變異係數低**: 個股表現相對一致
            - **計算方式影響**: {price_calc}可能影響短線報酬的極端值
            """)
    
    with tab3:
        fig3 = create_big_hist(df, "announce_week", 
                              f"T周 市場反應 ({price_calc})", 
                              "#ffaa00",
                              f"營收正式釋出後。若平均與中位線重合，代表利多已成為市場共識。計算方式：{price_calc}")
        if fig3:
            st.plotly_chart(fig3, use_container_width=True)
            st.info(f"""
            **科學解讀 ({price_calc})**:
            - **均值 > 中位數**: 右尾效應，少數股票反應過度
            - **峰度值**: 反映市場對資訊解讀的一致性
            - **上漲機率**: 顯示利多被市場認可的程度
            - **IQR**: 市場反應的分歧程度
            - **計算方式影響**: {price_calc}可能改變市場反應的強度估計
            """)
    
    with tab4:
        fig4 = create_big_hist(df, "after_week_1", 
                              f"T+1周 公告後續 ({price_calc})", 
                              "#32cd32",
                              f"利多公佈後的追價動能。若均值為正，代表有持續買盤。計算方式：{price_calc}")
        if fig4:
            st.plotly_chart(fig4, use_container_width=True)
            st.info(f"""
            **科學解讀 ({price_calc})**:
            - **均值方向**: 判斷追價動能強弱
            - **偏度變化**: 從T周到T+1周的偏度轉變
            - **上漲機率變化**: 顯示利多效應的擴散程度
            - **變異係數**: 後續走勢的分歧度
            - **計算方式影響**: {price_calc}可能影響追價動能的評估
            """)
    
    with tab5:
        fig5 = create_big_hist(df, "after_month", 
                              f"T+1月 趨勢結局 ({price_calc})", 
                              "#1e90ff",
                              f"波段收尾。若中位數為負代表大多數爆發股最終都會回吐，只有少數強者恆強。計算方式：{price_calc}")
        if fig5:
            st.plotly_chart(fig5, use_container_width=True)
            st.info(f"""
            **科學解讀 ({price_calc})**:
            - **中位數方向**: 判斷策略的普適性
            - **右尾/左尾比**: 強者恆強 vs 利多出盡的比例
            - **峰度**: 極端報酬的集中程度
            - **IQR**: 最終報酬的分佈範圍
            - **計算方式影響**: {price_calc}可能改變長期報酬的分布型態
            """)
    
    st.markdown("---")
    
    # ========== E. AI 診斷 (增強版) ==========
    st.subheader(f"🤖 AI 投資行為深度診斷 - {price_calc}")
    
    # 生成分佈摘要
    dist_txt = (f"T-1月分佈: {get_ai_summary_dist(df, 'pre_month')}\n"
                f"T+1月分佈: {get_ai_summary_dist(df, 'after_month')}")
    
    # 生成進階統計摘要
    def create_stat_summary(stats_dict):
        summary_lines = []
        for stage, stats in stats_dict.items():
            line = (f"{stage}: 均值={stats['mean']}%, 中位={stats['median']}%, "
                   f"偏度={stats['skew']}({stats['skew_significance']}), "
                   f"峰度={stats['kurtosis']}({stats['kurtosis_significance']}), "
                   f"變異係數={stats['cv']}%, 上漲機率={stats['win_rate']}%, "
                   f"IQR={stats['iqr']}%, 右尾/左尾比={stats['tail_ratio']}")
            summary_lines.append(line)
        return "\n".join(summary_lines)
    
    # 增強版提示詞（包含價格計算方式）
    prompt_text = f"""
# 台股營收爆發行為量化分析報告

## 計算方式說明
- **股價計算方式**: {price_calc}
- **計算基準**: 使用周{price_label}計算漲跌幅
- **實務意義**: {'代表實際可實現的報酬' if price_field == 'w_close' else '代表理論最大潛力漲幅'}

## 數據概要
- 分析年度：{target_year}
- 樣本規模：{total_n}檔符合{threshold}%增長門檻
- 指標類型：{study_metric}
- 爆發門檻：{threshold}%
- 樣本特性：初次爆發(前一月未達標，本月首度衝破{threshold}%)

## 核心統計數據
【全階段平均報酬】({price_calc})：
- 公告前一個月: {m_mean}% / 公告前一週: {w_mean}% / 公告當週: {a_mean}% / 公告後一週: {fw_mean}% / 公告後一個月: {fm_mean}%

【進階統計特徵】({price_calc})：
{create_stat_summary(advanced_stats) if advanced_stats else "無進階統計數據"}

【分佈摘要數據】：
{dist_txt}

## 診斷分析問題
請針對以上數據進行專業量化診斷，特別注意{price_calc}的影響：

### 1. 資訊不對稱分析 ({price_calc})
- 從 T-1 月與 T-1 周的「偏度值」({advanced_stats.get('T-1月', {}).get('skew', 'N/A')} vs {advanced_stats.get('T-1周', {}).get('skew', 'N/A')})來看，是否有證據顯示「主力/內部人提早知道訊息並佈局」？
- 右尾/左尾比({advanced_stats.get('T-1月', {}).get('tail_ratio', 'N/A')})如何解讀？{price_calc}是否放大了右尾效應？

### 2. 市場反應效率 ({price_calc})
- T周偏度({advanced_stats.get('T周', {}).get('skew', 'N/A')})與峰度({advanced_stats.get('T周', {}).get('kurtosis', 'N/A')})顯示市場呈現的是「理性定價」還是「過度反應」？
- T+1周表現(均值{fw_mean}%)相對於T周，顯示的是「追加買盤」還是「利多出盡」？{price_calc}如何影響這個判斷？

### 3. 風險與報酬特徵 ({price_calc})
- 變異係數趨勢(T-1月:{advanced_stats.get('T-1月', {}).get('cv', 'N/A')}% → T+1月:{advanced_stats.get('T+1月', {}).get('cv', 'N/A')}%)反映什麼風險變化？
- 峰度值變化如何影響「極端報酬」的發生機率？{price_calc}是否會改變峰度值的解讀？

### 4. 投資策略建議 ({price_calc})
- 針對這組數據特徵，給予投資人最具期望值的「進場點」與「出場點」建議
- 應設定怎樣的停利停損位置？(參考IQR:{advanced_stats.get('T周', {}).get('iqr', 'N/A')}%)
- 如何利用「偏度差值」({advanced_stats.get('T-1月', {}).get('mean_median_diff', 'N/A')}%)來篩選股票？
- **重要**：請特別說明{price_calc}對策略建議的影響，以及如果換成另一種計算方式，策略應如何調整？

### 5. 年度比較洞察 ({price_calc})
- 與過往年度相比，{target_year}年的營收公告效應呈現什麼特殊現象？
- 從「上漲機率」趨勢(T-1月:{advanced_stats.get('T-1月', {}).get('win_rate', 'N/A')}% → T+1月:{advanced_stats.get('T+1月', {}).get('win_rate', 'N/A')}%)看策略有效性
- 計算方式影響：{price_calc}的選擇是否會改變對年度效應的判斷？

### 6. 計算方式專題分析
- **{price_calc}的優缺點**：使用{price_label}計算漲跌幅有什麼優勢和劣勢？
- **實務應用建議**：投資者應如何解讀{price_calc}的結果？需要注意哪些潛在偏差？
- **極端值影響**：最高價計算是否會過度放大少數股票的表現？收盤價計算是否會低估潛在機會？
"""
    
    # 顯示提示詞
    col_prompt, col_actions = st.columns([3, 1])
    
    with col_prompt:
        st.write(f"📋 **AI 分析指令 (含{price_calc}完整統計參數)**")
        st.code(prompt_text, language="text", height=400)
    
    with col_actions:
        st.write("🚀 **AI 診斷工具**")
        
        # ChatGPT 連結
        encoded_p = urllib.parse.quote(prompt_text)
        st.link_button(
            "🔥 開啟 ChatGPT 分析", 
            f"https://chatgpt.com/?q={encoded_p}",
            help=f"在新分頁開啟 ChatGPT 並自動帶入{price_calc}分析指令"
        )
        
        # DeepSeek 使用說明
        st.info(f"""
        **使用 DeepSeek**:
        1. 複製上方指令
        2. 前往 [DeepSeek](https://chat.deepseek.com)
        3. 貼上指令並發送
        """)
        
        # Gemini 內建診斷
        if st.button("🔒 啟動 Gemini 專家診斷", type="secondary"):
            st.session_state.run_ai_diagnosis = True
    
    # Gemini AI 診斷
    if st.session_state.get("run_ai_diagnosis", False):
        with st.expander("🔒 內建 AI 診斷系統", expanded=True):
            with st.form("ai_diagnosis_form"):
                password = st.text_input("研究員密碼：", type="password", 
                                       help="請輸入授權密碼以使用內建AI")
                submit = st.form_submit_button("執行 AI 診斷")
                
                if submit:
                    if password == st.secrets.get("AI_ASK_PASSWORD", "default_password"):
                        if AI_AVAILABLE:
                            try:
                                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                                # 自動尋找可用模型
                                all_models = genai.list_models()
                                available_models = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
                                
                                # 優先選擇 gemini-1.5-flash 或 gemini-pro
                                target_model = None
                                for model_name in ["gemini-1.5-flash", "gemini-pro"]:
                                    for m in available_models:
                                        if model_name in m:
                                            target_model = m
                                            break
                                    if target_model:
                                        break
                                
                                if not target_model and available_models:
                                    target_model = available_models[0]
                                
                                if target_model:
                                    model = genai.GenerativeModel(target_model)
                                    with st.spinner(f"🤖 AI 正在深度分析 {total_n} 筆樣本數據 ({price_calc})..."):
                                        response = model.generate_content(prompt_text)
                                        
                                        st.success(f"✅ AI 診斷完成 ({price_calc})")
                                        st.markdown("---")
                                        st.markdown(f"## 📋 AI 專家診斷報告 ({price_calc})")
                                        st.markdown(response.text)
                                        
                                        # 提供下載報告
                                        report_text = f"# {target_year}年台股營收爆發分析報告 ({price_calc})\n\n" + response.text
                                        st.download_button(
                                            label="📥 下載 AI 報告",
                                            data=report_text.encode('utf-8'),
                                            file_name=f"stock_revenue_ai_report_{target_year}_{price_label}.md",
                                            mime="text/markdown"
                                        )
                                else:
                                    st.error("❌ 找不到可用的 AI 模型")
                            except Exception as e:
                                st.error(f"❌ AI 診斷失敗: {str(e)}")
                        else:
                            st.error("❌ Gemini AI 套件未安裝")
                    else:
                        st.error("❌ 密碼錯誤")

else:
    st.warning("⚠️ 查無符合條件之樣本，請調整搜尋參數。")
    st.info(f"""
    💡 建議調整：
    1. 降低門檻值
    2. 更換年度
    3. 放寬關鍵字搜尋
    4. 嘗試不同的股價計算方式：{price_calc}
    """)

# ========== 6. 頁尾資訊 ==========
st.markdown("---")
# ========== 6. 頁尾資訊 ==========
st.markdown("---")
footer_col1, footer_col2, footer_col3 = st.columns(3)
with footer_col1:
    st.markdown(f"**版本**：公告行為研究室 4.4 ({price_calc})")
with footer_col2:
    st.markdown(f"**數據週期**：2020-2025")
with footer_col3:
    st.markdown(f"**計算方式**：{price_calc}")

# ========== 7. 快速資源連結 ==========
st.divider()
st.markdown("### 🔗 快速資源連結")

# 使用 markdown 創建您想要的格式
st.markdown("""
<div style="text-align: center;">
    <table style="margin: 0 auto; border-collapse: separate; border-spacing: 30px 0;">
        <tr>
            <td style="text-align: center; vertical-align: top;">
                <div style="font-size: 1.5em;">🛠️</div>
                <a href="https://vocus.cc/article/695636c3fd89780001d873bd" target="_blank" style="text-decoration: none;">
                    <b>⚙️ 環境與 AI 設定教學</b>
                </a>
            </td>
            <td style="text-align: center; vertical-align: top;">
                <div style="font-size: 1.5em;">📊</div>
                <a href="https://vocus.cc/salon/grissomlin/room/695636ee0c0c0689d1e2aa9f" target="_blank" style="text-decoration: none;">
                    <b>📖 儀表板功能詳解</b>
                </a>
            </td>
            <td style="text-align: center; vertical-align: top;">
                <div style="font-size: 1.5em;">🐙</div>
                <a href="https://github.com/grissomlin/StockRevenueLab" target="_blank" style="text-decoration: none;">
                    <b>💻 GitHub 專案原始碼</b>
                </a>
            </td>
        </tr>
    </table>
</div>
""", unsafe_allow_html=True)

# 隱藏Streamlit預設元素
hide_st_style = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
</style>
"""
st.markdown(hide_st_style, unsafe_allow_html=True)

# 初始化session state變數
if 'run_ai_diagnosis' not in st.session_state:
    st.session_state.run_ai_diagnosis = False
if 'show_stats' not in st.session_state:
    st.session_state.show_stats = False
