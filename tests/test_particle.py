import json
import unittest
from job_search_helper.ats import HTTPResponse
from job_search_helper.company_sources import repair_source
from job_search_helper.particle import BOARD, _is_particle


class ParticleTests(unittest.TestCase):
    def test_official_chain_repairs_to_digi_ukg(self):
        ats, url, note = repair_source('Rippling', 'https://www.particle.io/careers/', 'COMP-0274', 'Particle')
        self.assertEqual(ats, 'Particle UKG')
        self.assertEqual(url, BOARD)
        self.assertIn('Verified company source repair', note)

    def test_structured_brand_is_authoritative(self):
        ok, mode = _is_particle({}, {'BrandName': 'Particle by Digi', 'Description': 'Digi only'})
        self.assertTrue(ok); self.assertIn('structured', mode)
        ok, _ = _is_particle({}, {'BrandName': 'Digi International', 'Description': 'Particle by Digi'})
        self.assertFalse(ok)

    def test_documented_legal_entity_mapping_and_bare_mentions(self):
        ok, mode = _is_particle({}, {'Description': 'Particle by Digi is hiring for this role.'})
        self.assertTrue(ok); self.assertIn('legal-entity', mode)
        ok, _ = _is_particle({}, {'Description': 'Digi builds connected products using Particle devices.'})
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
