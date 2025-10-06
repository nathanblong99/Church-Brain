from state.seed import reset_db_state, load_dev_seed, snapshot_hash


def reset_and_seed():
    """Reset global DB and load deterministic seed.
    Returns the snapshot hash for convenience in tests.
    """
    reset_db_state()
    load_dev_seed()
    return snapshot_hash()
