"""4.3ブルの積立シミュレーション（理論値）の計算部分。画面（app.py）から呼び出す。"""
import pandas as pd


def theoretical_nav(close, leverage=4.3, fee_yearly=0.00968):
    """日経平均の終値から、レバレッジ型の基準価額（理論値）を作る。
    毎日の騰落率に倍率を掛け、信託報酬（年率）を日割りで引く。"""
    r = close.pct_change().fillna(0.0)
    daily = (leverage * r - fee_yearly / 252).clip(lower=-0.999)
    return 10000.0 * (1.0 + daily).cumprod()


def simulate(nav, monthly=100_000, target=1_200_000, tax=0.20315, sell=True):
    """毎月、最初の営業日に monthly 円を買い、含み益が target 円以上になったら、その日に全部売る。
    売った後は、また積立を続ける。売却益には、税率 tax がかかるものとする。"""
    month_first = set(nav.groupby([nav.index.year, nav.index.month]).head(1).index)
    units, cost = 0.0, 0.0
    contributed = 0.0
    cash_net = 0.0          # 売って受け取った手取り（税引後）の合計
    sells = []
    first_buy_date = None
    for d, p in nav.items():
        if d in month_first:
            units += monthly / p
            cost += monthly
            contributed += monthly
            if first_buy_date is None:
                first_buy_date = d
            if cost == monthly:          # 売却後の最初の買い
                first_buy_date = d
        value = units * p
        if sell and units > 0 and value - cost >= target:
            gain = value - cost
            tax_amt = gain * tax
            net = value - tax_amt
            sells.append({
                "売却日": d.date(), "保有開始": first_buy_date.date(),
                "取得額": round(cost), "売却額": round(value),
                "利益": round(gain), "税額": round(tax_amt), "税引後の利益": round(gain - tax_amt),
            })
            cash_net += net
            units, cost = 0.0, 0.0
    last_p = nav.iloc[-1]
    hold_value = units * last_p
    return {
        "contributed": contributed,
        "sells": pd.DataFrame(sells),
        "cash_net": cash_net,
        "hold_value": hold_value,
        "hold_cost": cost,
        "total_wealth": cash_net + hold_value,
    }


def required_nav(units, avg_cost, keep_units=0, target_profit=20_000, tax=0.20315):
    """売る基準価額を、正確に計算する（平均取得単価の方式）。
    units: 保有口数、avg_cost: 平均取得単価（1万口あたりの円）、keep_units: 残す口数。
    売った分の手取り（税引後）が、全体の取得額＋target_profit 以上になる、基準価額（1万口あたり）を返す。"""
    sell = units - keep_units
    if sell <= 0:
        return None
    total_cost = units * avg_cost / 10_000
    sold_cost = sell * avg_cost / 10_000
    # 利益が出る場合：売却額×(1−税率) ＋ 税率×売った分の取得額 ＝ 取得額＋目標
    p_gain = 10_000 * (total_cost + target_profit - tax * sold_cost) / ((1 - tax) * sell)
    if p_gain > avg_cost:
        return p_gain
    # 利益が出ない（税金がかからない）場合
    return 10_000 * (total_cost + target_profit) / sell


def net_cash(units, avg_cost, keep_units, nav, tax=0.20315):
    """基準価額 nav で、keep_units を残して売った場合の、手取り（税引後）と税額を返す。"""
    sell = units - keep_units
    proceeds = sell * nav / 10_000
    gain = proceeds - sell * avg_cost / 10_000
    tax_amt = max(gain, 0) * tax
    return proceeds - tax_amt, tax_amt, proceeds
