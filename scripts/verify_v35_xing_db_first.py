from pathlib import Path
root=Path(__file__).resolve().parents[1]
checks={
 'xing package': (root/'src/krx_research/collectors/xing/query.py').is_file(),
 'db membership': (root/'src/krx_research/data_engine/index_membership_store.py').is_file(),
 'fast daily': (root/'scripts/run_fast_daily_update.py').is_file(),
 'xing setup': (root/'tools/setup/SETUP_XINGAPI_CREDENTIALS_ONCE.cmd').is_file(),
}
active=[root/'scripts/update_xing_venue_history.py',root/'scripts/update_market_indices.py',root/'scripts/update_ls_investor_raw.py',root/'scripts/update_ls_investor_date_range.py',root/'src/krx_research/collectors/ls_index_api.py',root/'src/krx_research/theme_research/public_sources.py']
for path in active:
 text=path.read_text(encoding='utf-8')
 checks[f'no openapi import {path.name}']='ls_openapi' not in text and 'LSOpenApiT8451Client' not in text and 'openapi.ls-sec.co.kr' not in text
checks['screen DB-only']='PostgreSQLIndexMembershipStore' in (root/'src/krx_research/collectors/ls_index_membership.py').read_text(encoding='utf-8')
for name,ok in checks.items():
 if not ok: raise AssertionError(name)
print('V35_XING_DB_FIRST_CHECK: PASS')
