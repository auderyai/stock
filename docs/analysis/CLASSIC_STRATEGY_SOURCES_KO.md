# 차트 고전전략 판정 근거

2026-10-10 확인. 외부 구현 코드는 사용하지 않고 아래 원전·공식 자료의 객관화 가능한 조건만 구현한다.

## 엘리어트 파동

- Elliott Wave International, Impulse: https://www.elliottwave.com/waveopedia/impulse/
- Elliott Wave International, Rules: https://www.elliottwave.com/articles/elevate-your-elliott-wave-analysis/
- 충격파는 5파이며 파동2는 파동1 시작점을 넘지 않고, 파동3은 1·3·5 중 최단이 아니며, 파동4는 파동1 가격영역과 겹치지 않아야 한다.
- 구현은 좌우 5봉으로 확인된 스윙에서 위 세 규칙을 모두 통과한 경우에만 `충격 5파 후보`로 표시한다. 파동 차수와 미래 진행을 확정하지 않는다.

## 제시 리버모어

- Jesse L. Livermore, How to Trade in Stocks(1940) 원문 미러: https://studylib.net/doc/28210069/jesse-livermore-how-to-trade-in-stocks--1940-original--en...
- 원전은 Pivotal Point 통과 후의 가격 행동과 거래량 확인을 강조한다. 현대 데이터에서 고정 3포인트 규칙을 그대로 적용하면 종목 가격단위에 따라 왜곡되므로 사용하지 않는다.
- 구현은 직전 252거래일 최고가를 장기 피벗 대리값으로 사용하고 종가 돌파로 가격을 확인한다. 거래량은 당일을 제외한 직전 20일 평균과 비교한다.
- `1.50배`는 원전의 숫자가 아니라 “확대 거래량”을 기계적으로 구분하기 위한 공개된 운영 임계값이다. 시장·업종 선도 여부는 이 종목 차트 판정에 포함하지 않는다.

## 알렉산더 엘더

- Alexander Elder 공식 사이트: https://www.elder.com/product-page/elder-disk-v3-for-metastock-v15-with-scanners-1
- The New Trading for a Living, Triple Screen: https://file.hstatic.net/1000205346/file/alexander_elder_-_the_new_trading_for_a_living__2014_.pdf
- 첫 화면은 주봉 MACD-Histogram의 최근 두 막대 방향, 둘째 화면은 일봉 오실레이터를 사용한다.
- 주봉 상승 중 일봉 Stochastic 30 미만은 매수 관심, 주봉 하락 중 70 초과는 매도 관심으로 판정한다.
- 셋째 화면은 매수 시 직전일 고가 돌파, 매도 시 직전일 저가 이탈로 진입을 확인한다.

## 표시 원칙

- `전체`에서는 전략 전용 도형을 표시하지 않는다.
- 개별 전략을 선택했을 때만 엘리어트 파동선·번호, 리버모어 피벗·평균 거래량, 엘더 진입선·Stochastic 30/70을 표시한다.
- 모든 결과는 저장된 PostgreSQL 자료의 마지막 시점까지로만 계산하며 미래 봉을 생성하지 않는다.
- 규칙 기반 참고 판정이며 자동매매 신호나 수익 보장이 아니다.
