from job_search_helper.applicant_manager import SOURCE, fetch_applicant_manager
from job_search_helper.ats import HTTPResponse
from job_search_helper.ats import fetch_inventory


def _detail(ident, title):
    return f"<html><head><title>{title} - Elma Electronic</title></head><body><h1>{title}</h1><div class=\"job_listing\"><p>Elma Electronic public job description with responsibilities and qualifications. " + ("Details. " * 30) + "</p></div></body></html>"


class Transport:
    def __init__(self):
        self.ids = ["E11101", "E11102", "E11103"]

    def get(self, url):
        if url == SOURCE:
            links = "".join(f'<a href="/jobs?pos={i}&fs=1.0em">Role {i}</a>' for i in self.ids)
            return HTTPResponse(200, f"<html><body>{links}</body></html>".encode())
        ident = url.split("pos=", 1)[1].split("&", 1)[0]
        return HTTPResponse(200, _detail(ident, f"Role {ident}").encode())


def test_applicant_manager_validates_complete_inventory_and_details():
    result = fetch_applicant_manager(SOURCE, "COMP-0425", "Elma Electronic", Transport())
    assert result.status == "complete"
    assert len(result.jobs) == 3
    assert {job["req_id"] for job in result.jobs} == {"E11101", "E11102", "E11103"}
    assert result.ats == "Applicant Manager"


def test_applicant_manager_rejects_unpinned_board():
    result = fetch_applicant_manager("https://theapplicantmanager.com/careers?co=other", "COMP-0425", "Elma Electronic", Transport())
    assert result.status == "unsupported"


def test_applicant_manager_dispatches_from_normal_entrypoint():
    result = fetch_inventory("Applicant Manager", "https://theapplicantmanager.com/careers?co=e1", "COMP-0425", "Elma Electronic", Transport())
    assert result.status == "complete"
    assert len(result.jobs) == 3
import unittest
from unittest.mock import patch



class ApplicantManagerRegressionTests(unittest.TestCase):
    def test_existing_complete_case(self):
        test_applicant_manager_validates_complete_inventory_and_details()

    def test_existing_source_guard_case(self):
        test_applicant_manager_rejects_unpinned_board()

    def test_existing_dispatch_case(self):
        test_applicant_manager_dispatches_from_normal_entrypoint()

    def test_normal_entrypoint_uses_pinned_html_transport(self):
        def get(url):
            if url == SOURCE:
                links = ''.join(f'<a href="/jobs?pos={i}&fs=1.0em">Role {i}</a>' for i in ['E11101', 'E11102'])
                return HTTPResponse(200, f'<html><body>{links}</body></html>'.encode())
            ident = url.split('pos=', 1)[1].split('&', 1)[0]
            return HTTPResponse(200, _detail(ident, f'Role {ident}').encode())
        with patch('job_search_helper.applicant_manager.ApplicantManagerTransport.get', side_effect=get):
            result = fetch_inventory('Applicant Manager', SOURCE, 'COMP-0425', 'Elma Electronic')
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(len(result.jobs), 2)

    def test_duplicate_ids_are_partial(self):
        class Duplicate(Transport):
            def get(self, url):
                if url == SOURCE:
                    return HTTPResponse(200, b'<a href="/jobs?pos=E11101&fs=1.0em">Role</a><a href="/jobs?pos=E11101&fs=1.0em">Role</a>')
                return super().get(url)
        result = fetch_applicant_manager(SOURCE, 'COMP-0425', 'Elma Electronic', Duplicate())
        self.assertEqual(result.status, 'partial')

    def test_changed_final_title_is_partial(self):
        class Drifting(Transport):
            def __init__(self):
                super().__init__(); self.calls = 0
            def get(self, url):
                if url == SOURCE:
                    self.calls += 1
                    title = 'Changed' if self.calls > 1 else 'Role E11101'
                    return HTTPResponse(200, f'<a href="/jobs?pos=E11101&fs=1.0em">{title}</a>'.encode())
                return super().get(url)
        result = fetch_applicant_manager(SOURCE, 'COMP-0425', 'Elma Electronic', Drifting())
        self.assertEqual(result.status, 'partial')

    def test_missing_job_container_is_partial(self):
        class Missing(Transport):
            def get(self, url):
                if url != SOURCE:
                    return HTTPResponse(200, b'<html><body><h1>Role E11101</h1><p>Elma Electronic ' + b'Details. ' * 30 + b'</p></body></html>')
                return HTTPResponse(200, b'<a href="/jobs?pos=E11101&fs=1.0em">Role E11101</a>')
        result = fetch_applicant_manager(SOURCE, 'COMP-0425', 'Elma Electronic', Missing())
        self.assertEqual(result.status, 'partial')

    def test_multiple_job_containers_is_partial(self):
        class Multiple(Transport):
            def get(self, url):
                if url != SOURCE:
                    body = b'<div class="job_listing">Elma Electronic ' + b'Details. ' * 20 + b'</div><div class="job_listing">extra</div>'
                    return HTTPResponse(200, b'<h1>Role E11101</h1>' + body)
                return HTTPResponse(200, b'<a href="/jobs?pos=E11101&fs=1.0em">Role E11101</a>')
        result = fetch_applicant_manager(SOURCE, 'COMP-0425', 'Elma Electronic', Multiple())
        self.assertEqual(result.status, 'partial')

    def test_transport_rejects_url_authority_and_detail_shape_variants(self):
        from job_search_helper.applicant_manager import ApplicantManagerTransport
        from job_search_helper.ats import FetchError
        transport = ApplicantManagerTransport(base=Transport())
        for bad in (
            'https://user:pass@theapplicantmanager.com/careers?co=e1',
            'https://theapplicantmanager.com:444/careers?co=e1',
            'https://theapplicantmanager.com/jobs?pos=E11101&fs=1.0em#frag',
            'https://theapplicantmanager.com/jobs?pos=../&fs=1.0em',
        ):
            with self.assertRaises(FetchError):
                transport.get(bad)

    def test_pinned_transport_uses_wildcard_accept_only_for_elma(self):
        from job_search_helper.applicant_manager import ApplicantManagerTransport
        from job_search_helper.discovery import CareersTransport
        self.assertEqual(CareersTransport().accept, 'text/html,application/xhtml+xml')
        self.assertEqual(ApplicantManagerTransport().base.accept, '*/*')

    def test_description_is_scoped_and_keeps_terminal_qualification_text(self):
        class Scoped(Transport):
            def get(self, url):
                if url != SOURCE:
                    html = ('<title>Role E11101 - Elma Electronic</title><h1>Role E11101</h1>'
                            '<div class="job_listing"><p>Elma Electronic Responsibilities</p>'
                            '<script>SECRET_APP_FORM</script><style>SECRET_CSS</style>'
                            '<form>SECRET_FORM</form><p>Qualifications<br><img src="x">Terminal qualification. ' + ('Details. ' * 20) + '</p></div>'
                            '<footer>SECRET_FOOTER</footer>')
                    return HTTPResponse(200, html.encode())
                return HTTPResponse(200, b'<a href="/jobs?pos=E11101&fs=1.0em">Role E11101</a>')
        result = fetch_applicant_manager(SOURCE, 'COMP-0425', 'Elma Electronic', Scoped())
        self.assertEqual(result.status, 'complete', result.reason)
        description = result.jobs[0]['description']
        self.assertIn('Terminal qualification', description)
        self.assertNotIn('SECRET_', description)


if __name__ == '__main__':
    unittest.main()
