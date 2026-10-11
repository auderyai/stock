# PostgreSQL 자격증명 정책

## 원칙
별도 READ 계정은 필수가 아니다.

### 조회(read_only=True)
1. KRX_DB_READ_USER / KRX_DB_READ_PASSWORD가 둘 다 실제로 구성된 경우 사용
2. 없으면 KRX_DB_WRITE_USER + KRX_DB_WRITE_PASSWORD 재사용
3. WRITE_USER가 없으면 KRX_DB_USER 사용
4. WRITE_PASSWORD가 없으면 KRX_DB_PASSWORD 사용

### 쓰기
1. KRX_DB_WRITE_USER + KRX_DB_WRITE_PASSWORD
2. 없으면 KRX_DB_USER + KRX_DB_PASSWORD

따라서 기존 PostgreSQL 계정 하나로 읽기/쓰기를 함께 사용하는 환경을 지원한다.
SQLite는 사용하지 않는다.
