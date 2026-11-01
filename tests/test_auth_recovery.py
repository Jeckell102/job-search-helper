"""Offline regressions for paired OAuth renewal and interrupted Sheets calls.

All credentials, transports and OAuth responses in this file are test doubles.
The tests require only Python's standard library; no network or Google login.
"""
from __future__ import annotations

from collections import defaultdict, deque
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from job_search_helper import cli, repository, runner


READ = "https://www.googleapis.com/auth/spreadsheets.readonly"
WRITE = "https://www.googleapis.com/auth/spreadsheets"


class RefreshError(Exception):
    def __init__(self, *args, retryable=False):
        super().__init__(*args)
        self.retryable = retryable


def revoked():
    return RefreshError("invalid_grant: expired test grant", {"error": "invalid_grant"})


def token_data(scope, expired=False):
    expiry = datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 2)
    label = "read" if scope == READ else "write"
    return {
        "token": "FAKE-ACCESS-" + label,
        "refresh_token": "FAKE-REFRESH-" + label,
        "client_id": "FAKE-CLIENT-ID", "client_secret": "FAKE-CLIENT-SECRET",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": [scope], "expiry": expiry.isoformat(),
    }


class FakeGoogle:
    def __init__(self):
        backend = self
        self.refreshes = []
        self.sign_ins = []
        self.requests = []
        self.builds = []
        self.refresh_outcomes = defaultdict(deque)
        self.sign_in_outcomes = defaultdict(deque)
        self.request_outcomes = deque()

        class Credentials:
            def __init__(self, info, scopes):
                self.info = dict(info)
                self.scopes = list(scopes)
                self.token = info.get("token")
                self.refresh_token = info.get("refresh_token")
                self.expiry = datetime.fromisoformat(info["expiry"])
                self.granted_scopes = info.get("granted_scopes", list(scopes))

            @property
            def valid(self):
                return bool(self.token) and datetime.now(timezone.utc) < self.expiry

            @classmethod
            def from_authorized_user_info(cls, info, scopes):
                return cls(info, scopes)

            def refresh(self, request):
                scope = self.scopes[0]
                backend.refreshes.append(scope)
                outcomes = backend.refresh_outcomes[scope]
                if outcomes:
                    outcome = outcomes.popleft()
                    if isinstance(outcome, BaseException):
                        raise outcome
                self.token = f"FAKE-RENEWED-{len(backend.refreshes)}"
                self.expiry = datetime.now(timezone.utc) + timedelta(hours=1)

            def to_json(self):
                return json.dumps({**self.info, "token": self.token,
                                   "refresh_token": self.refresh_token,
                                   "scopes": self.scopes, "expiry": self.expiry.isoformat()})

        class Flow:
            def __init__(self, scopes):
                self.scopes = scopes

            @classmethod
            def from_client_secrets_file(cls, path, scopes):
                return cls(scopes)

            def run_local_server(self, **kwargs):
                scope = self.scopes[0]
                backend.sign_ins.append((scope, kwargs))
                outcomes = backend.sign_in_outcomes[scope]
                outcome = outcomes.popleft() if outcomes else {}
                if isinstance(outcome, BaseException):
                    raise outcome
                data = token_data(scope)
                data.update(token=f"FAKE-NEW-ACCESS-{len(backend.sign_ins)}",
                            refresh_token=f"FAKE-NEW-REFRESH-{len(backend.sign_ins)}")
                data.update(outcome)
                return Credentials(data, self.scopes)

        class AuthorizedHttp:
            def __init__(self, credentials, http=None):
                self.credentials = credentials
                self.http = http

            def request(self, *args, **kwargs):
                backend.requests.append((args, dict(kwargs), self.credentials.token))
                outcome = backend.request_outcomes.popleft() if backend.request_outcomes else None
                if isinstance(outcome, BaseException):
                    raise outcome
                if callable(outcome):
                    return outcome(self)
                return outcome or ({"status": "200"}, b"{}")

        def build(*args, **kwargs):
            backend.builds.append((args, kwargs))
            return SimpleNamespace(_http=kwargs["http"])

        names = (
            "google", "google.auth", "google.auth.exceptions", "google.auth.transport",
            "google.auth.transport.requests", "google.oauth2", "google.oauth2.credentials",
            "google_auth_httplib2", "google_auth_oauthlib", "google_auth_oauthlib.flow",
            "googleapiclient", "googleapiclient.discovery", "googleapiclient.http",
        )
        self.modules = {name: ModuleType(name) for name in names}
        for name, module in self.modules.items():
            module.__path__ = []
            parent, _, child = name.rpartition(".")
            if parent:
                setattr(self.modules[parent], child, module)
        self.modules["google.auth.exceptions"].RefreshError = RefreshError
        self.modules["google.auth.transport.requests"].Request = object
        self.modules["google.oauth2.credentials"].Credentials = Credentials
        self.modules["google_auth_oauthlib.flow"].InstalledAppFlow = Flow
        self.modules["google_auth_httplib2"].AuthorizedHttp = AuthorizedHttp
        self.modules["googleapiclient.discovery"].build = build
        self.modules["googleapiclient.http"].build_http = object


class AuthRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.secrets = self.root / "private"
        self.secrets.mkdir(mode=0o700)
        self.paths = {READ: self.secrets / "read.json", WRITE: self.secrets / "write.json"}
        self.client = self.root / "client.json"
        self.client.write_text("{}", encoding="utf-8")
        self.google = FakeGoogle()
        modules = patch.dict(sys.modules, self.google.modules)
        modules.start()
        self.addCleanup(modules.stop)
        environment = patch.dict(os.environ, {
            "GOOGLE_CREDENTIALS_FILE": str(self.client),
            "GOOGLE_TOKEN_READ_FILE": str(self.paths[READ]),
            "GOOGLE_TOKEN_WRITE_FILE": str(self.paths[WRITE]),
            "SPREADSHEET_ID": "FAKE_WORKING_SPREADSHEET",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        out, err = redirect_stdout(self.stdout), redirect_stderr(self.stderr)
        out.__enter__()
        err.__enter__()
        self.addCleanup(out.__exit__, None, None, None)
        self.addCleanup(err.__exit__, None, None, None)

    def save(self, scope, expired=False):
        path = self.paths[scope]
        path.write_text(json.dumps(token_data(scope, expired)), encoding="utf-8")
        path.chmod(0o600)
        return path.read_bytes()

    def pair(self, read_expired=False, write_expired=False):
        self.save(READ, read_expired)
        self.save(WRITE, write_expired)
        return repository.authorize(write=True, interactive=True, renew_both=True)

    def assert_saved_pair(self):
        for scope, path in self.paths.items():
            self.assertEqual([scope], json.loads(path.read_text())["scopes"])
            self.assertEqual(0o600, path.stat().st_mode & 0o777)

    def test_valid_pair_uses_saved_credentials_without_refresh_or_sign_in(self):
        originals = {scope: self.save(scope) for scope in (READ, WRITE)}
        repository.authorize(write=True, interactive=True, renew_both=True)
        self.assertEqual([], self.google.refreshes)
        self.assertEqual([], self.google.sign_ins)
        for scope, content in originals.items():
            self.assertEqual(content, self.paths[scope].read_bytes())

    def test_expired_pair_refreshes_both_and_persists_private_scoped_files(self):
        self.pair(read_expired=True, write_expired=True)
        self.assertEqual([READ, WRITE], self.google.refreshes)
        self.assertEqual([], self.google.sign_ins)
        self.assert_saved_pair()

    def test_expired_write_also_renews_valid_read_credential(self):
        self.pair(write_expired=True)
        self.assertEqual([READ, WRITE], self.google.refreshes)
        self.assert_saved_pair()

    def test_expired_read_also_renews_valid_write_credential(self):
        self.pair(read_expired=True)
        self.assertEqual([READ, WRITE], self.google.refreshes)

    def test_revoked_writer_signs_in_and_leaves_both_valid(self):
        self.google.refresh_outcomes[WRITE].append(revoked())
        service = self.pair(write_expired=True)
        self.assertEqual([READ, WRITE], self.google.refreshes)
        self.assertEqual([WRITE], [scope for scope, _ in self.google.sign_ins])
        self.assertTrue(service._http.credentials.valid)
        self.assert_saved_pair()

    def test_revoked_pair_gets_two_independently_scoped_grants(self):
        for scope in (READ, WRITE):
            self.google.refresh_outcomes[scope].append(revoked())
        self.pair(read_expired=True, write_expired=True)
        self.assertEqual([READ, WRITE], [scope for scope, _ in self.google.sign_ins])
        self.assert_saved_pair()
        tokens = [json.loads(path.read_text())["refresh_token"] for path in self.paths.values()]
        self.assertNotEqual(tokens[0], tokens[1])

    def test_missing_pair_requests_offline_consent_for_each_scope(self):
        repository.authorize(write=True, interactive=True, renew_both=True)
        self.assertEqual([READ, WRITE], [scope for scope, _ in self.google.sign_ins])
        for scope, options in self.google.sign_ins:
            self.assertEqual("offline", options["access_type"])
            self.assertEqual("consent", options["prompt"])
        self.assert_saved_pair()

    def test_expiry_during_run_renews_pair_before_sending_write(self):
        service = self.pair()
        session = service._http._authorization
        session.credentials[True].expiry = datetime.now(timezone.utc) - timedelta(hours=1)
        self.google.refresh_outcomes[WRITE].append(revoked())
        service._http.request("FAKE_SHEETS_URI", "POST", body="exact change set")
        self.assertEqual([READ, WRITE], self.google.refreshes)
        self.assertEqual([WRITE], [scope for scope, _ in self.google.sign_ins])
        self.assertEqual(1, len(self.google.requests))
        self.assertTrue(self.google.requests[0][2].startswith("FAKE-NEW-ACCESS-"))
        self.assert_saved_pair()

    def test_transport_refresh_failure_recovers_and_retries_exact_request_once(self):
        service = self.pair()
        self.google.request_outcomes.append(revoked())
        self.google.refresh_outcomes[WRITE].append(revoked())
        arguments = ("FAKE_SHEETS_URI", "POST")
        keywords = {"body": "exact change set", "headers": {"Content-Type": "application/json"}}
        service._http.request(*arguments, **keywords)
        self.assertEqual(2, len(self.google.requests))
        for args, kwargs, _ in self.google.requests:
            self.assertEqual(arguments, args)
            self.assertEqual(keywords, kwargs)
        self.assertEqual([READ, WRITE], self.google.refreshes)
        self.assertTrue(self.google.requests[1][2].startswith("FAKE-NEW-ACCESS-"))

    def test_second_transport_refresh_failure_is_not_retried_again(self):
        service = self.pair()
        self.google.request_outcomes.extend([revoked(), revoked()])
        with self.assertRaises(RefreshError):
            service._http.request("FAKE_SHEETS_URI", "POST", body="exact change set")
        self.assertEqual(2, len(self.google.requests))
        self.assertEqual([READ, WRITE], self.google.refreshes)

    def test_network_failure_does_not_trigger_sign_in_or_write_replay(self):
        service = self.pair()
        self.google.request_outcomes.append(TimeoutError("FAKE-SECRET-RESPONSE"))
        repo = repository.GoogleRepository(service, "FAKE_WORKING_SPREADSHEET", min_request_interval=0)

        class Request:
            def execute(self):
                return service._http.request("FAKE_SHEETS_URI", "POST", body="exact change set")

        with self.assertRaises(repository.UncertainWriteError) as caught:
            repo._execute(Request(), "write")
        self.assertEqual(1, len(self.google.requests))
        self.assertEqual([], self.google.sign_ins)
        self.assertNotIn("FAKE-SECRET-RESPONSE", str(caught.exception))

    def test_retryable_refresh_failure_is_not_treated_as_revoked_consent(self):
        service = self.pair()
        error = RefreshError("invalid_grant: temporary", {"error": "invalid_grant"}, retryable=True)
        self.google.request_outcomes.append(error)
        with self.assertRaises(RefreshError):
            service._http.request("FAKE_SHEETS_URI", "POST", body="exact change set")
        self.assertEqual(1, len(self.google.requests))
        self.assertEqual([], self.google.refreshes)
        self.assertEqual([], self.google.sign_ins)

    def test_startup_server_failure_preserves_writer_token_without_sign_in(self):
        self.save(READ)
        original = self.save(WRITE, expired=True)
        self.google.refresh_outcomes[WRITE].append(
            RefreshError("server_error: FAKE-SECRET", {"error": "server_error"}, retryable=True))
        with self.assertRaises(repository.RepositoryError) as caught:
            repository.authorize(write=True, interactive=True, renew_both=True)
        self.assertEqual(original, self.paths[WRITE].read_bytes())
        self.assertEqual([], self.google.sign_ins)
        self.assertNotIn("FAKE-SECRET", str(caught.exception))

    def test_invalid_client_does_not_open_an_unhelpful_sign_in_loop(self):
        self.save(WRITE, expired=True)
        self.google.refresh_outcomes[WRITE].append(RefreshError("invalid_client: FAKE-SECRET"))
        with self.assertRaises(repository.RepositoryError):
            repository.authorize(write=True, interactive=True)
        self.assertEqual([], self.google.sign_ins)

    def test_read_command_refreshes_only_read_token_without_broadening_scope(self):
        self.save(READ, expired=True)
        original_write = self.save(WRITE, expired=True)
        service = repository.authorize()
        self.assertEqual([READ], self.google.refreshes)
        self.assertEqual([READ], service._http.credentials.scopes)
        self.assertEqual(original_write, self.paths[WRITE].read_bytes())

    def test_read_command_with_revoked_grant_requires_explicit_sign_in(self):
        self.save(READ, expired=True)
        self.google.refresh_outcomes[READ].append(revoked())
        with self.assertRaises(repository.RepositoryError):
            repository.authorize()
        self.assertEqual([], self.google.sign_ins)
        self.assertFalse(self.paths[WRITE].exists())

    def test_explicit_read_only_auth_does_not_create_write_token(self):
        repository.authorize(interactive=True)
        self.assertEqual([READ], [scope for scope, _ in self.google.sign_ins])
        self.assertFalse(self.paths[WRITE].exists())

    def test_denied_write_scope_does_not_overwrite_existing_writer_token(self):
        self.save(READ)
        original = self.save(WRITE, expired=True)
        self.google.refresh_outcomes[WRITE].append(revoked())
        self.google.sign_in_outcomes[WRITE].append({"granted_scopes": [READ]})
        with self.assertRaises(repository.RepositoryError):
            repository.authorize(write=True, interactive=True, renew_both=True)
        self.assertEqual(original, self.paths[WRITE].read_bytes())

    def test_new_grant_without_refresh_token_is_not_saved(self):
        self.google.sign_in_outcomes[WRITE].append({"refresh_token": None})
        with self.assertRaises(repository.RepositoryError):
            repository.authorize(write=True, interactive=True)
        self.assertFalse(self.paths[WRITE].exists())

    def test_nonprivate_token_is_rejected_before_either_credential_refreshes(self):
        self.save(READ, expired=True)
        original = self.save(WRITE, expired=True)
        self.paths[WRITE].chmod(0o644)
        with self.assertRaises(repository.RepositoryError):
            repository.authorize(write=True, interactive=True, renew_both=True)
        self.assertEqual([], self.google.refreshes)
        self.assertEqual([], self.google.sign_ins)
        self.assertEqual(original, self.paths[WRITE].read_bytes())

    def test_token_paths_must_be_distinct(self):
        with patch.dict(os.environ, {"GOOGLE_TOKEN_WRITE_FILE": str(self.paths[READ])}):
            with self.assertRaises(repository.RepositoryError):
                repository.authorize(write=True, interactive=True, renew_both=True)
        self.assertEqual([], self.google.sign_ins)

    def test_token_symlinks_are_rejected(self):
        self.save(READ)
        self.paths[WRITE].symlink_to(self.paths[READ])
        with self.assertRaises(repository.RepositoryError):
            repository.authorize(write=True, interactive=True, renew_both=True)
        self.assertEqual([], self.google.refreshes)

    def test_wrong_saved_scope_is_reauthorized_explicitly(self):
        data = token_data(READ)
        self.paths[WRITE].write_text(json.dumps(data), encoding="utf-8")
        self.paths[WRITE].chmod(0o600)
        repository.authorize(write=True, interactive=True)
        self.assertEqual([WRITE], [scope for scope, _ in self.google.sign_ins])
        self.assertEqual([WRITE], json.loads(self.paths[WRITE].read_text())["scopes"])

    def test_internal_successful_refresh_is_persisted_after_http_request(self):
        service = self.pair()

        def internal_refresh(http):
            http.credentials.refresh(object())
            return {"status": "200"}, b"{}"

        self.google.request_outcomes.append(internal_refresh)
        service._http.request("FAKE_SHEETS_URI", "GET")
        self.assertEqual(service._http.credentials.token, json.loads(self.paths[WRITE].read_text())["token"])

    def test_atomic_save_failure_preserves_old_token_and_removes_temporary_file(self):
        original = self.save(WRITE, expired=True)
        with patch.object(repository.os, "replace", side_effect=OSError("FAKE-SAVE-ERROR")):
            with self.assertRaises(repository.RepositoryError):
                repository.authorize(write=True)
        self.assertEqual(original, self.paths[WRITE].read_bytes())
        self.assertEqual([], list(self.secrets.glob("token-*.json")))

    def test_default_auth_command_renews_both_credentials(self):
        with patch.object(cli, "load_environment"), patch.object(cli, "authorize") as authorize:
            self.assertEqual(0, cli.main(["auth"]))
        authorize.assert_called_once_with(write=False, interactive=True, renew_both=True)

    def test_auth_scope_options_select_only_one_credential(self):
        for option, write in (("--write", True), ("--read-only", False)):
            with self.subTest(option=option):
                with patch.object(cli, "load_environment"), patch.object(cli, "authorize") as authorize:
                    self.assertEqual(0, cli.main(["auth", option]))
                authorize.assert_called_once_with(write=write, interactive=True, renew_both=False)

    def test_start_enables_paired_interactive_recovery(self):
        database = self.root / "state" / "state.db"
        with patch.object(runner, "_load_environment"), patch.object(runner, "load_title_blacklist"), \
                patch.object(runner, "load_title_review_list"), patch.object(runner, "state_path", return_value=database), \
                patch.object(runner, "writer_lock", return_value=nullcontext()), \
                patch.object(runner, "get_repository", side_effect=RuntimeError("STOP BEFORE SHEETS")) as get_repo:
            with self.assertRaisesRegex(RuntimeError, "STOP BEFORE SHEETS"):
                runner.run_start()
        get_repo.assert_called_once_with(write=True, interactive=True, renew_both=True, min_request_interval=1.1)

    def test_sync_uses_the_same_start_recovery_path(self):
        with patch.object(runner, "run_start", return_value=0) as start:
            self.assertEqual(0, runner.main(["sync"]))
        self.assertTrue(start.call_args.kwargs["sync_only"])

    def test_preflight_does_not_request_paired_or_write_authorization(self):
        repo = SimpleNamespace(validate_schema=lambda: True)
        with patch.object(cli, "load_environment"), patch.object(cli, "get_repository", return_value=repo) as get_repo:
            self.assertEqual(0, cli.main(["preflight"]))
        get_repo.assert_called_once_with(interactive=False)


if __name__ == "__main__":
    unittest.main()
