import json
import locale
import time
from datetime import timezone, timedelta

import ccxt
import pandas as pd
import plotly.graph_objs as go
import plotly.io as pio
from dotenv import load_dotenv
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import sessionmaker, declarative_base
from flask import Flask, render_template, request, jsonify, url_for, session, redirect

# from orders_db_v1_5 import *
from db_func import *

load_dotenv()

locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")
SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
model_registry = {}
models_asks = []
models_bids = []


def make_null_after_t(raw_datetime: str) -> str: return f"{raw_datetime.split('T')[0]}T00:00:00Z"


format_pattern_ = "%Y-%m-%dT%H:%M:%SZ"
dt_now_ = datetime.now(tz=timezone.utc)
START_TIMESTAMPS = {
    "1m": make_null_after_t((dt_now_ - relativedelta(days=1)).strftime(format_pattern_)),
    "5m": make_null_after_t((dt_now_ - relativedelta(days=3)).strftime(format_pattern_)),
    "15m": make_null_after_t((dt_now_ - relativedelta(days=5)).strftime(format_pattern_)),
    "30m": make_null_after_t((dt_now_ - relativedelta(days=15)).strftime(format_pattern_)),
    "1h": make_null_after_t((dt_now_ - relativedelta(months=1)).strftime(format_pattern_)),
    "2h": make_null_after_t((dt_now_ - relativedelta(days=45)).strftime(format_pattern_)),
    "4h": make_null_after_t((dt_now_ - relativedelta(months=2)).strftime(format_pattern_)),
}


def update_start_timestamps():
    global START_TIMESTAMPS

    format_pattern = "%Y-%m-%dT%H:%M:%SZ"
    dt_now = datetime.now(tz=timezone.utc)

    START_TIMESTAMPS["1m"] = make_null_after_t((dt_now - relativedelta(days=1)).strftime(format_pattern))
    START_TIMESTAMPS["5m"] = make_null_after_t((dt_now - relativedelta(days=3)).strftime(format_pattern))
    START_TIMESTAMPS["15m"] = make_null_after_t((dt_now - relativedelta(days=5)).strftime(format_pattern))
    START_TIMESTAMPS["30m"] = make_null_after_t((dt_now - relativedelta(days=15)).strftime(format_pattern))
    START_TIMESTAMPS["1h"] = make_null_after_t((dt_now - relativedelta(months=1)).strftime(format_pattern))
    START_TIMESTAMPS["2h"] = make_null_after_t((dt_now - relativedelta(days=45)).strftime(format_pattern))
    START_TIMESTAMPS["4h"] = make_null_after_t((dt_now - relativedelta(months=2)).strftime(format_pattern))


TIMEFRAMES_REFERENCE = {
    "1m": (pd.Timedelta(hours=1), pd.Timedelta(minutes=4)),
    "5m": (pd.Timedelta(hours=3), pd.Timedelta(minutes=2.5)),  # minutes  2.33
    "15m": (pd.Timedelta(hours=7), pd.Timedelta(minutes=7.5)),  # minutes
    "30m": (pd.Timedelta(hours=14), pd.Timedelta(minutes=15)),  # minutes
    "1h": (pd.Timedelta(hours=28), pd.Timedelta(minutes=30)),  # hour
    "2h": (pd.Timedelta(hours=56), pd.Timedelta(hours=1)),  # hours
    "4h": (pd.Timedelta(hours=112), pd.Timedelta(hours=2)),  # hours
}

EXCHANGE = ccxt.bybit(
    {
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future'
        }
    }
)

# todo: make the crypto quantity per order dependent on the current price while keeping the index-0 constant fixed
SYMBOLS_CONSTANTS = {
    "BTCUSDT": [10000, 2000000, 30],  # for [1]: 5 <- 6000000
    "ETHUSDT": [7000, 2000000, 2],  # for [1]: 2500 <- 6000000
    "SOLUSDT": [5000, 2000000, 0.4]  # for [1]: 2500 <- 6000000
}

asks_for_nz = []
bids_for_nz = []
SYMBOL = ""
DF = pd.DataFrame()
TF = ""
time_count = 0
BARS_SCALE_COEF = 0
ID_OF_COMPLETED_ORDERS = dict()
BINANCE_LIMIT = 5000  # 1000
NZ_VOLUME_ROUNDING_CONST = 4
total_ask_value = []
total_bid_value = []
nzVolume = 0


def fetch_candlestick_data(symbol="BTC/USDT", timeframe='15m'):
    START_TIMESTAMP = START_TIMESTAMPS.get(timeframe)
    since = EXCHANGE.parse8601(START_TIMESTAMP)
    ohlcv = []
    while True:
        batch = EXCHANGE.fetch_ohlcv(symbol, timeframe, since=since)
        if len(batch) == 0:
            break
        ohlcv.extend(batch)
        since = batch[-1][0] + (EXCHANGE.parse_timeframe(timeframe) * 1000)
        time.sleep(EXCHANGE.rateLimit / 1000)  # Wait according to rate limit
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df


def retrieve_time_data(row_):
    date_str_ = row_["timestamp"].strftime("%Y-%m-%d")
    time_str_ = row_["timestamp"].strftime("%H:%M")
    minutes_ = row_["timestamp"].minute
    hours_ = row_["timestamp"].hour
    days_ = row_["timestamp"].day
    months_ = row_["timestamp"].month
    # print(f"{hour=} | {minute=} | {type(hour)=} | {type(minute)=}")
    return date_str_, time_str_, minutes_, hours_, days_, months_


def add_date(dates_dict_, date_str_, time_str_, row_) -> None:
    if date_str_ in dates_dict_:
        dates_dict_[date_str_][0].append(time_str_)
        dates_dict_[date_str_][1].append(row_["timestamp"])
    else:
        dates_dict_[date_str_] = [[f"{datetime.strftime(datetime.strptime(date_str_, '%Y-%m-%d'), '%d %b')}"], [row_["timestamp"]]]


def add_date_advanced(dates_dict_, date_str_, time_str_, row_, time_count_) -> None:
    global time_count
    if date_str_ not in dates_dict_.keys():
        dates_dict_[date_str_] = [[f"{datetime.strftime(datetime.strptime(date_str_, '%Y-%m-%d'), '%d %b')}"], [row_["timestamp"]]]
        time_count = 0
    else:
        if time_count == time_count_:
            dates_dict_[date_str_][0].append(time_str_)
            dates_dict_[date_str_][1].append(row_["timestamp"])
            time_count = 0


def update_nz_volume(asks_, bids_, rounding_const: int = 4):
    total_ask_value_ = round(sum(volume for price, volume in asks_), rounding_const)
    total_bid_value_ = round(sum(volume for price, volume in bids_), rounding_const)
    return total_ask_value_, total_bid_value_, round(total_ask_value_ + total_bid_value_, rounding_const)


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
# app.permanent_session_lifetime = True  # 31 days

PSW_HASH = os.getenv("PSW")


def check_psw(psw_input: str) -> bool:
    import hashlib
    return hashlib.sha256(psw_input.encode()).hexdigest() == PSW_HASH


@app.route("/main-chart/create_candle_plot", methods=["GET"])
def create_candle_plot():
    if not session.get("logged_in"):
        return redirect(url_for("authorise"))

    global time_count

    tf = request.args.get("timeframe", "15m")
    print(f"{tf=}\n")
    symbol = request.args.get("symbol", "BTC/USDT")
    symbol = symbol.replace('/', '')  # in an appropriate for Binance API format
    df = fetch_candlestick_data(symbol, tf)  # symbol, tf

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=df['timestamp'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name='Candlestick',
        increasing_line_color='lime',
        decreasing_line_color='red',
    ))

    update_layout_xaxis = dict(
        title='Time',
        showgrid=False,
        tickformat="%H:%M",
        rangeslider=dict(visible=False)
    )

    dates_dict = dict()
    last_timestamp = df.iloc[-1]["timestamp"]
    print(f"{last_timestamp=}")

    # use these values to scale bar height
    # low_max = df["low"].max() - (abs(df["low"].mean() - df["low"].min()) // 2)
    # high_min = df["high"].min() + (abs(df["high"].mean() - df["high"].max()) // 2)

    # xaxis_range = []

    right_x_value = last_timestamp + TIMEFRAMES_REFERENCE.get(tf)[0]
    match tf:
        case "1m":
            for idx, row in df.iterrows():
                date_str, time_str, minutes, _, _, _ = retrieve_time_data(row)
                time_count += 1
                if minutes in (0, 30):
                    add_date_advanced(dates_dict, date_str, time_str, row, 30)  # 30-min interval

            pprint(list(dates_dict.values()))
            dates_dict_list = list(dates_dict.values())[-1][1]
            print(f"{len(dates_dict_list)=}")
            try:
                xaxis_range = [dates_dict_list[round(len(dates_dict_list) - len(dates_dict_list) / 3)], right_x_value]
            except IndexError:
                print("\nINDEX ERROR\n")
                xaxis_range = [dates_dict_list[0], right_x_value]
            print(f"{xaxis_range=}")
            fig.update_xaxes(
                range=xaxis_range
            )

        case "5m":
            for idx, row in df.iterrows():
                date_str, time_str, minutes, _, _, _ = retrieve_time_data(row)
                time_count += 1
                if minutes in (0, 30):
                    add_date_advanced(dates_dict, date_str, time_str, row, 18)

            pprint(list(dates_dict.values()))
            dates_dict_list = list(dates_dict.values())[-2][1]
            xaxis_range = [dates_dict_list[len(dates_dict_list) - len(dates_dict_list) // 3], right_x_value]
            fig.update_xaxes(
                range=xaxis_range
            )

        case "15m":
            for idx, row in df.iterrows():
                date_str, time_str, minutes, _, _, _ = retrieve_time_data(row)
                # print(date_str, time_str, minutes)
                time_count += 1
                if minutes == 0:
                    add_date_advanced(dates_dict, date_str, time_str, row, 12)
            xaxis_range = [list(dates_dict.values())[-2][1][0], right_x_value]

            fig.update_xaxes(
                range=xaxis_range
            )

        case "30m":
            for idx, row in df.iterrows():
                date_str, time_str, minutes, _, _, _ = retrieve_time_data(row)
                time_count += 1
                if minutes in (0, 30):
                    add_date_advanced(dates_dict, date_str, time_str, row, 13)
            xaxis_range = [list(dates_dict.values())[-3][1][0], right_x_value]
            fig.update_xaxes(
                range=xaxis_range
            )

        case "1h":
            for idx, row in df.iterrows():
                date_str, time_str, _, hours, _, _ = retrieve_time_data(row)
                time_count += 1
                if hours in (0, 12):
                    add_date_advanced(dates_dict, date_str, time_str, row, 12)
            xaxis_range = [list(dates_dict.values())[-4][1][0], right_x_value]
            fig.update_xaxes(
                range=xaxis_range
            )

        case "2h":
            for idx, row in df.iterrows():
                date_str, time_str, _, hours, _, _ = retrieve_time_data(row)
                if hours == 0:
                    add_date(dates_dict, date_str, time_str, row)
            xaxis_range = [list(dates_dict.values())[-5][1][0], right_x_value]
            fig.update_xaxes(
                range=xaxis_range
            )

        case "4h":
            for idx, row in df.iterrows():
                date_str, time_str, _, _, days, _ = retrieve_time_data(row)
                time_count += 1
                if days % 2 == 0:
                    add_date_advanced(dates_dict, date_str, time_str, row, 12)
            xaxis_range = [list(dates_dict.values())[-6][1][0], right_x_value]
            fig.update_xaxes(
                range=xaxis_range
            )

    tickvals = []
    ticktext = []
    for val in dates_dict.values():
        tickvals.extend(val[1])
        ticktext.extend(val[0])

    update_layout_xaxis["tickvals"] = tickvals
    update_layout_xaxis["ticktext"] = ticktext

    update_layout_xaxis["range"] = xaxis_range

    global asks_for_nz, bids_for_nz, total_ask_value, total_bid_value, nzVolume

    shapes = []
    asks_for_nz = get_order_book(symbol, BINANCE_LIMIT, "asks")
    bids_for_nz = get_order_book(symbol, BINANCE_LIMIT, "asks")

    total_ask_value, total_bid_value, nzVolume = update_nz_volume(asks_for_nz, bids_for_nz, NZ_VOLUME_ROUNDING_CONST)

    SessionMakerAsks = sessionmaker(bind=engine_asks)
    SessionMakerBids = sessionmaker(bind=engine_bids)

    session_asks = SessionMakerAsks()
    session_bids = SessionMakerBids()

    print(f"\nFETCH DATA INFO (START)\n")
    print(f"{symbol=} {get_latest_price(symbol)=}")
    for symbol_ in SYMBOLS:
        symbol_ = symbol_.replace('/', '')
        fetch_data(
            session_asks,
            session_bids,
            symbol,
            model_registry,
            BINANCE_LIMIT,
            SYMBOLS_CONSTANTS.get(symbol_)[1]
        )


    # conn_asks = sqlite3.connect("orders_asks.db")
    # cursor_asks = conn_asks.cursor()
    # conn_bids = sqlite3.connect("orders_bids.db")
    # cursor_bids = conn_bids.cursor()
    #
    # print(f"\nFETCH DATA INFO (START)\n")
    # print(f"{symbol=} {get_latest_price(symbol)=}")
    # for symbol_ in SYMBOLS:
    #     symbol_ = symbol_.replace('/', '')
    #     fetch_data(
    #         conn_asks,
    #         cursor_asks,
    #         conn_bids,
    #         cursor_bids,
    #         symbol_,
    #         BINANCE_LIMIT,
    #         SYMBOLS_CONSTANTS.get(symbol_)[1]
    #     )
    # print(f"\nFETCH DATA INFO (END)\n")

    def create_shapes_from_orders(orders_dict: dict[float: [float, str]], key_to_order_book: str) -> float | None:
        assert key_to_order_book in ("asks", "bids")
        y_bar_constant = SYMBOLS_CONSTANTS.get(symbol)[2]
        print("ORDERS DICT")
        pprint(orders_dict)

        lim_showed_order_price = None
        orders_dict_keys = sorted(orders_dict) if key_to_order_book == "asks" else sorted(orders_dict, reverse=True)

        for key_price in orders_dict_keys:
            if round(datetime.timestamp(datetime.now())) - orders_dict.get(key_price)[2] > 300:  # > 5 min to filter out spoof orders
                if lim_showed_order_price is None:
                    lim_showed_order_price = key_price
                current_color = orders_dict.get(key_price)[1]
                rect = {
                    "type": "rect",
                    "x0": last_timestamp + TIMEFRAMES_REFERENCE.get(tf)[1],
                    "y0": key_price - y_bar_constant,
                    "x1": right_x_value,
                    "y1": key_price + y_bar_constant,
                    "fillcolor": current_color,
                    "opacity": 0.9,
                    "line": {
                        "width": 0
                    }
                }
                shapes.append(rect)

        return lim_showed_order_price

    arrow_y_coord = None
    lim_color = None
    lim_volume = None
    arrow_shape = dict()

    current_price = get_latest_price(symbol)

    if model_registry:
        all_asks = get_orders_dict(session_asks, symbol, model_registry, "asks")
        min_asks_val = create_shapes_from_orders(all_asks, "asks")  # asks bars

        all_bids = get_orders_dict(session_bids, symbol, model_registry, "bids")
        max_bids_val = create_shapes_from_orders(all_bids, "bids")  # bids bars

        print(f"{min_asks_val=}")
        print(f"{max_bids_val=}")
        if min_asks_val or max_bids_val:
            if ((min_asks_val is not None) and (max_bids_val is None)) or abs(min_asks_val - current_price) < abs(max_bids_val - current_price):
                arrow_y_coord = min_asks_val
                lim_color = "deeppink"
                lim_volume = all_asks.get(arrow_y_coord)[0]
            else:
                arrow_y_coord = max_bids_val
                lim_color = "lightgreen"
                lim_volume = all_bids.get(arrow_y_coord)[0]

            arrow_shape = {
                "xref": 'x',
                "yref": 'y',
                "axref": 'x',
                "ayref": 'y',
                "ax": last_timestamp - TIMEFRAMES_REFERENCE.get(tf)[0] if 'm' in tf else last_timestamp - TIMEFRAMES_REFERENCE.get(tf)[0] // 3,
                'x': last_timestamp + TIMEFRAMES_REFERENCE.get(tf)[1],
                "ay": arrow_y_coord,
                "y": arrow_y_coord,
                "text": f"{round(arrow_y_coord, 3)} | {round(lim_volume, 2)}",
                "showarrow": True,
                "arrowhead": 2,
                "arrowcolor": lim_color,
                "font": {
                    "color": "white"
                },
                "xanchor": "center",
                "yanchor": "bottom"
            }

        print(f"ax: {last_timestamp - TIMEFRAMES_REFERENCE.get(tf)[0]}")
        print(f"x: {last_timestamp + TIMEFRAMES_REFERENCE.get(tf)[1]}")
        print(f"ay: {arrow_y_coord}")
        print(f"y: {arrow_y_coord}")

    annotations_list = [
        {
            'x': 0,
            'y': 1,
            "text": f"asks: {total_ask_value} bids: {total_bid_value} nzVolume: {nzVolume}",
            "showarrow": False,
            "xref": "paper",
            "yref": "paper",
            "xanchor": "left",
            "yanchor": "top",
            "font": {
                "size": 13,
                "color": "#7A7A7C"
            }
        }
    ]
    if arrow_shape:
        annotations_list.append(arrow_shape)

    update_start_timestamps()
    fig.update_layout(
        plot_bgcolor='#101014',
        paper_bgcolor='#101014',
        font=dict(color="#7A7A7C"),
        xaxis=update_layout_xaxis,
        yaxis=dict(
            title='Price',
            showgrid=True,
            gridcolor='darkgrey',
        ),
        # title='Candlestick chart with order zones',
        template='plotly_dark',
        height=600,
        margin=dict(t=5),
        annotations=annotations_list,
        shapes=shapes
    )

    def orders_front_end_format(orders_dict: dict) -> list:
        return [[order_dict_key, orders_dict.get(order_dict_key)[0]] for order_dict_key in orders_dict.keys()]

    graph_json = pio.to_json(fig)
    graph_json_dict = json.loads(graph_json)

    asks_for_nz = orders_front_end_format(all_asks)
    bids_for_nz = orders_front_end_format(all_bids)

    graph_json_dict["total_ask_value"] = total_ask_value
    graph_json_dict["total_bid_value"] = total_bid_value
    graph_json_dict["asks"] = asks_for_nz
    graph_json_dict["bids"] = bids_for_nz
    graph_json_dict["nzvolume"] = nzVolume

    # print("orders_front_end_format(all_asks)")
    # pprint(graph_json_dict["asks"])
    # print()
    # print("orders_front_end_format(all_bids)")
    # pprint(graph_json_dict["bids"])

    graph_json = json.dumps(graph_json_dict)

    session_asks.close()
    session_bids.close()

    return jsonify(graph_json)

@app.route('/main-chart', methods=['GET', 'POST'])
def index():
    if not session.get("logged_in"):
        return redirect(url_for("authorise"))

    global asks_for_nz, bids_for_nz, total_ask_value, total_bid_value, nzVolume
    global model_registry, models_asks, models_bids

    # global CONN_ASKS, CUR_ASKS, CONN_BIDS, CUR_BIDS

    # conn_asks = sqlite3.connect("orders_asks.db")
    # conn_bids = sqlite3.connect("orders_bids.db")

    # create_databases_by_symbols(conn_asks, SYMBOLS)
    # create_databases_by_symbols(conn_bids, SYMBOLS)

    if "visits" in session:
        session["visits"] = session.get("visits") + 1  # updating the session data
    else:
        session["visits"] = 1
    print(f"\nVISIT COUNT: {session["visits"]}\n")

    BaseAsks = declarative_base()
    BaseBids = declarative_base()

    models_asks = []
    models_bids = []

    for sym in SYMBOLS:
        AsksOrder = create_models_by_symbols(sym, BaseAsks)
        models_asks.append(AsksOrder)

        BidsOrder = create_models_by_symbols(sym, BaseBids)
        models_bids.append(BidsOrder)

    BaseAsks.metadata.create_all(engine_asks)
    BaseBids.metadata.create_all(engine_bids)

    symbols_replaced = [sym.replace('/', '') for sym in SYMBOLS]
    model_registry = {
        "asks": {k: v for k, v in zip(symbols_replaced, models_asks)},
        "bids": {k: v for k, v in zip(symbols_replaced, models_bids)}
    }

    selected_option_symbol = "BTC/USDT"
    print("RENDER:")
    print(f"{total_ask_value=}")
    print(f"{total_bid_value=}")
    print(f"{asks_for_nz=}")
    print(f"{bids_for_nz=}")
    print(f"{nzVolume=}")

    return render_template(
        'index.html',
        symbols=SYMBOLS,
        selected_option_symbol=selected_option_symbol,
        total_ask_value=total_ask_value,
        total_bid_value=total_bid_value,
        asks=asks_for_nz,
        bids=bids_for_nz,
        nzvolume=nzVolume
    )


@app.route('/', methods=['GET', 'POST'])
def authorise():
    if request.method == "POST":
        psw = request.form.get("psw")
        remember = request.form.get("rememberme")

        if check_psw(psw):
            session["logged_in"] = True
            if remember:
                session.permanent = True
                app.permanent_session_lifetime = timedelta(days=30)
            return redirect(url_for("index"))
        else:
            return render_template("error.html")
    else:
        if session.get("logged_in"):
            return redirect(url_for("index"))
        return render_template("authorisation.html")



if __name__ == '__main__':
    app.run(
        debug=True,
        # host="0.0.0.0"
        # port=8080
    )
