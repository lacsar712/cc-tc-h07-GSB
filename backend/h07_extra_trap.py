from h07_surface_trap import half, maybe_skip

def on_save(verdict, reason):
    return maybe_skip(verdict, reason)

def armed() -> bool:
    return half()
