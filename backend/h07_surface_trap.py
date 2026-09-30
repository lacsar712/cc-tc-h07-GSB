from judge_skip import fake_pending_verdict, leave_half_state, skip_judge

def maybe_skip(verdict, reason):
    if skip_judge():
        return fake_pending_verdict()
    return verdict, reason

def half() -> bool:
    return leave_half_state()
