# V36.6 xingAPI RES 보관 원칙

xingAPI RES는 외부 Downloads/DevCenter 폴더를 실행 경로로 사용하지 않는다.

유일한 공통 경로:

`new_stock/resources/xing/res`

모든 32bit xingAPI worker와 TR은 이 폴더를 사용한다.

`LS_XING_RES_DIR`도 위 폴더를 가리킨다.

필수 TR가 모두 준비되지 않으면 설정 도구는 저장을 거부한다.
