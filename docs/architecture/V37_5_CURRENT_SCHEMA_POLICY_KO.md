# V37.5 현재 공식 schema 정책

최신 DevCenter 화면과 최신 설치본 파일을 교차 확인한 결과:

현재 공식 RES 확인:
- t8424
- t8436
- t8429
- t8451

최신 설치본에서 직접 확인되지 않은 TR:
- t1516
- t1702

정책:
1. 설치 원본 `C:\LS_SEC\xingAPI_Program(2025.06.07)\Res`는 읽기 전용으로 취급한다.
2. 현재 공식 RES 4종과 `_2.res` 변형이 있으면 `new_stock/resources/xing/current_res`에 복사한다.
3. SHA256 manifest를 생성한다.
4. t1516/t1702는 과거 DLL sample header를 자동 승격하지 않는다.
5. t1516/t1702 최신 구조 확보 전까지 DLL runtime 전환을 차단한다.
