import json,os,subprocess,time,collections
PY=r"C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python"
BASE=r"C:/Users/basil/Desktop/Projects/FullStackProjects/CandleViewer/docs/research/xstate"
ENV=dict(os.environ); ENV["PYTHONIOENCODING"]="utf-8"; ENV["PYTHONUTF8"]="1"
S=["issues/post-6db65d8/new/repro/R8-04_always_ondone_reentry_settle_tripped.py",
"issues/post-6db65d8/new/repro/R8-07_send_wait_resolves_over_empty_configuration.py",
"issues/post-f28719c/new/repro/R9-08_send_wait_resolves_over_empty_configuration.py",
"issues/verify-0.8.0/LC-42_send_receipt.py",
"issues/verify-main-221ce7c/167_rollback_reinvoke_spin.py",
"issues/verify-main-3ed3099/105_external-send-not-charged-to-chain-budget.py",
"issues/verify-main-5327ba6/LC-37_wrongthreaderror-message.py",
"issues/verify-main-5327ba6/LC-42_send_receipt.py",
"issues/verify-main-cec108b/repro_147_151.py",
"issues/verify-main-f28719c/197_empty_config_wait.py",
"issues/post-c78ce99/new/repro/R11-07_nested_config_typos_silent.py",
"issues/post-c78ce99/new/repro/R11-09_chain_trip_erased_by_next_event.py",
"issues/verify-main-5e07ba8/final/fv4_r407_falsepos.py",
"issues/verify-main-5e07ba8/ref/refute_r407.py",
"issues/verify-main-5e07ba8/ref/refute_r407b.py"]
out={}
for rel in S:
    rs=[]
    for i in range(5):
        try:
            p=subprocess.run([PY,os.path.join(BASE,rel)],cwd=r"C:/Users/basil",env=ENV,
              capture_output=True,text=True,timeout=120,errors="replace")
            rs.append("PASS" if p.returncode==0 else "FAIL")
        except subprocess.TimeoutExpired: rs.append("TIMEOUT")
    out[rel]=rs
    print(rel, collections.Counter(rs), flush=True)
json.dump(out,open(os.path.join(BASE,"gate","r12_flaky.json"),"w"),indent=1)
