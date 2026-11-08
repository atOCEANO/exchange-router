from enum import Enum
from typing import List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketType(str, Enum):
    SPOT = "spot"
    LINEAR = "linear"
    INVERSE = "inverse"


class NotionalBasis(BaseModel):
    method: str = Field(
        ...,
        description="How notional was worked out. Known values: row_price, the native amount times the row's own price, a candle's close; contract_size, contracts times their size, exact, using no price; candle_close, the native amount times the close of the candle that ends at the reading's time; mark, the native amount times the mark price read with it. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    price: Optional[float] = Field(
        ...,
        description="The price notional was worked out at, in quote; null where no price was used, as on contract_size, or where none existed.",
    )
    ts: Optional[int] = Field(
        ...,
        description="The time of that price, in unix milliseconds: the row's own timestamp on row_price, the candle's end on candle_close, the mark price's own time on mark; null with price.",
    )


    @model_validator(mode="after")
    def _price_pair_consistency(self) -> "NotionalBasis":
        if (self.price is None) != (self.ts is None):
            raise ValueError("notional_basis: price and ts must both be set or both be null")
        return self


class QtyValue(BaseModel):
    native: float = Field(
        ...,
        description="The size in unit, as the venue states it.",
    )
    unit: str = Field(
        ...,
        description="What native counts. Known values: base, the base asset, on spot and linear; contract, on inverse. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    contract_size: Optional[float] = Field(
        ...,
        description="Quote notional of one contract; null when unit is base.",
    )
    notional: float = Field(
        ...,
        description="The size's value in quote, never converted: native times the row's price on base, native times contract_size on contracts.",
    )


    @model_validator(mode="after")
    def _contract_requires_size(self) -> "QtyValue":
        if self.unit == "contract" and self.contract_size is None:
            raise ValueError("QtyValue.contract_size must be set when unit == 'contract'")
        return self


class VolumeValue(BaseModel):
    native: float = Field(
        ...,
        description="Volume in unit, as the venue states it.",
    )
    unit: str = Field(
        ...,
        description="What native counts. Known values: base, the base asset, on spot and linear; contract, on inverse. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    contract_size: Optional[float] = Field(
        ...,
        description="Quote notional of one contract; null when unit is base.",
    )
    notional: Optional[float] = Field(
        ...,
        description="Turnover in quote, never converted: native times the price notional_basis names on base, native times contract_size on contracts; null where no price existed.",
    )
    notional_basis: NotionalBasis = Field(
        ...,
        description="How notional was worked out.",
    )


    @model_validator(mode="after")
    def _contract_requires_size(self) -> "VolumeValue":
        if self.unit == "contract" and self.contract_size is None:
            raise ValueError("VolumeValue.contract_size must be set when unit == 'contract'")
        return self


class OiValue(BaseModel):
    native: float = Field(
        ...,
        description="Open interest in unit, as the venue states it.",
    )
    unit: str = Field(
        ...,
        description="What native counts. Known values: base, the base asset, on linear; contract, on inverse. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    contract_size: Optional[float] = Field(
        ...,
        description="Quote notional of one contract; null when unit is base.",
    )
    notional: Optional[float] = Field(
        ...,
        description="Notional outstanding in quote, never converted: native times contract_size on contracts, native times the price notional_basis names on base; null where the router holds no price for the reading's time.",
    )
    notional_basis: NotionalBasis = Field(
        ...,
        description="How notional was worked out.",
    )


    @model_validator(mode="after")
    def _contract_requires_size(self) -> "OiValue":
        if self.unit == "contract" and self.contract_size is None:
            raise ValueError("OiValue.contract_size must be set when unit == 'contract'")
        return self


class FundingConvention(BaseModel):
    kind: str = Field(
        ...,
        description="Funding model of the market. Known values: discrete, settled at fixed cycles; continuous, accrued smoothly and sampled at a fixed cadence. The cycle lives on the mark price and the funding history, since a venue can change it without changing the model. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )


class QtyUnit(BaseModel):
    unit: str = Field(
        ...,
        description="What a size counts. Known values: base, the base asset, on spot and linear; contract, on inverse. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    contract_size: Optional[float] = Field(
        ...,
        description="Quote notional of one contract; null when unit is base.",
    )


    @model_validator(mode="after")
    def _contract_requires_size(self) -> "QtyUnit":
        if self.unit == "contract" and self.contract_size is None:
            raise ValueError("qty.contract_size must be set when qty.unit == 'contract'")
        return self


class QtyGrid(QtyUnit):
    step: Optional[float] = Field(
        ...,
        description="Step an order's size must sit on, in unit; null where the venue states none. Where a venue counts a linear market in contracts (OKX, KuCoin), it is the venue's lot times the contract's value, in the base asset.",
    )
    decimals: Optional[int] = Field(
        ...,
        description="Decimal places a size carries: the step's own decimals; null with the step.",
    )
    min: Optional[float] = Field(
        ...,
        description="Smallest order size, in unit; null where the venue states none.",
    )
    max: Optional[float] = Field(
        ...,
        description="Largest order size, in unit; null where the venue states none.",
    )


class PriceTick(BaseModel):
    kind: Literal["tick"] = Field(
        ...,
        description="The venue states a fixed price step. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    tick: float = Field(
        ...,
        description="Step an order's price must sit on, in quote. Snap with round(price / tick) * tick, then round to decimals.",
    )
    decimals: int = Field(
        ...,
        description="Decimal places a price carries: the tick's own decimals, and the exact rule for rounding.",
    )


class PriceSignificantFigures(BaseModel):
    kind: Literal["significant_figures"] = Field(
        ...,
        description="The venue states no tick and holds a price to a count of significant figures. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    figures: int = Field(
        ...,
        description="Significant figures a price may carry; a whole number is always allowed.",
    )
    decimals: int = Field(
        ...,
        description="Most decimal places a price may carry.",
    )


class PriceOther(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: str = Field(
        ...,
        description="A kind of price grid this schema does not know yet. Read kind, and leave the block uninterpreted.",
    )


class Notional(BaseModel):
    min: Optional[float] = Field(
        ...,
        description="Smallest order value, in quote; null where the venue states none.",
    )


class FundingDeadline(BaseModel):
    kind: str = Field(
        ...,
        description="What the deadline is. Known values: settlement, the moment per_cycle is charged, as the venue states it or its fixed schedule sets it; estimate, the router's reckoning where the venue does not say when its rate is next replaced. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    ts: int = Field(
        ...,
        description="The deadline, in unix milliseconds.",
    )


class FundingCurrent(BaseModel):
    kind: str = Field(
        ...,
        description="Funding model. Known values: discrete, per_cycle is the rate to be charged at the settlement valid_until names; continuous, per_cycle is the rate accrued over each cycle_ms-length window, and partial holds pay in proportion. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    per_cycle: float = Field(
        ...,
        description="Funding rate per cycle of length cycle_ms, dimensionless decimal (e.g. 0.0001 = 0.01%). On discrete: the estimate of what will be charged at the next settlement. On continuous: the instantaneous per-cycle-equivalent accrual rate sampled at the parent row's timestamp.",
    )
    cycle_ms: int = Field(
        ...,
        description="Cycle length in milliseconds. On discrete: the settlement interval (e.g. 28_800_000 for 8h). On continuous: the sample-window length (3_600_000 for Kraken's hourly sampling).",
    )
    valid_until: FundingDeadline = Field(
        ...,
        description="When this rate stops being the current one, and what kind of deadline that is: a settlement on discrete markets that state or fix one, an estimate on continuous markets and where the venue does not say.",
    )


class FundingHistorical(BaseModel):
    kind: Literal["discrete", "continuous"] = Field(
        ...,
        description="Funding model. 'discrete' rows are settlement events; 'continuous' rows are sample observations.",
    )
    per_cycle: float = Field(
        ...,
        description="Rate per cycle. On discrete: the rate actually charged at the parent row's timestamp. On continuous: the instantaneous per-cycle-equivalent rate observed at the parent row's timestamp.",
    )
    cycle_ms: int = Field(
        ...,
        description="Cycle length in milliseconds. Stable per symbol on discrete (8h or 4h cycles); always 3_600_000 on continuous (Kraken sample window).",
    )


class SymbolInfo(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol; exchange-native form with contract-type prefixes or suffixes stripped (e.g. 'BTCUSDT' on Binance, 'XBTUSD' on Kraken futures where the PF_ prefix is stripped). No base-currency translation (XBT stays XBT).",
    )
    market_type: MarketType = Field(
        ...,
        description="Market the instrument trades on.",
    )
    native_symbol: str = Field(
        ...,
        description="Raw upstream symbol when it differs from the routing-facing one (e.g. 'BTCUSD_PERP' on Binance COIN-M, 'PF_XBTUSD' on Kraken futures).",
    )
    status: str = Field(
        ...,
        description="Whether the market trades now, as of timestamp. Known values: trading; halted, listed but not matching; pre_trading, listed and not yet open; delisted, gone from trading and still served. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    base: str = Field(
        ...,
        description="Base asset, in the venue's own code (e.g. 'BTC' in BTC/USDT, 'XBT' on Kraken).",
    )
    quote: str = Field(
        ...,
        description="Quote asset; every price and notional on the instrument is in it, and every data record carries it as quote.",
    )
    price: Union[PriceTick, PriceSignificantFigures, PriceOther] = Field(
        ...,
        description="How a price steps: a tick, or a count of significant figures where the venue states no tick.",
    )
    qty: QtyGrid = Field(
        ...,
        description="What a size counts, how it steps and its limits.",
    )
    notional: Notional = Field(
        ...,
        description="Limits on an order's value.",
    )
    funding: Optional[FundingConvention] = Field(
        ...,
        description="Funding convention; null on spot.",
    )
    timestamp: int = Field(
        ...,
        description="When the router read the venue's record of the instrument, in unix milliseconds; a read by symbol refreshes a record older than five minutes.",
    )
    time_source: str = Field(
        ...,
        description="Whose clock stamped the record. Known values: venue, router. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )


class Ticker(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance of this row.",
    )
    quote: str = Field(
        ...,
        description="Quote currency for all price-denominated fields on this row, matching SymbolInfo.quote.",
    )
    price: Optional[float] = Field(
        ...,
        description="The price in quote that price_source names; null when the venue has no last trade. Can lag on thinly-traded inverse markets; consult MarkPrice for current fair value.",
    )
    price_source: str = Field(
        ...,
        description="Where price comes from. Known values: last_trade; mid, the middle of the best bid and ask, on Hyperliquid, whose asset context carries no last trade; mark, the mark price, where Hyperliquid has no mid. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )
    open_24h: Optional[float] = Field(
        ...,
        description="Price in quote 24 hours before timestamp, used as the open of the rolling 24h window; null whenever nothing traded in the window.",
    )
    high_24h: Optional[float] = Field(
        ...,
        description="Highest price in quote over the rolling 24h window ending at timestamp; null whenever nothing traded in the window.",
    )
    low_24h: Optional[float] = Field(
        ...,
        description="Lowest price in quote over the rolling 24h window ending at timestamp; null whenever nothing traded in the window.",
    )
    volume_24h: Optional[VolumeValue] = Field(
        ...,
        description="Volume over the rolling 24h window, with its notional in quote; on base, notional_basis names the row's price and timestamp, and notional is null with price. Null when the exchange publishes no 24-hour statistics for a market that does not trade, as Binance does for a contract being settled.",
    )
    price_change_percent: Optional[float] = Field(
        ...,
        description="24h price change as a percent, 5.0 meaning +5%, not +0.05; null whenever nothing traded in the window.",
    )
    timestamp: int = Field(
        ...,
        description="Snapshot time in unix milliseconds, by the clock time_source names.",
    )
    time_source: str = Field(
        ...,
        description="Whose clock stamped the row. Known values: venue, the venue's own time for the snapshot; router, the router's clock when it read a venue that sends none. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )


    @model_validator(mode="after")
    def _nothing_traded_reads_null(self) -> "Ticker":
        if not self.price:
            self.price = None
        if self.volume_24h is None or not self.volume_24h.native:
            self.open_24h, self.high_24h, self.low_24h, self.price_change_percent = None, None, None, None
        return self


    @model_validator(mode="after")
    def _row_price_basis(self) -> "Ticker":
        if self.volume_24h is not None and self.volume_24h.notional_basis.method == "row_price":
            if self.price is None:
                self.volume_24h.notional = None
            self.volume_24h.notional_basis = NotionalBasis(
                method = "row_price",
                price  = self.price,
                ts     = None if self.price is None else self.timestamp,
            )
        return self


class BookTicker(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance of this row.",
    )
    quote: str = Field(
        ...,
        description="Quote currency for price fields.",
    )
    bid_price: Optional[float] = Field(
        ...,
        description="Best bid price in quote; null, with bid_qty, when no one bids.",
    )
    bid_qty: Optional[QtyValue] = Field(
        ...,
        description="Size resting at bid_price, with its notional in quote; null with bid_price.",
    )
    ask_price: Optional[float] = Field(
        ...,
        description="Best ask price in quote; null, with ask_qty, when no one asks.",
    )
    ask_qty: Optional[QtyValue] = Field(
        ...,
        description="Size resting at ask_price, with its notional in quote; null with ask_price.",
    )
    timestamp: int = Field(
        ...,
        description="Snapshot time in unix milliseconds, by the clock time_source names.",
    )
    time_source: str = Field(
        ...,
        description="Whose clock stamped the row. Known values: venue, the venue's own time for the snapshot; router, the router's clock when it read a venue that sends none. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )


    @model_validator(mode="after")
    def _an_unquoted_side_is_null(self) -> "BookTicker":
        if not self.bid_price or self.bid_qty is None:
            self.bid_price, self.bid_qty = None, None
        if not self.ask_price or self.ask_qty is None:
            self.ask_price, self.ask_qty = None, None
        return self


class MarkPrice(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance. Always 'linear' or 'inverse' (no mark price on spot).",
    )
    quote: str = Field(
        ...,
        description="Quote currency.",
    )
    mark_price: float = Field(
        ...,
        description="Fair-value-anchored price in quote. Funding settles on this; liquidations and margin reference this rather than last-traded.",
    )
    index_price: Optional[float] = Field(
        None,
        description="Spot index reference in quote used to compute the mark. Null when the upstream payload omits an index price.",
    )
    funding: Optional[FundingCurrent] = Field(
        None,
        description="Current funding view. Null when the upstream payload omits funding info. See FundingCurrent.",
    )
    timestamp: int = Field(
        ...,
        description="Snapshot time in unix milliseconds, by the clock time_source names.",
    )
    time_source: str = Field(
        ...,
        description="Whose clock stamped the row. Known values: venue, the venue's own time for the snapshot; router, the router's clock when it read a venue that sends none. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )


    @model_validator(mode="after")
    def _funding_valid_until_after_timestamp(self) -> "MarkPrice":
        if self.funding is not None and self.funding.kind == "discrete":
            if self.funding.valid_until.ts < self.timestamp:
                raise ValueError(
                    f"discrete funding.valid_until.ts ({self.funding.valid_until.ts}) must be >= timestamp ({self.timestamp})"
                )
        return self


class Trade(BaseModel):
    id: Optional[str] = Field(
        None,
        description="Exchange-native trade id when available, with an adapter-synthesized event-time fallback on rows where the upstream omits it. Null when neither is available. Not all exchanges produce sortable values; do not rely on lexicographic ordering. Sort by timestamp for chronology.",
    )
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance of this row.",
    )
    quote: str = Field(
        ...,
        description="Quote currency.",
    )
    price: float = Field(
        ...,
        description="Execution price of this trade, in quote.",
    )
    qty: QtyValue = Field(
        ...,
        description="Trade size, with its notional in quote.",
    )
    side: Literal["buy", "sell"] = Field(
        ...,
        description="Taker side / aggressor side. A 'buy' means the taker hit the asks (a sell limit was filled).",
    )
    timestamp: int = Field(
        ...,
        description="Event time in unix milliseconds, as reported by the exchange.",
    )


class AggTrade(BaseModel):
    agg_id: str = Field(
        ...,
        description="Exchange-native aggregate-trade id, stringified.",
    )
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance of this row.",
    )
    quote: str = Field(
        ...,
        description="Quote currency.",
    )
    price: float = Field(
        ...,
        description="Price of the aggregated group, in quote. Same-price trades on the same side are what the exchange folds into one AggTrade.",
    )
    qty: QtyValue = Field(
        ...,
        description="Aggregated size, with its notional in quote.",
    )
    first_trade_id: str = Field(
        ...,
        description="Stringified id of the first constituent trade in this aggregation.",
    )
    last_trade_id: str = Field(
        ...,
        description="Stringified id of the last constituent trade in this aggregation.",
    )
    side: Literal["buy", "sell"] = Field(
        ...,
        description="Taker side / aggressor side.",
    )
    timestamp: int = Field(
        ...,
        description="Last-trade time of the aggregated group, in unix milliseconds.",
    )


class Candle(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance of this row.",
    )
    quote: str = Field(
        ...,
        description="Quote currency.",
    )
    interval: str = Field(
        ...,
        description="Bucket size as a canonical string matching the consumer's `period` parameter, e.g. '1m', '5m', '1h', '1d'.",
    )
    timestamp: int = Field(
        ...,
        description="Bucket open time in unix milliseconds on every exchange.",
    )
    open: float = Field(
        ...,
        description="First traded price of the bucket, in quote.",
    )
    high: float = Field(
        ...,
        description="Highest traded price during the bucket, in quote.",
    )
    low: float = Field(
        ...,
        description="Lowest traded price during the bucket, in quote.",
    )
    close: float = Field(
        ...,
        description="Last traded price of the bucket, in quote.",
    )
    volume: VolumeValue = Field(
        ...,
        description="Bucket volume, with its notional in quote; on base, notional_basis names the bar's close and timestamp.",
    )


    @model_validator(mode="after")
    def _row_price_basis(self) -> "Candle":
        if self.volume.notional_basis.method == "row_price":
            self.volume.notional_basis = NotionalBasis(method="row_price", price=self.close, ts=self.timestamp)
        return self


class OrderBook(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance of this row.",
    )
    quote: str = Field(
        ...,
        description="Quote currency for prices in bids/asks.",
    )
    qty: QtyUnit = Field(
        ...,
        description="What a level's size counts. On base, a level's notional is its price times its size; on contracts, its size times contract_size.",
    )
    bids: List[List[float]] = Field(
        ...,
        description="Array of [price, size] pairs sorted best (highest) first. Price is in quote; size is in qty.unit.",
    )
    asks: List[List[float]] = Field(
        ...,
        description="Array of [price, size] pairs sorted best (lowest) first. Same units as bids.",
    )
    timestamp: int = Field(
        ...,
        description="Depth snapshot time in unix milliseconds, by the clock time_source names.",
    )
    time_source: str = Field(
        ...,
        description="Whose clock stamped the row. Known values: venue, the venue's own time for the snapshot; router, the router's clock when it read a venue that sends none. Open: the known values are listed here, and a client that meets another leaves the block it qualifies uninterpreted.",
    )


class MarginTier(BaseModel):
    up_to: Optional[float] = Field(
        None,
        description="Position size where the tier ends, in up_to_unit. Null on an open last tier.",
    )
    max_leverage: float = Field(
        ...,
        description="Highest leverage the exchange allows for a position in this tier.",
    )
    maintenance_margin_rate: Optional[float] = Field(
        None,
        description="Maintenance margin as a fraction of position value. Null where the exchange does not serve it (Hyperliquid).",
    )
    initial_margin_rate: Optional[float] = Field(
        None,
        description="Initial margin as a fraction of position value. Null where the exchange does not serve it (Hyperliquid).",
    )
    maintenance_deduction: Optional[float] = Field(
        None,
        description="Amount taken off position value times maintenance_margin_rate to give the maintenance margin, in the position value's unit. Null where the exchange serves none, and on Bybit's first tier, which it leaves blank.",
    )


class MarginTiers(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance. Always 'linear' or 'inverse'.",
    )
    quote: str = Field(
        ...,
        description="Quote currency of the market.",
    )
    up_to_unit: Literal["quote", "base", "contract"] = Field(
        ...,
        description="How to read up_to: 'quote' is a position value in quote, 'base' an amount of the base asset, 'contract' a contract count.",
    )
    tiers: List[MarginTier] = Field(
        ...,
        description="The exchange's tiers in rising order. Empty when the exchange lists the symbol but serves no table for it.",
    )
    timestamp: int = Field(
        ...,
        description="When the router read the table from the exchange, in unix milliseconds; a table served from the cache keeps the time it was read.",
    )


    @model_validator(mode="after")
    def _rising(self) -> "MarginTiers":
        self.tiers = sorted(self.tiers, key=lambda tier: (tier.up_to is None, tier.up_to or 0.0))
        return self


class FundingRate(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance. Always 'linear' or 'inverse'.",
    )
    quote: str = Field(
        ...,
        description="Quote currency.",
    )
    rate: FundingHistorical = Field(
        ...,
        description="Historical funding view nested as kind + per_cycle + cycle_ms. See FundingHistorical.",
    )
    timestamp: int = Field(
        ...,
        description="Settlement time (discrete) or sample observation time (continuous), in unix milliseconds.",
    )


class OpenInterest(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance. Always 'linear' or 'inverse'.",
    )
    quote: str = Field(
        ...,
        description="Quote currency.",
    )
    interval: str = Field(
        ...,
        description="Bucket size as a canonical string, e.g. '5m', '1h'. Matches the route's `period` parameter.",
    )
    open_interest: OiValue = Field(
        ...,
        description="Open interest, with its notional in quote: contracts times contract_size on inverse; on linear, the close of the candle that ends at timestamp, joined by the router.",
    )
    timestamp: int = Field(
        ...,
        description="Bucket close time in unix milliseconds (end of `interval`).",
    )


class Liquidation(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance. Always 'linear' or 'inverse'.",
    )
    quote: str = Field(
        ...,
        description="Quote currency.",
    )
    side: Literal["buy", "sell"] = Field(
        ...,
        description="The liquidation order's book side, which is the opposite of the liquidated position's side. A long position being liquidated produces side='sell'. The feed is partial on every public exchange; see capabilities.liquidations.completeness.",
    )
    price: float = Field(
        ...,
        description="Price at which the liquidation order was executed (or bankruptcy reference, depending on what the upstream reports), in quote.",
    )
    qty: QtyValue = Field(
        ...,
        description="Liquidation size, with its notional in quote.",
    )
    timestamp: int = Field(
        ...,
        description="Event time in unix milliseconds, as reported by the exchange.",
    )


class LongShortRatio(BaseModel):
    symbol: str = Field(
        ...,
        description="Routing-facing symbol matching SymbolInfo.symbol.",
    )
    market_type: MarketType = Field(
        ...,
        description="Market provenance. Always 'linear' or 'inverse'.",
    )
    interval: str = Field(
        ...,
        description="Bucket size as a canonical string, e.g. '5m', '1h'.",
    )
    ratio: float = Field(
        ...,
        description="long_account / short_account. Dimensionless; > 1 means more accounts are long than short within the account_scope.",
    )
    long_account: Optional[float] = Field(
        None,
        description="Fraction of accounts (or top-trader accounts, per account_scope) on the long side, in [0, 1]. Null on exchanges that expose only the ratio (account_scope == 'opaque').",
    )
    short_account: Optional[float] = Field(
        None,
        description="Fraction of accounts on the short side, in [0, 1]. Null when account_scope == 'opaque'.",
    )
    account_scope: Literal["top_traders", "all_accounts", "opaque"] = Field(
        ...,
        description="Whose accounts are counted: 'top_traders', 'all_accounts', or 'opaque' when the upstream exposes no breakdown. Per-venue specifics live in Exchange Notes. Cross-exchange comparisons require matching scope.",
    )
    timestamp: int = Field(
        ...,
        description="Bucket close time in unix milliseconds (end of `interval`).",
    )
