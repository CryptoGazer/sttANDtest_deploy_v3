import os
from datetime import datetime
from pprint import pprint

import requests
from sqlalchemy import func
from sqlalchemy import Column, Integer, Float, String, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.decl_api import DeclarativeMeta

BINANCE_URL = "https://api.binance.com"
ROUNDING_CONSTANTS = {
    "BTCUSDT": -1,
    "ETHUSDT": 0,
    "SOLUSDT": 1
}

path_to_orders_asks = f"sqlite:///{os.path.join("orders_asks.db")}"
path_to_orders_bids = f"sqlite:///{os.path.join("orders_bids.db")}"

engine_asks = create_engine(path_to_orders_asks)
engine_bids = create_engine(path_to_orders_bids)


def create_models_by_symbols(symbol: str, CustomBase: DeclarativeMeta):
    symbol = symbol.replace('/', '')
    class Order(CustomBase):
        __tablename__ = f"orders_{symbol}"

        id = Column(Integer, primary_key=True, autoincrement=True)
        price = Column(Float)
        volume = Column(Float)
        color = Column(String(30))
        timestamp_created = Column(Integer)

    return Order


def get_latest_price(symbol="BTCUSDT"):
    """Fetch the latest price for a given symbol."""
    endpoint = f"/api/v3/ticker/price"
    params = {
        "symbol": symbol
    }
    response = requests.get(BINANCE_URL + endpoint, params=params, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return round(float(response.json().get("price")), 4)


def get_order_book(symbol="BTCUSDT", limit=100, book_type: str | None = None) -> dict | list:
    """Fetch the order book for a given symbol."""
    assert book_type in (None, "asks", "bids")

    endpoint = f"/api/v3/depth"
    params = {"symbol": symbol, "limit": limit}
    response = requests.get(BINANCE_URL + endpoint, params=params, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()  # Raise an error if the request fails
    return_response: dict = response.json()

    if book_type is None:
        return return_response
    if book_type == "asks":
        return [[round(float(asks_data[0])), round(float(asks_data[1]), 4)] for asks_data in return_response.get("asks")]
    return [[round(float(bids_data[0])), round(float(bids_data[1]), 4)] for bids_data in return_response.get("bids")]


def get_orders_dict(sess, symbol: str, model_registry: dict, key_to_order_book: str, without_colors=False) -> dict:
    assert key_to_order_book in ("asks", "bids")
    OrderModel = model_registry.get(key_to_order_book).get(symbol)
    row_count = sess.query(func.count()).select_from(OrderModel).scalar()
    if row_count == 0:
        print(f"DB orders_{symbol} is empty.")
        return dict()

    if without_colors:
        all_orders_list = sess.query(
            OrderModel.price,
            OrderModel.volume,
            OrderModel.timestamp_created
        ).all()
        all_orders_dict = {row[0]: [row[1], row[2]] for row in all_orders_list}
        pprint(all_orders_dict)
        return all_orders_dict

    all_orders_list = sess.query(
        OrderModel.price,
        OrderModel.volume,
        OrderModel.color,
        OrderModel.timestamp_created
    ).all()
    all_orders_dict = {row[0]: [row[1], row[2], row[3]] for row in all_orders_list}
    pprint(all_orders_dict)
    return all_orders_dict


def store_order_in_db(sess,
                      symbol,
                      price,
                      volume,
                      color,
                      timestamp_created,
                      key_to_order_book: str,
                      model_registry: dict):
    assert key_to_order_book in ("asks", "bids")

    OrderModel = model_registry.get(key_to_order_book).get(symbol)
    print(f"f{OrderModel=}")
    order = OrderModel(
        price=price,
        volume=volume,
        color=color,
        timestamp_created=timestamp_created
    )

    sess.add(order)
    sess.commit()


def update_value_in_db(sess,
                       symbol,
                       column_to_update,
                       condition_column,
                       new_value,
                       condition_value,
                       key_to_order_book: str,
                       model_registry: dict):
    assert key_to_order_book in ("asks", "bids")

    OrderModel = model_registry.get(key_to_order_book).get(symbol)

    column_attr = getattr(OrderModel, column_to_update)
    condition_attr = getattr(OrderModel, condition_column)

    sess.query(OrderModel).filter(condition_attr == condition_value).update({
        column_attr: new_value
    })
    sess.commit()


def remove_order_from_db(sess,
                         symbol,
                         condition_column,
                         condition_value,
                         key_to_order_book,
                         model_registry):
    OrderModel = model_registry.get(key_to_order_book).get(symbol)

    condition_attr = getattr(OrderModel, condition_column)
    deleted_count = sess.query(OrderModel).filter(condition_attr == condition_value).delete()
    sess.commit()
    print(f"Deleted {deleted_count} row(s)")

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


def fetch_data(sess_asks,
               sess_bids,
               symbol: str,
               model_registry: dict,
               limit,
               minimum_value):
    """
    Fetch the order book and average price for the given symbol.
    """
    # Fetch current price
    current_price = get_latest_price(symbol)
    order_book = get_order_book(symbol, limit)

    def process_retrieved_data(key_to_order_book: str, _current_price: float):
        all_dict = get_orders_dict(sess_asks if key_to_order_book == "asks" else sess_bids, symbol, model_registry, key_to_order_book)  # 1
        minimum_volume = minimum_value / get_latest_price(symbol)
        print(f"{minimum_volume=}")
        preprocessed_data = {
            round(float(orders_data[0]), ROUNDING_CONSTANTS.get(symbol)): round(float(orders_data[1]), 3)
            for orders_data in order_book[key_to_order_book] if round(float(orders_data[1]), 3) >= minimum_volume  # 0.5
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
                    sess_asks if key_to_order_book == "asks" else sess_bids,
                    symbol,
                    key_price,
                    preprocessed_data.get(key_price),
                    calculate_color(
                        current_value,
                        max_value,
                        is_ask=True if key_to_order_book == "asks" else False
                    ),
                    round(datetime.timestamp(datetime.now())),
                    key_to_order_book,
                    model_registry
                )
            else:
                if preprocessed_data.get(key_price) != all_dict.get(key_price):
                    update_value_in_db(
                        sess_asks if key_to_order_book == "asks" else sess_bids,
                        symbol,
                        "volume",
                        "price",
                        all_dict[key_price][0] + preprocessed_data.get(key_price),
                        key_price,
                        key_to_order_book,
                        model_registry
                    )

                    update_value_in_db(
                        sess_asks if key_to_order_book == "asks" else sess_bids,
                        symbol,
                        "color",
                        "price",
                        calculate_color(all_dict.get(key_price)[0], max_value, is_ask=True if key_to_order_book == "asks" else False),
                        key_price,
                        key_to_order_book,
                        model_registry
                    )
        all_dict = get_orders_dict(sess_asks if key_to_order_book == "asks" else sess_bids,
                                   symbol,
                                   model_registry,
                                   key_to_order_book)  # 2
        i = 0
        while i < len(all_dict.keys()):
            data_price = list(all_dict.keys())[i]
            if key_to_order_book == "asks":
                if data_price < _current_price:
                    # print(f"\n\tREMOVED: {data_price}\n")
                    remove_order_from_db(
                        sess_asks,
                        symbol,
                        "price",
                        data_price,
                        "asks",
                        model_registry
                    )
                i += 1
            elif key_to_order_book == "bids":
                if data_price > _current_price:
                    # print(f"\n\tREMOVED: {data_price}\n")
                    remove_order_from_db(
                        sess_bids,
                        symbol,
                        "price",
                        data_price,
                        "bids",
                        model_registry
                    )
                i += 1
            else:
                raise ValueError("Incorrect <key_to_order_book> value!")

        return preprocessed_data

    asks = process_retrieved_data("asks", current_price)
    bids = process_retrieved_data("bids", current_price)
