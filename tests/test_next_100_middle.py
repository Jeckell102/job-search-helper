import unittest

from job_search_helper.company_sources import REPAIRS, repair_source
from job_search_helper.shared_boards import board_link


CASES = {
    'COMP-0361': ('Fugro', 'Browser', 'https://www.fugro.com/careers'),
    'COMP-0228': ('Oxa', 'Browser', 'https://oxa.tech/careers'),
    'COMP-0144': ('Airgain', 'Browser', 'https://airgain.com/careers/'),
    'COMP-0269': ('Uhnder', 'Browser', 'https://www.uhnder.com/careers'),
    'COMP-0397': ('Hallam-ICS', '', 'https://www.hallam-ics.com/careers'),
    'COMP-0401': ('Polytron', 'Browser', 'https://polytron.com/careers/'),
    'COMP-0406': ('Federated Wireless', 'Browser', ''),
    'COMP-0408': ('Baicells', '', 'https://www.baicells.com/careers'),
    'COMP-0411': ('Airspan Networks', 'Browser', 'https://airspan.com/careers/airspan-careers/'),
    'COMP-0419': ('Mission Secure', 'Browser', 'https://careers.servicenow.com/'),
    'COMP-0422': ('Systel', '', 'https://systelusa.com/systel-careers/'),
    'COMP-0423': ('Abaco Systems', 'Browser', 'https://abaco.com/careers'),
    'COMP-0424': ('WOLF Advanced Technology', '', 'https://www.wolfadvancedtechnology.com/careers'),
    'COMP-0425': ('Elma Electronic', 'Browser', 'https://www.elma.com/en/about/careers'),
    'COMP-0428': ('Aitech Systems', '', 'https://aitechsystems.com/careers/'),
    'COMP-0430': ('CP Technologies', 'Direct inquiry', 'https://cpnorthamerica.com/our-company/careers/'),
    'COMP-0436': ('Honeywell Aerospace Technologies', 'Oracle Recruiting Cloud', 'https://icfcjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Aerospace/jobs'),
    'COMP-0444': ('JT4', 'Browser', 'https://www.jt4llc.com/careers/'),
    'COMP-0447': ('DCS Corporation', 'Browser', 'https://careers.dcscorp.com/'),
    'COMP-0449': ('IERUS Technologies', '', 'https://ierustech.com/careers/open-positions/'),
    'COMP-0453': ('Tactical Edge', '', 'https://www.tacticaledge.us/careers/'),
    'COMP-0461': ('JANUS Research Group', 'Browser', 'https://www.janusresearch.com/careers'),
    'COMP-0467': ('DTC, a Codan Company', '', 'https://www.dtccodan.com/about/careers/'),
    'COMP-0469': ('Mutualink', 'Browser', ''),
    'COMP-0475': ('Mission Critical Partners', 'Browser', 'https://www.missioncriticalpartners.com/careers'),
    'COMP-0477': ('Wabtec', '', 'https://careers.wabtec.com/'),
    'COMP-0485': ('Fox Robotics', 'Browser (shared parent board)', 'https://www.symbotic.com/careers/jobs/'),
    'COMP-0486': ('Haivision', 'Browser', 'https://www.haivision.com/about/careers/'),
    'COMP-0487': ('Vislink Technologies', 'Browser', 'https://www.vislink.com/about/careers/'),
    'COMP-0492': ('Southwest Antennas', 'Browser', 'https://southwestantennas.com/careers-southwest-antennas'),
    'COMP-0493': ('Antenna Research Associates', '', 'https://ara-inc.com/careers/'),
    'COMP-0501': ('Reliable Robotics', 'Ashby', 'https://reliable.co/careers'),
    'COMP-0506': ('Scythe Robotics', 'Browser', 'https://joinscythe.com/'),
    'COMP-0512': ('Tarana Wireless', 'Official careers page', 'https://taranawireless.com/careers/'),
    'COMP-0516': ('Wisk Aero', 'Official careers page', 'https://wisk.aero/careers'),
    'COMP-0519': ('Zoox', 'Lever', 'https://jobs.lever.co/zoox?location=Foster+City%2C+CA'),
    'COMP-0121': ('Telesat', 'Browser', 'https://www.telesat.com/careers/'),
    'COMP-0155': ('Qorvo', 'Browser', 'https://careers.qorvo.com/'),
    'COMP-0520': ('Verkada', 'Official careers page', 'https://www.verkada.com/careers/'),
}


class MiddleBatchRoutes(unittest.TestCase):
    def test_every_selected_company_has_a_guarded_route(self):
        self.assertEqual(set(CASES), set(REPAIRS) & set(CASES))
        for cid, (company, source, expected) in CASES.items():
            with self.subTest(company=company):
                ats, url, note = repair_source(source, expected, cid, company)
                self.assertEqual((ats, url), (REPAIRS[cid]['ats'], REPAIRS[cid]['url']))
                self.assertTrue(note)
                self.assertEqual(repair_source(source, expected, cid, 'Other Employer'), (source, expected, ''))

    def test_systel_jazzhr_board_is_employer_scoped(self):
        board = board_link(REPAIRS['COMP-0422']['url'])
        self.assertEqual((board.name, board.slug, board.path),
                         ('JazzHR', 'systelusa', '/apply'))


if __name__ == '__main__':
    unittest.main()
