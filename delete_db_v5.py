from sqlalchemy import Table, MetaData
from db_func import engine_asks, engine_bids


for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
    metadata = MetaData()

    asks_table_to_drop = Table(f"orders_{sym}", metadata, autoload_with=engine_asks)
    bids_table_to_drop = Table(f"orders_{sym}", metadata, autoload_with=engine_bids)

    asks_table_to_drop.drop(engine_asks)
    bids_table_to_drop.drop(engine_bids)

print("DONE")
