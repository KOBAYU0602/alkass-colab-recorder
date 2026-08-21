# Security

## Never commit authentication material

Do not commit or paste any of the following into code, notebooks, issues, logs, or state files:

- Netscape cookie contents
- `PHPSESSID`, `Token`, `cookiesession1`, or JWT values
- `Authorization: Bearer ...`
- Signed HLS URLs or query parameters
- Personal Google Drive file/folder IDs when they should remain private

Use the Colab Secret named `ALKASS_COOKIES`, or a private cookie file in your own Google Drive. Each person must use their own authorized account.

## Before sharing a notebook

1. In Colab, select **Edit → Clear all outputs**.
2. Save a new copy, not the operational notebook that contains recording history.
3. Run `tools/sanitize_notebook.py` on the exported `.ipynb`.
4. Run `tools/scan_secrets.py` on every file to be shared.
5. Revoke or rotate any token that was pasted into a notebook or chat.

## Reporting

Do not open a public issue containing credentials or stream URLs. Report only the code location and a redacted description.
