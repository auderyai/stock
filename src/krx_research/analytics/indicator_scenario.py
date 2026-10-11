"""Conditional indicator scenarios with chronological validation (read-only)."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

INDICATORS = {
    "RSI(14)": "rsi",
    "Slow %K(5,3,3)": "stoch_k",
    "MACD oscillator (% price)": "macd_pct",
    "Bollinger position (sigma)": "bb_z",
    "EMA 5 gap (%)": "ema5_gap",
    "EMA 15 gap (%)": "ema15_gap",
    **{f"EMA {span} 일별 변화율 (%)": f"ema{span}_change_pct"
       for span in (5, 10, 15, 33, 56, 112, 224, 448)},
}
FEATURES = ["ret1", "ret5", "ret20", "volatility20", "volume_ratio",
            *list(INDICATORS.values())[:-2]]
MARKET_FEATURES = ["market_ret1", "market_ret5", "market_ret20", "market_vol20",
                   "relative_ret1", "relative_ret5", "relative_ret20", "bear_strength"]


@dataclass(frozen=True)
class Checkpoint:
    days: int
    current_price: float
    baseline_price: float
    scenario_price: float
    lower_price: float
    upper_price: float
    validation_mae_pct: float
    naive_mae_pct: float
    validation_direction_pct: float
    signal: str
    train_start: str
    train_end: str
    train_count: int
    test_start: str
    test_end: str
    test_count: int
    selected_count: int
    market_context: str = "종합지수 이력 없음 · 종목 단독 모델"
    relative_strength: float = 0.0
    resisting_market_decline: bool = False
    selection_start: str = ""
    selection_end: str = ""


@dataclass(frozen=True)
class PathResult:
    path: pd.DataFrame
    achieved_value: float
    requested_value: float
    required_terminal_price: float
    feasible: bool
    observed_return_limits: tuple[float, float]
    within_historical_limits: bool = True


def features_from_ohlcv(bars: pd.DataFrame) -> pd.DataFrame:
    """All features at t use only OHLCV up to and including t."""
    names = {"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}
    data = bars.rename(columns=names).copy()
    if "date" in data.columns:
        data = data.set_index("date")
    if "날짜" in data.columns:
        data = data.set_index("날짜")
    if "trade_date" in data.columns:
        data = data.set_index("trade_date")
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data.loc[data.index.notna()].sort_index()
    data = data.loc[~data.index.duplicated(keep="last")]
    required = ["open", "high", "low", "close", "volume"]
    if any(c not in data for c in required):
        raise ValueError("날짜, 시가, 고가, 저가, 종가, 거래량 열이 필요합니다.")
    for c in required:
        data[c] = pd.to_numeric(data[c], errors="coerce")
    data = data.dropna(subset=required)
    data = data.loc[(data[required[:4]] > 0).all(axis=1) & data.volume.ge(0)]
    if len(data) < 20:
        raise ValueError("RSI 등 보조지표 계산에는 최소 20거래일의 일봉이 필요합니다.")
    close = data.close
    result = pd.DataFrame(index=data.index)
    result["close"] = close
    result["ret1"] = close.pct_change(fill_method=None) * 100
    result["ret5"] = close.pct_change(5, fill_method=None) * 100
    result["ret20"] = close.pct_change(20, fill_method=None) * 100
    result["volatility20"] = result.ret1.rolling(20).std()
    result["volume_ratio"] = data.volume / data.volume.rolling(20).mean().replace(0, np.nan)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    result["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    result.loc[loss.eq(0) & gain.gt(0), "rsi"] = 100
    result.loc[loss.eq(0) & gain.eq(0), "rsi"] = 50
    low = data.low.rolling(5).min()
    high = data.high.rolling(5).max()
    fast_k = (close - low) / (high - low).replace(0, np.nan) * 100
    result["stoch_k"] = fast_k.rolling(3).mean()
    macd = close.ewm(span=12, adjust=False, min_periods=12).mean() - close.ewm(span=26, adjust=False, min_periods=26).mean()
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    result["macd_pct"] = (macd - signal) / close * 100
    mid = close.rolling(20).mean()
    result["bb_z"] = (close - mid) / close.rolling(20).std(ddof=0).replace(0, np.nan)
    for span in (5, 10, 15, 33, 56, 112, 224, 448):
        ema = close.ewm(span=span, adjust=False, min_periods=span).mean()
        # Day-on-day change of the moving average itself, percentage points.
        result[f"ema{span}_change_pct"] = ema.pct_change(fill_method=None) * 100
        if span in (5, 15):
            # Existing model features and inverse-scenario inputs are preserved.
            result[f"ema{span}_gap"] = (close / ema - 1) * 100
    return result.replace([np.inf, -np.inf], np.nan).dropna(subset=['ret1'])


def add_market_features(frame: pd.DataFrame, market_bars: pd.DataFrame | None):
    """Join only same-day market observations; no backfill from future dates."""
    if market_bars is None or market_bars.empty:
        return frame, FEATURES, "종합지수 이력 없음 · 종목 단독 모델"
    bars = market_bars.copy()
    if 'date' in bars:
        bars = bars.set_index('date')
    if 'trade_date' in bars:
        bars = bars.set_index('trade_date')
    bars.index = pd.to_datetime(bars.index, errors='coerce')
    bars = bars.loc[bars.index.notna()].sort_index()
    bars = bars.loc[~bars.index.duplicated(keep='last')]
    if 'close' not in bars and '종가' in bars:
        bars = bars.rename(columns={'종가': 'close'})
    if 'close' not in bars:
        return frame, FEATURES, "종합지수 종가 누락 · 종목 단독 모델"
    close = pd.to_numeric(bars.close, errors='coerce').where(lambda s: s.gt(0))
    market = pd.DataFrame(index=bars.index)
    for days in (1, 5, 20):
        market[f'market_ret{days}'] = close.pct_change(days, fill_method=None) * 100
    market['market_vol20'] = market.market_ret1.rolling(20).std()
    combined = frame.join(market, how='left')
    for days in (1, 5, 20):
        combined[f'relative_ret{days}'] = combined[f'ret{days}'] - combined[f'market_ret{days}']
    # Positive on market-down days only: distinguish unusual resistance to selling.
    combined['bear_strength'] = combined.relative_ret1.where(combined.market_ret1 < 0, 0)
    combined = combined.replace([np.inf, -np.inf], np.nan).dropna(subset=MARKET_FEATURES)
    # Never forecast with stale market data or train on too few aligned dates.
    if len(combined) < 60 or combined.index[-1] != frame.index[-1]:
        return frame, FEATURES, "종합지수 날짜·학습량 부족 · 종목 단독 모델"
    return combined, FEATURES + MARKET_FEATURES, "종목·종합지수 동시 학습"


def _short_history_forecast(frame: pd.DataFrame, column: str, target: float,
                            horizon: int, selected_features: list[str],
                            market_features: list[str], context: str,
                            source_frame: pd.DataFrame) -> list[Checkpoint]:
    """Regularized small-sample model; purge labels overlapping test dates."""
    latest = frame.iloc[-1]
    low_target, high_target = frame[column].quantile([.01, .99])
    outside_history = not low_target <= target <= high_target
    checkpoints = sorted({1, max(1, horizon // 2), horizon})
    results = []
    market_ready = bool(market_features and len(frame) >= 80)
    for days in checkpoints:
        label = (frame.close.shift(-days) / frame.close - 1) * 100
        usable = frame.assign(label=label).dropna(subset=['label'])
        model_labels_available = len(usable) >= 8
        if len(usable) < 8:
            historical_label = (source_frame.close.shift(-days) / source_frame.close - 1) * 100
            usable = source_frame.assign(label=historical_label).dropna(subset=['label'])
        if len(usable) < 8:
            raise ValueError(f'{days}일 뒤 수익률을 계산할 과거 거래일이 부족합니다. 기간을 줄여 주세요.')
        test_start = int(len(usable) * .8)
        train_end = test_start - days
        holdout = usable.iloc[test_start:]
        stock_cols = selected_features
        full_cols = selected_features + market_features if market_ready else selected_features
        use_ridge = (model_labels_available and len(frame) >= 25 and
                     train_end >= 15 and len(holdout) >= 5)
        if use_ridge:
            train = usable.iloc[:train_end]
            # The last segment of training chooses regularization without
            # observing labels that cross into the validation segment.
            inner_start = int(len(train) * .8)
            inner_end = inner_start - days
            best_alpha = 100.0
            if inner_end >= 12 and len(train) - inner_start >= 5:
                scored = []
                for alpha in (10.0, 100.0, 1000.0):
                    candidate = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
                    candidate.fit(train.iloc[:inner_end][full_cols], train.iloc[:inner_end].label)
                    err = mean_absolute_error(train.iloc[inner_start:].label,
                                              candidate.predict(train.iloc[inner_start:][full_cols]))
                    scored.append((err, alpha))
                best_alpha = min(scored)[1]
            market_model = make_pipeline(StandardScaler(), Ridge(alpha=best_alpha))
            market_model.fit(train[full_cols], train.label)
            stock_model = None
            if market_ready:
                stock_model = make_pipeline(StandardScaler(), Ridge(alpha=best_alpha))
                stock_model.fit(train[stock_cols], train.label)

            def predict(dataset):
                estimate = market_model.predict(dataset[full_cols])
                if stock_model is not None:
                    estimate = .8 * stock_model.predict(dataset[stock_cols]) + .2 * estimate
                return estimate

            prediction = predict(holdout)
            errors = holdout.label.to_numpy() - prediction
            mae = float(mean_absolute_error(holdout.label, prediction))
            naive = float(mean_absolute_error(holdout.label, np.zeros(len(holdout))))
            direction = float((np.sign(prediction) == np.sign(holdout.label.to_numpy())).mean() * 100)
            # Refit using all known labeled rows after the holdout estimate.
            market_model.fit(usable[full_cols], usable.label)
            if stock_model is not None:
                stock_model.fit(usable[stock_cols], usable.label)
            current = latest.to_frame().T
            adjusted = current.copy()
            adjusted[column] = float(latest[column]) + (target - float(latest[column])) * days / horizon
            baseline = float(predict(current)[0])
            scenario = float(predict(adjusted)[0])
            low, high = (float(x) for x in np.quantile(errors, [.1, .9]))
            if outside_history:
                signal = '신호 보류 (입력 지표가 과거 범위 밖)'
            elif len(holdout) < 10 or mae >= naive:
                signal = '신호 보류 (소표본 검증 기준 미달)'
            else:
                signal = '관망'  # No automatic trade recommendation from a small listing history.
            start, end = str(train.index[0].date()), str(train.index[-1].date())
            test_first, test_last = str(holdout.index[0].date()), str(holdout.index[-1].date())
            count, test_count = len(train), len(holdout)
            detail = ('소표본 Ridge(시간순 검증)' +
                      (' · 해당 시장 지수 연동 20%' if market_ready else ' · 종목 이력만 사용'))
        else:
            # Too few disjoint observations for an honest validation: use a
            # robust historical-return baseline and never issue a trade signal.
            available = usable.iloc[:max(train_end, 0)]
            if len(available) < 5:
                available = usable
            baseline = scenario = float(available.label.median())
            low, high = (float(x) for x in available.label.quantile([.1, .9]))
            mae = naive = direction = float('nan')
            signal = '신호 보류 (검증 가능한 이력 부족)'
            start, end = str(available.index[0].date()), str(available.index[-1].date())
            test_first = test_last = '-'
            count, test_count = len(available), 0
            detail = '소표본 과거수익률 중앙값 · 시간순 검증 불가'
        price = float(latest.close)
        results.append(Checkpoint(days, price, max(.01, price * (1 + baseline / 100)),
                                  max(.01, price * (1 + scenario / 100)),
                                  max(.01, price * (1 + (scenario + low) / 100)),
                                  max(.01, price * (1 + (scenario + high) / 100)),
                                  mae, naive, direction, signal, start, end, count,
                                  test_first, test_last, test_count, len(frame), detail,
                                  float(latest.get('relative_ret1', 0)),
                                  bool(latest.get('market_ret1', 0) < 0 and latest.ret1 > 0),
                                  '-', '-'))
    return results


def evaluate(bars: pd.DataFrame, indicator: str, target: float, horizon: int,
             lookback: int | None = None, market_bars: pd.DataFrame | None = None) -> list[Checkpoint]:
    """Train direct horizon models; compare baseline and altered-indicator scenarios."""
    if indicator not in INDICATORS:
        raise ValueError("목록에서 보조지표를 선택하세요.")
    if not np.isfinite(target) or not 1 <= horizon <= 60:
        raise ValueError("목표값은 유한한 숫자, 기간은 1~60거래일이어야 합니다.")
    if indicator in ("RSI(14)", "Slow %K(5,3,3)") and not 0 <= target <= 100:
        raise ValueError("RSI와 스토캐스틱 목표값은 0~100입니다.")
    frame, _, market_context = add_market_features(features_from_ohlcv(bars), market_bars)
    column = INDICATORS[indicator]
    stock_features = FEATURES + ([column] if column not in FEATURES else [])
    if lookback is not None:
        if not 20 <= lookback <= 20000:
            raise ValueError("학습 기간은 20~20000거래일을 입력하거나 비워 두세요.")
        frame = frame.tail(lookback)
    if frame.empty or not np.isfinite(frame[column].iloc[-1]):
        raise ValueError(f'{indicator} 계산에 필요한 종목 이력이 부족합니다. 다른 지표를 선택하세요.')
    has_market = market_context == "종목·종합지수 동시 학습"
    long_columns = stock_features + (MARKET_FEATURES if has_market else [])
    full_frame = frame.dropna(subset=long_columns)
    if len(full_frame) < 750:
        candidates = ['ret1', 'ret5', 'volatility20', 'volume_ratio']
        fast_features = [name for name in candidates
                         if np.isfinite(frame[name].iloc[-1]) and frame[name].notna().sum() >= 8]
        fast_features = list(dict.fromkeys([*fast_features, column]))
        short_market = (['market_ret1', 'relative_ret1', 'bear_strength']
                        if has_market else [])
        short_frame = frame.dropna(subset=fast_features + short_market)
        if short_frame.empty:
            raise ValueError(f'{indicator} 계산에 필요한 거래일이 부족합니다.')
        return _short_history_forecast(short_frame, column, target, horizon,
                                       fast_features, short_market, market_context, frame)
    frame = full_frame
    used_features = long_columns
    lo, hi = frame[column].quantile([0.01, 0.99])
    outside_history = not lo <= target <= hi and not np.isclose(target, frame[column].iloc[-1])
    checkpoints = sorted(set([1, max(1, horizon // 2), horizon]))
    results = []
    latest = frame.iloc[-1]
    for days in checkpoints:
        labels = (frame.close.shift(-days) / frame.close - 1) * 100
        usable = frame.assign(label=labels).dropna(subset=["label"])
        # Selection and final test are disjoint; purge labels crossing each boundary.
        selection_start = int(len(usable) * .70)
        test_start = int(len(usable) * .85)
        train_end = selection_start - days
        selection_end = test_start - days
        if train_end < 250 or selection_end - selection_start < 30 or len(usable) - test_start < 50:
            raise ValueError("선택한 기간의 시간순 검증에 필요한 거래일이 부족합니다.")
        train = usable.iloc[:train_end]
        selection = usable.iloc[selection_start:selection_end]
        final_train = usable.iloc[:test_start-days]
        holdout = usable.iloc[test_start:]
        model = HistGradientBoostingRegressor(
            max_iter=120, max_leaf_nodes=12, min_samples_leaf=25,
            l2_regularization=1.0, early_stopping=False, random_state=42,
        )
        model.fit(train[used_features], train.label)
        market_weight = 0.0
        stock_model = None
        if market_context == "종목·종합지수 동시 학습":
            # A fixed, modest market component lets broad-index direction enter
            # the forecast without making a stock's own history irrelevant.
            stock_model = HistGradientBoostingRegressor(
                max_iter=120, max_leaf_nodes=12, min_samples_leaf=25,
                l2_regularization=1.0, early_stopping=False, random_state=42,
            )
            stock_model.fit(train[stock_features], train.label)
            market_weight = 0.20
            selected_context = '종목 80% · 종합지수 연동 20% (과거 동시 학습)'
        else:
            selected_context = market_context
        model.fit(final_train[used_features], final_train.label)
        market_prediction = model.predict(holdout[used_features])
        if stock_model is not None:
            stock_model.fit(final_train[stock_features], final_train.label)
            stock_prediction = stock_model.predict(holdout[stock_features])
            prediction = (1-market_weight)*stock_prediction + market_weight*market_prediction
        else:
            prediction = market_prediction
        error = holdout.label.to_numpy() - prediction
        mae = mean_absolute_error(holdout.label, prediction)
        naive = mean_absolute_error(holdout.label, np.zeros(len(holdout)))
        direction = float((np.sign(prediction) == np.sign(holdout.label.to_numpy())).mean() * 100)
        model.fit(usable[used_features], usable.label)
        if stock_model is not None:
            stock_model.fit(usable[stock_features], usable.label)
        current = latest.to_frame().T
        adjusted = current.copy()
        column = INDICATORS[indicator]
        adjusted[column] = float(latest[column]) + (target - float(latest[column])) * days / horizon
        baseline = float(model.predict(current[used_features])[0])
        scenario = float(model.predict(adjusted[used_features])[0])
        if stock_model is not None:
            baseline = ((1-market_weight)*float(stock_model.predict(current[stock_features])[0])
                        +market_weight*baseline)
            scenario = ((1-market_weight)*float(stock_model.predict(adjusted[stock_features])[0])
                        +market_weight*scenario)
        qlow, qhigh = np.quantile(error, [0.10, 0.90])
        lower = float(latest.close * (1 + (scenario + qlow) / 100))
        upper = float(latest.close * (1 + (scenario + qhigh) / 100))
        # A signal is withheld when the model has not beaten a zero-return baseline.
        threshold = max(1.0, float(np.quantile(np.abs(error), 0.75)))
        if outside_history:
            verdict = "신호 보류 (입력 지표가 과거 1~99백분위 밖)"
        elif mae >= naive:
            verdict = "신호 보류 (검증 기준 미달)"
        elif scenario > threshold and scenario + qlow > 0:
            verdict = "매수 검토"
        elif scenario < -threshold and scenario + qhigh < 0:
            verdict = "매도 검토"
        else:
            verdict = "관망"
        results.append(Checkpoint(days, float(latest.close),
                                  float(latest.close * (1 + baseline/100)),
                                  float(latest.close * (1 + scenario/100)),
                                  lower, upper, float(mae), float(naive), direction, verdict,
                                  str(final_train.index[0].date()), str(final_train.index[-1].date()),
                                  len(final_train), str(holdout.index[0].date()),
                                  str(holdout.index[-1].date()), len(holdout), len(frame),
                                  selected_context,
                                  float(latest.get('relative_ret1', 0)),
                                  bool(latest.get('market_ret1', 0) < 0 and latest.ret1 > 0),
                                  str(selection.index[0].date()),str(selection.index[-1].date())))
    return results


def scenario_path(bars: pd.DataFrame, indicator: str, target: float, horizon: int,
                  lookback: int | None = None, market_bars: pd.DataFrame | None = None) -> PathResult:
    """Find an in-range price path reaching the target and recompute every indicator.

    This is an inverse scenario, not a causal forecast. Future intraday ranges and
    volumes use recent medians; the generated price path is log-linear.
    """
    if indicator not in INDICATORS or not 1 <= horizon <= 60 or not np.isfinite(target):
        raise ValueError("지표, 목표값 또는 1~60거래일 기간을 확인하세요.")
    names = {"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}
    base = bars.rename(columns=names).copy()
    for key in ("date", "날짜", "trade_date"):
        if key in base.columns:
            base = base.set_index(key)
            break
    base.index = pd.to_datetime(base.index, errors="coerce")
    base = base.loc[base.index.notna()].sort_index().loc[:, ["open", "high", "low", "close", "volume"]]
    base = base.loc[~base.index.duplicated(keep="last")]
    base = base.apply(pd.to_numeric, errors="coerce").dropna()
    if len(base) < 20:
        raise ValueError("RSI 등 보조지표 계산에는 최소 20거래일의 일봉이 필요합니다.")
    if lookback is not None:
        if not 20 <= lookback <= 20000:
            raise ValueError("학습 기간은 20~20000거래일을 입력하거나 비워 두세요.")
        # Retain a short lead-in so rolling/EMA indicators warm up before
        # the first selected observation; returns use only the selected dates.
        base = base.tail(lookback + 100)
    else:
        # Preserve the previous inverse-scenario window when left blank.
        base = base.tail(1200)
    observed_base = base.tail(lookback) if lookback is not None else base
    observed = observed_base.close.shift(-horizon).div(observed_base.close).sub(1).dropna()
    if len(observed) < 8:
        raise ValueError("선택한 도달 기간의 수익률을 파악할 자료가 부족합니다. 도달 기간을 줄여 주세요.")
    if market_bars is not None and not market_bars.empty:
        market = market_bars.rename(columns={'종가': 'close'}).copy()
        for key in ('date', 'trade_date'):
            if key in market.columns:
                market = market.set_index(key)
                break
        market.index = pd.to_datetime(market.index, errors='coerce')
        market = market.loc[market.index.notna()].sort_index()
        if 'close' in market:
            market_close = pd.to_numeric(market['close'], errors='coerce')
            market_close = market_close.where(market_close.gt(0)).reindex(observed_base.index)
            aligned = pd.DataFrame({'stock': observed,
                                    'market': market_close.shift(-horizon).div(market_close).sub(1)}).dropna()
            market_daily = market_close.pct_change(fill_method=None).dropna()
            if len(aligned) >= 350 and not market_daily.empty and market_daily.index[-1] == base.index[-1]:
                in_decline = market_daily.iloc[-1] < 0
                same_regime = aligned.loc[aligned.market.lt(0) if in_decline else aligned.market.ge(0), 'stock']
                if len(same_regime) >= 100:
                    observed = same_regime
    lower, upper = (float(x) for x in observed.quantile([.01, .99]))
    # Search the observed range first; broaden it only when the requested
    # indicator cannot be reached there. A synthetic path may exceed history.
    lower, upper = min(lower, 0.0), max(upper, 0.0)
    last = float(base.close.iloc[-1])
    dates = pd.bdate_range(base.index[-1] + pd.offsets.BDay(1), periods=horizon)
    recent = base.tail(20)
    wick_hi = float((recent.high / recent[["open", "close"]].max(axis=1) - 1).clip(lower=0).median())
    wick_lo = float((1 - recent.low / recent[["open", "close"]].min(axis=1)).clip(lower=0).median())
    volume = float(recent.volume.median())
    column = INDICATORS[indicator]

    def make_path(terminal_return: float, shape: float) -> tuple[float, pd.DataFrame, bool]:
        progress = (np.arange(1, horizon+1) / horizon) ** shape
        prices = last * np.exp(np.log1p(terminal_return) * progress)
        opens = np.r_[last, prices[:-1]]
        future = pd.DataFrame({
            "open": opens,
            "high": np.maximum(opens, prices) * (1 + wick_hi),
            "low": np.minimum(opens, prices) * (1 - wick_lo),
            "close": prices,
            "volume": np.full(horizon, volume),
        }, index=dates)
        full = pd.concat([base, future])
        derived = features_from_ohlcv(full).tail(horizon)
        daily_returns = future.close.pct_change(fill_method=None)
        daily_returns.iloc[0] = future.close.iloc[0] / last - 1
        plausible = bool(daily_returns.between(daily_low, daily_high).all())
        return float(derived[column].iloc[-1]), derived, plausible

    # Search multiple smooth trajectories. The chosen curve must track a
    # straight-line indicator target as closely as the price/return limits allow.
    # An early target crossing is allowed; the endpoint is always verified.
    current_indicator = float(features_from_ohlcv(base)[column].iloc[-1])
    observed_daily = observed_base.close.pct_change(fill_method=None).dropna()
    daily_low, daily_high = (float(x) for x in observed_daily.quantile([.01, .99]))
    choices = []
    tolerance = max(.01, abs(target) * .0001)
    desired = np.linspace(current_indicator, target, horizon + 1)[1:]

    def search(bounds: tuple[float, float]) -> None:
        for shape in (1.0, 1.5, 2.0, 3.0, 4.0, 6.0):
            grid = np.linspace(*bounds, 31)
            measures = [(ret, *make_path(float(ret), shape)) for ret in grid]
            refined = list(measures)
            for left, right in zip(measures, measures[1:]):
                if (left[1] - target) * (right[1] - target) > 0:
                    continue
                a, b = float(left[0]), float(right[0])
                fa = left[1] - target
                for _ in range(22):
                    mid = (a + b) / 2
                    value, data, plausible = make_path(mid, shape)
                    refined.append((mid, value, data, plausible))
                    if fa * (value - target) <= 0:
                        b = mid
                    else:
                        a, fa = mid, value - target
            for ret, value, data, plausible in refined:
                if not np.isfinite(value):
                    continue
                gradual = float(np.mean(np.abs(data[column].to_numpy() - desired)))
                terminal_error = abs(value - target)
                score = gradual + terminal_error * 5
                within_limits = lower <= ret <= upper and plausible
                choices.append((terminal_error <= tolerance, score, terminal_error,
                                value, data, within_limits))

    search((lower, upper))
    if not any(item[0] for item in choices):
        search((min(lower, -.90), max(upper, 3.0)))
    feasible = [item for item in choices if item[0]]
    if feasible:
        chosen = min(feasible, key=lambda item: (not item[5], item[1]))
    else:
        chosen = min(choices, key=lambda item: (item[2], item[1]))
    return PathResult(chosen[4], float(chosen[3]), float(target),
                      float(chosen[4].close.iloc[-1]), bool(feasible),
                      (lower * 100, upper * 100), bool(chosen[5]))
