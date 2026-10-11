from __future__ import annotations

from krx_research_nextgen.models.chart_data import IndicatorConfig
from krx_research_nextgen.services.chart_service import ChartService


class AuxiliaryService:
    LABELS = {"institution": "기관", "foreign": "외국인", "individual": "개인"}

    def __init__(self, repository, chart_service: ChartService | None = None) -> None:
        self._repository, self._charts = repository, chart_service or ChartService()

    def investor_dashboard(self, start, end, limit: int = 10) -> dict:
        source, result = self._repository.investor_rows(start, end), []
        rows = self._investor_facts(source)
        totals = {}
        for market in ("KOSPI", "KOSDAQ"):
            selected = [row for row in rows if str(row["market"]).upper() == market]
            for key, label in self.LABELS.items():
                totals[(market, key)] = sum(float(row[key] or 0) for row in selected)
                for direction, reverse in (("순매수", True), ("순매도", False)):
                    ranked = sorted(selected, key=lambda row: float(row[key] or 0), reverse=reverse)[:limit]
                    result.extend({"market": market, "investor": label, "direction": direction,
                                   "rank": rank, "stock_code": row["stock_code"],
                                   "stock_name": row["stock_name"], "net": float(row[key] or 0),
                                   "daily_return": row["daily_return"], "weekly_return": row["weekly_return"],
                                   "monthly_return": row["monthly_return"], "trading_value_eok": row["trading_value_eok"]}
                                  for rank, row in enumerate(ranked, 1))
        return {"rows": result, "totals": totals}

    def _investor_facts(self, source: dict) -> list[dict]:
        fields = {"institution": ("tjj0000","tjj0001","tjj0002","tjj0003","tjj0004","tjj0005"),
                  "foreign": ("tjj0009","tjj0010"), "individual": ("tjj0008",)}
        master = {str(x["ticker"]).strip(): x for x in source["master"]}
        prices, by_day = {}, {}
        for row in source["prices"]:
            code = str(row["ticker"]).strip(); prices.setdefault(code, []).append(row); by_day[(code, str(row["trade_date"]))] = row
        grouped = {}
        for row in source["raw"]:
            code, day, values = str(row["stock_code"]).strip(), str(row["trade_date"]), row["source_fields"]
            item = grouped.setdefault((code, day), {key: 0.0 for key in fields} | {"reported": 0.0})
            for key, names in fields.items(): item[key] += sum(float(values.get(name) or 0) for name in names)
            item["reported"] = max(item["reported"], abs(float(values.get("value") or 0)))
        flows = {}
        for (code, day), item in grouped.items():
            amount = float((by_day.get((code, day)) or {}).get("amount") or 0)
            factors = [factor for factor in (1,1000,1000000) if amount and abs(item["reported"]*factor-amount)/amount <= .02]
            if len(factors) != 1: continue
            target = flows.setdefault(code, {key: 0.0 for key in fields})
            for key in fields: target[key] += item[key]*factors[0]/100_000_000
        result = []
        for code, flow in flows.items():
            history, info = prices.get(code, []), master.get(code, {})
            close = lambda offset: float(history[offset]["close"]) if len(history)>offset and history[offset]["close"] else None
            current = close(0)
            rate = lambda offset: (current/close(offset)-1)*100 if current is not None and close(offset) else None
            result.append({"stock_code": code, "stock_name": info.get("name") or code, "market": info.get("market") or "", **flow,
                           "daily_return": rate(1), "weekly_return": rate(5), "monthly_return": rate(20),
                           "trading_value_eok": float(history[0]["amount"] or 0)/100_000_000 if history else None})
        return result

    def index_entries(self) -> list[dict]: return self._repository.index_entries()

    def index_chart(self, entry: dict):
        frame = self._repository.index_bars(str(entry["index_code"]))
        if frame.empty: raise ValueError(f"{entry['index_code']} 지수 일봉이 없습니다.")
        title = f"{entry['index_name']} ({entry['index_code']})"
        return self._charts.prepare(title, frame, config=IndicatorConfig(rsi_period=14.0), timeframe="D")
