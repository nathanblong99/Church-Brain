from tests.fixtures import reset_and_seed
from state.seed import snapshot_hash, load_dev_seed


def test_seed_reproducibility():
    h1 = reset_and_seed()
    h2 = reset_and_seed()
    assert h1 == h2, f"Hashes differ across reseed: {h1} vs {h2}"

    # Load again without reset should not change
    load_dev_seed()
    h3 = snapshot_hash()
    assert h1 == h3, "Idempotent load changed snapshot"

    # If anchor date env var changes, hash should differ (skip setting env var here to keep test stable)
