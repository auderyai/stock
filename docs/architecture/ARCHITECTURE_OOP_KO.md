# new_stock 객체지향 구조

## 의존성 방향

```text
NewStockApplication (composition root)
        |
        v
WorkstationWindow(View) <-> WorkstationController
                              |
               +--------------+---------------+
               |              |               |
               v              v               v
       ScreeningService   ChartService   SecuritySearchService
               |              |               |
               +--------------+---------------+
                              |
                              v
                        WorkstationData
                              |
                              v
                          PostgreSQL
```

Qt View는 PostgreSQL Repository나 SQL을 직접 호출하지 않습니다.

## 차트

```text
ChartWindow(View)
      ^ signals / presentation
      |
ChartController
      |
ChartService
      |
WorkstationData -> PostgreSQL
```

`ChartWindow`는 FigureCanvasQTAgg로 렌더링하고, 데이터 로딩은 Controller/Service가 담당합니다.

## 특징주/테마

```text
FeaturedResearchView -> FeaturedResearchController -> FeaturedResearchService -> FeaturedResearchRepository
ThemeResearchView    -> ThemeResearchController    -> ThemeResearchService    -> ThemeResearchRepository
```

## 화면 표시 모델

`ScreenResultPresenter`가 내부 DataFrame을 사용자용 한글 표시 모델로 변환합니다.
내부 컬럼명과 SQL 구문은 화면에 노출하지 않습니다.

## 이동평균 유사배열

`SecuritySearchPanel`에서 기준 종목을 검색/선택합니다.
선택된 6자리 종목코드는 `ScreenQuery.comparison_ticker`로 전달되고,
`ScreeningService -> WorkstationData -> PostgreSQLOnDemandData` 경로를 통해 EMA 유사배열 계산에 사용됩니다.

## V6 추가 구조

차트 탐색은 Strategy 패턴으로 분리됩니다.

```text
WorkstationController
  └─ ChartNavigationStrategy
       ├─ NewChartWindowStrategy
       └─ SynchronizedChartStrategy
```

동일 차트 갱신 시:

```text
ChartWindow(ResultTable)
  → navigationTickerChanged
  → ChartController
  → ChartService
  → WorkstationData / PostgreSQL Repository
```

공통 테이블 표시:

```text
ResultTable / QTableView
  → DataFrameModel
  → TablePresentationPolicy
```

View와 Controller는 PostgreSQL Repository나 SQL을 직접 사용하지 않습니다.
수급 대시보드와 시장지수도 별도의 Controller/Service 계층으로 분리했습니다.

## V7 추가 계층
수급 화면은 다음 구조를 사용합니다.

`WorkstationController -> AuxiliaryWindowFactory -> InvestorDashboardView <-> InvestorDashboardController -> InvestorDashboardService -> PostgreSQL Repository`

표시 전용 변환은 `InvestorFlowPresenter`, 공통 숫자/정렬 형식은 `TablePresentationPolicy`가 담당합니다. View는 SQL/Repository를 직접 호출하지 않습니다.
