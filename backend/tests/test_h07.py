from h07_extra_trap import armed, on_save

def test_skip():
    v, r = on_save("合格", "ok")
    assert v is None
    assert armed() is True
