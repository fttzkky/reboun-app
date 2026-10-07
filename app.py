import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="レバウン式", page_icon="📈", layout="wide")
st.title("📈 レバウン式")
st.caption("日経平均下落 × レバレッジ乖離で買いシグナルを検出")

# --- サイドバー設定 ---
st.sidebar.header("⚙️ 設定")

mode = st.sidebar.radio("モード選択", ["円モード", "％モード"])

if mode == "円モード":
    threshold = st.sidebar.number_input(
        "日経平均 累積下落幅（円）",
        min_value=100, max_value=5000, value=300, step=100
    )
    st.sidebar.caption("例：300 → 累積-300円以上の下落でシグナル候補")
else:
    threshold = st.sidebar.number_input(
        "日経平均 累積下落率（%）",
        min_value=0.1, max_value=10.0, value=0.3, step=0.1, format="%.1f"
    )
    st.sidebar.caption("例：0.3 → 累積-0.3%以上の下落でシグナル候補")

cumulative_days = st.sidebar.slider("累積日数（連続下落を何日まで合算）", 1, 10, 3)

lev_excess = st.sidebar.number_input(
    "1570の超過下落倍率（理論2倍超え）",
    min_value=1.0, max_value=5.0, value=2.0, step=0.1, format="%.1f",
    help="1570の下落率が日経の何倍以上で乖離とみなすか（通常2倍が理論値）"
)

start_date = st.sidebar.date_input("開始日", value=datetime(2020, 1, 1))

st.sidebar.markdown("---")
st.sidebar.markdown("**両アプリURL**")
st.sidebar.markdown("[ちょるこ式](https://choruko-swing-dwf39ocwzqubb3uattpjmi.streamlit.app)")
st.sidebar.markdown("[ひよこ式](https://choruko-swing-anvaomt9aunocm5irspcob.streamlit.app)")

# --- データ取得 ---
@st.cache_data(ttl=3600)
def load_data(start):
    end = datetime.today().strftime("%Y-%m-%d")
    n225_raw = yf.download("^N225", start=start, end=end, progress=False)["Close"]
    lev_raw  = yf.download("1570.T", start=start, end=end, progress=False)["Close"]
    # yfinance may return DataFrame with MultiIndex columns; squeeze to Series
    if isinstance(n225_raw, pd.DataFrame):
        n225_raw = n225_raw.squeeze()
    if isinstance(lev_raw, pd.DataFrame):
        lev_raw = lev_raw.squeeze()
    df = pd.DataFrame({"N225": n225_raw, "LEV": lev_raw}).dropna()
    df.index = pd.to_datetime(df.index)
    return df

with st.spinner("データ取得中..."):
    try:
        df = load_data(start_date.strftime("%Y-%m-%d"))
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        st.stop()

if df.empty:
    st.error("データが取得できませんでした。")
    st.stop()

# --- 騰落率計算 ---
df["N225_ret"]  = df["N225"].pct_change() * 100
df["N225_diff"] = df["N225"].diff()
df["LEV_ret"]   = df["LEV"].pct_change() * 100

df["LEV_theory"] = df["N225_ret"] * 2.0
df["LEV_excess"]  = df["LEV_ret"] - df["LEV_theory"]

df["N225_cum_diff"] = df["N225_diff"].rolling(cumulative_days).sum()
df["N225_cum_ret"]  = df["N225_ret"].rolling(cumulative_days).sum()

# --- シグナル判定 ---
if mode == "円モード":
    cond_nikkei = df["N225_cum_diff"] <= -threshold
else:
    cond_nikkei = df["N225_cum_ret"] <= -threshold

cond_lev = df["LEV_ret"] <= (df["N225_ret"] * lev_excess)

df["signal"] = cond_nikkei & cond_lev & (df["N225_ret"] < 0)

# --- 結果表示 ---
col1, col2, col3 = st.columns(3)
signals = df[df["signal"]]

col1.metric("シグナル発生回数", f"{len(signals)}回")
col2.metric("分析期間", f"{df.index[0].date()} 〜 {df.index[-1].date()}")
col3.metric("総営業日数", f"{len(df)}日")

st.markdown("---")

# --- 翌日・3日後リターン計算 ---
returns = []
for idx in signals.index:
    pos = df.index.get_loc(idx)
    row = {"シグナル日": idx.date(),
           "日経(円)": round(df["N225_diff"].iloc[pos], 0),
           "日経累積(円)": round(df["N225_cum_diff"].iloc[pos], 0) if mode == "円モード" else "-",
           "日経累積(%)": round(df["N225_cum_ret"].iloc[pos], 2),
           "1570変化率(%)": round(df["LEV_ret"].iloc[pos], 2),
           "理論値(%)": round(df["LEV_theory"].iloc[pos], 2),
           "乖離(%)": round(df["LEV_excess"].iloc[pos], 2)}

    for days, label in [(1,"翌日1570%"), (3,"3日後1570%"), (5,"5日後1570%")]:
        if pos + days < len(df):
            future_ret = ((df["LEV"].iloc[pos + days] - df["LEV"].iloc[pos]) / df["LEV"].iloc[pos]) * 100
            row[label] = round(future_ret, 2)
        else:
            row[label] = None

    returns.append(row)

if returns:
    result_df = pd.DataFrame(returns)

    for col in ["翌日1570%", "3日後1570%", "5日後1570%"]:
        vals = result_df[col].dropna()
        wins = (vals > 0).sum()
        total = len(vals)
        avg = vals.mean()
        st.markdown(f"**{col}** ｜ 勝率: **{wins}/{total} ({wins/total*100:.1f}%)** ｜ 平均リターン: **{avg:+.2f}%**")

    st.markdown("---")
    st.subheader("📋 シグナル一覧")

    def color_ret(val):
        if val is None or val == "-": return ""
        try:
            v = float(val)
            return "color: red" if v < 0 else "color: blue"
        except: return ""

    st.dataframe(
        result_df.style.applymap(color_ret, subset=["翌日1570%","3日後1570%","5日後1570%"]),
        use_container_width=True, hide_index=True
    )
else:
    st.warning("条件に合うシグナルが見つかりませんでした。閾値を下げてみてください。")

# --- チャート ---
st.markdown("---")
st.subheader("📊 日経225 vs 1570 累積リターン比較")

df_chart = df[["N225","LEV"]].copy()
df_chart["N225_norm"] = df_chart["N225"] / df_chart["N225"].iloc[0] * 100
df_chart["LEV_norm"]  = df_chart["LEV"]  / df_chart["LEV"].iloc[0]  * 100

st.line_chart(df_chart[["N225_norm","LEV_norm"]], use_container_width=True)
st.caption("基準日=100として正規化（青：日経225、赤：1570）")

if len(signals) > 0:
    st.markdown("---")
    st.subheader("🔴 シグナル発生日の乖離詳細")
    detail = signals[["N225_diff","N225_cum_diff","N225_ret","LEV_ret","LEV_theory","LEV_excess"]].copy()
    detail.columns = ["日経日次(円)","日経累積(円)","日経日次(%)","1570実際(%)","1570理論(%)","乖離(%)"]
    detail.index = detail.index.date
    st.dataframe(detail.style.applymap(
        lambda v: "color: red" if isinstance(v, float) and v < 0 else "color: blue" if isinstance(v, float) and v > 0 else ""
    ), use_container_width=True)
