import sys, subprocess
R="C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine"
for term in ["Receipt.deferred","deferred=True","RunawayChainError","persist_event","restore_event","is_system_event","system_event","has_dormant_invocations","last_error","normalize_logic_name"]:
    out=subprocess.run(["grep","-rl",term,f"{R}/docs"],capture_output=True,text=True).stdout.strip()
    print(f"{term:26s} docs: {out.replace(R+'/docs/','') if out else '*** NONE ***'}")
