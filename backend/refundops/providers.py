"""Official OpenAI SDK transport for OpenAI and OpenRouter.

The extraction prompt, schema, validation and existing OpenRouter cache identity
remain owned by llm.py. Provider selection changes only credentials and transport.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from openai import APIConnectionError, APIStatusError, DefaultHttpx2Client, OpenAI
from pydantic import ValidationError

from .domain import fingerprint
from .llm import EvidenceExtractor, ProviderError, http_failure_code, strict_schema
from .storage import dump, now, uid

PROVIDERS = {
    'openai': {'label': 'OpenAI', 'base_url': 'https://api.openai.com/v1',
               'key_env': 'OPENAI_API_KEY', 'model_env': 'OPENAI_MODEL', 'model': 'gpt-6.1-sol'},
    'openrouter': {'label': 'OpenRouter', 'base_url': 'https://openrouter.ai/api/v1',
                   'key_env': 'OPENROUTER_API_KEY', 'model_env': 'OPENROUTER_MODEL', 'model': 'openai/gpt-6.1-sol'},
}
TRANSPORT_REVISION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def configured_provider():
    explicit = os.environ.get('AI_PROVIDER', '').strip().lower()
    if explicit:
        if explicit not in PROVIDERS:
            raise ValueError('AI_PROVIDER must be openai or openrouter.')
        return explicit
    # Existing OpenRouter installations keep their provider. New installs use OpenAI.
    return 'openrouter' if os.environ.get('OPENROUTER_API_KEY') and not os.environ.get('OPENAI_API_KEY') else 'openai'


class AIProvider(EvidenceExtractor):
    """Same validated extraction interface, one standard SDK for both endpoints."""

    def __init__(self, store):
        super().__init__(store)
        self.provider = configured_provider()
        config = PROVIDERS[self.provider]
        self.env_key = os.environ.get(config['key_env'], '')
        self.model = os.environ.get(config['model_env']) or config['model']
        self.enabled = bool(self.env_key)
        self._saved_analysis_disabled = False
        # Demo provenance is immutable for a running workspace. Read once, before
        # any policy transaction can ask for a manifest while holding a write lock.
        with self.store.connect() as connection:
            row = connection.execute("SELECT value FROM state WHERE key='demo_provenance'").fetchone()
        try:
            self._saved_provenance = json.loads(row[0]) if row else None
        except (TypeError, ValueError):
            self._saved_provenance = None

    def saved_analysis(self):
        """Reuse exact recorded demo provenance without impersonating a configured model."""
        if self.key or self._saved_analysis_disabled:
            return None
        if not self._saved_provenance:
            return None
        try:
            provenance = self._saved_provenance
            provider = provenance['provider']
            saved = provenance['model_manifest']
            if provider not in PROVIDERS or not isinstance(saved.get('model'), str):
                return None
            expected = super().manifest()
            expected['model'] = saved['model']
            if provider == 'openai':
                expected.update(provider='openai', transport=TRANSPORT_REVISION)
            if saved != expected:
                return None
            return provenance
        except (KeyError, TypeError, ValueError):
            return None

    def manifest(self):
        saved = self.saved_analysis()
        if saved:
            return dict(saved['model_manifest'])
        manifest = super().manifest()
        if self.provider == 'openai':
            manifest.update(provider='openai', transport=TRANSPORT_REVISION)
        # Preserves valid, grounded OpenRouter extractions when only transport changes.
        return manifest

    def status(self):
        saved = self.saved_analysis()
        return {**super().status(), 'provider': self.provider,
                'base_url': PROVIDERS[self.provider]['base_url'],
                'analysis_mode': 'saved_demo' if saved else 'live' if self.key else 'unavailable',
                'saved_analysis_provider': saved['provider'] if saved else None,
                'saved_analysis_model': saved['model_manifest']['model'] if saved else None}

    def configure(self, key=None, model=None, enabled=None, provider=None):
        selected = provider or (('openrouter' if key.startswith('sk-or-') else 'openai') if key else self.provider)
        if selected not in PROVIDERS:
            raise ValueError('Choose OpenAI or OpenRouter.')
        config = PROVIDERS[selected]
        if key is not None:
            expected = 'openrouter' if key.startswith('sk-or-') else 'openai'
            if len(key) < 20 or not key.startswith('sk-') or expected != selected:
                raise ValueError(f"Enter a valid {config['label']} API key for the selected provider.")
        changed = selected != self.provider
        default_model = (os.environ.get(config['model_env']) or config['model']) if changed else self.model
        selected_model = model or default_model
        if len(selected_model) > 200 or any(ch.isspace() for ch in selected_model):
            raise ValueError('Enter a model identifier without spaces.')
        if selected == 'openrouter' and '/' not in selected_model:
            raise ValueError('OpenRouter models use a provider/model identifier.')
        if selected == 'openai' and '/' in selected_model:
            raise ValueError('OpenAI uses a native model identifier, for example gpt-6.1-sol.')
        self._saved_analysis_disabled = True
        if changed:
            self.session_key = None
            self.env_key = os.environ.get(config['key_env'], '')
            self.provider = selected
            self.enabled = bool(self.env_key)
        if key is not None:
            self.session_key = key
            self.enabled = True
        self.model = selected_model
        if enabled is not None:
            self.enabled = bool(enabled)
        self.checked = False
        return self.status()

    def disconnect(self):
        self._saved_analysis_disabled = True
        return super().disconnect()

    def sdk(self, *, provider=None, key=None):
        selected = provider or self.provider
        credential = self.key if key is None else key
        if not credential:
            raise ProviderError(f"Add an {PROVIDERS[selected]['label']} API key in Settings.", 'authentication')
        # SDK retries are disabled: persisted application retries own the call budget.
        return OpenAI(api_key=credential, base_url=PROVIDERS[selected]['base_url'],
                      timeout=30, max_retries=0,
                      http_client=DefaultHttpx2Client(timeout=30, follow_redirects=False))

    def models(self):
        try:
            with self.sdk() as client:
                result = client.models.list()
                models = []
                for item in result.data:
                    data = item.model_dump()
                    if self.provider == 'openrouter' and not ({'structured_outputs', 'response_format'} & set(data.get('supported_parameters') or [])):
                        continue
                    if self.provider == 'openai' and (not data['id'].startswith(('gpt-', 'o1', 'o3', 'o4')) or any(x in data['id'] for x in ('audio', 'realtime', 'transcribe', 'image', 'tts'))):
                        continue
                    models.append({'id': data['id'], 'name': data.get('name') or data['id'],
                                   'pricing': data.get('pricing') or {},
                                   'supported_parameters': data.get('supported_parameters') or []})
                return models
        except (APIConnectionError, APIStatusError) as exc:
            raise self.public_error(exc) from exc

    def public_error(self, exc):
        label = PROVIDERS[self.provider]['label']
        if isinstance(exc, APIStatusError):
            return ProviderError(f'{label} returned HTTP {exc.status_code}. Check the key, model access and account limits.', http_failure_code(exc.status_code))
        blocked = '10013' in str(exc.__cause__ or '')
        message = ('Windows blocked network access (WinError 10013). Launch START.cmd directly from Windows and retry.'
                   if blocked else f'{label} connection failed. Check network access and retry.')
        return ProviderError(message, 'network_blocked' if blocked else 'connection_failed')

    def check(self):
        schema = {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['ok']}},
                  'required': ['status'], 'additionalProperties': False}
        value = self.call('connection_check', 'Return status ok. This is a connectivity test.', {}, schema, False)
        if value != {'status': 'ok'}:
            raise ProviderError('The structured-output connection test returned an unexpected response.', 'invalid_response')
        self.checked = True
        return self.status()

    def call(self, purpose, system, payload, schema, cache=True, validator=None):
        # Capture configuration so an in-flight call never changes host, key or model.
        provider, model, key = self.provider, self.model, self.key
        if not key:
            raise ProviderError('AI is offline. Add a key or review the evidence manually.', 'authentication')
        if len(json.dumps(payload)) > 24000:
            raise ProviderError('The input is too long for this analysis budget. Review it manually or narrow the policy request.', 'input_too_long')
        identity = [model, self.PROMPT_VERSION, system, payload, schema]
        if provider != 'openrouter':
            identity = [provider, *identity]
        cache_key = fingerprint(identity)
        with self.store.connect() as connection:
            old = connection.execute('SELECT data FROM llm_cache WHERE key=?', (cache_key,)).fetchone()
            spent = connection.execute('SELECT COALESCE(SUM(cost),0) FROM llm_calls').fetchone()[0]
        if old and cache:
            value = json.loads(old[0])
            if validator:
                validator(value)
            return value
        if spent >= self.budget:
            raise ProviderError('The configured AI reported-cost threshold has been reached.', 'budget')
        params = {'model': model, 'messages': [{'role': 'system', 'content': system},
                  {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
                  'response_format': {'type': 'json_schema', 'json_schema':
                                      {'name': 'result', 'strict': True, 'schema': strict_schema(schema)}}}
        if provider == 'openrouter':
            params.update(max_tokens=5000, extra_body={'provider': {'require_parameters': True, 'allow_fallbacks': False}},
                          extra_headers={'X-OpenRouter-Title': 'Refund Operations'})
        else:
            params.update(max_completion_tokens=5000, store=False)
        start = time.monotonic()
        usage, cost, status, generation = {}, None, 'error', uid()
        try:
            with self.sdk(provider=provider, key=key) as client:
                result = client.chat.completions.create(**params)
            raw = result.model_dump()
            generation = raw.get('id') or generation
            usage = raw.get('usage') or {}
            # OpenAI reports tokens, not a billed dollar cost. Unknown must stay NULL.
            cost = usage.get('cost') if provider == 'openrouter' else None
            choice = raw['choices'][0]
            if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal'):
                raise ProviderError('The model response was refused or incomplete. Manual review remains available.', 'invalid_response')
            value = json.loads(choice['message']['content'])
            if validator:
                validator(value)
            status = 'ok'
            if cache:
                with self.store.tx() as connection:
                    connection.execute('INSERT OR REPLACE INTO llm_cache VALUES(?,?,?)', (cache_key, dump(value), now()))
            return value
        except (APIConnectionError, APIStatusError) as exc:
            raise self.public_error(exc) from exc
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise ProviderError('AI analysis failed or the response was invalid. Manual review remains available.', 'invalid_response') from exc
        finally:
            with self.store.tx() as connection:
                connection.execute('INSERT OR REPLACE INTO llm_calls VALUES(?,?,?,?,?,?,?,?,?)',
                                   (generation, purpose, model, provider, dump(usage), cost,
                                    round(time.monotonic() - start, 3), status, now()))
