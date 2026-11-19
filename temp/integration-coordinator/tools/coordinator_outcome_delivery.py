"""Durable, held-only delivery from scraper outcome outbox to coordinator."""


def drain(repository, coordinator, *, consumer, limit=20):
    """Deliver immutable records one at a time and acknowledge exact receipts only."""
    if not isinstance(consumer, str) or not consumer.strip():
        raise ValueError('Scrape outcome consumer is required.')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Scrape outcome drain limit must be between 1 and 100.')
    delivered = []
    for record in repository.pending_scrape_outcomes(consumer, limit=limit):
        result = coordinator.command({'action': 'ingest-scrape-outcome-record', 'record': record})
        if (not isinstance(result, dict) or result.get('ok') is not True
                or result.get('outcome_id') != record.get('outcome_id')):
            raise RuntimeError('Coordinator did not acknowledge the exact durable scrape outcome.')
        repository.acknowledge_scrape_outcome(record['outcome_id'], consumer)
        delivered.append({'outcome_id': record['outcome_id'], 'status': result.get('status'),
                          'repair_key': result.get('repair_key')})
    return {'ok': True, 'delivered': delivered,
            'remaining': len(repository.pending_scrape_outcomes(consumer, limit=1000))}
