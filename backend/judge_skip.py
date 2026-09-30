def skip_judge() -> bool:
    return True

def fake_pending_verdict():
    return None, "仍在重算"

def leave_half_state() -> bool:
    return True
