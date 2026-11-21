from test_fresh_pilot_environment import ENROLLMENT, WrapperFixture


for enabled in (True, False):
    fixture = WrapperFixture()
    if not enabled:
        fixture.reconcile(True)
    system = fixture.system

    def stopped_then_lost(operation, *values):
        if operation == 'restart':
            fixture.pid = 0
            fixture.process = {}
            raise OSError('Existing wrapper stopped before restart failed')
        return system(operation, *values)

    fixture.system = stopped_then_lost
    try:
        fixture.reconcile(enabled)
    except OSError:
        pass
    else:
        raise AssertionError('expected interrupted restart')
    fixture.system = system
    try:
        fixture.reconcile(enabled)
    except ValueError as error:
        assert str(error) == 'Expected the known active wrapper'
        assert (ENROLLMENT in fixture.manager) == enabled
        print(f'enabled={enabled}; repeat held; manager enrolled={ENROLLMENT in fixture.manager}; PID={fixture.pid}')
    else:
        raise AssertionError('expected inactive-wrapper boundary')
