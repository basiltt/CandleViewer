# -*- coding: utf-8 -*-
PHASE = "P5 Collaboration & Polish"
MS = "R5 Hardening / GA"

def T(key, kind, title, labels, component, sprint, priority, perspective, risk,
      estimate, parent, blocked_by, body):
    return dict(key=key, kind=kind, title=title, labels=labels, component=component,
                phase=PHASE, sprint=sprint, priority=priority, perspective=perspective,
                risk=risk, estimate=estimate, parent=parent, blocked_by=blocked_by,
                milestone=MS, body=body)
