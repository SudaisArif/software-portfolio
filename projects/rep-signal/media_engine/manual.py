"""Evidence-bound bookkeeping for a human-operated provider UI. No network calls."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from urllib.parse import parse_qs, urlparse

MANUAL_SCHEMA = '''
CREATE TABLE IF NOT EXISTS manual_deliveries(
 delivery_id TEXT PRIMARY KEY REFERENCES deliveries(id) ON DELETE CASCADE,
 authorization TEXT NOT NULL,account_label TEXT NOT NULL,actor TEXT NOT NULL,
 created_at REAL NOT NULL,action TEXT,observation TEXT);
'''


def _text(value, name):
    from .engine import GateError
    if not isinstance(value, str) or not value.strip() or len(value) > 12000:
        raise GateError(name + ' must be nonempty text.')
    return value.strip()


def _time(value):
    from .engine import GateError, timestamp
    try:
        result = timestamp(value)
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise GateError('An explicit, valid observation or schedule timestamp is required.') from None
    if isinstance(value, bool) or not math.isfinite(result):
        raise GateError('Timestamp must be finite.')
    return result


def _post_url(platform, value):
    """Reject profile/Buffer URLs: published evidence identifies an actual post."""
    from .engine import GateError
    value = _text(value, 'Published post URL')
    p = urlparse(value)
    host = (p.hostname or '').lower()
    valid = False
    if p.scheme == 'https' and not p.username and not p.password and p.port in (None, 443):
        if platform == 'youtube':
            valid = (host in {'youtube.com', 'www.youtube.com', 'm.youtube.com'} and (
                bool(re.fullmatch(r'/shorts/[A-Za-z0-9_-]{11}/?', p.path)) or
                (p.path == '/watch' and bool(re.fullmatch(r'[A-Za-z0-9_-]{11}', parse_qs(p.query).get('v', [''])[0]))))) or (
                host == 'youtu.be' and bool(re.fullmatch(r'/[A-Za-z0-9_-]{11}/?', p.path)))
        elif platform == 'instagram':
            valid = host in {'instagram.com', 'www.instagram.com'} and bool(re.fullmatch(r'/(?:reel|p)/[A-Za-z0-9_-]+/?', p.path))
        elif platform == 'tiktok':
            valid = host in {'tiktok.com', 'www.tiktok.com'} and bool(re.fullmatch(r'/@[^/]+/video/[0-9]+/?', p.path))
    if not valid:
        raise GateError('Verified publication requires an HTTPS post URL on the selected platform.')
    return value


class ManualDeliveryMixin:
    def schedule_manual(self, job_id, when_iso, *, revision, artifact_sha256,
                        platform_accounts, authorization, actor):
        """Record specific owner consent and reserve the shared daily video quota."""
        from .engine import ConflictError, GateError, PLATFORMS, dumps
        when = _time(when_iso)
        actor = _text(actor, 'Recording actor')
        if not isinstance(authorization, dict) or authorization.get('source') != 'owner_chat':
            raise GateError('Manual publication requires an identified owner-chat authorization.')
        auth = {'source': 'owner_chat', 'quote': _text(authorization.get('quote'), 'Owner quote'),
                'reference': _text(authorization.get('reference'), 'Conversation reference'),
                'received_at': _time(authorization.get('received_at'))}
        if auth['received_at'] > self.clock() + 60:
            raise GateError('Owner authorization cannot be dated in the future.')
        if not isinstance(platform_accounts, dict) or not platform_accounts or not set(platform_accounts) <= PLATFORMS:
            raise GateError('At least one supported platform and observed account identity is required.')
        accounts = {}
        for platform, account in platform_accounts.items():
            if not isinstance(account, dict):
                raise GateError('Each account requires its provider ID and observed label.')
            accounts[platform] = {'id': _text(account.get('id'), 'Account ID'),
                                  'label': _text(account.get('label'), 'Account label')}
        with self._tx() as c:
            j = self._job(c, job_id)
            self._publish_gates(c, j)
            if revision != j['revision'] or artifact_sha256 != j['artifact_sha256']:
                raise ConflictError('Manual authorization must identify the current revision and exact artifact hash.')
            if j['state'] not in {'QC', 'SCHEDULED'}:
                raise GateError('Job is not available for manual scheduling.')
            existing = c.execute('SELECT d.*,m.authorization,m.account_label,m.actor FROM deliveries d LEFT JOIN manual_deliveries m ON m.delivery_id=d.id WHERE d.job_id=?', (job_id,)).fetchall()
            if existing:
                same = len(existing) == len(accounts) and all(
                    r['dispatch_mode'] == 'manual' and r['revision'] == revision and r['fingerprint'] == artifact_sha256
                    and r['scheduled_at'] == when and r['platform'] in accounts
                    and r['account_id'] == accounts[r['platform']]['id']
                    and r['account_label'] == accounts[r['platform']]['label']
                    and r['authorization'] == dumps(auth) and r['actor'] == actor for r in existing)
                if same:
                    return [dict(c.execute('SELECT * FROM deliveries WHERE id=?', (r['id'],)).fetchone()) for r in existing]
                raise ConflictError('Existing deliveries have different authorization or scope; no delivery was replaced.')
            day = self._day(c, when)
            self._manual_reserve_day(c, j, day)
            for platform, account in accounts.items():
                delivery_id = uuid.uuid4().hex
                try:
                    c.execute("INSERT INTO deliveries(id,job_id,revision,platform,fingerprint,scheduled_at,day,status,account_id,dispatch_mode) VALUES(?,?,?,?,?,?,?,'SCHEDULED',?,'manual')",
                              (delivery_id, job_id, revision, platform, artifact_sha256, when, day, account['id']))
                except sqlite3.IntegrityError as exc:
                    raise ConflictError('This exact video already has a delivery for ' + platform) from exc
                c.execute('INSERT INTO manual_deliveries(delivery_id,authorization,account_label,actor,created_at) VALUES(?,?,?,?,?)',
                          (delivery_id, dumps(auth), account['label'], actor, self.clock()))
                self._event(c, job_id, 'manual_delivery_authorized', actor, delivery_id=delivery_id,
                            revision=revision, artifact_sha256=artifact_sha256, platform=platform,
                            account=account, scheduled_at=when, authorization=auth)
            self._change(c, job_id, state='SCHEDULED')
        return self.get_job(job_id)['deliveries']

    def _manual_reserve_day(self, c, j, day):
        from .engine import GateError
        if c.execute('SELECT 1 FROM reservations WHERE job_id=? AND revision=? AND day=?', (j['id'], j['revision'], day)).fetchone():
            return
        if c.execute('SELECT count(*) FROM reservations WHERE day=?', (day,)).fetchone()[0] >= self._setting(c, 'daily_video_limit'):
            raise GateError('Daily unique-video publication limit reached.')
        c.execute('INSERT INTO reservations VALUES(?,?,?)', (j['id'], j['revision'], day))

    def _manual_scope(self, c, delivery_id, revision, artifact_sha256, account_id, account_label):
        from .engine import ConflictError, GateError
        row = c.execute('SELECT d.*,m.authorization,m.account_label,m.action,m.observation FROM deliveries d JOIN manual_deliveries m ON m.delivery_id=d.id WHERE d.id=?', (delivery_id,)).fetchone()
        if not row or row['dispatch_mode'] != 'manual':
            raise GateError('A scoped manual delivery is required.')
        if row['revision'] != revision or row['fingerprint'] != artifact_sha256 or row['account_id'] != account_id or row['account_label'] != account_label:
            raise ConflictError('Observed account, revision or artifact does not match the owner-authorized delivery.')
        j = self._job(c, row['job_id'])
        if j['revision'] != revision or j['artifact_sha256'] != artifact_sha256:
            raise ConflictError('The authorized job artifact changed.')
        return row, j

    def begin_manual_delivery(self, delivery_id, *, revision, artifact_sha256, account_id,
                              account_label, action, actor):
        """Call immediately BEFORE the one UI send; a second claim always fails closed."""
        from .engine import ConflictError, GateError
        actor = _text(actor, 'Recording actor')
        if action not in {'publish_now', 'schedule'}:
            raise GateError('Manual action must be publish_now or schedule.')
        with self._tx() as c:
            row, j = self._manual_scope(c, delivery_id, revision, artifact_sha256, account_id, account_label)
            self._publish_gates(c, j)
            if row['status'] != 'SCHEDULED' or row['attempts'] != 0:
                raise ConflictError('Delivery has already been claimed; inspect the provider and record evidence, never resend.')
            now = self.clock()
            if action == 'publish_now':
                if self._day(c, now) != row['day']:
                    raise GateError('Immediate publication must occur on the explicitly authorized content day.')
                self._manual_reserve_day(c, j, self._day(c, now))
            elif row['scheduled_at'] <= now:
                raise GateError('A queued manual delivery requires an authorized time in the future.')
            c.execute("UPDATE deliveries SET status='IN_FLIGHT',attempts=1,lease_until=? WHERE id=?", (now + 1800, delivery_id))
            c.execute('UPDATE manual_deliveries SET action=? WHERE delivery_id=?', (action, delivery_id))
            self._event(c, j['id'], 'manual_delivery_claimed', actor, delivery_id=delivery_id,
                        revision=revision, artifact_sha256=artifact_sha256, account_id=account_id,
                        account_label=account_label, action=action, scheduled_at=row['scheduled_at'])
            return dict(c.execute('SELECT * FROM deliveries WHERE id=?', (delivery_id,)).fetchone())

    def record_manual_delivery(self, delivery_id, *, revision, artifact_sha256, account_id,
                               account_label, status, evidence, observed_at, actor,
                               receipt_id=None, public_url=None, published_at=None, scheduled_at=None):
        """Persist an observed result. This never sends, retries or enables publication."""
        from .engine import ConflictError, GateError, dumps
        actor = _text(actor, 'Recording actor')
        evidence = _text(evidence, 'Observed provider evidence')
        observed = _time(observed_at)
        if observed > self.clock() + 60:
            raise GateError('Provider evidence cannot be dated in the future.')
        if status not in {'queued', 'published', 'unknown'}:
            raise GateError('Result must be queued, published or unknown.')
        if status != 'unknown':
            receipt_id = _text(receipt_id, 'Durable Buffer receipt ID')
        elif receipt_id is not None:
            receipt_id = _text(receipt_id, 'Durable Buffer receipt ID')
        if status != 'published' and (public_url is not None or published_at is not None):
            raise GateError('Only a verified published result may have a public URL or publication time.')
        with self._tx() as c:
            row, j = self._manual_scope(c, delivery_id, revision, artifact_sha256, account_id, account_label)
            if row['status'] not in {'IN_FLIGHT', 'SUBMITTED', 'UNKNOWN', 'PUBLISHED'} or not row['attempts']:
                raise GateError('Claim the delivery before making the UI submission.')
            if row['external_id'] and receipt_id and receipt_id != row['external_id']:
                raise ConflictError('The observed provider receipt differs from the original receipt.')
            receipt_id = receipt_id or row['external_id']
            at = None
            if status == 'published':
                public_url = _post_url(row['platform'], public_url)
                at = _time(published_at)
                if at > observed + 60:
                    raise GateError('Publication cannot occur after its observation.')
            if status == 'queued' and row['action'] == 'schedule':
                if _time(scheduled_at) != row['scheduled_at']:
                    raise ConflictError('Observed provider schedule does not match the authorized time.')
            if row['status'] == 'PUBLISHED':
                if status != 'published' or public_url != row['url']:
                    raise ConflictError('A published delivery cannot be downgraded or replaced.')
                return dict(c.execute('SELECT * FROM deliveries WHERE id=?', (delivery_id,)).fetchone())
            if row['observation'] and observed < json.loads(row['observation'])['observed_at']:
                raise ConflictError('Older evidence cannot replace a newer observation.')
            observation = {'status': status, 'evidence': evidence, 'observed_at': observed,
                           'receipt_id': receipt_id, 'public_url': public_url, 'published_at': at,
                           'scheduled_at': _time(scheduled_at) if scheduled_at is not None else None,
                           'actor': actor}
            new_status = {'queued': 'SUBMITTED', 'published': 'PUBLISHED', 'unknown': 'UNKNOWN'}[status]
            # An external fact is retained even if the provider violated its promised day.
            # Stop future work and reserve the actual day rather than hiding that publication.
            if at is not None:
                day = self._day(c, at)
                if day != row['day']:
                    self._set(c, 'kill_switch', True)
                    self._event(c, j['id'], 'manual_delivery_schedule_deviation', actor, delivery_id=delivery_id,
                                authorized_day=row['day'], actual_day=day)
                try:
                    self._manual_reserve_day(c, j, day)
                except GateError:
                    c.execute('INSERT OR IGNORE INTO reservations VALUES(?,?,?)', (j['id'], j['revision'], day))
                    self._set(c, 'kill_switch', True)
                    self._event(c, j['id'], 'manual_delivery_daily_limit_violation', actor, delivery_id=delivery_id, actual_day=day)
            c.execute('UPDATE deliveries SET status=?,external_id=?,url=?,lease_until=NULL,retry_at=NULL,error=? WHERE id=?',
                      (new_status, receipt_id, public_url, 'Manual delivery uncertain; inspect provider without resending.' if status == 'unknown' else None, delivery_id))
            c.execute('UPDATE manual_deliveries SET observation=? WHERE delivery_id=?', (dumps(observation), delivery_id))
            uncertain = c.execute("SELECT 1 FROM deliveries WHERE job_id=? AND status='UNKNOWN'", (j['id'],)).fetchone()
            remaining = c.execute("SELECT 1 FROM deliveries WHERE job_id=? AND status<>'PUBLISHED'", (j['id'],)).fetchone()
            self._change(c, j['id'], state='FAILED' if uncertain else 'SCHEDULED' if remaining else 'PUBLISHED',
                         error='Manual delivery outcome uncertain; reconcile without resending.' if uncertain else None)
            self._event(c, j['id'], 'manual_delivery_observed', actor, delivery_id=delivery_id,
                        revision=revision, artifact_sha256=artifact_sha256, platform=row['platform'],
                        account_id=account_id, account_label=account_label, **{k:v for k,v in observation.items() if k != 'actor'})
            return dict(c.execute('SELECT * FROM deliveries WHERE id=?', (delivery_id,)).fetchone())
