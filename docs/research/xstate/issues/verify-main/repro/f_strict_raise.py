from xstate_statemachine import create_machine
# strict machine raising a typo'd RESERVED-namespace event: should it be caught?
cfg={"id":"m","strict":True,"initial":"a","states":{"a":{"entry":[{"type":"raise","params":{"event":"done.reveiw"}}],"on":{"done.review":{"target":"b"}}},"b":{}}}
try:
    create_machine(cfg); print("built OK - typo'd reserved raise NOT caught")
except Exception as e: print("caught:", e)
