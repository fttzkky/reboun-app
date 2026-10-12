import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, date

st.set_page_config(page_title="1570 vs 日経225 下回り日数", page_icon="📉", layout="wide")
st.title("📉 1570が日経225を下回った日数")
st.caption("データ元: Yahoo Finance（^N225 / 1570.T）の終値（Close、配当・分割調整なし）")

start = st.sidebar.date_input("開始日", value=date(2020, 1, 1))
end = st.sidebar.date_input("終了日", value=date.today())
basis = st.sidebar.radio(
    "比較方法",
    ["終値そのもの（円）", "前日比騰落率（%）", "基準日=100で正規化"],
    help="終値（円）同士はスケールが違うため、ほぼ毎日1570の方が低くなります。",
)


@st.cache_data(ttl=3600)
def load(start, end):
    # yfinance の end は排他的なので1日足す
    end_excl = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    out = {}
    for name, tk in [("日経225", "^N225"), ("1570", "1570.T")]:
        s = yf.download(tk, start=start, end=end_excl, progress=False, auto_adjust=False)["Close"]
        if isinstance(s, pd.DataFrame):
            s = s.squeeze()
        out[name] = s
    df = pd.DataFrame(out)
    df.index = pd.to_datetime(df.index).date
    return df


with st.spinner("データ取得中..."):
    raw = load(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

if raw.empty:
    st.error("データが取得できませんでした。")
    st.stop()

# 両方の終値がある日だけ比較（片方が休場・欠損の日は除外して別表示）
missing = raw[raw.isna().any(axis=1)]
df = raw.dropna().copy()

if basis == "終値そのもの（円）":
    a, b, unit = df["1570"], df["日経225"], "円"
elif basis == "前日比騰落率（%）":
    a = df["1570"].pct_change() * 100
    b = df["日経225"].pct_change() * 100
    unit = "%"
else:
    a = df["1570"] / df["1570"].iloc[0] * 100
    b = df["日経225"] / df["日経225"].iloc[0] * 100
    unit = "pt"

df["1570比較値"] = a.round(4)
df["日経225比較値"] = b.round(4)
df["差(1570-日経)"] = (a - b).round(4)
df["1570が下回った"] = a < b
valid = df.dropna(subset=["1570比較値", "日経225比較値"])
hit = valid[valid["1570が下回った"]]

c1, c2, c3, c4 = st.columns(4)
c1.metric("下回った日数", f"{len(hit)}日")
c2.metric("比較対象営業日", f"{len(valid)}日")
c3.metric("割合", f"{len(hit) / len(valid) * 100:.1f}%" if len(valid) else "-")
c4.metric("期間", f"{valid.index[0]} 〜 {valid.index[-1]}")

if basis == "終値そのもの（円）":
    st.info("1570の価格は日経平均の数値より小さい水準で推移しているため、円の終値比較だと"
            "ほぼ全日『下回り』になります。値動きで比べたい場合は『前日比騰落率』を選んでください。")

st.subheader("📅 年別")
yearly = valid.groupby(pd.to_datetime(valid.index).year)["1570が下回った"].agg(["sum", "count"])
yearly.columns = ["下回った日数", "営業日数"]
st.dataframe(yearly, use_container_width=True)

st.subheader(f"🧾 エビデンス：下回った日一覧（{len(hit)}日）")
st.caption("各日の両終値と比較値。Yahoo Financeの時系列ページで日付ごとに照合できます：" 
           "[^N225](https://finance.yahoo.com/quote/%5EN225/history/) / "
           "[1570.T](https://finance.yahoo.com/quote/1570.T/history/)")
cols = ["日経225", "1570", "日経225比較値", "1570比較値", "差(1570-日経)"]
show = hit[cols].rename(columns={"日経225": "日経225終値", "1570": "1570終値"})
show.index.name = "日付"
st.dataframe(show, use_container_width=True)
st.download_button("下回った日一覧をCSVで保存", show.to_csv().encode("utf-8-sig"),
                   file_name=f"1570_below_n225_{basis[:4]}.csv", mime="text/csv")

with st.expander("全営業日の比較データ（検証用）"):
    full = valid[cols + ["1570が下回った"]]
    st.dataframe(full, use_container_width=True)
    st.download_button("全データをCSVで保存", full.to_csv().encode("utf-8-sig"),
                       file_name="1570_vs_n225_all.csv", mime="text/csv")

if not missing.empty:
    with st.expander(f"片方しかデータがない日（除外: {len(missing)}日）"):
        st.dataframe(missing, use_container_width=True)
