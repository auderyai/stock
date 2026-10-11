from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'KRX_Menu_Launcher'/'scripts'/'run_job_progress_gui.py'
s=p.read_text(encoding='utf-8')
assert 'class JobLogService' in s
assert 'self.path.unlink()' in s
assert 'project_root / "logs"' in s
assert '로그 열기' in s
assert 'self.job_log.append(line)' in s
assert 'self.job_log.finish(result, code, elapsed)' in s
assert '정상 완료' in s and '미완료/오류' in s
print('V28_JOB_LOGGING_CHECK: PASS')
