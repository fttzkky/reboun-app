import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time
from datetime import datetime, date, timedelta

st.set_page_config(page_title="レバウン式", page_icon="📈", layout="wide")
st.title("📈 レバウン式")
st.caption("日経平均下落 × レバレッジ乖離で買いシグナルを検出（売買の基準は終値）")

# --- 対象ETF ---
ETFS = {
    "1570 日経レバ（2012年〜）":  ("1570.T", date(2012, 1, 1), 2.0),
    "1568 TOPIXレバ（2012年〜）": ("1568.T", date(2012, 1, 1), 2.0),
    "1306 TOPIX連動（2006年〜）": ("1306.T", date(2006, 1, 1), 1.0),
}

# --- サイドバー設定 ---
st.sidebar.header("⚙️ 設定")

etf_label = st.sidebar.selectbox("対象ETF", list(ETFS.keys()))
ticker, default_start, leverage = ETFS[etf_label]
is_1570 = ticker == "1570.T"

start_date = st.sidebar.date_input(
    "開始日", value=default_start, min_value=date(2000, 1, 1),
    max_value=date.today(), key=f"start_{ticker}",
)

st.sidebar.markdown("**買い条件**")
use_nikkei = st.sidebar.checkbox("日経平均の下落を条件にする", value=True)

mode = st.sidebar.radio("モード選択", ["円モード", "％モード"])
if mode == "円モード":
    threshold = st.sidebar.number_input(
        "日経平均 累積下落幅（円）",
        min_value=100, max_value=5000, value=1000, step=100
    )
    st.sidebar.caption("ひよこ式＝累積日数1・1000円。例：300 → 累積-300円以上の下落")
else:
    threshold = st.sidebar.number_input(
        "日経平均 累積下落率（%）",
        min_value=0.1, max_value=10.0, value=0.3, step=0.1, format="%.1f"
    )
    st.sidebar.caption("例：0.3 → 累積-0.3%以上の下落でシグナル候補")

cumulative_days = st.sidebar.slider("累積日数（連続下落を何日まで合算）", 1, 10, 1)

use_lev_below = st.sidebar.checkbox("ETF終値＜日経平均終値を条件に加える", value=True)
use_s3 = st.sidebar.checkbox("STEP3（4点中N点以上）を条件に加える", value=False)
s3_min = st.sidebar.slider("STEP3 必要点数", 1, 4, 3, disabled=not use_s3)
st.sidebar.caption("4点＝前日比≤-2.5%／MA25乖離<0／BB≤-3σ／RCI≤-80%")

st.sidebar.markdown("**売り条件（終値）**")
target_yen = st.sidebar.number_input(
    "利確：日経平均が購入日の終値から＋何円で売る", min_value=100, max_value=5000,
    value=1000, step=100)
max_hold = st.sidebar.slider("最大保有日数（超えたらその日の終値で売る）", 1, 60, 20)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 最新データで再計算", use_container_width=True):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption("設定を変えると自動で再計算します。このボタンは株価データを取り直します。")

st.sidebar.markdown("---")
st.sidebar.markdown("**両アプリURL**")
st.sidebar.markdown("[ちょる子式](https://choruko-swing-dwf39ocwzqubb3uattpjmi.streamlit.app)")
st.sidebar.markdown("[ひよこ式](https://choruko-swing-anvaomt9aunocm5irspcob.streamlit.app)")


# --- データ取得 ---
def _fetch_close(symbol, start, end, tries=3):
    """終値を取得。失敗・空なら待って再試行し、download→Ticker.historyの順で切り替える。"""
    last_err = None
    for i in range(tries):
        for method in ("download", "history"):
            try:
                if method == "download":
                    raw = yf.download(symbol, start=start, end=end, progress=False)["Close"]
                else:
                    raw = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=True)["Close"]
                if isinstance(raw, pd.DataFrame):
                    raw = raw.squeeze()
                if isinstance(raw, pd.Series) and raw.dropna().size > 0:
                    idx = pd.to_datetime(raw.index)
                    if idx.tz is not None:
                        idx = idx.tz_localize(None)
                    raw.index = idx.normalize()
                    return raw.dropna()
            except Exception as e:
                last_err = e
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{symbol} の株価を取得できませんでした（{tries}回再試行）: {last_err}")


@st.cache_data(ttl=3600)
def load_data(tkr, start):
    # 指標計算用に開始日の約半年前から取得し、後で開始日以降に絞る
    buffer_start = (pd.Timestamp(start) - pd.Timedelta(days=200)).strftime("%Y-%m-%d")
    end = datetime.today().strftime("%Y-%m-%d")
    n225_raw = _fetch_close("^N225", buffer_start, end)
    lev_raw  = _fetch_close(tkr, buffer_start, end)
    df = pd.DataFrame({"N225": n225_raw, "LEV": lev_raw}).dropna()
    if df.empty:
        raise RuntimeError("日経平均とETFの取引日が重なるデータがありませんでした。")
    return df


def _rci(x):
    n = len(x)
    price_rank = pd.Series(x).rank().values
    d = np.arange(1, n + 1)
    return (1 - 6 * np.sum((d - price_rank) ** 2) / (n * (n ** 2 - 1))) * 100


with st.spinner("データ取得中..."):
    try:
        df = load_data(ticker, start_date.strftime("%Y-%m-%d"))
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        st.info("Yahoo側の混雑が原因のことが多いです。数分おいて、下のボタンで再取得できます。")
        if st.button("再取得する"):
            st.cache_data.clear()
            st.rerun()
        st.stop()

if df.empty:
    st.error("データが取得できませんでした。")
    st.stop()

# --- 騰落率計算 ---
df["N225_ret"]  = df["N225"].pct_change() * 100
df["N225_diff"] = df["N225"].diff()
df["LEV_ret"]   = df["LEV"].pct_change() * 100

df["LEV_theory"] = df["N225_ret"] * leverage
df["LEV_excess"]  = df["LEV_ret"] - df["LEV_theory"]

df["N225_cum_diff"] = df["N225_diff"].rolling(cumulative_days).sum()
df["N225_cum_ret"]  = df["N225_ret"].rolling(cumulative_days).sum()

# --- STEP3（ETF自身の終値で判定） ---
ma25 = df["LEV"].rolling(25).mean()
sd25 = df["LEV"].rolling(25).std()
df["MA25_dev"] = (df["LEV"] / ma25 - 1) * 100
df["BB_sigma"] = (df["LEV"] - ma25) / sd25.replace(0, np.nan)
df["RCI9"]     = df["LEV"].rolling(9).apply(_rci, raw=True)
df["s3n"] = (
    (df["LEV_ret"] <= -2.5).astype(int)
    + (df["MA25_dev"] < 0).astype(int)
    + (df["BB_sigma"] <= -3.0).astype(int)
    + (df["RCI9"] <= -80).astype(int)
)

# --- 開始日以降に絞る（指標は絞る前に計算済み） ---
df = df[df.index >= pd.Timestamp(start_date)].copy()
if df.empty:
    st.error("開始日以降のデータがありません。")
    st.stop()

# --- シグナル判定（終値基準） ---
signal = pd.Series(True, index=df.index)
if use_nikkei:
    if mode == "円モード":
        signal &= df["N225_cum_diff"] <= -threshold
    else:
        signal &= df["N225_cum_ret"] <= -threshold
    signal &= df["N225_ret"] < 0
if use_lev_below:
    signal &= df["LEV"] < df["N225"]
if use_s3:
    signal &= df["s3n"] >= s3_min
if not (use_nikkei or use_lev_below or use_s3):
    signal &= False  # 条件が1つも選ばれていない場合はシグナルなし
df["signal"] = signal.fillna(False)

# --- 結果表示 ---
signals = df[df["signal"]]

col1, col2, col3 = st.columns(3)
col1.metric("シグナル発生回数", f"{len(signals)}回")
col2.metric("分析期間", f"{df.index[0].date()} 〜 {df.index[-1].date()}")
col3.metric("総営業日数", f"{len(df)}日")

if not (use_nikkei or use_lev_below or use_s3):
    st.warning("買い条件が1つも選ばれていません。サイドバーで条件を選んでください。")


# --- 売買シミュレーション（買い＝シグナル日の終値、売り＝利確日or期限日の終値） ---
def simulate(frame, target, hold_limit):
    n225 = frame["N225"].values
    lev = frame["LEV"].values
    last_pos = len(frame) - 1
    rows = []
    for idx in frame.index[frame["signal"].values]:
        pos = frame.index.get_loc(idx)
        if pos >= last_pos:
            rows.append({"買い日": idx.date(), "売り日": None, "保有日数": 0,
                         "ETF損益(%)": None, "最大含み損(%)": None, "結果": "保有中"})
            continue
        horizon = min(pos + hold_limit, last_pos)
        exit_pos, reason = None, None
        for j in range(pos + 1, horizon + 1):
            if n225[j] - n225[pos] >= target:
                exit_pos, reason = j, "利確"
                break
        if exit_pos is None:
            exit_pos = horizon
            reason = "期限売り" if pos + hold_limit <= last_pos else "保有中"
        path = lev[pos + 1: exit_pos + 1] / lev[pos] - 1
        rows.append({
            "買い日": idx.date(),
            "売り日": frame.index[exit_pos].date(),
            "保有日数": exit_pos - pos,
            "ETF損益(%)": round((lev[exit_pos] / lev[pos] - 1) * 100, 2),
            "最大含み損(%)": round(min(path.min(), 0) * 100, 2),
            "結果": reason,
        })
    return pd.DataFrame(rows)


st.markdown("---")
st.subheader("🧪 バックテスト（終値で買い、終値で売り）")
st.caption(
    "買い：条件を満たした日の終値。売り：日経平均が購入日の終値から"
    f"＋{target_yen:,}円に到達した日の終値、最大{max_hold}日で期限売り。"
    "シグナルが続く日は、それぞれ独立して買ったものとして数えます。"
    "手数料・信託報酬・税金は含みません。"
)

if len(signals) == 0:
    st.warning("条件に合うシグナルが見つかりませんでした。条件をゆるめてみてください。")
else:
    trades = simulate(df, target_yen, max_hold)
    closed = trades[trades["結果"].isin(["利確", "期限売り"])]
    if len(closed) == 0:
        st.info("決済済みの取引がまだありません。")
    else:
        wins = int((closed["ETF損益(%)"] > 0).sum())
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("決済済み件数", f"{len(closed)}件")
        c2.metric("勝率", f"{wins / len(closed) * 100:.1f}%", f"{wins}勝{len(closed) - wins}敗")
        c3.metric("平均損益", f"{closed['ETF損益(%)'].mean():+.2f}%")
        c4.metric("平均保有日数", f"{closed['保有日数'].mean():.1f}日")
        c5.metric("最悪の含み損", f"{closed['最大含み損(%)'].min():.1f}%")
        n_exp = int((closed["結果"] == "期限売り").sum())
        st.markdown(f"利確 **{len(closed) - n_exp}件** ／ 期限売り **{n_exp}件**"
                    f"（期限売りの平均損益: {closed[closed['結果'] == '期限売り']['ETF損益(%)'].mean():+.2f}%）"
                    if n_exp else f"利確 **{len(closed)}件** ／ 期限売り **0件**")

        st.markdown("**年別**")
        tmp = closed.copy()
        tmp["年"] = pd.to_datetime(tmp["買い日"]).dt.year
        yearly = tmp.groupby("年").agg(
            件数=("ETF損益(%)", "size"),
            勝率=("ETF損益(%)", lambda s: round((s > 0).mean() * 100, 1)),
            平均損益=("ETF損益(%)", lambda s: round(s.mean(), 2)),
            最悪含み損=("最大含み損(%)", "min"),
        )
        st.dataframe(yearly, use_container_width=True)

    with st.expander("取引一覧"):
        def color_pl(val):
            try:
                v = float(val)
                return "color: red" if v < 0 else "color: blue"
            except (TypeError, ValueError):
                return ""
        st.dataframe(trades.style.map(color_pl, subset=["ETF損益(%)", "最大含み損(%)"]),
                     use_container_width=True, hide_index=True)

st.markdown("---")

# --- 翌日・3日後・5日後リターン計算 ---
returns = []
for idx in signals.index:
    pos = df.index.get_loc(idx)
    row = {"シグナル日": idx.date(),
           "日経(円)": round(df["N225_diff"].iloc[pos], 0),
           "日経累積(円)": round(df["N225_cum_diff"].iloc[pos], 0) if mode == "円モード" else "-",
           "日経累積(%)": round(df["N225_cum_ret"].iloc[pos], 2),
           "ETF変化率(%)": round(df["LEV_ret"].iloc[pos], 2),
           "STEP3点数": int(df["s3n"].iloc[pos])}
    if is_1570:
        row["理論値(%)"] = round(df["LEV_theory"].iloc[pos], 2)
        row["乖離(%)"] = round(df["LEV_excess"].iloc[pos], 2)

    for days, label in [(1, "翌日%"), (3, "3日後%"), (5, "5日後%")]:
        if pos + days < len(df):
            future_ret = ((df["LEV"].iloc[pos + days] - df["LEV"].iloc[pos]) / df["LEV"].iloc[pos]) * 100
            row[label] = round(future_ret, 2)
        else:
            row[label] = None

    returns.append(row)

if returns:
    result_df = pd.DataFrame(returns)

    st.subheader("📋 シグナル後の固定日数リターン（終値→終値）")
    for col in ["翌日%", "3日後%", "5日後%"]:
        vals = result_df[col].dropna()
        if len(vals) == 0:
            continue
        wins = (vals > 0).sum()
        total = len(vals)
        avg = vals.mean()
        st.markdown(f"**{col}** ｜ 勝率: **{wins}/{total} ({wins/total*100:.1f}%)** ｜ 平均リターン: **{avg:+.2f}%**")

    def color_ret(val):
        if val is None or val == "-": return ""
        try:
            v = float(val)
            return "color: red" if v < 0 else "color: blue"
        except: return ""

    styled = result_df.style.map(color_ret, subset=["翌日%", "3日後%", "5日後%"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

# --- チャート ---
st.markdown("---")
st.subheader(f"📊 日経225 vs {etf_label.split('（')[0]} 累積リターン比較")

df_chart = df[["N225", "LEV"]].copy()
df_chart["N225_norm"] = df_chart["N225"] / df_chart["N225"].iloc[0] * 100
df_chart["LEV_norm"]  = df_chart["LEV"]  / df_chart["LEV"].iloc[0]  * 100

st.line_chart(df_chart[["N225_norm", "LEV_norm"]], use_container_width=True)
st.caption("基準日=100として正規化（青：日経225、赤：選択したETF）")

if len(signals) > 0 and is_1570:
    st.markdown("---")
    st.subheader("🔴 シグナル発生日の乖離詳細")
    detail = signals[["N225_diff", "N225_cum_diff", "N225_ret", "LEV_ret", "LEV_theory", "LEV_excess"]].copy()
    detail.columns = ["日経日次(円)", "日経累積(円)", "日経日次(%)", "1570実際(%)", "1570理論(%)", "乖離(%)"]
    detail.index = detail.index.date
    st.dataframe(detail.style.map(
        lambda v: "color: red" if isinstance(v, float) and v < 0 else "color: blue" if isinstance(v, float) and v > 0 else ""
    ), use_container_width=True)

st.caption("⚠️ 投資判断はご自身の責任で。過去の結果は将来の成績を保証しません。")
