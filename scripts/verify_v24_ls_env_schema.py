from pathlib import Path
root=Path(__file__).resolve().parents[1]
text=(root/'src/krx_research/collectors/xing/credentials.py').read_text(encoding='utf-8')
assert 'LS_XING_ID' in text and 'LS_XING_PASSWORD' in text
assert 'LS_APP_KEY' not in text and 'LS_APP_SECRET' not in text
print('V24_LS_ENV_SCHEMA_CHECK: PASS')
