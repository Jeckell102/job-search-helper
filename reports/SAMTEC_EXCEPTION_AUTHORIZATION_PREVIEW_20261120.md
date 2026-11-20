# Samtec exception authorization preview

Read-only preview generated 2026-11-20 for the one queued operator request
`operator-samtec-m1-20261119`. This preview does not activate an exception,
create a retained store, fetch Samtec, write Sheets, create a cycle, or alter
the historical Saronic cycle.

## Current historical evidence

- Retained cycle: `CYC-B639C6D864EC`
- Manifest digest: `60b315dc4a63f3152b992eec0b4363f814e57f7049ff8ad10f0330cebff95f36`
- Workbook ID digest: `eee8e8e1caa4fdd5de6465e8418a18373b8119fed78347db18ca95a846f70826`
- Cycle digest: `191cefbc6b5ba26ceacc54ae2be1770691331fa343d83b1f3ee2c8835297bd50`
- Inventory evidence digest: `77050806f6170495c0e20c7d702ccccd7b01ca1846ec4ae13b1adb18e8f3305c`
- Job evidence digest: `c76ba80a7c6bc6ff04c0c50327de37fb55ea25444fc7034e4906b80c49002942`

## Required signed claim payload

```json
{
  "action": "activate-retained-work-exception-v1",
  "cycle_digest": "191cefbc6b5ba26ceacc54ae2be1770691331fa343d83b1f3ee2c8835297bd50",
  "cycle_id": "CYC-B639C6D864EC",
  "expires_at": "2026-11-21T02:52:40+00:00",
  "inventory_evidence_digest": "77050806f6170495c0e20c7d702ccccd7b01ca1846ec4ae13b1adb18e8f3305c",
  "job_evidence_digest": "c76ba80a7c6bc6ff04c0c50327de37fb55ea25444fc7034e4906b80c49002942",
  "manifest_digest": "60b315dc4a63f3152b992eec0b4363f814e57f7049ff8ad10f0330cebff95f36",
  "version": 1,
  "workbook_id_digest": "eee8e8e1caa4fdd5de6465e8418a18373b8119fed78347db18ca95a846f70826"
}
```

The production verifier accepts only an envelope signed by a configured
Ed25519 public key for this exact payload. A test verifier is forbidden.
The evidence must be regenerated and re-signed if any digest or expiry changes.
