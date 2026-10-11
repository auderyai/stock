# V37 xingAPI DLL 기준

최종 방향:

PySide6 64bit -> Controller -> Service -> Repository -> PostgreSQL
                                  ^
                                  |
                         32bit xingAPI DLL Worker
                                  |
                    C:\LS_SEC\xingAPI\XingAPI.dll

TR 구조체 정의는 `C:\LS_SEC\xingAPI\Header` 아래의 최신 날짜 폴더를 기준으로 한다.
해당 헤더는 `new_stock/resources/xing/headers/<YYYYMMDD>`에 1회 복사하여 프로젝트에서 관리한다.

V36의 RES 기반 정책은 폐기한다.
`LS_XING_RES_DIR`, `resources/xing/res`, `ResFileName`은 신규 DLL 경로에서 사용하지 않는다.
