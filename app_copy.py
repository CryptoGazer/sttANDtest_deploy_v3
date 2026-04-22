import ccxt
import requests
from flask import Flask, render_template, request, jsonify
# from flask_sqlalchemy import SQLAlchemy
# from sqlalchemy import inspect
# from sqlalchemy.ext.declarative import as_declarative, declared_attr
import plotly.graph_objs as go
import plotly.io as pio
import pandas as pd

import json
import time
import locale
import sqlite3
import threading
from pprint import pprint
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

# from orders_db_v1_5 import *

locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")
# DATABASES = {
#     "order_asks": "sqlite:///order_asks.db",
#     "orders_bids.db": "sqlite:///orders_bids.db.db"
# }
SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")


# app.config["SQLALCHEMY_BINDS"] = DATABASES
# db = SQLAlchemy(app)


# def is_db_empty(bind) -> bool:
#     with app.app_context():
#         engine = db.engines[bind]  # because .get_engine(bind) is deprecated
#         inspector = inspect(engine)
#         tables = inspector.get_table_names()
#         return len(tables) == 0
#
#
# def dynamic_symbol_model_generation(symbol: str, bind_key: str):
#     assert bind_key in ("order_asks", "orders_bids.db")
#
#     class SymbolModel(db.Model):
#         __tablename__ = symbol
#         __bind_key__ = bind_key
#         id = db.Column(db.Integer, primary_key=True)
#         price = db.Column(db.REAL)
#         volume = db.Column(db.REAL)
#         color = db.Column(db.TEXT(20))
#     return SymbolModel

# def create_new_tables(symbols_, bind_key: str) -> None:
#     for symbol in symbols_:
#         _ = dynamic_symbol_model_generation(symbol, bind_key)
#     with app.app_context():
#         print("creating...")
#         db.create_all(bind_key=bind_key)


# if is_db_empty("order_asks"):
#     create_new_tables(SYMBOLS, "order_asks")
# if is_db_empty("orders_bids.db"):
#     create_new_tables(SYMBOLS, "orders_bids.db")


def make_null_after_t(raw_datetime: str):
    return f"{raw_datetime.split('T')[0]}T00:00:00Z"


format_pattern_ = "%Y-%m-%dT%H:%M:%SZ"
dt_now_ = datetime.now(tz=timezone.utc)
START_TIMESTAMPS = {
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

    START_TIMESTAMPS["5m"] = make_null_after_t((dt_now - relativedelta(days=3)).strftime(format_pattern))
    START_TIMESTAMPS["15m"] = make_null_after_t((dt_now - relativedelta(days=5)).strftime(format_pattern))
    START_TIMESTAMPS["30m"] = make_null_after_t((dt_now - relativedelta(days=15)).strftime(format_pattern))
    START_TIMESTAMPS["1h"] = make_null_after_t((dt_now - relativedelta(months=1)).strftime(format_pattern))
    START_TIMESTAMPS["2h"] = make_null_after_t((dt_now - relativedelta(days=45)).strftime(format_pattern))
    START_TIMESTAMPS["4h"] = make_null_after_t((dt_now - relativedelta(months=2)).strftime(format_pattern))


TIMEFRAMES_REFERENCE = {
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

# todo: сделать величину количества криптовалюты в ордере зависимой от текущей цены при неизменной константе по индексу 0
SYMBOLS_CONSTANTS = {
    "BTCUSDT": [10000, 5, 30],  # 1
    "ETHUSDT": [7000, 130, 2],
    "SOLUSDT": [5000, 2500, 0.4]
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
BASE_URL = "https://api.binance.com"
ROUNDING_CONSTANTS = {
    "BTCUSDT": -1,
    "ETHUSDT": 0,
    "SOLUSDT": 1
}


def create_databases_by_symbols(conn, symbols_: list | tuple):
    cursor = conn.cursor()
    print("creating DB")
    for symbol in symbols_:
        symbol = symbol.replace('/', '')
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS orders_{symbol} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                price REAL,
                volume REAL,
                color VARCHAR(30)
            )
        ''')


def store_order_in_db(conn, cursor, symbol, price, volume, color):
    cursor.execute(f'''
        INSERT INTO orders_{symbol} (price, volume, color)
        VALUES (?, ?, ?)
    ''', (price, volume, color))
    conn.commit()


def get_orders_dict(cursor, symbol: str, without_colors=False) -> dict:
    cursor.execute(f"SELECT COUNT(*) FROM orders_{symbol}")
    row_count = cursor.fetchone()[0]
    if row_count == 0:  # если количество строк = 0, то есть, если БД пуста
        print(f"Эта БД (orders_{symbol}) пустая!")
        return dict()

    if without_colors:
        cursor.execute(f"SELECT price, volume FROM orders_{symbol}")
        all_orders_list: list = cursor.fetchall()
        all_orders_dict = {row[0]: row[1] for row in all_orders_list}
        pprint(all_orders_dict)
        return all_orders_dict

    cursor.execute(f"SELECT price, volume, color FROM orders_{symbol}")
    all_orders_list: list = cursor.fetchall()
    all_orders_dict = {row[0]: [row[1], row[2]] for row in all_orders_list}
    pprint(all_orders_dict)
    return all_orders_dict


def update_value_in_db(conn,
                       cursor,
                       symbol,
                       column_to_update,
                       condition_column,
                       new_value,
                       condition_value):
    query_for_update = f"UPDATE orders_{symbol} SET {column_to_update} = ? WHERE {condition_column} = ?"
    cursor.execute(query_for_update, (new_value, condition_value))
    conn.commit()


def remove_order_from_db(conn,
                         cursor,
                         symbol,
                         condition_column,
                         condition_value):
    query_for_delete = f"DELETE FROM orders_{symbol} WHERE {condition_column} = ?"
    cursor.execute(query_for_delete, (condition_value,))
    conn.commit()
    print(f"Deleted {cursor.rowcount} row(s)")


def get_order_book(symbol="BTCUSDT", limit=100, book_type: str | None = None) -> dict | list:
    """Fetch the order book for a given symbol."""
    assert book_type in (None, "asks", "bids")

    endpoint = f"/api/v3/depth"
    params = {"symbol": symbol, "limit": limit}
    response = requests.get(BASE_URL + endpoint, params=params, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()  # Raise an error if the request fails
    return_response: dict = response.json()

    if book_type is None:
        return return_response
    if book_type == "asks":
        return [[round(float(asks_data[0])), round(float(asks_data[1]), 4)] for asks_data in return_response.get("asks")]
    return [[round(float(bids_data[0])), round(float(bids_data[1]), 4)] for bids_data in return_response.get("bids")]


def get_latest_price(symbol="BTCUSDT"):
    """Fetch the latest price for a given symbol."""
    endpoint = f"/api/v3/ticker/price"
    params = {
        "symbol": symbol
    }
    response = requests.get(BASE_URL + endpoint, params=params, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return round(float(response.json().get("price")), 4)


def calculate_color(value, max_value, is_ask=True) -> str:
    """
    Calculate color of a bar in dependence on the value of an order
    and the max. value of the entire orders dictionary.
    """

    intensity = value / max_value
    if intensity > 0.58:  # 0.75
        color = "darkred" if is_ask else "darkgreen"
    elif intensity > 0.39:  # 0.5
        color = "red" if is_ask else "green"
    elif intensity > 0.1:  # 0.25
        color = "orange" if is_ask else "lime"
    else:
        color = "lightcoral" if is_ask else "lightgreen"
    return color


def fetch_data(conn_asks,
               cursor_asks,
               conn_bids,
               cursor_bids,
               symbol,
               limit,
               minimum_value):
    """
    Fetch the order book and average price for the given symbol.
    """
    # Fetch current price
    current_price = get_latest_price(symbol)
    order_book = get_order_book(symbol, limit)

    # print()
    # print('=' * 100)

    def process_retrieved_data(key_to_order_book: str, _current_price: float):
        all_dict = get_orders_dict(cursor_asks if key_to_order_book == "asks" else cursor_bids, symbol)  # 1
        preprocessed_data = {
            round(float(orders_data[0]), ROUNDING_CONSTANTS.get(symbol)): round(float(orders_data[1]), 3)
            for orders_data in order_book[key_to_order_book] if round(float(orders_data[1]), 3) >= minimum_value  # 0.5
        }
        # print(f"{preprocessed_data=}")
        # print(f"{key_to_order_book}: {preprocessed_data}")
        for key_price in preprocessed_data.keys():
            current_value = preprocessed_data.get(key_price)
            if all_dict:
                max_value = max(all_dict.values(), key=lambda a: a[0])[0]
            else:
                max_value = max(preprocessed_data.values())

            if key_price not in all_dict.keys():
                store_order_in_db(
                    conn_asks if key_to_order_book == "asks" else conn_bids,
                    cursor_asks if key_to_order_book == "asks" else cursor_bids,
                    symbol,
                    key_price,
                    preprocessed_data.get(key_price),
                    calculate_color(
                        current_value,
                        max_value,
                        is_ask=True if key_to_order_book == "asks" else False
                    )
                )
                # all_dict[key_price] = [preprocessed_data.get(key_price), calculate_color(current_value, max_value, is_ask=True if key_to_order_book == "asks" else False)]
            else:
                if preprocessed_data.get(key_price) != all_dict.get(key_price):
                    # print(f"\n\tMATCH: {key_price=} {current_price=}\n")
                    update_value_in_db(
                        conn_asks if key_to_order_book == "asks" else conn_bids,
                        cursor_asks if key_to_order_book == "asks" else cursor_bids,
                        symbol,
                        "volume",
                        "price",
                        all_dict[key_price][0] + preprocessed_data.get(key_price),
                        key_price
                    )
                    # all_dict[key_price][0] += preprocessed_data.get(key_price)

                    update_value_in_db(
                        conn_asks if key_to_order_book == "asks" else conn_bids,
                        cursor_asks if key_to_order_book == "asks" else cursor_bids,
                        symbol,
                        "color",
                        "price",
                        calculate_color(all_dict.get(key_price)[0], max_value, is_ask=True if key_to_order_book == "asks" else False),
                        key_price
                    )
                    # all_dict[key_price][1] = calculate_color(all_dict.get(key_price)[0], max_value, is_ask=True if key_to_order_book == "asks" else False)
        all_dict = get_orders_dict(cursor_asks if key_to_order_book == "asks" else cursor_bids, symbol)  # 2
        i = 0
        while i < len(all_dict.keys()):
            data_price = list(all_dict.keys())[i]
            if key_to_order_book == "asks":
                if data_price < _current_price:
                    # print(f"\n\tREMOVED: {data_price}\n")
                    remove_order_from_db(
                        conn_asks,
                        cursor_asks,
                        symbol,
                        "price",
                        data_price
                    )
                    # all_dict.pop(data_price)
                i += 1
            elif key_to_order_book == "bids":
                if data_price > _current_price:
                    # print(f"\n\tREMOVED: {data_price}\n")
                    remove_order_from_db(
                        conn_bids,
                        cursor_bids,
                        symbol,
                        "price",
                        data_price
                    )
                    # all_dict.pop(data_price)
                i += 1
            else:
                raise ValueError("Incorrect <key_to_order_book> value!")

        return preprocessed_data

    #  "скопление шортов"
    asks = process_retrieved_data("asks", current_price)
    #  "скопление лонгов"
    bids = process_retrieved_data("bids", current_price)

    # print(f"Current price: {current_price}")
    # print("Asks (Long Clusters):")
    # pprint(asks)
    # print("Bids (Short Clusters):")
    # pprint(bids)
    # print()

    # print("ALL")
    # print("ALL ASKS:")
    # pprint(ALL_ASKS)
    # print("ALL_BIDS:")
    # pprint(ALL_BIDS)

# def get_order_book(symbol="BTCUSDT", limit=100, book_type: str | None = None) -> dict | list:
#     """Fetch the order book for a given symbol."""
#     assert book_type in (None, "asks", "bids")
#
#     endpoint = f"/api/v3/depth"
#     params = {"symbol": symbol, "limit": limit}
#     response = requests.get(BINANCE_URL + endpoint, params=params)
#     response.raise_for_status()  # Raise an error if the request fails
#     return_response: dict = response.json()
#
#     if book_type is None:
#         return return_response
#     if book_type == "asks":
#         return [[round(float(asks_data[0])), round(float(asks_data[1]), 4)] for asks_data in return_response.get("asks")]
#     return [[round(float(bids_data[0])), round(float(bids_data[1]), 4)] for bids_data in return_response.get("bids")]
#
#
# def get_latest_price(symbol="BTCUSDT"):
#     """Fetch the latest price for a given symbol."""
#     endpoint = f"/api/v3/ticker/price"
#     params = {"symbol": symbol}
#     response = requests.get(BINANCE_URL + endpoint, params=params)
#     response.raise_for_status()
#     return round(float(response.json().get("price")), 4)
#
#
# def calculate_color(value, max_value, is_ask=True) -> str:
#     """
#     Calculate color of a bar in dependence on the value of an order
#     and the max. value of the entire orders dictionary.
#     """
#
#     intensity = value / max_value
#     if intensity > 0.58:  # 0.75
#         color = 'darkred' if is_ask else 'darkgreen'
#     elif intensity > 0.39:  # 0.5
#         color = 'red' if is_ask else 'green'
#     elif intensity > 0.1:  # 0.25
#         color = 'orange' if is_ask else 'lime'
#     else:
#         color = 'lightcoral' if is_ask else 'lightgreen'
#     return color
#
#
# def fetch_data(symbol, limit, minimum_value):
#     """
#     Fetch the order book and average price for the given symbol.
#     """
#     global ALL_ASKS, ALL_BIDS
#     # Fetch current price
#     current_price = get_latest_price(symbol)
#     order_book = get_order_book(symbol, limit)
#
#     print()
#     print('=' * 100)
#
#     def process_retrieved_data(key_to_order_book, all_dict: dict, _current_price: float):
#         preprocessed_data = {
#             round(float(orders_data[0]), -1): round(float(orders_data[1]), 3)
#             for orders_data in order_book[key_to_order_book] if round(float(orders_data[1]), 3) >= minimum_value  # 0.5
#         }
#         print(f"{key_to_order_book}: {preprocessed_data}")
#         for key_price in preprocessed_data.keys():
#             current_value = preprocessed_data.get(key_price)
#             if all_dict:
#                 max_value = max(all_dict.values(), key=lambda a: a[0])[0]
#             else:
#                 max_value = max(preprocessed_data.values())
#
#             if key_price not in all_dict.keys():
#                 all_dict[key_price] = [preprocessed_data.get(key_price), calculate_color(current_value, max_value, is_ask=True if key_to_order_book == "asks" else False)]
#             else:
#                 if preprocessed_data.get(key_price) != all_dict.get(key_price):
#                     print("\n\tMATCH\n")
#                     all_dict[key_price][0] += preprocessed_data.get(key_price)
#                     all_dict[key_price][1] = calculate_color(all_dict.get(key_price)[0], max_value, is_ask=True if key_to_order_book == "asks" else False)
#
#         i = 0
#         while i < len(all_dict.keys()):
#             data_price = list(all_dict.keys())[i]
#             if key_to_order_book == "asks":
#                 if data_price < _current_price:
#                     print(f"\n\tREMOVED: {data_price}\n")
#                     all_dict.pop(data_price)
#                 else:
#                     i += 1
#             elif key_to_order_book == "bids":
#                 if data_price > _current_price:
#                     print(f"\n\tREMOVED: {data_price}\n")
#                     all_dict.pop(data_price)
#                 else:
#                     i += 1
#             else:
#                 raise ValueError("Incorrect <key_to_order_book> value!")
#
#         return preprocessed_data
#
#     #  "скопление шортов"
#     asks = process_retrieved_data("asks", ALL_ASKS, current_price)
#     #  "скопление лонгов"
#     bids = process_retrieved_data("bids", ALL_BIDS, current_price)
#
#     print(f"Current price: {current_price}")
#     print("Asks (Long Clusters):")
#     pprint(asks)
#     print("Bids (Short Clusters):")
#     pprint(bids)
#     print()
#     print("ALL")
#     print("ALL ASKS:")
#     pprint(ALL_ASKS)
#     print("ALL_BIDS:")
#     pprint(ALL_BIDS)


def find_walls(orders, threshold, is_ask=True):
    walls = []
    for price, amount in orders:
        total_value = price * amount
        if total_value >= threshold:
            walls.append((price, amount, total_value))
    return walls


def filter_spoof_orders(walls, threshold):
    filtered_walls = [wall for wall in walls if wall[1] < threshold]
    return filtered_walls


# Функция для получения данных свечного графика
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
    # если дата уже в словаре, добавить время
    if date_str_ in dates_dict_:
        dates_dict_[date_str_][0].append(time_str_)
        dates_dict_[date_str_][1].append(row_["timestamp"])
    else:
        # в ином случае, добавить новый ключ для этой даты
        dates_dict_[date_str_] = [[f"{datetime.strftime(datetime.strptime(date_str_, '%Y-%m-%d'),
                                                        '%d %b')}"], [row_["timestamp"]]]


def add_date_advanced(dates_dict_, date_str_, time_str_, row_, time_count_) -> None:
    global time_count
    if date_str_ not in dates_dict_.keys():
        dates_dict_[date_str_] = [[f"{datetime.strftime(datetime.strptime(date_str_, '%Y-%m-%d'),
                                                        '%d %b')}"], [row_["timestamp"]]]
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


# class ProcessDbMultithread(threading.Thread):
#     def __init__(self, symbol: str):
#         super().__init__()
#         self.symbol = symbol
#
#     def run(self):
#         conn_asks = sqlite3.connect("orders_asks.db")
#         conn_bids = sqlite3.connect("orders_bids.db")
#         cursor_asks = conn_asks.cursor()
#         cursor_bids = conn_bids.cursor()
#         try:
#             while True:
#                 fetch_data(
#                     conn_asks,
#                     cursor_asks,
#                     conn_bids,
#                     cursor_bids,
#                     self.symbol,
#                     5000,
#                     SYMBOLS_CONSTANTS.get(self.symbol)[1]
#                 )
#                 sleep(10)
#         except Exception as e:
#             print(f"\nError in Threading!\n{e}\n{e.args}\n")
#         finally:
#             cursor_asks.close()
#             cursor_bids.close()
#             conn_asks.close()
#             conn_bids.close()

# print("Threading starts...")
# for symbol in SYMBOLS:
#     symbol = symbol.replace('/', '')
#     ProcessDbMultithread(symbol).start()
# ProcessDbMultithread("BTCUSDT").start()
app = Flask(__name__)


# Функция для создания свечного графика
@app.route("/create_candle_plot", methods=["GET"])
def create_candle_plot():
    global time_count

    tf = request.args.get("timeframe", "15m")
    print(f"{tf=}\n")
    symbol = request.args.get("symbol", "BTC/USDT")
    symbol = symbol.replace('/', '')  # in an appropriate for Binance API format
    df = fetch_candlestick_data(symbol, tf)  # symbol, tf

    fig = go.Figure()

    # Свечной график
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
        title='Время',
        showgrid=False,
        tickformat="%H:%M",  # Формат времени на часовой основе
        rangeslider=dict(visible=False)
    )

    dates_dict = dict()
    last_timestamp = df.iloc[-1]["timestamp"]
    print(f"{last_timestamp=}")

    # использовать эти данные для масштабирования высоты полоски
    low_max = df["low"].max() - (abs(df["low"].mean() - df["low"].min()) // 2)
    high_min = df["high"].min() + (abs(df["high"].mean() - df["high"].max()) // 2)

    xaxis_range = []
    right_x_value = last_timestamp + TIMEFRAMES_REFERENCE.get(tf)[0]
    match tf:
        case "5m":
            for idx, row in df.iterrows():
                date_str, time_str, minutes, _, _, _ = retrieve_time_data(row)
                time_count += 1
                if minutes in (0, 30):
                    add_date_advanced(dates_dict, date_str, time_str, row, 18)

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

    # pprint(dates_dict)
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

    conn_asks = sqlite3.connect("orders_asks.db")
    cursor_asks = conn_asks.cursor()
    conn_bids = sqlite3.connect("orders_bids.db")
    cursor_bids = conn_bids.cursor()

    print(f"\nFETCH DATA INFO (START)\n")
    print(f"{symbol=} {get_latest_price(symbol)=}")
    for symbol_ in SYMBOLS:
        symbol_ = symbol_.replace('/', '')
        fetch_data(
            conn_asks,
            cursor_asks,
            conn_bids,
            cursor_bids,
            symbol_,
            BINANCE_LIMIT,
            SYMBOLS_CONSTANTS.get(symbol_)[1]
        )
    print(f"\nFETCH DATA INFO (END)\n")

    def create_shapes_from_orders(orders_dict: dict[float: [float, str]]):
        # y_bar_constant = get_latest_price(symbol) * 0.000052  # 5, 7, 10
        y_bar_constant = SYMBOLS_CONSTANTS.get(symbol)[2]
        for key_price in orders_dict:
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

    all_asks = get_orders_dict(cursor_asks, symbol)
    create_shapes_from_orders(all_asks)  # asks bars

    all_bids = get_orders_dict(cursor_bids, symbol)
    create_shapes_from_orders(all_bids)  # bids bars

    # Обновление графика с временными метками
    update_start_timestamps()
    fig.update_layout(
        plot_bgcolor='#101014',
        paper_bgcolor='#101014',
        font=dict(color="#7A7A7C"),
        xaxis=update_layout_xaxis,
        yaxis=dict(
            title='Цена',
            showgrid=True,
            gridcolor='darkgrey',
        ),
        # title='Свечной график с зонами ордеров',
        template='plotly_dark',
        height=600,
        margin=dict(t=5),
        annotations=[
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
        ],
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

    cursor_asks.close()
    conn_asks.close()
    cursor_bids.close()
    conn_bids.close()

    return jsonify(graph_json)

@app.route('/', methods=['GET', 'POST'])
def index():
    global asks_for_nz, bids_for_nz, total_ask_value, total_bid_value, nzVolume
    # global CONN_ASKS, CUR_ASKS, CONN_BIDS, CUR_BIDS

    conn_asks = sqlite3.connect("orders_asks.db")
    conn_bids = sqlite3.connect("orders_bids.db")

    create_databases_by_symbols(conn_asks, SYMBOLS)
    create_databases_by_symbols(conn_bids, SYMBOLS)

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

if __name__ == '__main__':
    app.run(
        debug=True,
        # host="0.0.0.0"
        # port=8080
    )
