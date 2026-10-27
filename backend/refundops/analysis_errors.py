"""Public diagnostics selected by code, never by raw provider response text."""
MESSAGES = {
    'network_blocked': 'Windows is blocking this server from accessing the AI service (WinError 10013). Open START.cmd from Windows to replace the restricted server. Analysis will resume automatically.',
    'connection_failed': 'The AI service cannot be reached. Analysis will retry automatically when the connection is restored.',
    'authentication': 'The AI service rejected the configured key. The Refund Operations Manager can update it in Settings; analysis will then resume automatically.',
    'credits': 'The AI account has insufficient credits or has reached its provider spending limit. Analysis will resume when the account is available.',
    'budget': 'The configured workspace AI budget has been reached. The Refund Operations Manager needs to review the budget before analysis can continue.',
    'rate_limit': 'The AI service is rate limiting requests. Analysis is paused briefly and will retry automatically.',
    'provider_error': 'The AI service returned an error. Analysis will retry automatically.',
    'citation_invalid': 'The model returned a quotation that could not be verified against the original notes. That result was discarded; existing evidence remains available.',
    'invalid_response': 'The model response did not pass validation. That result was discarded; existing evidence remains available.',
    'input_too_long': 'The request text exceeds the analysis input limit. The Refund Operations Manager can review the source data; staff review remains available.',
    'unknown': 'Automatic analysis encountered an unexpected error. Existing evidence remains available; the Refund Operations Manager can check the AI connection.',
}
PROVIDER_WIDE = {'network_blocked','connection_failed','authentication','credits','budget','rate_limit','provider_error'}


def public_failure(ex):
    code = getattr(ex, 'code', 'unknown')
    if code not in MESSAGES: code = 'unknown'
    result = {'code': code, 'message': MESSAGES[code]}
    if getattr(ex, 'diagnostics', None): result['diagnostics'] = ex.diagnostics
    return result
