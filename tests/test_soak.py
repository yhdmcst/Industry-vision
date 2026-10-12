from scripts.run_soak import decision, POLICY


def test_soak_requires_duration_and_clean_shutdown_even_without_errors():
    result = {'errors': [], 'shutdown_clean': True, 'elapsed_seconds': 30}
    assert decision(result) == 'smoke_only'
    result['elapsed_seconds'] = POLICY['minimum_seconds']
    assert decision(result) == 'passed'
    result['shutdown_clean'] = False
    assert decision(result) == 'failed'
    result['shutdown_clean'] = True
    result['errors'] = ['capture stalled']
    assert decision(result) == 'failed'
